"""Deterministic pipeline services. Registered as jobs on the internal job queue."""
from datetime import datetime, timezone

from . import cannibalization as cann
from .scoring import assign_tiers, recommend, score_entity


class Pipelines:
    def __init__(self, uow, ledger, router, audit):
        self.uow = uow
        self.ledger = ledger
        self.router = router
        self.audit = audit

    def register(self, queue):
        queue.register("recompute_opportunities", self.recompute_opportunities, "opportunity_scoring")
        queue.register("detect_cannibalization", self.detect_cannibalization, "cannibalization_judge")
        queue.register("detect_anomalies", self.detect_anomalies, "anomaly_detector")
        queue.register("classify_intents", self.classify_intents, "intent_classifier")

    # ------------------------------------------------------------------ scoring
    async def recompute_opportunities(self, markets: list[str] | None = None) -> dict:
        markets = markets or ["AU", "NZ"]
        now = datetime.now(timezone.utc).isoformat()
        issue_counts = {}
        for row in await self.uow.technical_issues.aggregate([
            {"$match": {"status": "open"}},
            {"$group": {"_id": "$url", "n": {"$sum": 1}}},
        ]):
            issue_counts[row["_id"]] = row["n"]

        written = 0
        await self.uow.opportunity_scores.delete({})
        for market in markets:
            keyword_agg = await self.uow.gsc_performance.aggregate([
                {"$match": {"market": market}},
                {"$group": {"_id": "$query", "impressions": {"$sum": "$impressions"},
                            "clicks": {"$sum": "$clicks"},
                            "position": {"$avg": "$position"},
                            "urls": {"$addToSet": "$url"}}},
            ])
            keywords = {k["query"]: k for k in await self.uow.keywords.find({"market": market}, limit=20000)}
            max_impr = max([k["impressions"] for k in keyword_agg] or [1])
            rows = []
            for agg in keyword_agg:
                query = agg["_id"]
                meta = keywords.get(query, {})
                intent = meta.get("intent", "commercial")
                pref = meta.get("preferred_url")
                s = score_entity(impressions=agg["impressions"], clicks=agg["clicks"],
                                 position=agg["position"], intent=intent,
                                 technical_issues=issue_counts.get(pref, 0), max_impressions=max_impr)
                rows.append({
                    "entity_type": "keyword", "entity_id": query, "entity_label": query, "market": market,
                    "score": s["score"], "components": s["components"], "weights": s["weights"],
                    "intent": intent, "intent_confidence": meta.get("intent_confidence"),
                    "preferred_url": pref, "page_type": meta.get("preferred_page_type"),
                    "category": meta.get("category"),
                    "evidence": {"impressions_30d": agg["impressions"], "clicks_30d": agg["clicks"],
                                 "avg_position": round(agg["position"], 1), "ctr": s["ctr"],
                                 "expected_ctr": s["expected_ctr"], "urls_ranking": len(agg["urls"]),
                                 "open_technical_issues": issue_counts.get(pref, 0),
                                 "signal_source": "gsc_performance"},
                    "computed_at": now,
                })

            url_agg = await self.uow.gsc_performance.aggregate([
                {"$match": {"market": market}},
                {"$group": {"_id": {"url": "$url", "page_type": "$page_type"},
                            "impressions": {"$sum": "$impressions"}, "clicks": {"$sum": "$clicks"},
                            "position": {"$avg": "$position"}, "queries": {"$addToSet": "$query"}}},
            ])
            max_u = max([u["impressions"] for u in url_agg] or [1])
            handles = {p["url"]: p["product_handle"] for p in
                       await self.uow.product_market.find({"market": market}, limit=20000,
                                                          select=["url", "product_handle"])}
            for agg in url_agg:
                url = agg["_id"]["url"]
                page_type = agg["_id"].get("page_type") or "page"
                s = score_entity(impressions=agg["impressions"], clicks=agg["clicks"],
                                 position=agg["position"], intent="transactional" if page_type == "product" else "commercial",
                                 technical_issues=issue_counts.get(url, 0), max_impressions=max_u)
                rows.append({
                    "entity_type": page_type if page_type in ("product", "collection") else "page",
                    "entity_id": url, "entity_label": handles.get(url, url.split("/")[-1]),
                    "market": market, "score": s["score"], "components": s["components"],
                    "weights": s["weights"], "intent": "transactional" if page_type == "product" else "commercial",
                    "preferred_url": url, "page_type": page_type,
                    "evidence": {"impressions_30d": agg["impressions"], "clicks_30d": agg["clicks"],
                                 "avg_position": round(agg["position"], 1), "ctr": s["ctr"],
                                 "expected_ctr": s["expected_ctr"], "queries_ranking": len(agg["queries"]),
                                 "open_technical_issues": issue_counts.get(url, 0),
                                 "signal_source": "gsc_performance"},
                    "computed_at": now,
                })

            for r in assign_tiers(rows):
                r["recommended_action"] = recommend(r["entity_type"], r["tier"])
                r["confidence"] = round(min(0.99, 0.45 + min(r["evidence"]["impressions_30d"], 5000) / 5000 * 0.5), 2)
            for i in range(0, len(rows), 2000):
                written += await self.uow.opportunity_scores.insert_many(rows[i:i + 2000])
        return {"markets": markets, "scored_entities": written}

    # ------------------------------------------------------------------ cannibalization
    async def detect_cannibalization(self, markets: list[str] | None = None) -> dict:
        markets = markets or ["AU", "NZ"]
        await self.uow.cannibalization.delete({})
        agg = await self.uow.gsc_performance.aggregate([
            {"$match": {"market": {"$in": markets}}},
            {"$group": {"_id": {"query": "$query", "url": "$url", "market": "$market",
                                "page_type": "$page_type"},
                        "impressions": {"$sum": "$impressions"}, "clicks": {"$sum": "$clicks"},
                        "position": {"$avg": "$position"}}},
        ])
        rows = [{"query": a["_id"]["query"], "url": a["_id"]["url"], "market": a["_id"]["market"],
                 "page_type": a["_id"].get("page_type"), "impressions": a["impressions"],
                 "clicks": a["clicks"], "position": a["position"]} for a in agg]
        findings = cann.detect(rows)
        if findings:
            await self.uow.cannibalization.insert_many(findings)
        return {"findings": len(findings),
                "needs_llm_judge": sum(1 for f in findings if f["needs_llm_judge"]),
                "deterministic": sum(1 for f in findings if not f["needs_llm_judge"])}

    # ------------------------------------------------------------------ anomalies
    async def detect_anomalies(self, markets: list[str] | None = None) -> dict:
        markets = markets or ["AU", "NZ"]
        agg = await self.uow.gsc_performance.aggregate([
            {"$match": {"market": {"$in": markets}}},
            {"$group": {"_id": {"url": "$url", "market": "$market"},
                        "clicks": {"$sum": "$clicks"}, "prev_clicks": {"$sum": "$prev_clicks"},
                        "impressions": {"$sum": "$impressions"},
                        "position": {"$avg": "$position"}, "prev_position": {"$avg": "$prev_position"}}},
        ])
        found = 0
        for a in agg:
            prev, cur = a["prev_clicks"], a["clicks"]
            if prev < 50:
                continue
            drop = (prev - cur) / prev
            if drop >= 0.4:
                found += 1
        return {"markets": markets, "click_drop_anomalies": found, "urls_evaluated": len(agg)}

    # ------------------------------------------------------------------ intent (LLM)
    async def classify_intents(self, limit: int = 15, market: str = "AU") -> dict:
        from .llm_router import INTENT_SYSTEM, LLMUnavailable

        candidates = await self.uow.keywords.find(
            {"market": market, "intent_method": "deterministic_rules", "intent_confidence": {"$lt": 0.7}},
            order_by=[("impressions_30d", -1)], limit=limit)
        updated, escalated, errors = 0, 0, []
        for k in candidates:
            prompt = (f"Query: \"{k['query']}\"\nMarket: {market}\n"
                      f"Monthly impressions: {k['impressions_30d']}\nAverage position: {k['avg_position']}\n"
                      f"Current landing page type: {k.get('preferred_page_type')}\n"
                      "Classify the search intent.")
            try:
                res = await self.router.complete_json(
                    task="intent_classification", agent_role="intent_classifier",
                    system=INTENT_SYSTEM, prompt=prompt, cache_key=f"{market}:{k['query']}")
            except (LLMUnavailable, ValueError) as e:
                errors.append(str(e))
                break
            await self.uow.keywords.update_one({"id": k["id"]}, {
                "intent": res.get("intent", k["intent"]),
                "intent_confidence": float(res.get("confidence", 0.5)),
                "intent_method": "llm:" + str(res.get("_model")),
                "intent_reasoning": res.get("reasoning"),
                "recommended_page_type": res.get("recommended_page_type"),
                "intent_ambiguous": bool(res.get("ambiguous", False)),
            })
            updated += 1
            if res.get("_cached"):
                escalated += 0
        return {"market": market, "candidates": len(candidates), "updated": updated, "errors": errors[:3]}
