"""Stage 1 LIVE DATA control-plane tests: connections, secret hygiene, rollback, guard rails,
webhook HMAC, live-endpoint failure handling, acceptance report and DEMO fixture scoping."""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
BACKEND_ENV = "/app/backend/.env"

BOGUS_TOKEN = "shpat_TESTbogus0000000000000000000deadbeef"
BOGUS_PK_MARKER = "TESTPRIVATEKEYMARKER9f2b"
BOGUS_SA = json.dumps({
    "type": "service_account", "project_id": "test-proj",
    "private_key_id": "abc123", "client_email": "test-sa@test-proj.iam.gserviceaccount.com",
    "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token",
    "private_key": f"-----BEGIN PRIVATE KEY-----\n{BOGUS_PK_MARKER}\n-----END PRIVATE KEY-----\n",
})


@pytest.fixture(scope="session")
def creds():
    return {"email": "admin@urbandotted.com", "password": "Stage1Admin!2026"}


def _clear_lockout(email: str):
    """The regression suite deliberately locks the admin out; clear it so parallel
    workers are not blocked by another test file's brute-force scenario."""
    try:
        from dotenv import dotenv_values as _dv
        from pymongo import MongoClient
        env = _dv("/app/backend/.env")
        client = MongoClient(env["MONGO_URL"])
        client[env["DB_NAME"]].login_attempts.delete_many({"identifier": {"$regex": email}})
        client.close()
    except Exception as exc:  # noqa: BLE001
        print(f"lockout cleanup skipped: {exc}")


@pytest.fixture(scope="session")
def H(creds):
    for attempt in range(4):
        r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
        if r.status_code == 200:
            return {"Authorization": f"Bearer {r.json()['access_token']}"}
        if r.status_code == 429:
            _clear_lockout(creds["email"])
            time.sleep(2 * (attempt + 1))
            continue
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    pytest.fail("login failed after retries (rate limited)")


def env_text():
    return open(BACKEND_ENV).read()


# ------------------------------------------------------------------ connections presence-only
class TestConnectionsStatus:
    def test_presence_only_no_secrets(self, H):
        r = requests.get(f"{API}/admin/connections", headers=H, timeout=30)
        assert r.status_code == 200, r.text
        body = r.text
        data = r.json()
        assert data["shopify"]["required_read_scopes"], data
        assert data["shopify"]["write_scopes_requested"] == []
        assert isinstance(data["shopify"]["admin_token_configured"], bool)
        # no secret material anywhere in the response
        for needle in ("shpat_", "PRIVATE KEY", "private_key", "admin_api_token",
                       "service_account_json"):
            assert needle not in body, f"secret-ish token '{needle}' leaked in /connections"
        assert data["live_data_mode"] is False
        assert data["data_mode"] == "DEMO"

    def test_requires_auth(self):
        assert requests.get(f"{API}/admin/connections", timeout=30).status_code == 401


# ------------------------------------------------------------------ credential failure + rollback
class TestShopifyCredentialFailure:
    def test_bogus_shopify_rejected_sanitised_and_rolled_back(self, H):
        before = requests.get(f"{API}/admin/connections", headers=H, timeout=30).json()
        r = requests.post(f"{API}/admin/connections/shopify", headers=H, timeout=90, json={
            "shop_domain": "nonexistent-test-store-9f2b.myshopify.com",
            "admin_api_token": BOGUS_TOKEN})
        assert 400 <= r.status_code < 500, f"expected 4xx got {r.status_code}: {r.text[:300]}"
        assert BOGUS_TOKEN not in r.text
        assert "shpat_TESTbogus" not in r.text
        assert "PRIVATE KEY" not in r.text
        # rollback: env must not retain the bogus token
        assert BOGUS_TOKEN not in env_text(), "bogus SHOPIFY_ADMIN_API_TOKEN persisted in .env"
        after = requests.get(f"{API}/admin/connections", headers=H, timeout=30).json()
        assert after["shopify"]["admin_token_configured"] == \
            before["shopify"]["admin_token_configured"]
        assert after["shopify"]["shop_domain"] == before["shopify"]["shop_domain"]
        # the rejected domain must never be retained as the configured store
        assert after["shopify"]["shop_domain"] != "nonexistent-test-store-9f2b.myshopify.com"
        assert "SHOPIFY_ADMIN_API_TOKEN=\"shpat_" not in env_text(), \
            "an unverified Shopify token is persisted in the backend env"

    def test_no_token_in_backend_logs(self):
        out = subprocess.run("grep -l 'shpat_TESTbogus' /var/log/supervisor/backend.*.log",
                             shell=True, capture_output=True, text=True)
        assert out.returncode != 0, f"token leaked into logs: {out.stdout}"


class TestGSCCredentialFailure:
    def test_invalid_json_rejected(self, H):
        r = requests.post(f"{API}/admin/connections/gsc", headers=H, timeout=60, json={
            "site_url": "https://urbandotted.com/", "service_account_json": "{not-json" + "x" * 60})
        assert 400 <= r.status_code < 500, r.text[:300]
        assert "PRIVATE KEY" not in r.text

    def test_valid_json_unauthorised_rejected_and_rolled_back(self, H):
        before = requests.get(f"{API}/admin/connections", headers=H, timeout=30).json()
        r = requests.post(f"{API}/admin/connections/gsc", headers=H, timeout=90, json={
            "site_url": "https://urbandotted.com/", "service_account_json": BOGUS_SA})
        assert 400 <= r.status_code < 500, f"{r.status_code}: {r.text[:300]}"
        assert BOGUS_PK_MARKER not in r.text, "private key echoed in error response"
        assert "BEGIN PRIVATE KEY" not in r.text
        assert BOGUS_PK_MARKER not in env_text(), "bogus service account persisted in .env"
        after = requests.get(f"{API}/admin/connections", headers=H, timeout=30).json()
        assert after["gsc"]["service_account_configured"] == \
            before["gsc"]["service_account_configured"]
        assert after["gsc"]["site_url"] == before["gsc"]["site_url"]

    def test_private_key_not_in_logs(self):
        out = subprocess.run(f"grep -l '{BOGUS_PK_MARKER}' /var/log/supervisor/backend.*.log",
                             shell=True, capture_output=True, text=True)
        assert out.returncode != 0, f"private key leaked into logs: {out.stdout}"


# ------------------------------------------------------------------ activation guard
class TestActivateLiveGuard:
    def test_refuses_without_verified_sources(self, H):
        r = requests.post(f"{API}/admin/connections/activate-live", headers=H, timeout=60)
        assert 400 <= r.status_code < 500, f"activation must refuse, got {r.status_code}"
        mode = requests.get(f"{API}/meta/mode", headers=H, timeout=30).json()
        assert mode.get("data_mode") == "DEMO", mode
        assert mode.get("live_data_mode") is False, mode
        assert 'LIVE_DATA_MODE="true"' not in env_text()

    def test_requires_auth(self):
        assert requests.post(f"{API}/admin/connections/activate-live",
                             timeout=30).status_code == 401


# ------------------------------------------------------------------ crawl settings
class TestCrawlSettings:
    def test_valid_settings_applied(self, H):
        r = requests.post(f"{API}/admin/connections/crawl-settings", headers=H, timeout=30,
                          json={"requests_per_sec": 2.5, "workers": 3})
        assert r.status_code == 200, r.text
        assert r.json()["requests_per_sec"] == 2.5
        st = requests.get(f"{API}/admin/crawl/status", headers=H, timeout=30)
        assert st.status_code == 200, st.text
        cfg = st.json()["configured"]
        assert cfg["requests_per_sec"] == 2.5
        assert cfg["workers"] == 3
        assert "effective_rate_per_sec" in cfg and "floor_rate_per_sec" in cfg

    def test_out_of_range_rejected(self, H):
        r = requests.post(f"{API}/admin/connections/crawl-settings", headers=H, timeout=30,
                          json={"requests_per_sec": 50, "workers": 3})
        assert r.status_code == 422, r.status_code
        r2 = requests.post(f"{API}/admin/connections/crawl-settings", headers=H, timeout=30,
                           json={"requests_per_sec": 3, "workers": 99})
        assert r2.status_code == 422, r2.status_code

    def test_restore_defaults(self, H):
        r = requests.post(f"{API}/admin/connections/crawl-settings", headers=H, timeout=30,
                          json={"requests_per_sec": 3, "workers": 3})
        assert r.status_code == 200


# ------------------------------------------------------------------ webhook HMAC rejection
class TestWebhookHmacRejection:
    def test_missing_hmac_rejected_and_audited(self, H):
        before = requests.get(f"{API}/admin/shopify/webhooks", headers=H, timeout=30).json()
        payload = json.dumps({"id": 999111, "updated_at": "2026-01-01T00:00:00Z"})
        wid = f"TEST-nohmac-{uuid.uuid4()}"
        r = requests.post(f"{API}/webhooks/shopify", data=payload, timeout=30, headers={
            "Content-Type": "application/json", "X-Shopify-Topic": "products/update",
            "X-Shopify-Shop-Domain": "test.myshopify.com", "X-Shopify-Webhook-Id": wid})
        assert r.status_code == 401, f"{r.status_code}: {r.text[:200]}"
        after = requests.get(f"{API}/admin/shopify/webhooks", headers=H, timeout=30).json()
        assert after["total_events"] == before["total_events"], "row created for rejected delivery"
        audit = requests.get(f"{API}/audit", headers=H, timeout=30,
                             params={"action": "webhook.hmac_rejected", "limit": 5}).json()
        assert audit["total"] >= 1, "hmac rejection not audited"

    def test_wrong_hmac_rejected(self, H):
        payload = json.dumps({"id": 999112})
        r = requests.post(f"{API}/webhooks/shopify", data=payload, timeout=30, headers={
            "Content-Type": "application/json", "X-Shopify-Topic": "products/update",
            "X-Shopify-Hmac-Sha256": base64.b64encode(b"wrong-signature").decode(),
            "X-Shopify-Shop-Domain": "test.myshopify.com"})
        assert r.status_code == 401, r.status_code


# ------------------------------------------------------------------ live endpoints fail cleanly
class TestLiveEndpointsFailCleanly:
    @pytest.mark.parametrize("path,params", [
        ("/admin/shopify/sync", {"background": "false"}),
        ("/admin/gsc/daily", {"days": 1}),
        ("/admin/crawl/robots", {}),
        ("/admin/crawl/batch", {"limit": 5}),
    ])
    def test_reports_failed_job_not_500(self, H, path, params):
        r = requests.post(f"{API}{path}", headers=H, params=params, timeout=120)
        assert r.status_code < 500, f"{path} crashed: {r.status_code} {r.text[:300]}"
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        body = r.json()
        # crawler/robots jobs may legitimately succeed with an empty live inventory
        assert "status" in body, body
        if body["status"] == "failed":
            assert body.get("error"), body
            assert "shpat_" not in json.dumps(body)

    def test_failures_visible_in_activity(self, H):
        r = requests.get(f"{API}/agents/activity", headers=H, timeout=30, params={"limit": 50})
        assert r.status_code == 200, r.text
        rows = r.json().get("rows", r.json().get("activity", []))
        assert rows, "no agent activity rows"
        jobs = {row["job"] for row in rows}
        assert "shopify_full_sync" in jobs or "gsc_daily_ingest" in jobs, jobs
        failed = [row for row in rows if row.get("status") == "failed"]
        assert failed, "live-source failures are not visible in /api/agents/activity"
        assert all("shpat_" not in (row.get("error") or "") for row in failed)


# ------------------------------------------------------------------ acceptance report
REQUIRED_SECTIONS = ["provenance", "catalogue", "market_mapping", "gsc", "url_reconciliation",
                     "unmatched_by_category", "crawler", "tier_distribution",
                     "top_20_opportunities", "paid_api_usage", "failures_and_retries",
                     "stage1_invariants", "readiness"]


class TestAcceptanceReport:
    def test_sections_present(self, H):
        r = requests.get(f"{API}/admin/live-acceptance-report", headers=H, timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        missing = [s for s in REQUIRED_SECTIONS if s not in data]
        assert not missing, f"missing sections: {missing}"
        assert set(data["top_20_opportunities"].keys()) >= {"AU", "NZ"}

    def test_demo_mode_counts_zero_and_not_ready(self, H):
        data = requests.get(f"{API}/admin/live-acceptance-report", headers=H, timeout=60).json()
        assert data["data_mode"] == "DEMO"
        assert data["catalogue"]["products"] == 0, data["catalogue"]
        assert data["gsc"]["keywords_discovered"] == 0
        assert data["crawler"]["urls_with_crawl_data"] == 0
        assert data["readiness"]["ready_for_stage1_acceptance"] is False
        assert data["readiness"]["blocking"], data["readiness"]

    def test_stage1_invariants(self, H):
        inv = requests.get(f"{API}/admin/live-acceptance-report", headers=H,
                           timeout=60).json()["stage1_invariants"]
        assert inv["shopify_write_route_count"] == 0
        assert inv["all_write_policies_deny"] is True
        assert inv["shopify_write_scopes_requested"] == []
        assert inv["executor"] == "no_op_logger"

    def test_no_secrets_in_report(self, H):
        body = requests.get(f"{API}/admin/live-acceptance-report", headers=H, timeout=60).text
        for needle in ("shpat_", "BEGIN PRIVATE KEY", BOGUS_PK_MARKER, "X-Shopify-Access-Token"):
            assert needle not in body, needle


class TestStageInvariantsGlobal:
    def test_meta_stage_invariants(self, H):
        d = requests.get(f"{API}/meta/stage-invariants", headers=H, timeout=30).json()
        assert d["shopify_write_routes"] == 0 or d.get("write_route_count") == 0, d

    def test_execute_refused(self, H):
        opps = requests.get(f"{API}/actions", headers=H, timeout=30)
        if opps.status_code != 200:
            pytest.skip("no actions endpoint listing")
        rows = opps.json().get("rows", [])
        if not rows:
            pytest.skip("no actions to execute")
        r = requests.post(f"{API}/actions/{rows[0]['id']}/execute", headers=H, timeout=30)
        assert "STAGE_1_WRITES_DISABLED" in r.text, r.text[:300]

    def test_openapi_has_no_shopify_write_routes(self):
        # the schema is only served on the app root, which the ingress maps to the SPA,
        # so probe the app directly for the route inventory
        spec = requests.get("http://localhost:8001/openapi.json", timeout=30)
        assert spec.status_code == 200, spec.status_code
        paths = spec.json()["paths"]
        assert any(p.startswith("/api/admin/connections") for p in paths), "unexpected schema"
        offenders = [p for p in paths
                     if any(k in p.lower() for k in ("/publish", "/mutate", "shopify/write",
                                                     "shopify/update", "shopify/create"))]
        assert not offenders, offenders


# ------------------------------------------------------------------ fixture scoping / DEMO
class TestDemoFixtureScoping:
    @pytest.mark.parametrize("path", ["/overview", "/markets/AU/warroom", "/opportunities",
                                      "/keywords", "/technical/summary", "/cost/summary",
                                      "/agents/roles", "/memory"])
    def test_demo_dashboards_non_empty(self, H, path):
        r = requests.get(f"{API}{path}", headers=H, timeout=60)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        assert r.json(), f"{path} returned empty body"

    def test_live_counts_zero(self, H):
        s = requests.get(f"{API}/admin/shopify/sync/status", headers=H, timeout=30).json()
        assert all(v == 0 for v in s["catalogue"].values()), s["catalogue"]
        g = requests.get(f"{API}/admin/gsc/status", headers=H, timeout=30).json()
        assert g["keywords"] == 0, g
        assert g["by_market_and_source"] == [], g


class TestUrlReconciliation:
    def test_shape(self, H):
        r = requests.get(f"{API}/admin/gsc/url-reconciliation", headers=H, timeout=30)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert set(d.keys()) >= {"report", "total", "rows"}
        assert isinstance(d["rows"], list)

    def test_run_no_500(self, H):
        r = requests.post(f"{API}/admin/gsc/url-reconciliation/run", headers=H, timeout=120)
        assert r.status_code < 500, f"{r.status_code}: {r.text[:300]}"


# ------------------------------------------------------------------ RBAC + audit
class TestAdminRBAC:
    @pytest.mark.parametrize("method,path", [
        ("post", "/admin/connections/shopify"), ("post", "/admin/connections/gsc"),
        ("post", "/admin/connections/bigquery"), ("post", "/admin/connections/crawl-settings"),
        ("post", "/admin/connections/activate-live"),
        ("post", "/admin/intelligence/purge-fixtures"), ("post", "/admin/shopify/sync"),
        ("post", "/admin/gsc/daily"), ("post", "/admin/crawl/batch"),
        ("get", "/admin/connections"), ("get", "/admin/crawl/status"),
        ("get", "/admin/live-acceptance-report"), ("get", "/admin/gsc/status"),
    ])
    def test_unauthenticated_401(self, method, path):
        r = getattr(requests, method)(f"{API}{path}", timeout=30, json={})
        assert r.status_code == 401, f"{path} -> {r.status_code}"


class TestAudit:
    def test_admin_actions_audited(self, H):
        for action in ("connection.shopify_failed", "crawl.settings_changed"):
            d = requests.get(f"{API}/audit", headers=H, timeout=30,
                             params={"action": action, "limit": 5}).json()
            assert d["total"] >= 1, f"{action} not audited"
            assert "shpat_" not in json.dumps(d["rows"]), action

    def test_chain_valid(self, H):
        d = requests.get(f"{API}/audit/verify", headers=H, timeout=60).json()
        assert d.get("valid") is True, d
