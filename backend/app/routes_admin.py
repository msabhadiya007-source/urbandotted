"""Connections + live ingest control plane. Read-only with respect to Shopify content."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .config import get_settings
from .deps import (audit, crawler, current_user, gsc_ingest, ledger, permission, pipelines,
                   policy, queue, shopify_sync, uow, webhooks)
from .services import secrets as secret_store
from .services.policy import SHOPIFY_WRITE_ACTIONS
from .services.webhooks import STAGE1_TOPICS, verify_hmac
from .sources import (BigQueryGSCSource, LiveShopifyAdapter, SearchAnalyticsAPISource,
                      SourceUnavailable)

router = APIRouter(prefix="/admin", tags=["admin"])
S = get_settings()


def _sanitise(exc: Exception) -> str:
    return secret_store.redact(f"{type(exc).__name__}: {exc}")[:400]


# ------------------------------------------------------------------ connections
class ShopifyCredentials(BaseModel):
    shop_domain: str = Field(min_length=4)
    admin_api_token: str = Field(min_length=10)
    webhook_secret: str | None = None


class GSCCredentials(BaseModel):
    site_url: str = Field(min_length=8)
    service_account_json: str = Field(min_length=50)


class BigQueryCredentials(BaseModel):
    project: str
    dataset: str = "searchconsole"
    location: str | None = None


class CrawlSettings(BaseModel):
    requests_per_sec: float = Field(ge=0.2, le=10)
    workers: int = Field(ge=1, le=10)


@router.get("/connections")
async def connections(user: dict = Depends(current_user)):
    s = get_settings()
    status = secret_store.status()
    verified = {v["provider"]: v for v in
                await uow.unscoped().repo("connection_state").find({}, limit=20)}
    for provider in ("shopify", "gsc", "bigquery"):
        status[provider]["verified"] = bool(verified.get(provider, {}).get("verified"))
        status[provider]["verified_at"] = verified.get(provider, {}).get("verified_at")
    status["data_mode"] = s.data_mode
    status["infra_adapter"] = "mongodb_dev_adapter" if s.demo_infra_mode else "postgresql_16"
    status["active_markets"] = s.active_markets
    status["gsc_bootstrap_months"] = s.gsc_bootstrap_months
    status["last_shopify_sync"] = (await uow.unscoped().sync_runs.find(
        {"kind": "shopify_full_sync"}, order_by=[("started_at", -1)], limit=1) or [None])[0]
    status["webhooks"] = await webhooks.stats()
    return status


def _mark_verified(provider: str, actor: str, extra: dict | None = None):
    return uow.unscoped().repo("connection_state").update_one({"provider": provider}, {
        "provider": provider, "verified": True, "verified_at": datetime.now(timezone.utc).isoformat(),
        "verified_by": actor, **(extra or {})}, upsert=True)


@router.post("/connections/shopify")
async def connect_shopify(payload: ShopifyCredentials, user: dict = Depends(permission("manage_budget"))):
    """Verifies with a read-only call FIRST and persists the credential only on success."""
    domain = payload.shop_domain.replace("https://", "").replace("http://", "").strip("/")
    try:
        verified = await LiveShopifyAdapter(shop_domain=domain,
                                           admin_token=payload.admin_api_token).verify()
    except Exception as exc:  # noqa: BLE001
        await audit.record(actor=user["email"], actor_role=user["role"],
                           action="connection.shopify_failed", entity_type="integration",
                           metadata={"error": _sanitise(exc), "shop_domain": domain})
        raise HTTPException(status_code=400, detail=_sanitise(exc))

    secret_store.write_secrets({
        "SHOPIFY_SHOP_DOMAIN": domain,
        "SHOPIFY_ADMIN_API_TOKEN": payload.admin_api_token,
        **({"SHOPIFY_WEBHOOK_SECRET": payload.webhook_secret} if payload.webhook_secret else {}),
    })
    get_settings.cache_clear()
    await _mark_verified("shopify", user["email"], {"shop_name": verified["shop_name"]})
    await audit.record(actor=user["email"], actor_role=user["role"], action="connection.shopify_verified",
                       entity_type="integration",
                       metadata={"shop": verified["shop_name"], "markets": len(verified["markets"])})
    return {"verified": True, "shopify": verified,
            "scopes_requested": LiveShopifyAdapter.read_only_scopes, "write_scopes_requested": []}


@router.post("/connections/gsc")
async def connect_gsc(payload: GSCCredentials, user: dict = Depends(permission("manage_budget"))):
    try:
        source = SearchAnalyticsAPISource(site_url=payload.site_url,
                                          service_account_json=payload.service_account_json)
        verified = await source.verify()
        verified["available_range"] = await source.available_range()
    except Exception as exc:  # noqa: BLE001
        await audit.record(actor=user["email"], actor_role=user["role"],
                           action="connection.gsc_failed", entity_type="integration",
                           metadata={"error": _sanitise(exc), "site_url": payload.site_url})
        raise HTTPException(status_code=400, detail=_sanitise(exc))

    secret_store.write_secrets({"GSC_SITE_URL": payload.site_url,
                                "GSC_SERVICE_ACCOUNT_JSON": payload.service_account_json})
    get_settings.cache_clear()
    await _mark_verified("gsc", user["email"], {"site_url": verified["site_url"],
                                               "permission_level": verified.get("permission_level")})
    await audit.record(actor=user["email"], actor_role=user["role"], action="connection.gsc_verified",
                       entity_type="integration", metadata={"site_url": verified["site_url"],
                                                            "permission": verified.get("permission_level")})
    return {"verified": True, "gsc": verified}


@router.post("/connections/bigquery")
async def connect_bigquery(payload: BigQueryCredentials, user: dict = Depends(permission("manage_budget"))):
    try:
        verified = await BigQueryGSCSource(project=payload.project, dataset=payload.dataset,
                                          location=payload.location).verify()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_sanitise(exc))

    secret_store.write_secrets({"BIGQUERY_PROJECT": payload.project, "BIGQUERY_DATASET": payload.dataset,
                                **({"BIGQUERY_LOCATION": payload.location} if payload.location else {})})
    get_settings.cache_clear()
    await _mark_verified("bigquery", user["email"], {"dataset": verified.get("dataset")})
    await audit.record(actor=user["email"], actor_role=user["role"], action="connection.bigquery_verified",
                       entity_type="integration", metadata=verified)
    return {"verified": True, "bigquery": verified,
            "note": "BigQuery is now the preferred ongoing source; the Search Analytics API remains "
                    "available for historical backfill and fallback."}


@router.post("/connections/crawl-settings")
async def set_crawl_settings(payload: CrawlSettings, user: dict = Depends(permission("manage_budget"))):
    secret_store.write_secrets({"CRAWL_REQUESTS_PER_SEC": str(payload.requests_per_sec),
                                "CRAWL_WORKERS": str(payload.workers)})
    get_settings.cache_clear()
    crawler.s = get_settings()
    crawler.limiter.rate = crawler.limiter.ceiling = payload.requests_per_sec
    await audit.record(actor=user["email"], actor_role=user["role"], action="crawl.settings_changed",
                       entity_type="crawler", metadata=payload.model_dump())
    return {"ok": True, "requests_per_sec": payload.requests_per_sec, "workers": payload.workers,
            "note": "The limiter is global: all workers share this combined ceiling."}


@router.post("/connections/activate-live")
async def activate_live(user: dict = Depends(permission("manage_budget"))):
    """Flips data mode to LIVE only after both sources verify. Never automatic, never silent."""
    state = {v["provider"]: v for v in await uow.unscoped().repo("connection_state").find({}, limit=20)}
    unverified = [p for p in ("shopify", "gsc") if not state.get(p, {}).get("verified")]
    if unverified:
        raise HTTPException(status_code=400,
                            detail=f"These connections have never verified: {', '.join(unverified)}")
    checks = {}
    try:
        checks["shopify"] = await LiveShopifyAdapter().verify()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Shopify not ready: {_sanitise(exc)}")
    try:
        checks["gsc"] = await SearchAnalyticsAPISource().verify()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"GSC not ready: {_sanitise(exc)}")

    secret_store.write_secrets({"LIVE_DATA_MODE": "true"})
    await audit.record(actor=user["email"], actor_role=user["role"], action="mode.activate_live",
                       entity_type="system", metadata={"shopify": checks["shopify"]["shop_name"],
                                                       "gsc": checks["gsc"]["site_url"]})
    return {"data_mode": "LIVE", "checks": checks,
            "restart_required": True,
            "note": "Seeded fixtures are excluded from every read in LIVE mode. DEMO mode is retained "
                    "as an explicit development adapter and can be re-enabled by an admin."}


@router.post("/connections/deactivate-live")
async def deactivate_live(user: dict = Depends(permission("manage_budget"))):
    secret_store.write_secrets({"LIVE_DATA_MODE": "false"})
    await audit.record(actor=user["email"], actor_role=user["role"], action="mode.deactivate_live",
                       entity_type="system", metadata={})
    return {"data_mode": "DEMO", "restart_required": True}


# ------------------------------------------------------------------ shopify
@router.post("/shopify/sync")
async def shopify_sync_run(background: bool = True, max_products: int | None = None,
                           user: dict = Depends(permission("run_pipeline"))):
    if background:
        asyncio.create_task(queue.enqueue("shopify_full_sync", actor=user["email"],
                                          max_products=max_products))
        return {"started": True, "job": "shopify_full_sync", "mode": "background",
                "poll": "/api/admin/shopify/sync/status"}
    return await queue.enqueue("shopify_full_sync", actor=user["email"], max_products=max_products)


@router.get("/shopify/sync/status")
async def shopify_sync_status(user: dict = Depends(current_user)):
    runs = await uow.unscoped().sync_runs.find({}, order_by=[("started_at", -1)], limit=10)
    return {"runs": runs, "catalogue": {
        "products": await uow.unscoped().products.count({"data_mode": "LIVE"}),
        "variants": await uow.unscoped().repo("product_variants").count({"data_mode": "LIVE"}),
        "collections": await uow.unscoped().collections.count({"data_mode": "LIVE"}),
        "product_market_rows": await uow.unscoped().product_market.count({"data_mode": "LIVE"}),
        "pages": await uow.unscoped().pages.count({"data_mode": "LIVE"}),
    }}


@router.post("/shopify/reconcile")
async def shopify_reconcile(user: dict = Depends(permission("run_pipeline"))):
    return await queue.enqueue("shopify_reconcile", actor=user["email"])


@router.post("/shopify/webhooks/register")
async def register_webhooks(request: Request, user: dict = Depends(permission("manage_budget"))):
    base = str(request.base_url).rstrip("/")
    return await webhooks.register(f"{base}/api/webhooks/shopify")


@router.get("/shopify/webhooks")
async def webhook_stats(user: dict = Depends(current_user)):
    return await webhooks.stats()


# ------------------------------------------------------------------ gsc
@router.post("/gsc/bootstrap")
async def gsc_bootstrap(months: int | None = None, background: bool = True,
                        user: dict = Depends(permission("run_pipeline"))):
    if background:
        asyncio.create_task(queue.enqueue("gsc_bootstrap", actor=user["email"], months=months))
        return {"started": True, "job": "gsc_bootstrap", "months": months or S.gsc_bootstrap_months,
                "poll": "/api/admin/gsc/status"}
    return await queue.enqueue("gsc_bootstrap", actor=user["email"], months=months)


@router.post("/gsc/daily")
async def gsc_daily(days: int = 3, prefer: str = "auto", user: dict = Depends(permission("run_pipeline"))):
    return await queue.enqueue("gsc_daily_ingest", actor=user["email"], days=days, prefer=prefer)


@router.get("/gsc/status")
async def gsc_status(user: dict = Depends(current_user)):
    live = uow.unscoped()
    rows = await live.gsc_performance.aggregate([
        {"$match": {"data_mode": "LIVE"}},
        {"$group": {"_id": {"market": "$market", "source": "$ingested_via"},
                    "rows": {"$sum": 1}, "impressions": {"$sum": "$impressions"},
                    "clicks": {"$sum": "$clicks"},
                    "first": {"$min": "$period_start"}, "last": {"$max": "$period_end"}}}])
    return {"by_market_and_source": [
        {"market": r["_id"]["market"], "source": r["_id"]["source"], "rows": r["rows"],
         "impressions": r["impressions"], "clicks": r["clicks"],
         "date_coverage": [r["first"], r["last"]]} for r in rows],
        "keywords": await live.keywords.count({"data_mode": "LIVE"}),
        "url_reconciliation": await live.repo("reports").find_one({"kind": "url_reconciliation"})}


@router.get("/gsc/url-reconciliation")
async def url_reconciliation(category: str | None = None, limit: int = 50, offset: int = 0,
                             user: dict = Depends(current_user)):
    live = uow.unscoped()
    where = {"category": category} if category else {}
    return {"report": await live.repo("reports").find_one({"kind": "url_reconciliation"}),
            "total": await live.repo("url_reconciliation").count(where),
            "rows": await live.repo("url_reconciliation").find(
                where, order_by=[("impressions", -1)], limit=min(limit, 200), offset=offset)}


@router.post("/gsc/url-reconciliation/run")
async def run_url_reconciliation(user: dict = Depends(permission("run_pipeline"))):
    return await queue.enqueue("gsc_url_reconciliation", actor=user["email"])


# ------------------------------------------------------------------ crawler
@router.post("/crawl/robots")
async def crawl_robots(user: dict = Depends(permission("run_pipeline"))):
    return await queue.enqueue("fetch_robots_and_sitemaps", actor=user["email"])


@router.post("/crawl/batch")
async def crawl_batch(limit: int = 50, background: bool = False,
                      user: dict = Depends(permission("run_pipeline"))):
    if background:
        asyncio.create_task(queue.enqueue("crawl_batch", actor=user["email"], limit=limit))
        return {"started": True, "job": "crawl_batch", "limit": limit}
    return await queue.enqueue("crawl_batch", actor=user["email"], limit=limit)


@router.post("/crawl/full")
async def crawl_full(batch_size: int = 200, max_batches: int = 5,
                     user: dict = Depends(permission("run_pipeline"))):
    asyncio.create_task(queue.enqueue("crawl_full", actor=user["email"],
                                      batch_size=batch_size, max_batches=max_batches))
    return {"started": True, "job": "crawl_full", "batch_size": batch_size, "max_batches": max_batches}


@router.get("/crawl/status")
async def crawl_status(user: dict = Depends(current_user)):
    live = uow.unscoped()
    inventory = await live.pages.count({"data_mode": "LIVE"})
    crawled = await live.page_market.count({"data_mode": "LIVE"})
    return {"live_state": crawler.state,
            "configured": {"requests_per_sec": crawler.s.crawl_requests_per_sec,
                           "effective_rate_per_sec": round(crawler.limiter.rate, 2),
                           "workers": crawler.s.crawl_workers,
                           "floor_rate_per_sec": crawler.s.crawl_min_requests_per_sec},
            "url_inventory": inventory, "urls_with_crawl_data": crawled,
            "coverage_pct": round(crawled / inventory * 100, 2) if inventory else 0.0,
            "runs": await live.repo("crawl_runs").find({}, order_by=[("started_at", -1)], limit=10),
            "hosts": await live.repo("crawl_config").find({}, limit=10)}


# ------------------------------------------------------------------ recompute + acceptance
@router.post("/intelligence/recompute")
async def recompute_all(user: dict = Depends(permission("run_pipeline"))):
    results = {}
    for job in ("recompute_opportunities", "detect_cannibalization", "detect_anomalies"):
        results[job] = await queue.enqueue(job, actor=user["email"])
    return results


@router.post("/intelligence/purge-fixtures")
async def purge_fixtures(user: dict = Depends(permission("manage_budget"))):
    """Removes seeded demo rows once live data is in place. Audit log is never touched."""
    live = uow.unscoped()
    removed = {}
    for table in ("products", "product_market", "collections", "pages", "page_market", "keywords",
                  "gsc_performance", "opportunity_scores", "technical_issues", "competitors",
                  "serp_snapshots", "cannibalization", "sync_runs"):
        removed[table] = await live.repo(table).delete({"data_mode": "DEMO"})
    await audit.record(actor=user["email"], actor_role=user["role"], action="fixtures.purged",
                       entity_type="system", metadata=removed)
    return {"removed": removed}


@router.get("/live-acceptance-report")
async def live_acceptance_report(request: Request, user: dict = Depends(current_user)):
    """The Stage 1 LIVE DATA ACCEPTANCE REPORT, computed from stored live rows only."""
    S = get_settings()
    live = uow.unscoped()
    live_only = {"data_mode": "LIVE"}

    sync = (await live.sync_runs.find({"kind": "shopify_full_sync"},
                                      order_by=[("started_at", -1)], limit=1) or [None])[0]
    catalogue = {
        "products": await live.products.count(live_only),
        "products_active": await live.products.count({**live_only, "status": "ACTIVE"}),
        "products_archived_or_draft": await live.products.count(
            {**live_only, "status": {"$nin": ["ACTIVE", None]}}),
        "variants": await live.repo("product_variants").count(live_only),
        "collections": await live.collections.count(live_only),
        "product_market_rows": await live.product_market.count(live_only),
        "pages": await live.pages.count(live_only),
        "demo_rows_still_present": await live.products.count({"data_mode": "DEMO"}),
    }
    market_rows = await live.product_market.aggregate([
        {"$match": live_only}, {"$group": {"_id": "$market", "n": {"$sum": 1},
                                           "available": {"$sum": {"$cond": ["$available", 1, 0]}}}}])
    gsc_rows = await live.gsc_performance.aggregate([
        {"$match": live_only},
        {"$group": {"_id": {"market": "$market", "source": "$ingested_via"}, "rows": {"$sum": 1},
                    "impressions": {"$sum": "$impressions"}, "clicks": {"$sum": "$clicks"},
                    "first": {"$min": "$period_start"}, "last": {"$max": "$period_end"}}}])
    tiers = await live.opportunity_scores.aggregate([
        {"$match": live_only},
        {"$group": {"_id": {"tier": "$tier", "market": "$market"}, "n": {"$sum": 1}}}])
    tier_dist: dict[str, dict] = {}
    for t in tiers:
        tier = t["_id"]["tier"]
        tier_dist.setdefault(tier, {"tier": tier, "total": 0})
        tier_dist[tier]["total"] += t["n"]
        tier_dist[tier][t["_id"]["market"]] = t["n"]

    top = {}
    for market in S.active_markets:
        top[market] = await live.opportunity_scores.find(
            {**live_only, "market": market}, order_by=[("score", -1)], limit=20)

    inventory = catalogue["pages"] or 1
    crawled = await live.page_market.count(live_only)
    crawl_runs = await live.repo("crawl_runs").find({}, order_by=[("started_at", -1)], limit=5)
    cost = await ledger.spend_summary()
    write_routes = [r.path for r in request.app.routes
                    if any(k in r.path for k in ("/shopify/write", "/publish", "/mutate"))]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_mode": S.data_mode,
        "provenance": {
            "shopify": "shopify_admin_graphql (read-only scopes)" if S.live_data_mode else "seed_fixture",
            "gsc_bootstrap": "gsc_search_analytics_api",
            "gsc_ongoing_preferred": "gsc_bigquery_bulk_export" if S.bigquery_project else "not_configured",
            "crawler": "internal read-only crawler",
            "infra_adapter": "mongodb_dev_adapter" if S.demo_infra_mode else "postgresql_16",
        },
        "catalogue": catalogue,
        "shopify_sync": (sync or {}).get("report"),
        "market_mapping": (sync or {}).get("market_mapping"),
        "market_rows": [{"market": m["_id"], "rows": m["n"], "available": m["available"]}
                        for m in market_rows],
        "gsc": {
            "by_market_and_source": [
                {"market": r["_id"]["market"], "source": r["_id"]["source"], "rows": r["rows"],
                 "impressions": r["impressions"], "clicks": r["clicks"],
                 "date_coverage": [r["first"], r["last"]]} for r in gsc_rows],
            "keywords_discovered": await live.keywords.count(live_only),
        },
        "url_reconciliation": await live.repo("reports").find_one({"kind": "url_reconciliation"}),
        "unmatched_by_category": {
            c["_id"]: c["n"] for c in await live.repo("url_reconciliation").aggregate([
                {"$group": {"_id": "$category", "n": {"$sum": 1}}}])},
        "crawler": {"url_inventory": inventory, "urls_with_crawl_data": crawled,
                    "coverage_pct": round(crawled / inventory * 100, 2),
                    "recent_runs": crawl_runs},
        "tier_distribution": sorted(tier_dist.values(), key=lambda x: x["tier"]),
        "cannibalization_findings": await live.cannibalization.count(live_only),
        "technical_issues_open": await live.technical_issues.count({**live_only, "status": "open"}),
        "top_20_opportunities": top,
        "paid_api_usage": {k: cost[k] for k in ("spend_usd", "global_cap_usd", "pct_used",
                                               "by_provider", "by_agent", "blocked_calls",
                                               "saved_by_cache_usd")},
        "failures_and_retries": {
            "sync_errors": (sync or {}).get("errors", []),
            "sync_retries": ((sync or {}).get("report") or {}).get("retries"),
            "crawl_failures": sum(r.get("failures", 0) for r in crawl_runs),
            "crawl_throttled_429": sum(r.get("throttled_429", 0) for r in crawl_runs),
            "failed_jobs": await live.agent_activity.count({"status": "failed"}),
            "webhook_events_failed": await live.repo("webhook_events").count({"status": "failed"}),
        },
        "stage1_invariants": {
            "shopify_write_route_count": len(write_routes),
            "shopify_write_routes": write_routes,
            "denied_action_types": len(SHOPIFY_WRITE_ACTIONS),
            "all_write_policies_deny": all(policy.classify(a)["decision"] == "DENY"
                                           for a in SHOPIFY_WRITE_ACTIONS),
            "executor": "no_op_logger",
            "shopify_scopes_requested": LiveShopifyAdapter.read_only_scopes,
            "shopify_write_scopes_requested": [],
        },
        "readiness": _readiness(catalogue, gsc_rows, crawled, inventory, S),
    }


def _readiness(catalogue, gsc_rows, crawled, inventory, S) -> dict:
    checks = {
        "shopify_catalogue_synced": catalogue["products"] > 0,
        "no_demo_rows_in_live_reads": catalogue["demo_rows_still_present"] == 0,
        "gsc_ingested": len(gsc_rows) > 0,
        "crawl_coverage_above_10pct": inventory > 0 and (crawled / inventory) > 0.10,
        "bigquery_configured": bool(S.bigquery_project and S.bigquery_dataset),
        "live_data_mode_on": S.live_data_mode,
    }
    return {"checks": checks, "ready_for_stage1_acceptance": all(checks.values()),
            "blocking": [k for k, v in checks.items() if not v]}


# ------------------------------------------------------------------ webhook receiver
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post("/shopify")
async def receive_shopify_webhook(request: Request):
    raw = await request.body()
    header_hmac = request.headers.get("X-Shopify-Hmac-Sha256")
    topic = request.headers.get("X-Shopify-Topic", "")
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    webhook_id = request.headers.get("X-Shopify-Webhook-Id")
    triggered = request.headers.get("X-Shopify-Triggered-At")

    if not verify_hmac(raw, header_hmac, get_settings().shopify_webhook_secret):
        await audit.record(actor=f"shopify:{shop or 'unknown'}", actor_role="webhook",
                           action="webhook.hmac_rejected", entity_type="shopify_webhook",
                           status=401, metadata={"topic": topic, "webhook_id": webhook_id})
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    if topic not in STAGE1_TOPICS:
        return {"status": "ignored_topic", "topic": topic}

    import json
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    return await webhooks.ingest(topic=topic, shop_domain=shop, webhook_id=webhook_id,
                                 triggered_at=triggered, payload=payload, verified=True)
