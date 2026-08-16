"""Secret handling.

Secrets are accepted over HTTPS, written only to the backend environment file with 0600
permissions, and never returned, logged or persisted to the database or audit payloads.
Rotation is a re-POST of the same field; no code change is required.
"""
import os
import re
import threading
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_WRITE_LOCK = threading.Lock()

MANAGED_KEYS = {
    "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ADMIN_API_TOKEN", "SHOPIFY_WEBHOOK_SECRET",
    "GSC_SITE_URL", "GSC_SERVICE_ACCOUNT_JSON", "BIGQUERY_PROJECT", "BIGQUERY_DATASET",
    "BIGQUERY_LOCATION", "LIVE_DATA_MODE", "CRAWL_REQUESTS_PER_SEC", "CRAWL_WORKERS",
}
SECRET_KEYS = {"SHOPIFY_ADMIN_API_TOKEN", "SHOPIFY_WEBHOOK_SECRET", "GSC_SERVICE_ACCOUNT_JSON"}


def redact(text: str) -> str:
    """Strip anything that looks like a credential out of a log line or error message."""
    if not text:
        return text
    out = text
    for key in SECRET_KEYS:
        value = os.environ.get(key)
        if value and len(value) > 8:
            out = out.replace(value, "***REDACTED***")
    out = re.sub(r"(shpat_|shpca_|shppa_)[A-Za-z0-9_\-]+", r"\1***REDACTED***", out)
    out = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
                 "***REDACTED_PRIVATE_KEY***", out)
    out = re.sub(r"\"private_key\"\s*:\s*\"[^\"]+\"", '"private_key":"***REDACTED***"', out)
    out = re.sub(r"Bearer\s+[A-Za-z0-9._\-]{12,}", "Bearer ***REDACTED***", out)
    return out


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def write_secrets(values: dict[str, str]) -> list[str]:
    """Upsert (or remove, when the value is empty) keys in the env file.

    The write is atomic (temp file + os.replace) and guarded by a process lock, so concurrent
    admin writes cannot lose a key. Returns key names only, never values.
    """
    unknown = set(values) - MANAGED_KEYS
    if unknown:
        raise ValueError(f"Unmanaged keys rejected: {sorted(unknown)}")

    with _WRITE_LOCK:
        lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
        written = []
        for key, value in values.items():
            value = "" if value is None else str(value)
            lines = [l for l in lines
                     if not (("=" in l) and l.split("=", 1)[0].strip() == key)]
            if value:
                lines.append(f'{key}="{_escape(value)}"')
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
            written.append(key)

        tmp = ENV_PATH.with_suffix(".env.tmp")
        tmp.write_text("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, ENV_PATH)
        os.chmod(ENV_PATH, 0o600)
    return written


def status() -> dict:
    """Presence-only view. Never exposes a secret value."""
    def present(key: str) -> bool:
        return bool(os.environ.get(key))

    return {
        "shopify": {
            "shop_domain": os.environ.get("SHOPIFY_SHOP_DOMAIN") or None,
            "admin_token_configured": present("SHOPIFY_ADMIN_API_TOKEN"),
            "webhook_secret_configured": present("SHOPIFY_WEBHOOK_SECRET"),
            "api_version": os.environ.get("SHOPIFY_API_VERSION"),
            "required_read_scopes": ["read_products", "read_inventory", "read_markets",
                                     "read_online_store_pages", "read_content"],
            "write_scopes_requested": [],
        },
        "gsc": {
            "site_url": os.environ.get("GSC_SITE_URL") or None,
            "service_account_configured": present("GSC_SERVICE_ACCOUNT_JSON"),
            "service_account_email": _service_account_email(),
        },
        "bigquery": {
            "project": os.environ.get("BIGQUERY_PROJECT") or None,
            "dataset": os.environ.get("BIGQUERY_DATASET") or None,
            "configured": present("BIGQUERY_PROJECT") and present("BIGQUERY_DATASET"),
        },
        "crawl": {
            "requests_per_sec": float(os.environ.get("CRAWL_REQUESTS_PER_SEC", "3")),
            "workers": int(os.environ.get("CRAWL_WORKERS", "3")),
        },
        "live_data_mode": os.environ.get("LIVE_DATA_MODE", "false").lower() == "true",
    }


def _service_account_email() -> str | None:
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    import json
    try:
        return json.loads(raw).get("client_email")
    except (ValueError, TypeError):
        return None
