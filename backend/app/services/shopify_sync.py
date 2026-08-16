"""Shopify catalogue sync: idempotent, resumable, cursor-paginated. Read-only.

Race safety during bootstrap: webhook deliveries that arrive while a full sync is running are
queued (never applied inline) and drained by the reconciler once the sync completes, so an
in-flight sync page cannot overwrite a newer webhook state.
"""
from datetime import datetime, timezone

from ..sources import LiveShopifyAdapter, SourceUnavailable
from .secrets import redact

MARKET_HREFLANG = {"AU": "en-AU", "NZ": "en-NZ", "US": "en-US", "UK": "en-GB", "CA": "en-CA"}
COUNTRY_TO_MARKET = {"AU": "AU", "NZ": "NZ", "US": "US", "GB": "UK", "UK": "UK", "CA": "CA"}


def _gid_num(gid: str | None) -> str | None:
    return gid.rsplit("/", 1)[-1] if gid else None


def _words(html: str | None) -> int:
    if not html:
        return 0
    text = html
    for tag in ("<br>", "</p>", "</li>"):
        text = text.replace(tag, " ")
    while "<" in text and ">" in text:
        start = text.find("<")
        end = text.find(">", start)
        if end == -1:
            break
        text = text[:start] + " " + text[end + 1:]
    return len([w for w in text.split() if w.strip()])


class ShopifySyncService:
    """Persists the catalogue keyed on the stable Shopify GID."""

    def __init__(self, uow, audit, settings):
        self.uow = uow
        self.audit = audit
        self.s = settings

    def register(self, queue):
        queue.register("shopify_full_sync", self.full_sync, "shopify_sync")
        queue.register("shopify_reconcile", self.reconcile, "shopify_sync")
        queue.register("shopify_verify", self.verify, "shopify_sync")

    # ------------------------------------------------------------------ markets
    async def resolve_markets(self, adapter: LiveShopifyAdapter) -> dict:
        """Derives market -> URL prefix at runtime from Shopify Markets webPresence. No hard-coding."""
        shop = await adapter.shop()
        primary_host = ((shop.get("primaryDomain") or {}).get("host")
                        or shop.get("myshopifyDomain") or adapter.domain)
        markets = await adapter.market_config()
        mapping: dict[str, dict] = {}
        unmapped = []
        for m in markets:
            if not m.get("enabled"):
                continue
            presence = m.get("webPresence") or {}
            root_urls = presence.get("rootUrls") or []
            root = (root_urls[0]["url"].rstrip("/") if root_urls
                    else f"https://{(presence.get('domain') or {}).get('host') or primary_host}")
            codes = [r["code"] for r in (m.get("regions") or {}).get("nodes", []) if r and r.get("code")]
            claimed = {COUNTRY_TO_MARKET[c] for c in codes if c in COUNTRY_TO_MARKET}
            targets = claimed & set(self.s.active_markets)
            if not targets:
                unmapped.append({"market_handle": m["handle"], "countries": codes,
                                 "reason": "no active Stage 1 country in this Shopify market"})
                continue
            for market in targets:
                mapping[market] = {
                    "shopify_market_id": m["id"], "shopify_market_handle": m["handle"],
                    "shopify_market_name": m["name"], "primary": bool(m.get("primary")),
                    "root_url": root, "subfolder_suffix": presence.get("subfolderSuffix"),
                    "default_locale": presence.get("defaultLocale"),
                    "countries": codes, "hreflang": MARKET_HREFLANG.get(market),
                }
        missing = [m for m in self.s.active_markets if m not in mapping]
        return {"mapping": mapping, "unmapped_shopify_markets": unmapped, "missing_active_markets": missing,
                "primary_host": primary_host}

    # ------------------------------------------------------------------ full sync
    async def full_sync(self, resume: bool = True, max_products: int | None = None) -> dict:
        adapter = LiveShopifyAdapter()
        started = datetime.now(timezone.utc)
        uow = self.uow.unscoped()

        run = None
        if resume:
            open_runs = await uow.sync_runs.find(
                {"kind": "shopify_full_sync", "status": "running"}, order_by=[("started_at", -1)], limit=1)
            run = open_runs[0] if open_runs else None
        markets_info = await self.resolve_markets(adapter)
        if not markets_info["mapping"]:
            raise SourceUnavailable(
                "No enabled Shopify market maps to the active Stage 1 markets "
                f"({', '.join(self.s.active_markets)}). Check Markets configuration.")

        if run:
            run_id = run["id"]
            product_cursor = run.get("product_cursor")
            collection_cursor = run.get("collection_cursor")
            counters = run.get("counters", {})
        else:
            counters = {"products": 0, "variants": 0, "collections": 0, "product_market": 0,
                        "active": 0, "archived_or_draft": 0, "invalid": 0}
            run_id = await uow.sync_runs.insert({
                "kind": "shopify_full_sync", "status": "running", "data_mode": "LIVE",
                "source": "shopify_admin_graphql", "markets": self.s.active_markets,
                "market_mapping": markets_info["mapping"],
                "unmapped_shopify_markets": markets_info["unmapped_shopify_markets"],
                "started_at": started.isoformat(), "counters": counters,
                "product_cursor": None, "collection_cursor": None, "errors": [],
            })
            product_cursor = collection_cursor = None

        invalid: list[dict] = []
        errors: list[str] = []

        try:
            async for node, cursor in adapter.iter_collections(collection_cursor):
                handle = node.get("handle")
                if not handle:
                    invalid.append({"type": "collection", "shopify_id": node.get("id"), "reason": "missing handle"})
                    continue
                seo = node.get("seo") or {}
                await uow.collections.update_one({"shopify_id": node["id"]}, {
                    "shopify_id": node["id"], "shopify_numeric_id": _gid_num(node["id"]),
                    "handle": handle, "title": node.get("title"),
                    "seo_title": seo.get("title"), "seo_description": seo.get("description"),
                    "description_words": _words(node.get("descriptionHtml")),
                    "product_count": (node.get("productsCount") or {}).get("count"),
                    "sort_order": node.get("sortOrder"),
                    "image_url": (node.get("image") or {}).get("url"),
                    "image_alt_missing": not ((node.get("image") or {}).get("altText")),
                    "updated_at": node.get("updatedAt"), "data_mode": "LIVE",
                    "source": "shopify_admin_graphql", "synced_at": datetime.now(timezone.utc).isoformat(),
                }, upsert=True)
                counters["collections"] += 1
                for market, cfg in markets_info["mapping"].items():
                    url = f"{cfg['root_url']}/collections/{handle}"
                    await uow.pages.update_one({"url": url}, {
                        "url": url, "page_type": "collection", "entity_handle": handle,
                        "market": market, "title": node.get("title"), "shopify_id": node["id"],
                        "data_mode": "LIVE", "source": "shopify_admin_graphql",
                    }, upsert=True)
                if counters["collections"] % 50 == 0:
                    await uow.sync_runs.update_one({"id": run_id},
                                                   {"collection_cursor": cursor, "counters": counters})

            async for node, cursor in adapter.iter_products(product_cursor):
                handle = node.get("handle")
                if not handle:
                    invalid.append({"type": "product", "shopify_id": node.get("id"), "reason": "missing handle"})
                    continue
                seo = node.get("seo") or {}
                variants = (node.get("variants") or {}).get("nodes", [])
                images = (node.get("images") or {}).get("nodes", [])
                status = (node.get("status") or "").upper()
                collections = [c["handle"] for c in (node.get("collections") or {}).get("nodes", [])]
                metafields = {f"{m['namespace']}.{m['key']}": m["value"]
                              for m in (node.get("metafields") or {}).get("nodes", [])}
                inventory = sum(int(v.get("inventoryQuantity") or 0) for v in variants)

                await uow.products.update_one({"shopify_id": node["id"]}, {
                    "shopify_id": node["id"], "shopify_numeric_id": _gid_num(node["id"]),
                    "handle": handle, "title": node.get("title"),
                    "product_type": node.get("productType"), "vendor": node.get("vendor"),
                    "status": status, "tags": node.get("tags") or [],
                    "collection_handle": collections[0] if collections else None,
                    "collection_handles": collections,
                    "seo_title": seo.get("title"), "seo_description": seo.get("description"),
                    "description_words": _words(node.get("descriptionHtml")),
                    "image_count": len(images),
                    "image_alt_missing": any(not (i.get("altText") or "").strip() for i in images) or not images,
                    "variant_count": len(variants), "inventory_total": inventory,
                    "metafields": metafields, "vertical": "homeware",
                    "created_at": node.get("createdAt"), "updated_at": node.get("updatedAt"),
                    "online_store_url": node.get("onlineStoreUrl"),
                    "data_mode": "LIVE", "source": "shopify_admin_graphql",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                }, upsert=True)
                counters["products"] += 1
                counters["active" if status == "ACTIVE" else "archived_or_draft"] += 1

                for v in variants:
                    await uow.repo("product_variants").update_one({"shopify_id": v["id"]}, {
                        "shopify_id": v["id"], "product_shopify_id": node["id"], "sku": v.get("sku"),
                        "title": v.get("title"), "price": v.get("price"),
                        "compare_at_price": v.get("compareAtPrice"),
                        "inventory_quantity": v.get("inventoryQuantity"),
                        "available": v.get("availableForSale"), "data_mode": "LIVE",
                    }, upsert=True)
                    counters["variants"] += 1

                for market, cfg in markets_info["mapping"].items():
                    url = f"{cfg['root_url']}/products/{handle}"
                    await uow.product_market.update_one(
                        {"product_shopify_id": node["id"], "market": market}, {
                            "product_shopify_id": node["id"], "product_handle": handle,
                            "market": market, "url": url, "hreflang": cfg["hreflang"],
                            "shopify_market_id": cfg["shopify_market_id"],
                            "available": any(v.get("availableForSale") for v in variants),
                            "inventory_quantity": inventory,
                            "price": variants[0].get("price") if variants else None,
                            "published": status == "ACTIVE", "data_mode": "LIVE",
                            "source": "shopify_admin_graphql",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }, upsert=True)
                    await uow.pages.update_one({"url": url}, {
                        "url": url, "page_type": "product", "entity_handle": handle, "market": market,
                        "title": node.get("title"), "shopify_id": node["id"],
                        "data_mode": "LIVE", "source": "shopify_admin_graphql",
                    }, upsert=True)
                    counters["product_market"] += 1

                if counters["products"] % 50 == 0:
                    await uow.sync_runs.update_one({"id": run_id},
                                                   {"product_cursor": cursor, "counters": counters})
                if max_products and counters["products"] >= max_products:
                    break
        except SourceUnavailable as exc:
            errors.append(redact(str(exc)))
            await uow.sync_runs.update_one({"id": run_id}, {
                "status": "interrupted_resumable", "counters": counters, "errors": errors,
                "finished_at": datetime.now(timezone.utc).isoformat()})
            raise

        finished = datetime.now(timezone.utc)
        report = {
            "run_id": run_id, "counters": counters,
            "market_mapping": {k: {"root_url": v["root_url"], "hreflang": v["hreflang"],
                                   "shopify_market_handle": v["shopify_market_handle"],
                                   "countries": v["countries"]}
                               for k, v in markets_info["mapping"].items()},
            "unmapped_shopify_markets": markets_info["unmapped_shopify_markets"],
            "missing_active_markets": markets_info["missing_active_markets"],
            "invalid_records": invalid[:50], "invalid_count": len(invalid),
            "duration_seconds": round((finished - started).total_seconds(), 1),
            "requests": adapter.stats["requests"], "retries": adapter.stats["retries"],
            "throttled": adapter.stats["throttled"], "errors": errors,
        }
        await uow.sync_runs.update_one({"id": run_id}, {
            "status": "success", "counters": counters, "invalid_count": len(invalid),
            "invalid_records": invalid[:50], "report": report,
            "finished_at": finished.isoformat(),
            "duration_seconds": report["duration_seconds"],
        })
        # Drain any webhook events that arrived during the bootstrap.
        drained = await self.drain_pending_webhooks()
        report["webhook_events_drained_after_sync"] = drained
        return report

    # ------------------------------------------------------------------ webhook drain
    async def drain_pending_webhooks(self) -> int:
        uow = self.uow.unscoped()
        pending = await uow.repo("webhook_events").find({"status": "queued"},
                                                        order_by=[("received_at", 1)], limit=1000)
        applied = 0
        for event in pending:
            try:
                await self.apply_webhook(event)
                await uow.repo("webhook_events").update_one(
                    {"id": event["id"]}, {"status": "applied",
                                          "applied_at": datetime.now(timezone.utc).isoformat()})
                applied += 1
            except Exception as exc:  # noqa: BLE001
                attempts = int(event.get("attempts", 0)) + 1
                await uow.repo("webhook_events").update_one({"id": event["id"]}, {
                    "status": "queued" if attempts < 5 else "failed", "attempts": attempts,
                    "last_error": redact(str(exc))[:300]})
        return applied

    async def apply_webhook(self, event: dict) -> None:
        """Idempotent, order-safe: an older payload never overwrites newer stored state."""
        uow = self.uow.unscoped()
        topic = event["topic"]
        payload = event.get("payload") or {}
        shopify_id = event.get("shopify_gid")
        if not shopify_id:
            return

        if topic.endswith("/delete"):
            table = "products" if topic.startswith("products") else "collections"
            await uow.repo(table).update_one({"shopify_id": shopify_id}, {
                "status": "DELETED_IN_SHOPIFY", "deleted_at": datetime.now(timezone.utc).isoformat()})
            return

        updated_at = payload.get("updated_at") or payload.get("updatedAt")
        table = "products" if topic.startswith("products") else "collections"
        existing = await uow.repo(table).find_one({"shopify_id": shopify_id})
        if existing and updated_at and existing.get("updated_at") and updated_at <= existing["updated_at"]:
            return  # stale / duplicate delivery

        if table == "products":
            values = {
                "shopify_id": shopify_id, "handle": payload.get("handle"),
                "title": payload.get("title"), "product_type": payload.get("product_type"),
                "vendor": payload.get("vendor"), "status": (payload.get("status") or "").upper(),
                "variant_count": len(payload.get("variants") or []),
                "inventory_total": sum(int(v.get("inventory_quantity") or 0)
                                       for v in payload.get("variants") or []),
                "image_count": len(payload.get("images") or []),
                "updated_at": updated_at, "data_mode": "LIVE", "source": "shopify_webhook",
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            values = {"shopify_id": shopify_id, "handle": payload.get("handle"),
                      "title": payload.get("title"), "updated_at": updated_at,
                      "data_mode": "LIVE", "source": "shopify_webhook",
                      "synced_at": datetime.now(timezone.utc).isoformat()}
        await uow.repo(table).update_one({"shopify_id": shopify_id}, values, upsert=True)

    # ------------------------------------------------------------------ reconciliation
    async def reconcile(self) -> dict:
        """Nightly safety net for dropped or delayed webhooks. Stays enabled permanently."""
        adapter = LiveShopifyAdapter()
        uow = self.uow.unscoped()
        started = datetime.now(timezone.utc)
        drained = await self.drain_pending_webhooks()

        seen: set[str] = set()
        stale, created = 0, 0
        async for node, _cursor in adapter.iter_products(None):
            seen.add(node["id"])
            local = await uow.products.find_one({"shopify_id": node["id"]})
            if not local:
                created += 1
                await uow.products.update_one({"shopify_id": node["id"]}, {
                    "shopify_id": node["id"], "handle": node.get("handle"), "title": node.get("title"),
                    "status": (node.get("status") or "").upper(), "updated_at": node.get("updatedAt"),
                    "data_mode": "LIVE", "source": "shopify_reconciler",
                    "synced_at": started.isoformat()}, upsert=True)
            elif node.get("updatedAt") and node["updatedAt"] != local.get("updated_at"):
                stale += 1
                await uow.products.update_one({"shopify_id": node["id"]}, {
                    "title": node.get("title"), "status": (node.get("status") or "").upper(),
                    "updated_at": node.get("updatedAt"), "source": "shopify_reconciler",
                    "synced_at": datetime.now(timezone.utc).isoformat()})

        local_all = await uow.products.find({"data_mode": "LIVE"}, limit=100000,
                                            select=["shopify_id", "status"])
        missing = [p["shopify_id"] for p in local_all
                   if p.get("shopify_id") not in seen and p.get("status") != "DELETED_IN_SHOPIFY"]
        for gid in missing:
            await uow.products.update_one({"shopify_id": gid}, {
                "status": "MISSING_IN_SHOPIFY", "flagged_at": datetime.now(timezone.utc).isoformat()})

        report = {"shopify_products_seen": len(seen), "created_locally": created,
                  "refreshed_stale": stale, "flagged_missing_in_shopify": len(missing),
                  "webhook_events_drained": drained,
                  "requests": adapter.stats["requests"], "retries": adapter.stats["retries"],
                  "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1)}
        await uow.sync_runs.insert({"kind": "shopify_reconcile", "status": "success", "data_mode": "LIVE",
                                    "source": "shopify_reconciler", "report": report,
                                    "started_at": started.isoformat(),
                                    "finished_at": datetime.now(timezone.utc).isoformat()})
        return report

    async def verify(self) -> dict:
        return await LiveShopifyAdapter().verify()
