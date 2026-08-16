"""Iteration 3: verify-before-write credential hygiene, RBAC granularity, atomic secret writes,
job error redaction and settings freshness. Runs against the public preview URL.

Do NOT flip LIVE_DATA_MODE and do NOT purge fixtures from here.
"""
import concurrent.futures
import json
import os
import re
import subprocess
import time

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
BACKEND_ENV = "/app/backend/.env"

BOGUS_TOKEN = "shpat_ITER3bogus0000000000000000deadbeef"
PK_MARKER = "ITER3PRIVATEKEYMARKER7c1d"
BOGUS_SA = json.dumps({
    "type": "service_account", "project_id": "iter3-proj", "private_key_id": "abc",
    "client_email": "iter3-sa@iter3-proj.iam.gserviceaccount.com", "client_id": "1",
    "token_uri": "https://oauth2.googleapis.com/token",
    "private_key": f"-----BEGIN PRIVATE KEY-----\n{PK_MARKER}\n-----END PRIVATE KEY-----\n",
})
SHOPIFY_KEYS = ("SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ADMIN_API_TOKEN", "SHOPIFY_WEBHOOK_SECRET")
GSC_KEYS = ("GSC_SITE_URL", "GSC_SERVICE_ACCOUNT_JSON")
BQ_KEYS = ("BIGQUERY_PROJECT", "BIGQUERY_DATASET", "BIGQUERY_LOCATION")


def _clear_lockout(email: str):
    try:
        from pymongo import MongoClient
        env = dotenv_values(BACKEND_ENV)
        client = MongoClient(env["MONGO_URL"])
        client[env["DB_NAME"]].login_attempts.delete_many({"identifier": {"$regex": email}})
        client.close()
    except Exception as exc:  # noqa: BLE001
        print(f"lockout cleanup skipped: {exc}")


def _login(email: str, password: str):
    for attempt in range(4):
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
        if r.status_code == 200:
            return {"Authorization": f"Bearer {r.json()['access_token']}"}
        if r.status_code == 429:
            _clear_lockout(email)
            time.sleep(2 * (attempt + 1))
            continue
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    pytest.fail(f"login failed after retries for {email}")


@pytest.fixture(scope="session")
def H():
    return _login("admin@urbandotted.com", "Stage1Admin!2026")


@pytest.fixture(scope="session")
def AH():
    return _login("analyst@urbandotted.com", "Stage1Analyst!2026")


def env_lines():
    return [l for l in open(BACKEND_ENV).read().splitlines() if l.strip()]


def env_keys():
    return [l.split("=", 1)[0].strip() for l in env_lines() if "=" in l]


def assert_no_credential_keys(context: str):
    keys = env_keys()
    text = open(BACKEND_ENV).read()
    for key in SHOPIFY_KEYS + GSC_KEYS + BQ_KEYS:
        assert key not in keys, f"[{context}] {key} present in .env after a failed verification"
    assert "shpat_" not in text, f"[{context}] shopify token pattern in .env"
    assert PK_MARKER not in text, f"[{context}] private key marker in .env"
    assert "LIVE_DATA_MODE" not in keys or 'LIVE_DATA_MODE="false"' in text, \
        f"[{context}] LIVE_DATA_MODE unexpectedly set"


def connections(H):
    r = requests.get(f"{API}/admin/connections", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------- verify-before-write (Shopify)
class TestShopifyVerifyBeforeWrite:
    def test_bogus_shopify_fails_fast_and_writes_nothing(self, H):
        t0 = time.time()
        r = requests.post(f"{API}/admin/connections/shopify", headers=H, timeout=60, json={
            "shop_domain": "iter3-nonexistent-shop.myshopify.com",
            "admin_api_token": BOGUS_TOKEN})
        elapsed = time.time() - t0
        assert r.status_code == 400, f"{r.status_code}: {r.text[:400]}"
        assert elapsed < 15, f"non-retryable failure took {elapsed:.1f}s (expected fail-fast)"
        assert BOGUS_TOKEN not in r.text
        assert_no_credential_keys("bogus shopify submit")
        data = connections(H)
        assert data["shopify"]["verified"] is False
        assert data["shopify"]["admin_token_configured"] is False
        assert data["shopify"]["shop_domain"] is None

    def test_client_abort_mid_request_writes_nothing(self, H):
        token = H["Authorization"]
        payload = json.dumps({"shop_domain": "iter3-abort.myshopify.com",
                              "admin_api_token": BOGUS_TOKEN})
        for max_time in ("0.5", "1", "2"):
            subprocess.run(["curl", "-s", "-o", "/dev/null", "--max-time", max_time,
                            "-X", "POST", f"{API}/admin/connections/shopify",
                            "-H", f"Authorization: {token}",
                            "-H", "Content-Type: application/json", "-d", payload],
                           capture_output=True)
        time.sleep(3)
        assert_no_credential_keys("client abort mid-request")
        data = connections(H)
        assert data["shopify"]["admin_token_configured"] is False
        assert data["shopify"]["verified"] is False

    def test_repeated_failed_attempts_loop(self, H):
        for i in range(6):
            r = requests.post(f"{API}/admin/connections/shopify", headers=H, timeout=60, json={
                "shop_domain": f"iter3-loop-{i}.myshopify.com", "admin_api_token": BOGUS_TOKEN})
            assert r.status_code == 400, f"attempt {i}: {r.status_code} {r.text[:200]}"
            assert_no_credential_keys(f"loop attempt {i}")
        assert connections(H)["shopify"]["admin_token_configured"] is False

    def test_concurrent_shopify_gsc_crawl_posts(self, H):
        def post(path, body):
            return path, requests.post(f"{API}/admin/connections/{path}", headers=H,
                                       timeout=90, json=body)

        jobs = [
            ("shopify", {"shop_domain": "iter3-conc.myshopify.com", "admin_api_token": BOGUS_TOKEN}),
            ("gsc", {"site_url": "https://iter3.example.com/", "service_account_json": BOGUS_SA}),
            ("crawl-settings", {"requests_per_sec": 2.5, "workers": 3}),
            ("bigquery", {"project": "iter3-proj", "dataset": "iter3_ds"}),
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda j: post(*j), jobs))
        for path, resp in results:
            if path == "crawl-settings":
                assert resp.status_code == 200, resp.text[:300]
            else:
                assert resp.status_code == 400, f"{path}: {resp.status_code} {resp.text[:300]}"
        assert_no_credential_keys("concurrent shopify+gsc+bq+crawl")
        # no managed key lost, no duplicates, no empty placeholders
        keys = env_keys()
        for required in ("MONGO_URL", "DB_NAME", "JWT_SECRET", "ADMIN_EMAIL",
                         "CRAWL_REQUESTS_PER_SEC", "CRAWL_WORKERS", "SHOPIFY_API_VERSION"):
            assert required in keys, f"{required} lost from .env"
        assert len(keys) == len(set(keys)), f"duplicate keys in .env: {keys}"
        assert not [l for l in env_lines() if l.endswith('=""')], "empty KEY=\"\" placeholder left"


# ------------------------------------------------------- verify-before-write (GSC / BigQuery)
class TestGSCBigQueryVerifyBeforeWrite:
    @pytest.mark.parametrize("body,label", [
        ({"site_url": "https://iter3.example.com/", "service_account_json": "not-json-at-all"},
         "invalid json"),
        ({"site_url": "https://iter3.example.com/", "service_account_json": BOGUS_SA},
         "fake private key"),
        ({"site_url": "https://iter3.example.com/",
          "service_account_json": json.dumps({"type": "service_account",
                                              "private_key": "x"})}, "missing client_email"),
    ])
    def test_gsc_failures_write_nothing(self, H, body, label):
        r = requests.post(f"{API}/admin/connections/gsc", headers=H, timeout=90, json=body)
        assert r.status_code in (400, 422), f"[{label}] {r.status_code}: {r.text[:300]}"
        assert PK_MARKER not in r.text, f"[{label}] private key material echoed in response"
        assert "BEGIN PRIVATE KEY" not in r.text, f"[{label}] private key block echoed"
        assert_no_credential_keys(f"gsc {label}")
        data = connections(H)
        assert data["gsc"]["service_account_configured"] is False
        assert data["gsc"]["verified"] is False

    def test_bigquery_failure_writes_nothing(self, H):
        r = requests.post(f"{API}/admin/connections/bigquery", headers=H, timeout=90,
                          json={"project": "iter3-proj", "dataset": "iter3_ds",
                                "location": "australia-southeast1"})
        assert r.status_code == 400, f"{r.status_code}: {r.text[:300]}"
        assert_no_credential_keys("bigquery bogus")
        assert connections(H)["bigquery"]["configured"] is False

    def test_no_secret_material_in_backend_logs(self):
        out = subprocess.run("grep -c -e 'BEGIN PRIVATE KEY' -e '" + PK_MARKER + "' -e '"
                             + BOGUS_TOKEN + "' /var/log/supervisor/backend.*.log || true",
                             shell=True, capture_output=True, text=True).stdout
        hits = [int(x.split(":")[-1]) for x in out.strip().splitlines() if x.strip().split(":")[-1].isdigit()]
        assert sum(hits) == 0, f"secret material found in backend logs: {out}"


# ------------------------------------------------------- verified-state gating
class TestActivateLiveGating:
    def test_activate_live_refused_on_unverified(self, H):
        r = requests.post(f"{API}/admin/connections/activate-live", headers=H, timeout=60)
        assert r.status_code == 400, r.text[:300]
        detail = r.json()["detail"]
        assert "never verified" in detail, detail
        assert "shopify" in detail and "gsc" in detail, detail
        assert 'LIVE_DATA_MODE="true"' not in open(BACKEND_ENV).read()

    def test_mode_still_demo(self):
        m = requests.get(f"{API}/meta/mode", timeout=30).json()
        assert m["data_mode"] == "DEMO"
        assert m["live_data_mode"] is False


# ------------------------------------------------------- atomic crawl-settings writes
class TestCrawlSettingsAtomicity:
    def test_concurrent_writes_keep_env_consistent(self, H):
        before = set(env_keys())
        values = [1.0, 1.5, 2.0, 2.5, 3.0, 2.0]

        def post(v):
            return requests.post(f"{API}/admin/connections/crawl-settings", headers=H, timeout=60,
                                 json={"requests_per_sec": v, "workers": 3})

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(post, values))
        assert all(r.status_code == 200 for r in results), [r.status_code for r in results]
        keys = env_keys()
        assert before.issubset(set(keys)), f"keys lost: {before - set(keys)}"
        assert len(keys) == len(set(keys)), f"duplicates: {keys}"
        assert not [l for l in env_lines() if l.endswith('=""')]
        assert_no_credential_keys("crawl-settings concurrency")

    def test_settings_freshness_reflected_without_restart(self, H):
        r = requests.post(f"{API}/admin/connections/crawl-settings", headers=H, timeout=60,
                          json={"requests_per_sec": 2.0, "workers": 3})
        assert r.status_code == 200, r.text
        st = requests.get(f"{API}/admin/crawl/status", headers=H, timeout=60).json()
        assert st["configured"]["requests_per_sec"] == 2.0, st["configured"]
        assert st["configured"]["effective_rate_per_sec"] == 2.0, st["configured"]
        # restore
        r = requests.post(f"{API}/admin/connections/crawl-settings", headers=H, timeout=60,
                          json={"requests_per_sec": 3.0, "workers": 3})
        assert r.status_code == 200
        st = requests.get(f"{API}/admin/crawl/status", headers=H, timeout=60).json()
        assert st["configured"]["requests_per_sec"] == 3.0

    def test_connections_and_acceptance_report_agree_on_mode(self, H):
        c = connections(H)
        a = requests.get(f"{API}/admin/live-acceptance-report", headers=H, timeout=120).json()
        assert c["data_mode"] == "DEMO" and c["live_data_mode"] is False
        assert a["data_mode"] == c["data_mode"], (a["data_mode"], c["data_mode"])
        assert a["provenance"]["shopify"] == "seed_fixture", a["provenance"]
        assert a["readiness"]["ready_for_stage1_acceptance"] is False


# ------------------------------------------------------- RBAC granularity
ADMIN_ONLY_POSTS = [
    ("/admin/connections/shopify", {"shop_domain": "x.myshopify.com", "admin_api_token": "shpat_x"}),
    ("/admin/connections/gsc", {"site_url": "https://x.example.com/", "service_account_json": "{}"}),
    ("/admin/connections/bigquery", {"project": "p", "dataset": "d"}),
    ("/admin/connections/crawl-settings", {"requests_per_sec": 3.0, "workers": 3}),
    ("/admin/connections/activate-live", None),
    ("/admin/connections/deactivate-live", None),
    ("/admin/shopify/webhooks/register", None),
    ("/admin/intelligence/purge-fixtures", None),
    ("/cost/override", {"reason": "iter3 rbac probe", "global_cap_usd": 200}),
    ("/cost/simulate-exhaustion", None),
]


class TestAnalystRBAC:
    @pytest.mark.parametrize("path,body", ADMIN_ONLY_POSTS)
    def test_analyst_denied(self, AH, path, body):
        r = requests.post(f"{API}{path}", headers=AH, timeout=60,
                          **({"json": body} if body is not None else {}))
        assert r.status_code == 403, f"{path} returned {r.status_code}: {r.text[:250]}"
        assert_no_credential_keys(f"analyst denied {path}")

    def test_analyst_denied_audit(self, AH):
        r = requests.get(f"{API}/audit", headers=AH, timeout=60)
        assert r.status_code == 403, f"{r.status_code}: {r.text[:200]}"

    @pytest.mark.parametrize("path", ["/overview", "/opportunities", "/admin/connections",
                                      "/admin/live-acceptance-report"])
    def test_analyst_allowed_reads(self, AH, path):
        r = requests.get(f"{API}{path}", headers=AH, timeout=120)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:250]}"

    @pytest.mark.parametrize("job", ["recompute_opportunities", "detect_anomalies"])
    def test_analyst_allowed_run_pipeline(self, AH, job):
        r = requests.post(f"{API}/pipelines/{job}/run", headers=AH, timeout=180)
        assert r.status_code == 200, f"{job}: {r.status_code} {r.text[:250]}"


# ------------------------------------------------------- job failure sanitisation
class TestJobFailureSanitisation:
    def test_failing_live_job_error_is_clean(self, H):
        r = requests.post(f"{API}/admin/shopify/sync?background=false", headers=H, timeout=120)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        job = r.json()
        assert job["status"] == "failed", job
        assert "credentials are not configured" in job["error"], job
        assert "***" not in job["error"] or "REDACTED" in job["error"]
        body = r.text
        assert "shpat_" not in body and "Bearer " not in body

        act = requests.get(f"{API}/agents/activity", headers=H, timeout=60)
        assert act.status_code == 200
        text = act.text
        assert "shpat_" not in text, "shopify token pattern in agent activity"
        assert not re.search(r"Bearer\s+[A-Za-z0-9._\-]{12,}", text), "raw Bearer token in activity"
        payload = act.json()
        rows = payload["rows"] if isinstance(payload, dict) else payload
        failed = [x for x in rows if (x.get("status") == "failed"
                                      or (x.get("error") or ""))]
        assert failed, "no failed activity row recorded for the failing live job"
        for f in failed[:10]:
            err = f.get("error") or ""
            assert "PRIVATE KEY" not in err and "shpat_" not in err, err


# ------------------------------------------------------- live-only endpoints fail cleanly
class TestLiveOnlyEndpoints:
    @pytest.mark.parametrize("path", [
        "/admin/shopify/sync?background=false", "/admin/shopify/reconcile",
        "/admin/gsc/bootstrap?background=false", "/admin/gsc/daily?background=false",
        "/admin/crawl/robots", "/admin/crawl/batch?limit=2", "/admin/crawl/full?background=false",
    ])
    def test_no_500(self, H, path):
        r = requests.post(f"{API}{path}", headers=H, timeout=180)
        assert r.status_code != 500, f"{path} -> 500: {r.text[:300]}"
        assert r.status_code < 600
        assert "shpat_" not in r.text
        assert_no_credential_keys(f"live-only {path}")


# ------------------------------------------------------- Stage 1 invariants
class TestStage1Invariants:
    def test_no_write_routes_in_openapi(self):
        """The public ingress serves the SPA at /openapi.json, so the schema is read from the
        internal backend port for this invariant only."""
        spec = requests.get("http://localhost:8001/openapi.json", timeout=60).json()
        offenders = [f"{m.upper()} {p}" for p, ops in spec["paths"].items()
                     for m in ops if m.lower() in ("put", "patch", "delete")]
        assert not offenders, offenders

    def test_write_policy_invariants(self, H):
        inv = requests.get(f"{API}/admin/live-acceptance-report", headers=H,
                           timeout=180).json()["stage1_invariants"]
        assert inv["shopify_write_route_count"] == 0, inv
        assert inv["shopify_write_routes"] == []
        assert inv["all_write_policies_deny"] is True, inv
        assert inv["executor"] == "no_op_logger", inv
        assert inv["shopify_write_scopes_requested"] == [], inv

    def test_execute_refuses(self, H):
        r = requests.post(f"{API}/actions/00000000-0000-0000-0000-000000000000/execute",
                          headers=H, timeout=60)
        assert r.status_code == 200, r.status_code
        d = r.json()
        assert d["executed"] is False and d["reason"] == "STAGE_1_WRITES_DISABLED", d
        assert d["policy"]["decision"] == "DENY", d


# ------------------------------------------------------- acceptance report completeness
class TestAcceptanceReport:
    def test_report_sections(self, H):
        r = requests.get(f"{API}/admin/live-acceptance-report", headers=H, timeout=180)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for section in ("provenance", "catalogue", "market_mapping", "gsc", "url_reconciliation",
                        "unmatched_by_category", "crawler", "tier_distribution",
                        "top_20_opportunities", "paid_api_usage", "failures_and_retries",
                        "stage1_invariants", "readiness"):
            assert section in d, f"missing section {section}"
        assert d["readiness"]["ready_for_stage1_acceptance"] is False
        assert d["readiness"]["blocking"], "no blocking reasons listed in DEMO mode"
        assert d["catalogue"]["products"] == 0, d["catalogue"]
        assert d["catalogue"]["demo_rows_still_present"] > 0, d["catalogue"]
        assert set(d["top_20_opportunities"]) >= {"AU", "NZ"}, list(d["top_20_opportunities"])
        assert "shpat_" not in r.text and "PRIVATE KEY" not in r.text


# ------------------------------------------------------- final env integrity
def test_final_env_has_no_credentials():
    assert_no_credential_keys("final")
    text = open(BACKEND_ENV).read()
    assert 'LIVE_DATA_MODE="true"' not in text
    assert oct(os.stat(BACKEND_ENV).st_mode)[-3:] == "600", oct(os.stat(BACKEND_ENV).st_mode)
