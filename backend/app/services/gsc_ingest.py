"""GSC ingest + URL reconciliation.

Bootstrap uses the Search Analytics API; BigQuery bulk export becomes the preferred ongoing
source once configured. Rows are upserted on the natural key so overlapping windows between the
two sources can never duplicate a record. Unmatched URLs are categorised, never discarded.
"""
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

from ..sources import SearchAnalyticsAPISource, SourceUnavailable, get_gsc_source
from .secrets import redact

INTENT_RULES = [
    (("buy", "sale", "cheap", "price", "discount", "order", "for sale", "delivery"), "transactional"),
    (("best", "vs", "review", "reviews", "top", "compare", "which"), "commercial"),
    (("how", "what", "why", "clean", "care", "guide", "ideas", "dimensions", "size"), "informational"),
]


def classify_intent(query: str, brand_tokens: tuple[str, ...]) -> tuple[str, float]:
    q = query.lower()
    if any(b in q for b in brand_tokens):
        return "navigational", 0.9
    for tokens, intent in INTENT_RULES:
        if any(t in q.split() or t in q for t in tokens):
            return intent, 0.88
    return "commercial", 0.55


def normalise(url: str) -> tuple[str, dict]:
    """Returns (canonical-ish key, notes). Notes flag parameters and trailing-slash handling."""
    parsed = urlparse(url)
    notes = {"had_query_params": bool(parsed.query), "had_fragment": bool(parsed.fragment)}
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
        notes["trailing_slash_stripped"] = True
    clean = urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))
    return clean, notes


class GSCIngestService:
    def __init__(self, uow, audit, settings, ledger):
        self.uow = uow
        self.audit = audit
        self.s = settings
        self.ledger = ledger

    def register(self, queue):
        queue.register("gsc_bootstrap", self.bootstrap, "gsc_ingest")
        queue.register("gsc_daily_ingest", self.daily_ingest, "gsc_ingest")
        queue.register("gsc_url_reconciliation", self.reconcile_urls, "gsc_ingest")
        queue.register("gsc_verify", self.verify, "gsc_ingest")

    async def verify(self) -> dict:
        api = SearchAnalyticsAPISource()
        info = await api.verify()
        try:
            info["available_range"] = await api.available_range()
        except Exception as exc:  # noqa: BLE001
            info["available_range_error"] = redact(str(exc))
        return info

    # ------------------------------------------------------------------ ingest
    async def bootstrap(self, months: int | None = None, prefer: str = "api") -> dict:
        """Historical backfill in monthly windows (GSC API max lookback is 16 months)."""
        months = months or self.s.gsc_bootstrap_months
        today = date.today()
        end = today - timedelta(days=2)  # allow for GSC finalisation lag
        windows = []
        cursor_end = end
        for _ in range(months):
            cursor_start = (cursor_end.replace(day=1) - timedelta(days=1)).replace(day=1) \
                if cursor_end.day == 1 else cursor_end.replace(day=1)
            windows.append((cursor_start, cursor_end))
            cursor_end = cursor_start - timedelta(days=1)
        windows.reverse()

        total, per_window = 0, []
        for start, stop in windows:
            try:
                result = await self.ingest_window(start.isoformat(), stop.isoformat(), prefer=prefer)
            except SourceUnavailable as exc:
                per_window.append({"start": start.isoformat(), "end": stop.isoformat(),
                                   "error": redact(str(exc))})
                continue
            total += result["rows_upserted"]
            per_window.append({"start": start.isoformat(), "end": stop.isoformat(),
                               "rows": result["rows_upserted"], "source": result["source"]})
        reconciliation = await self.reconcile_urls()
        return {"months_requested": months, "windows": per_window, "rows_upserted": total,
                "url_reconciliation": reconciliation}

    async def daily_ingest(self, days: int = 3, prefer: str = "auto") -> dict:
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=days)
        return await self.ingest_window(start.isoformat(), end.isoformat(), prefer=prefer)

    async def ingest_window(self, start_date: str, end_date: str, prefer: str = "auto") -> dict:
        source = get_gsc_source(prefer)
        rows = await source.fetch_performance(start_date=start_date, end_date=end_date,
                                              markets=self.s.active_markets)
        uow = self.uow.unscoped()
        now = datetime.now(timezone.utc).isoformat()
        upserted = 0
        for r in rows:
            key = {"url": r["url"], "query": r["query"], "market": r["market"],
                   "device": r["device"], "period_start": start_date, "period_end": end_date}
            await uow.gsc_performance.update_one(key, {
                **key, "country": r["country"], "impressions": r["impressions"],
                "clicks": r["clicks"], "position": round(r["position"], 2),
                "page_type": self._guess_page_type(r["url"]),
                "ingested_via": source.name, "data_mode": "LIVE", "source": source.name,
                "ingested_at": now,
            }, upsert=True)
            upserted += 1
        if source.name.startswith("gsc_bigquery"):
            await self.ledger.charge(provider="bigquery", operation="gsc_rollup_query",
                                     cost_usd=0.01, agent_role="gsc_ingest")
        await self._rebuild_keywords(start_date, end_date)
        return {"source": source.name, "window": [start_date, end_date], "rows_upserted": upserted}

    @staticmethod
    def _guess_page_type(url: str) -> str:
        path = urlparse(url).path
        if "/products/" in path:
            return "product"
        if "/collections/" in path:
            return "collection"
        if "/blogs/" in path:
            return "blog"
        if "/pages/" in path:
            return "page"
        return "home" if path in ("", "/") else "other"

    async def _rebuild_keywords(self, start_date: str, end_date: str) -> int:
        """Keyword universe + preferred-landing-page mapping from real queries only."""
        uow = self.uow.unscoped()
        host_tokens = ("urbandotted", "urban dotted")
        written = 0
        for market in self.s.active_markets:
            agg = await uow.gsc_performance.aggregate([
                {"$match": {"market": market, "data_mode": "LIVE"}},
                {"$group": {"_id": {"query": "$query", "url": "$url"},
                            "impressions": {"$sum": "$impressions"},
                            "clicks": {"$sum": "$clicks"}, "position": {"$avg": "$position"},
                            "page_type": {"$first": "$page_type"}}},
            ])
            by_query: dict[str, dict] = {}
            for a in agg:
                q = a["_id"]["query"]
                entry = by_query.setdefault(q, {"impressions": 0, "clicks": 0, "urls": []})
                entry["impressions"] += a["impressions"]
                entry["clicks"] += a["clicks"]
                entry["urls"].append({"url": a["_id"]["url"], "impressions": a["impressions"],
                                      "clicks": a["clicks"], "position": a["position"],
                                      "page_type": a.get("page_type")})
            for query, entry in by_query.items():
                # Preferred landing page = the URL Google already rewards most for this query.
                best = sorted(entry["urls"], key=lambda u: (-u["clicks"], -u["impressions"], u["position"]))[0]
                intent, conf = classify_intent(query, host_tokens)
                await uow.keywords.update_one({"query": query, "market": market}, {
                    "query": query, "market": market, "preferred_url": best["url"],
                    "preferred_page_type": best.get("page_type"),
                    "preferred_url_basis": "highest clicks then impressions then best position",
                    "impressions_30d": entry["impressions"], "clicks_30d": entry["clicks"],
                    "avg_position": round(sum(u["position"] for u in entry["urls"]) / len(entry["urls"]), 2),
                    "urls_ranking": len(entry["urls"]),
                    "intent": intent, "intent_confidence": conf,
                    "intent_method": "deterministic_rules",
                    "cluster": best.get("page_type") or "other",
                    "category": None, "source": "gsc_query", "data_mode": "LIVE",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, upsert=True)
                written += 1
        return written

    # ------------------------------------------------------------------ URL reconciliation
    async def reconcile_urls(self) -> dict:
        """Maps every GSC landing URL to a catalogue entity and categorises every miss."""
        uow = self.uow.unscoped()
        pages = await uow.pages.find({"data_mode": "LIVE"}, limit=200000,
                                     select=["url", "page_type", "entity_handle", "market"])
        index: dict[str, dict] = {}
        for p in pages:
            key, _ = normalise(p["url"])
            index[key] = p

        urls = await uow.gsc_performance.aggregate([
            {"$match": {"data_mode": "LIVE"}},
            {"$group": {"_id": {"url": "$url", "market": "$market"},
                        "impressions": {"$sum": "$impressions"}, "clicks": {"$sum": "$clicks"}}},
        ])

        buckets = {"matched": 0, "matched_after_normalisation": 0, "parameterised": 0,
                   "redirected_or_moved": 0, "canonicalised_elsewhere": 0, "non_catalogue_page": 0,
                   "unknown": 0}
        unmatched_rows = []
        matched_impressions = total_impressions = 0

        await uow.repo("url_reconciliation").delete({})
        for u in urls:
            url, market = u["_id"]["url"], u["_id"]["market"]
            impressions = u["impressions"]
            total_impressions += impressions
            key, notes = normalise(url)
            hit = index.get(key)
            category = None

            if hit:
                buckets["matched" if key == url else "matched_after_normalisation"] += 1
                matched_impressions += impressions
                await uow.gsc_performance.update_one(
                    {"url": url, "market": market},
                    {"matched_entity_type": hit["page_type"], "matched_entity_handle": hit["entity_handle"],
                     "url_match_status": "matched"}, upsert=False)
                continue

            path = urlparse(url).path
            if notes.get("had_query_params"):
                category = "parameterised"
            elif any(seg in path for seg in ("/collections/", "/products/")):
                category = "redirected_or_moved"
            elif any(seg in path for seg in ("/blogs/", "/pages/", "/policies/", "/search")):
                category = "non_catalogue_page"
            elif path in ("", "/"):
                category = "canonicalised_elsewhere"
            else:
                category = "unknown"
            buckets[category] += 1
            unmatched_rows.append({
                "url": url, "market": market, "category": category, "impressions": impressions,
                "clicks": u["clicks"], "normalised": key, "notes": notes,
                "detected_at": datetime.now(timezone.utc).isoformat(), "data_mode": "LIVE",
            })

        if unmatched_rows:
            unmatched_rows.sort(key=lambda r: -r["impressions"])
            for i in range(0, len(unmatched_rows), 2000):
                await uow.repo("url_reconciliation").insert_many(unmatched_rows[i:i + 2000])

        total_urls = sum(buckets.values())
        report = {
            "gsc_urls_total": total_urls, "buckets": buckets,
            "match_rate_pct": round((buckets["matched"] + buckets["matched_after_normalisation"])
                                    / total_urls * 100, 2) if total_urls else 0.0,
            "impression_coverage_pct": round(matched_impressions / total_impressions * 100, 2)
            if total_impressions else 0.0,
            "unmatched_retained": len(unmatched_rows),
            "top_unmatched": unmatched_rows[:20],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        await uow.repo("reports").update_one({"kind": "url_reconciliation"},
                                            {"kind": "url_reconciliation", **report}, upsert=True)
        return report
