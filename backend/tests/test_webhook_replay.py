"""Shopify webhook HMAC / idempotency / order-safety tests.

Requires SHOPIFY_WEBHOOK_SECRET to be set in /app/backend/.env and the backend restarted.
Test rows are removed in the module teardown.
"""
import base64
import hashlib
import hmac
import json
import os
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
backend_env = dotenv_values("/app/backend/.env")
SECRET = backend_env.get("SHOPIFY_WEBHOOK_SECRET")
TEST_GID = "gid://shopify/Product/99900001"
TEST_PRODUCT_ID = 99900001


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(backend_env["MONGO_URL"])
    yield client[backend_env["DB_NAME"]]
    client.close()


@pytest.fixture(scope="module")
def H(mongo):
    for attempt in range(4):
        r = requests.post(f"{API}/auth/login", timeout=30, json={
            "email": "admin@urbandotted.com", "password": "Stage1Admin!2026"})
        if r.status_code == 200:
            return {"Authorization": f"Bearer {r.json()['access_token']}"}
        if r.status_code == 429:
            mongo.login_attempts.delete_many({"identifier": {"$regex": "admin@urbandotted.com"}})
            continue
        pytest.fail(f"login failed {r.status_code}: {r.text[:200]}")
    pytest.fail("login rate limited")


@pytest.fixture(scope="module", autouse=True)
def cleanup(mongo):
    yield
    mongo.webhook_events.delete_many({"webhook_id": {"$regex": "^TEST-"}})
    mongo.products.delete_many({"shopify_id": TEST_GID})


def sign(raw: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), raw, hashlib.sha256).digest()).decode()


def post(raw: bytes, webhook_id: str, signed: bool = True, topic: str = "products/update"):
    headers = {"Content-Type": "application/json", "X-Shopify-Topic": topic,
               "X-Shopify-Shop-Domain": "test-store.myshopify.com",
               "X-Shopify-Webhook-Id": webhook_id,
               "X-Shopify-Triggered-At": "2026-07-01T00:00:00Z"}
    if signed:
        headers["X-Shopify-Hmac-Sha256"] = sign(raw)
    return requests.post(f"{API}/webhooks/shopify", data=raw, headers=headers, timeout=30)


pytestmark = pytest.mark.skipif(not SECRET, reason="SHOPIFY_WEBHOOK_SECRET not configured")


def body(updated_at: str, title: str) -> bytes:
    return json.dumps({"id": TEST_PRODUCT_ID, "handle": "test-webhook-product",
                       "title": title, "status": "active", "updated_at": updated_at,
                       "variants": [], "images": []}).encode()


class TestWebhookReplayAndOrder:
    def test_signed_delivery_accepted(self, mongo):
        wid = "TEST-replay-1"
        raw = body("2026-06-01T10:00:00Z", "Newer Title")
        r = post(raw, wid)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert r.json()["status"] in ("applied", "queued_during_bootstrap",
                                     "queued_for_retry"), r.json()
        assert mongo.webhook_events.count_documents({"webhook_id": wid}) == 1
        stored = mongo.products.find_one({"shopify_id": TEST_GID})
        assert stored is not None, "webhook did not persist the product"
        assert stored["title"] == "Newer Title"
        assert stored["data_mode"] == "LIVE"

    def test_duplicate_webhook_id_ignored(self, mongo):
        wid = "TEST-replay-1"
        raw = body("2026-06-01T10:00:00Z", "Newer Title")
        r = post(raw, wid)
        assert r.status_code == 200, r.text[:200]
        assert r.json()["status"] == "duplicate_ignored", r.json()
        assert mongo.webhook_events.count_documents({"webhook_id": wid}) == 1, "replay stored twice"

    def test_older_payload_does_not_regress(self, mongo):
        raw = body("2026-01-01T10:00:00Z", "STALE Title")
        r = post(raw, "TEST-replay-stale")
        assert r.status_code == 200, r.text[:200]
        stored = mongo.products.find_one({"shopify_id": TEST_GID})
        assert stored["title"] == "Newer Title", f"stale delivery regressed state: {stored['title']}"
        assert stored["updated_at"] == "2026-06-01T10:00:00Z"

    def test_unknown_topic_ignored(self):
        raw = json.dumps({"id": 1}).encode()
        headers = {"Content-Type": "application/json", "X-Shopify-Topic": "orders/create",
                   "X-Shopify-Hmac-Sha256": sign(raw),
                   "X-Shopify-Webhook-Id": f"TEST-topic-{uuid.uuid4()}"}
        r = requests.post(f"{API}/webhooks/shopify", data=raw, headers=headers, timeout=30)
        assert r.status_code == 200 and r.json()["status"] == "ignored_topic", r.text[:200]

    def test_bad_signature_rejected_no_row(self, mongo):
        wid = "TEST-badsig"
        raw = body("2026-06-02T10:00:00Z", "Should Not Apply")
        r = post(raw, wid, signed=False)
        assert r.status_code == 401, r.status_code
        assert mongo.webhook_events.count_documents({"webhook_id": wid}) == 0
        stored = mongo.products.find_one({"shopify_id": TEST_GID})
        assert stored["title"] == "Newer Title"

    def test_stats_and_no_secret_leak(self, H):
        r = requests.get(f"{API}/admin/shopify/webhooks", headers=H, timeout=30)
        assert r.status_code == 200
        assert SECRET not in r.text, "webhook secret leaked in stats response"
        assert r.json()["total_events"] >= 2
