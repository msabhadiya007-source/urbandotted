"""Shopify webhook ingestion: HMAC verified, replay-resistant, queued, retryable, auditable.

Registration is control-plane only. No product/content/market write capability is created here.
"""
import base64
import hashlib
import hmac
from datetime import datetime, timezone

import httpx

from ..sources import LiveShopifyAdapter, SourceUnavailable
from .secrets import redact

STAGE1_TOPICS = [
    "products/create", "products/update", "products/delete",
    "collections/create", "collections/update", "collections/delete",
    "inventory_levels/update",
]


def verify_hmac(raw_body: bytes, header_hmac: str | None, secret: str | None) -> bool:
    if not (header_hmac and secret):
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode("utf-8"), header_hmac)


class WebhookService:
    def __init__(self, uow, audit, settings, sync_service):
        self.uow = uow
        self.audit = audit
        self.s = settings
        self.sync = sync_service

    async def register(self, callback_url: str) -> dict:
        """Registers Stage 1 read-relevant topics. Idempotent: existing topics are left alone."""
        adapter = LiveShopifyAdapter()
        existing = await adapter._gql(
            "{webhookSubscriptions(first:100){nodes{id topic endpoint{__typename "
            "... on WebhookHttpEndpoint{callbackUrl}}}}}")
        current = {n["topic"]: (n["endpoint"] or {}).get("callbackUrl")
                   for n in existing["webhookSubscriptions"]["nodes"]}
        results = []
        for topic in STAGE1_TOPICS:
            api_topic = topic.upper().replace("/", "_")
            if current.get(api_topic) == callback_url:
                results.append({"topic": topic, "status": "already_registered"})
                continue
            # webhookSubscriptionCreate is a subscription/control-plane call. It cannot read or
            # modify products, content or markets.
            mutation = (
                "mutation Reg($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {"
                " webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {"
                " webhookSubscription { id topic } userErrors { field message } } }")
            try:
                data = await adapter._gql(mutation, {
                    "topic": api_topic,
                    "sub": {"callbackUrl": callback_url, "format": "JSON"}})
                payload = data["webhookSubscriptionCreate"]
                errs = payload.get("userErrors") or []
                results.append({"topic": topic,
                                "status": "registered" if not errs else "rejected",
                                "errors": [e["message"] for e in errs]})
            except SourceUnavailable as exc:
                results.append({"topic": topic, "status": "failed", "errors": [redact(str(exc))]})
        await self.audit.record(actor="system", actor_role="system", action="shopify.webhooks_register",
                               entity_type="integration",
                               metadata={"callback_url": callback_url,
                                         "topics": [r["topic"] for r in results]})
        return {"callback_url": callback_url, "topics": results}

    async def ingest(self, *, topic: str, shop_domain: str, webhook_id: str | None,
                     triggered_at: str | None, payload: dict, verified: bool) -> dict:
        """Stores the event exactly once. Applied inline unless a full sync is in flight."""
        uow = self.uow.unscoped()
        events = uow.repo("webhook_events")
        if webhook_id and await events.find_one({"webhook_id": webhook_id}):
            return {"status": "duplicate_ignored", "webhook_id": webhook_id}

        gid = payload.get("admin_graphql_api_id")
        if not gid and payload.get("id"):
            kind = "Product" if topic.startswith("products") else "Collection"
            gid = f"gid://shopify/{kind}/{payload['id']}"

        row = {
            "webhook_id": webhook_id, "topic": topic, "shop_domain": shop_domain,
            "shopify_gid": gid, "triggered_at": triggered_at, "hmac_verified": verified,
            "payload": payload, "status": "queued", "attempts": 0,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        event_id = await events.insert(row)
        row["id"] = event_id

        syncing = await uow.sync_runs.count({"kind": "shopify_full_sync", "status": "running"})
        if syncing:
            status = "queued_during_bootstrap"
        else:
            try:
                await self.sync.apply_webhook(row)
                await events.update_one({"id": event_id}, {
                    "status": "applied", "applied_at": datetime.now(timezone.utc).isoformat()})
                status = "applied"
            except Exception as exc:  # noqa: BLE001
                await events.update_one({"id": event_id}, {
                    "status": "queued", "attempts": 1, "last_error": redact(str(exc))[:300]})
                status = "queued_for_retry"

        await self.audit.record(actor=f"shopify:{shop_domain}", actor_role="webhook",
                               action=f"webhook.{topic}", entity_type="shopify_webhook",
                               entity_id=event_id, metadata={"status": status, "verified": verified})
        return {"status": status, "event_id": event_id}

    async def stats(self) -> dict:
        uow = self.uow.unscoped()
        rows = await uow.repo("webhook_events").aggregate([
            {"$group": {"_id": {"topic": "$topic", "status": "$status"}, "n": {"$sum": 1}}}])
        by_topic: dict[str, dict] = {}
        for r in rows:
            topic = r["_id"]["topic"]
            by_topic.setdefault(topic, {"topic": topic, "applied": 0, "queued": 0, "failed": 0,
                                        "queued_during_bootstrap": 0})
            key = r["_id"]["status"]
            by_topic[topic][key] = by_topic[topic].get(key, 0) + r["n"]
        return {"subscribed_topics": STAGE1_TOPICS, "by_topic": list(by_topic.values()),
                "total_events": await uow.repo("webhook_events").count({}),
                "unverified_rejected": await uow.repo("webhook_events").count({"hmac_verified": False}),
                "recent": await uow.repo("webhook_events").find(
                    {}, order_by=[("received_at", -1)], limit=20,
                    select=["topic", "status", "shopify_gid", "received_at", "hmac_verified", "attempts"])}
