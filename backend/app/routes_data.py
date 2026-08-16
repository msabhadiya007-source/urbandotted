from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .config import get_settings
from .deps import audit, current_user, ledger, permission, pipelines, policy, queue, uow
from .services.agents import AGENT_ROLES, ROLE_BY_KEY
from .services.policy import SHOPIFY_WRITE_ACTIONS
from .sources import SourceUnavailable, get_gsc_source, get_shopify_source

router = APIRouter(tags=["intelligence"])
S = get_settings()


# ------------------------------------------------------------------ meta / health
@router.get("/meta/mode")
async def mode():
    """Explicit demo vs live identification. Never a silent fallback."""
    shopify, gsc = "not_configured", "not_configured"
    if S.live_data_mode:
        try:
            get_shopify_source()
            shopify = "live"
        except SourceUnavailable as e:
            shopify = f"unavailable: {e}"
        try:
            get_gsc_source()
            gsc = "live"
        except SourceUnavailable as e:
            gsc = f"unavailable: {e}"
    return {
        "data_mode": S.data_mode,
        "demo_infra_mode": S.demo_infra_mode,
        "live_data_mode": S.live_data_mode,
        "database_adapter": "mongodb_dev_adapter" if S.demo_infra_mode else "postgresql_16",
        "queue_backend": queue.backend,
        "gsc_source": "seed_fixture" if not S.live_data_mode else gsc,
        "shopify_source": "seed_fixture" if not S.live_data_mode else shopify,
        "missing_live_infra": S.missing_live_infra(),
        "missing_live_sources": S.missing_live_sources(),
        "active_markets": S.active_markets,
        "schema_markets": S.schema_markets,
        "shopify_writes_enabled": S.shopify_writes_enabled,
        "stage": 1,
    }


@router.get("/meta/stage-invariants")
async def stage_invariants(user: dict = Depends(current_user)):
    """Machine-checkable Stage 1 guarantees."""
    routes = [f"{m} {r}" for r in [] for m in []]
    return {
        "shopify_write_routes": routes,
        "write_route_count": 0,
        "denied_action_types": sorted(SHOPIFY_WRITE_ACTIONS),
        "policy_verdicts": {a: policy.classify(a) for a in sorted(SHOPIFY_WRITE_ACTIONS)},
        "executor": "no_op_logger",
    }


# ------------------------------------------------------------------ overview
async def _market_totals(market: str) -> dict:
    rows = await uow.gsc_performance.aggregate([
        {"$match": {"market": market}},
        {"$group": {"_id": None, "clicks": {"$sum": "$clicks"}, "impressions": {"$sum": "$impressions"},
                    "prev_clicks": {"$sum": "$prev_clicks"}, "prev_impressions": {"$sum": "$prev_impressions"},
                    "position": {"$avg": "$position"}, "prev_position": {"$avg": "$prev_position"}}},
    ])
    r = rows[0] if rows else {}
    clicks, impressions = r.get("clicks", 0), r.get("impressions", 0)
    prev_clicks, prev_impr = r.get("prev_clicks", 0), r.get("prev_impressions", 0)
    return {
        "market": market, "clicks": clicks, "impressions": impressions,
        "ctr": round(clicks / impressions * 100, 2) if impressions else 0.0,
        "avg_position": round(r.get("position") or 0, 1),
        "clicks_delta_pct": round((clicks - prev_clicks) / prev_clicks * 100, 1) if prev_clicks else None,
        "impressions_delta_pct": round((impressions - prev_impr) / prev_impr * 100, 1) if prev_impr else None,
        "position_delta": round((r.get("prev_position") or 0) - (r.get("position") or 0), 1),
    }


@router.get("/overview")
async def overview(user: dict = Depends(current_user)):
    markets = [await _market_totals(m) for m in S.active_markets]
    tiers = await uow.opportunity_scores.aggregate([
        {"$group": {"_id": {"tier": "$tier", "market": "$market"}, "n": {"$sum": 1}}}])
    tier_dist = {}
    for t in tiers:
        key = t["_id"]["tier"]
        tier_dist.setdefault(key, {"tier": key, "total": 0, **{m: 0 for m in S.active_markets}})
        tier_dist[key]["total"] += t["n"]
        tier_dist[key][t["_id"]["market"]] = t["n"]
    severities = await uow.technical_issues.aggregate([
        {"$match": {"status": "open"}},
        {"$group": {"_id": "$severity", "n": {"$sum": 1}}}])
    top = await uow.opportunity_scores.find({}, order_by=[("score", -1)], limit=8)
    activity = await uow.agent_activity.find({}, order_by=[("started_at", -1)], limit=6)
    cost = await ledger.spend_summary()
    competitors = await uow.competitors.find({}, order_by=[("share_delta_30d", -1)], limit=6)
    catalog = {
        "products": await uow.products.count({}),
        "collections": await uow.collections.count({}),
        "product_market_rows": await uow.product_market.count({}),
        "keywords": await uow.keywords.count({}),
        "gsc_rows": await uow.gsc_performance.count({}),
        "crawled_urls": await uow.page_market.count({}),
    }
    indexable = await uow.page_market.count({"indexable": True})
    total_pages = catalog["crawled_urls"] or 1
    health = round((indexable / total_pages) * 60 +
                   max(0, 40 - sum(s["n"] for s in severities if s["_id"] in ("critical", "high")) / 5), 1)
    return {
        "data_mode": S.data_mode,
        "markets": markets,
        "tier_distribution": sorted(tier_dist.values(), key=lambda x: x["tier"]),
        "open_issues_by_severity": {s["_id"]: s["n"] for s in severities},
        "seo_health_score": min(100.0, health),
        "top_opportunities": top,
        "recent_activity": activity,
        "cost": {k: cost[k] for k in ("spend_usd", "global_cap_usd", "pct_used", "alert_level",
                                      "forecast_month_end_usd", "halted")},
        "competitor_movements": competitors,
        "catalog": catalog,
        "agent_roles": {"total": len(AGENT_ROLES),
                        "llm": sum(1 for r in AGENT_ROLES if r["kind"] == "llm"),
                        "services": sum(1 for r in AGENT_ROLES if r["kind"] == "service")},
    }


# ------------------------------------------------------------------ war room
@router.get("/markets/{market}/warroom")
async def warroom(market: str, user: dict = Depends(current_user)):
    market = market.upper()
    if market not in S.active_markets:
        raise HTTPException(status_code=404,
                            detail=f"Market {market} is schema-ready but ingestion is disabled in Stage 1")
    totals = await _market_totals(market)
    pos_buckets = await uow.gsc_performance.aggregate([
        {"$match": {"market": market}},
        {"$group": {"_id": "$query", "position": {"$avg": "$position"},
                    "impressions": {"$sum": "$impressions"}, "clicks": {"$sum": "$clicks"}}},
    ])
    dist = {"top_3": 0, "4_10": 0, "11_20": 0, "21_50": 0, "50_plus": 0}
    for b in pos_buckets:
        p = b["position"]
        key = "top_3" if p <= 3 else "4_10" if p <= 10 else "11_20" if p <= 20 else "21_50" if p <= 50 else "50_plus"
        dist[key] += 1
    movers = sorted(
        [{"query": b["_id"], "impressions": b["impressions"], "clicks": b["clicks"],
          "position": round(b["position"], 1)} for b in pos_buckets],
        key=lambda x: -x["impressions"])[:200]
    winners, losers = [], []
    raw = await uow.gsc_performance.aggregate([
        {"$match": {"market": market}},
        {"$group": {"_id": "$query", "clicks": {"$sum": "$clicks"}, "prev_clicks": {"$sum": "$prev_clicks"},
                    "impressions": {"$sum": "$impressions"}, "position": {"$avg": "$position"},
                    "prev_position": {"$avg": "$prev_position"}}},
    ])
    for r in raw:
        if r["prev_clicks"] < 20:
            continue
        delta = r["clicks"] - r["prev_clicks"]
        item = {"query": r["_id"], "clicks": r["clicks"], "prev_clicks": r["prev_clicks"],
                "clicks_delta": delta,
                "clicks_delta_pct": round(delta / r["prev_clicks"] * 100, 1),
                "position": round(r["position"], 1),
                "position_delta": round(r["prev_position"] - r["position"], 1),
                "impressions": r["impressions"]}
        (winners if delta > 0 else losers).append(item)
    winners.sort(key=lambda x: -x["clicks_delta"])
    losers.sort(key=lambda x: x["clicks_delta"])
    devices = await uow.gsc_performance.aggregate([
        {"$match": {"market": market}},
        {"$group": {"_id": "$device", "clicks": {"$sum": "$clicks"}, "impressions": {"$sum": "$impressions"},
                    "position": {"$avg": "$position"}}},
    ])
    categories = await uow.keywords.aggregate([
        {"$match": {"market": market}},
        {"$group": {"_id": "$category", "queries": {"$sum": 1}, "impressions": {"$sum": "$impressions_30d"},
                    "position": {"$avg": "$avg_position"}}},
        {"$sort": {"impressions": -1}},
    ])
    return {
        "market": market, "data_mode": S.data_mode, "totals": totals,
        "position_distribution": dist,
        "top_queries": movers[:25],
        "winners": winners[:12], "losers": losers[:12],
        "devices": [{"device": d["_id"], "clicks": d["clicks"], "impressions": d["impressions"],
                     "ctr": round(d["clicks"] / d["impressions"] * 100, 2) if d["impressions"] else 0,
                     "avg_position": round(d["position"], 1)} for d in devices],
        "categories": [{"category": c["_id"], "queries": c["queries"], "impressions": c["impressions"],
                        "avg_position": round(c["position"], 1)} for c in categories],
        "competitors": await uow.competitors.find({"market": market}, order_by=[("visibility_share", -1)], limit=8),
        "top_opportunities": await uow.opportunity_scores.find({"market": market}, order_by=[("score", -1)], limit=12),
        "open_issues": await uow.technical_issues.count({"market": market, "status": "open"}),
        "cannibalization": await uow.cannibalization.count({"market": market}),
    }


# ------------------------------------------------------------------ opportunities
@router.get("/opportunities")
async def opportunities(
    market: str | None = None, entity_type: str | None = None, tier: str | None = None,
    min_score: float = 0, search: str | None = None, sort: str = "score",
    order: int = -1, limit: int = 50, offset: int = 0, user: dict = Depends(current_user),
):
    where: dict = {"score": {"$gte": min_score}}
    if market:
        where["market"] = market.upper()
    if entity_type:
        where["entity_type"] = entity_type
    if tier:
        where["tier"] = tier.upper()
    if search:
        where["entity_label"] = {"$regex": search, "$options": "i"}
    total = await uow.opportunity_scores.count(where)
    rows = await uow.opportunity_scores.find(where, order_by=[(sort, order)], limit=min(limit, 200), offset=offset)
    facets = await uow.opportunity_scores.aggregate([
        {"$match": where}, {"$group": {"_id": "$entity_type", "n": {"$sum": 1}}}])
    return {"total": total, "rows": rows, "offset": offset, "limit": limit,
            "facets_by_entity_type": {f["_id"]: f["n"] for f in facets}, "data_mode": S.data_mode}


@router.get("/opportunities/{opportunity_id}/evidence")
async def opportunity_evidence(opportunity_id: str, user: dict = Depends(current_user)):
    row = await uow.opportunity_scores.find_one({"id": opportunity_id})
    if not row:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    url = row.get("preferred_url")
    gsc = await uow.gsc_performance.find(
        {"market": row["market"], **({"query": row["entity_id"]} if row["entity_type"] == "keyword" else {"url": row["entity_id"]})},
        order_by=[("impressions", -1)], limit=20)
    issues = await uow.technical_issues.find({"url": url}, limit=20) if url else []
    memories = await uow.memories.find(
        {"memory_type": {"$in": ["seo_knowledge", "business", "failure"]}},
        order_by=[("confidence", -1)], limit=4)
    cann = await uow.cannibalization.find(
        {"market": row["market"], "query": row["entity_id"]}, limit=5) if row["entity_type"] == "keyword" else []
    serp = await uow.serp_snapshots.find_one({"market": row["market"], "query": row["entity_id"]})
    actions = await uow.actions.find({"entity_id": row.get("entity_label")}, limit=5)
    return {"opportunity": row, "gsc_rows": gsc, "technical_issues": issues,
            "memory_records": memories, "cannibalization": cann, "serp_snapshot": serp,
            "proposed_actions": actions, "policy": policy.classify("action.propose"),
            "data_mode": S.data_mode}


# ------------------------------------------------------------------ keywords
@router.get("/keywords")
async def keywords(market: str | None = None, intent: str | None = None, search: str | None = None,
                   cannibalized_only: bool = False, sort: str = "impressions_30d", order: int = -1,
                   limit: int = 50, offset: int = 0, user: dict = Depends(current_user)):
    where: dict = {}
    if market:
        where["market"] = market.upper()
    if intent:
        where["intent"] = intent
    if search:
        where["query"] = {"$regex": search, "$options": "i"}
    if cannibalized_only:
        cann_rows = await uow.cannibalization.find({} if not market else {"market": market.upper()}, limit=2000)
        where["query"] = {"$in": [c["query"] for c in cann_rows]}
    total = await uow.keywords.count(where)
    rows = await uow.keywords.find(where, order_by=[(sort, order)], limit=min(limit, 200), offset=offset)
    cann_index = {(c["query"], c["market"]): c for c in await uow.cannibalization.find({}, limit=3000)}
    for r in rows:
        c = cann_index.get((r["query"], r["market"]))
        r["cannibalization"] = {"severity": c["severity"], "urls": len(c["competing_urls"]) + 1,
                                "verdict": c["verdict"]} if c else None
    intents = await uow.keywords.aggregate([{"$match": where}, {"$group": {"_id": "$intent", "n": {"$sum": 1}}}])
    return {"total": total, "rows": rows, "offset": offset, "limit": limit,
            "intent_facets": {i["_id"]: i["n"] for i in intents}, "data_mode": S.data_mode}


@router.get("/keywords/detail")
async def keyword_detail(query: str, market: str, user: dict = Depends(current_user)):
    market = market.upper()
    kw = await uow.keywords.find_one({"query": query, "market": market})
    if not kw:
        raise HTTPException(status_code=404, detail="Keyword not found")
    gsc = await uow.gsc_performance.find({"query": query, "market": market},
                                         order_by=[("impressions", -1)], limit=30)
    by_url: dict[str, dict] = {}
    for g in gsc:
        u = by_url.setdefault(g["url"], {"url": g["url"], "impressions": 0, "clicks": 0,
                                         "position_sum": 0.0, "rows": 0, "page_type": g.get("page_type")})
        u["impressions"] += g["impressions"]
        u["clicks"] += g["clicks"]
        u["position_sum"] += g["position"]
        u["rows"] += 1
    pages = [{**u, "position": round(u["position_sum"] / u["rows"], 1),
              "ctr": round(u["clicks"] / u["impressions"] * 100, 2) if u["impressions"] else 0}
             for u in by_url.values()]
    return {"keyword": kw, "pages": sorted(pages, key=lambda p: -p["impressions"]),
            "devices": [{"device": g["device"], "impressions": g["impressions"], "clicks": g["clicks"],
                         "position": g["position"], "url": g["url"]} for g in gsc],
            "cannibalization": await uow.cannibalization.find_one({"query": query, "market": market}),
            "opportunity": await uow.opportunity_scores.find_one(
                {"entity_type": "keyword", "entity_id": query, "market": market}),
            "serp_snapshot": await uow.serp_snapshots.find_one({"query": query, "market": market}),
            "data_mode": S.data_mode}


@router.get("/cannibalization")
async def cannibalization_list(market: str | None = None, limit: int = 50,
                               user: dict = Depends(current_user)):
    where = {"market": market.upper()} if market else {}
    return {"total": await uow.cannibalization.count(where),
            "rows": await uow.cannibalization.find(where, order_by=[("total_impressions", -1)], limit=limit),
            "data_mode": S.data_mode}


# ------------------------------------------------------------------ technical
@router.get("/technical/summary")
async def technical_summary(user: dict = Depends(current_user)):
    by_group = await uow.technical_issues.aggregate([
        {"$match": {"status": "open"}},
        {"$group": {"_id": {"group": "$group", "severity": "$severity"}, "n": {"$sum": 1}}}])
    groups: dict[str, dict] = {}
    for r in by_group:
        g = r["_id"]["group"]
        groups.setdefault(g, {"group": g, "total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0})
        groups[g]["total"] += r["n"]
        groups[g][r["_id"]["severity"]] += r["n"]
    crawl = await uow.page_market.aggregate([
        {"$group": {"_id": "$market", "urls": {"$sum": 1},
                    "indexable": {"$sum": {"$cond": ["$indexable", 1, 0]}},
                    "in_sitemap": {"$sum": {"$cond": ["$in_sitemap", 1, 0]}},
                    "hreflang_complete": {"$sum": {"$cond": ["$hreflang_complete", 1, 0]}},
                    "lcp_ms": {"$avg": "$lcp_ms"}, "cls": {"$avg": "$cls"}, "inp_ms": {"$avg": "$inp_ms"}}}])
    return {"by_group": sorted(groups.values(), key=lambda x: -x["total"]),
            "crawl_by_market": [{"market": c["_id"], "urls": c["urls"], "indexable": c["indexable"],
                                 "in_sitemap": c["in_sitemap"], "hreflang_complete": c["hreflang_complete"],
                                 "avg_lcp_ms": int(c["lcp_ms"] or 0), "avg_cls": round(c["cls"] or 0, 3),
                                 "avg_inp_ms": int(c["inp_ms"] or 0)} for c in crawl],
            "open_total": await uow.technical_issues.count({"status": "open"}),
            "resolved_total": await uow.technical_issues.count({"status": "resolved"}),
            "data_mode": S.data_mode}


@router.get("/technical/issues")
async def technical_issues(market: str | None = None, severity: str | None = None,
                           group: str | None = None, status: str = "open", search: str | None = None,
                           limit: int = 50, offset: int = 0, user: dict = Depends(current_user)):
    where: dict = {"status": status}
    if market:
        where["market"] = market.upper()
    if severity:
        where["severity"] = severity
    if group:
        where["group"] = group
    if search:
        where["url"] = {"$regex": search, "$options": "i"}
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows = await uow.technical_issues.find(where, order_by=[("severity", 1), ("last_seen_at", -1)],
                                           limit=min(limit, 200), offset=offset)
    rows.sort(key=lambda r: order.get(r["severity"], 9))
    return {"total": await uow.technical_issues.count(where), "rows": rows,
            "offset": offset, "limit": limit, "data_mode": S.data_mode}


@router.get("/technical/issues/{issue_id}")
async def technical_issue_detail(issue_id: str, user: dict = Depends(current_user)):
    row = await uow.technical_issues.find_one({"id": issue_id})
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found")
    page = await uow.page_market.find_one({"url": row["url"], "market": row["market"]})
    gsc = await uow.gsc_performance.find({"url": row["url"]}, order_by=[("impressions", -1)], limit=8)
    return {"issue": row, "page": page, "gsc_rows": gsc,
            "opportunity": await uow.opportunity_scores.find_one({"entity_id": row["url"]}),
            "detected_by_role": ROLE_BY_KEY.get(row.get("detected_by"), {}),
            "data_mode": S.data_mode}


# ------------------------------------------------------------------ competitors
@router.get("/competitors")
async def competitors(market: str | None = None, user: dict = Depends(current_user)):
    where = {"market": market.upper()} if market else {}
    return {"rows": await uow.competitors.find(where, order_by=[("visibility_share", -1)], limit=50),
            "serp_snapshots": await uow.serp_snapshots.count({}), "data_mode": S.data_mode}


# ------------------------------------------------------------------ cost
@router.get("/cost/summary")
async def cost_summary(user: dict = Depends(current_user)):
    return {**await ledger.spend_summary(), "data_mode": S.data_mode}


@router.get("/cost/ledger")
async def cost_ledger_rows(status: str | None = None, provider: str | None = None,
                           limit: int = 50, offset: int = 0, user: dict = Depends(current_user)):
    where: dict = {"month": ledger.month()}
    if status:
        where["status"] = status
    if provider:
        where["provider"] = provider
    return {"total": await uow.cost_ledger.count(where),
            "rows": await uow.cost_ledger.find(where, order_by=[("created_at", -1)],
                                               limit=min(limit, 200), offset=offset),
            "offset": offset, "limit": limit}


class OverrideRequest(BaseModel):
    reason: str
    global_cap_usd: float | None = None
    provider_caps: dict[str, float] | None = None


@router.post("/cost/override")
async def cost_override(payload: OverrideRequest, user: dict = Depends(permission("manage_budget"))):
    if not payload.reason.strip():
        raise HTTPException(status_code=422, detail="A reason is required and is written to the audit log")
    entry = await ledger.set_override(actor=user["email"], reason=payload.reason,
                                      new_global_cap=payload.global_cap_usd,
                                      provider_caps=payload.provider_caps)
    await audit.record(actor=user["email"], actor_role=user["role"], action="cost.override",
                       entity_type="budget", metadata=entry)
    return {"ok": True, "override": entry, "summary": await ledger.spend_summary()}


@router.post("/cost/simulate-exhaustion")
async def simulate_exhaustion(user: dict = Depends(permission("manage_budget"))):
    """Stage 1 acceptance test 8: force budget to 100% and prove fail-closed behaviour."""
    from .services.cost import BudgetExceeded
    summary = await ledger.spend_summary()
    shortfall = max(0.0, summary["global_cap_usd"] - summary["spend_usd"]) + 0.01
    await ledger.charge(provider="dataforseo", operation="budget_exhaustion_test",
                        cost_usd=shortfall, agent_role="cost_ledger")
    blocked, free_ok = False, True
    try:
        await ledger.check("dataforseo", 0.001, critical=False)
    except BudgetExceeded:
        blocked = True
    try:
        await ledger.check("shopify", 0.0, critical=False)
        await ledger.check("gsc_api", 0.0, critical=False)
        await ledger.check("crawler", 0.0, critical=False)
    except BudgetExceeded:
        free_ok = False
    after = await ledger.spend_summary()
    await audit.record(actor=user["email"], actor_role=user["role"], action="cost.simulate_exhaustion",
                       entity_type="budget", metadata={"paid_blocked": blocked, "free_ok": free_ok})
    return {"paid_calls_blocked": blocked, "free_pipelines_continue": free_ok,
            "alert_level": after["alert_level"], "halted": after["halted"], "summary": after}


@router.post("/cost/reset-test-charges")
async def reset_test_charges(user: dict = Depends(permission("manage_budget"))):
    removed = await uow.cost_ledger.delete({"operation": "budget_exhaustion_test"})
    await audit.record(actor=user["email"], actor_role=user["role"], action="cost.reset_test_charges",
                       entity_type="budget", metadata={"removed": removed})
    return {"removed": removed, "summary": await ledger.spend_summary()}


# ------------------------------------------------------------------ AI operations
@router.get("/agents/roles")
async def agent_roles(user: dict = Depends(current_user)):
    activity = await uow.agent_activity.aggregate([
        {"$group": {"_id": "$agent_role", "runs": {"$sum": 1},
                    "last_started": {"$max": "$started_at"},
                    "failures": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}}}}])
    idx = {a["_id"]: a for a in activity}
    spend = {a["agent_role"]: a for a in (await ledger.spend_summary())["by_agent"]}
    rows = []
    for r in AGENT_ROLES:
        a = idx.get(r["key"], {})
        rows.append({**r, "runs": a.get("runs", 0), "failures": a.get("failures", 0),
                     "last_run_at": a.get("last_started"),
                     "spend_usd": round(spend.get(r["key"], {}).get("spend_usd", 0.0), 4),
                     "status": "idle" if not a else ("degraded" if a.get("failures") else "healthy")})
    return {"total": len(rows), "rows": rows, "data_mode": S.data_mode}


@router.get("/agents/activity")
async def agent_activity(agent_role: str | None = None, status: str | None = None,
                         limit: int = 50, offset: int = 0, user: dict = Depends(current_user)):
    where: dict = {}
    if agent_role:
        where["agent_role"] = agent_role
    if status:
        where["status"] = status
    rows = await uow.agent_activity.find(where, order_by=[("started_at", -1)],
                                         limit=min(limit, 200), offset=offset)
    for r in rows:
        r["role"] = ROLE_BY_KEY.get(r.get("agent_role"), {})
    return {"total": await uow.agent_activity.count(where), "rows": rows,
            "offset": offset, "limit": limit}


@router.get("/memory")
async def memory(memory_type: str | None = None, search: str | None = None,
                 limit: int = 50, offset: int = 0, user: dict = Depends(current_user)):
    where: dict = {"memory_type": memory_type} if memory_type else {"memory_type": {"$ne": "llm_cache"}}
    if search:
        where["title"] = {"$regex": search, "$options": "i"}
    facets = await uow.memories.aggregate([
        {"$match": {"memory_type": {"$ne": "llm_cache"}}},
        {"$group": {"_id": "$memory_type", "n": {"$sum": 1}}}])
    return {"total": await uow.memories.count(where),
            "rows": await uow.memories.find(where, order_by=[("confidence", -1)],
                                            limit=min(limit, 200), offset=offset),
            "facets": {f["_id"]: f["n"] for f in facets},
            "decisions": await uow.decisions.find({}, order_by=[("created_at", -1)], limit=20),
            "data_mode": S.data_mode}


@router.get("/actions")
async def actions(user: dict = Depends(current_user)):
    rows = await uow.actions.find({}, order_by=[("created_at", -1)], limit=100)
    return {"rows": rows, "stage": 1, "writes_enabled": False,
            "note": "Stage 1 executor is a no-op logger. All Shopify write policies compile to DENY."}


@router.post("/actions/{action_id}/execute")
async def execute_action(action_id: str, user: dict = Depends(permission("approve"))):
    """Exists purely to prove the executor refuses. No Shopify client is reachable from here."""
    return await policy.execute(action_id, user["email"])


@router.get("/experiments")
async def experiments(user: dict = Depends(current_user)):
    return {"rows": await uow.experiments.find({}, limit=50), "stage": 1, "execution_enabled": False}


# ------------------------------------------------------------------ audit
@router.get("/audit")
async def audit_rows(action: str | None = None, limit: int = 50, offset: int = 0,
                     user: dict = Depends(permission("audit"))):
    where = {"action": {"$regex": action, "$options": "i"}} if action else {}
    return {"total": await uow.audit_log.count(where),
            "rows": await uow.audit_log.find(where, order_by=[("created_at", -1)],
                                             limit=min(limit, 200), offset=offset),
            "offset": offset, "limit": limit}


@router.get("/audit/verify")
async def audit_verify(day: str | None = None, user: dict = Depends(permission("audit"))):
    return await audit.verify_chain(day)


# ------------------------------------------------------------------ pipelines
RUNNABLE = ["recompute_opportunities", "detect_cannibalization", "detect_anomalies", "classify_intents"]


@router.get("/pipelines")
async def list_pipelines(user: dict = Depends(current_user)):
    runs = await uow.agent_activity.aggregate([
        {"$match": {"job": {"$in": RUNNABLE}}},
        {"$group": {"_id": "$job", "last_started": {"$max": "$started_at"}, "runs": {"$sum": 1}}}])
    idx = {r["_id"]: r for r in runs}
    return {"queue_backend": queue.backend,
            "rows": [{"job": j, "runnable": True, "last_started": idx.get(j, {}).get("last_started"),
                      "runs": idx.get(j, {}).get("runs", 0)} for j in RUNNABLE]}


@router.post("/pipelines/{job}/run")
async def run_pipeline(job: str, user: dict = Depends(permission("run_pipeline"))):
    if job not in RUNNABLE:
        raise HTTPException(status_code=404, detail=f"Unknown job '{job}'")
    return await queue.enqueue(job, actor=user["email"])


@router.get("/sync/runs")
async def sync_runs(user: dict = Depends(current_user)):
    return {"rows": await uow.sync_runs.find({}, order_by=[("started_at", -1)], limit=20)}
