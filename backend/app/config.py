"""Runtime configuration. Nothing about the app is hard-coded around the demo dataset."""
import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        # Infrastructure mode. DEMO_INFRA_MODE=true => Mongo dev adapter + seeded fixtures.
        # In production mode the app requires Postgres/Redis/BigQuery config and must NEVER
        # silently fall back to demo infrastructure.
        self.demo_infra_mode: bool = os.environ.get("DEMO_INFRA_MODE", "true").lower() == "true"
        self.data_mode: str = "DEMO" if self.demo_infra_mode else "LIVE"

        self.mongo_url: str = os.environ["MONGO_URL"]
        self.db_name: str = os.environ["DB_NAME"]

        self.postgres_dsn: str | None = os.environ.get("POSTGRES_DSN")
        self.redis_url: str | None = os.environ.get("REDIS_URL")
        self.bigquery_project: str | None = os.environ.get("BIGQUERY_PROJECT")
        self.bigquery_dataset: str | None = os.environ.get("BIGQUERY_DATASET")

        self.shopify_shop_domain: str | None = os.environ.get("SHOPIFY_SHOP_DOMAIN")
        self.shopify_admin_token: str | None = os.environ.get("SHOPIFY_ADMIN_API_TOKEN")
        self.shopify_api_version: str = os.environ.get("SHOPIFY_API_VERSION", "2025-01")

        self.gsc_site_url: str | None = os.environ.get("GSC_SITE_URL")
        self.gsc_service_account_json: str | None = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")

        self.dataforseo_login: str | None = os.environ.get("DATAFORSEO_LOGIN")
        self.dataforseo_password: str | None = os.environ.get("DATAFORSEO_PASSWORD")

        self.emergent_llm_key: str | None = os.environ.get("EMERGENT_LLM_KEY")
        self.llm_default_model: str = os.environ.get("LLM_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
        self.llm_default_provider: str = os.environ.get("LLM_DEFAULT_PROVIDER", "anthropic")
        self.llm_escalation_model: str = os.environ.get("LLM_ESCALATION_MODEL", "claude-sonnet-4-6")
        self.llm_escalation_provider: str = os.environ.get("LLM_ESCALATION_PROVIDER", "anthropic")
        self.llm_fallback_model: str = os.environ.get("LLM_FALLBACK_MODEL", "gpt-5.4-mini")
        self.llm_fallback_provider: str = os.environ.get("LLM_FALLBACK_PROVIDER", "openai")
        self.llm_confidence_threshold: float = float(os.environ.get("LLM_CONFIDENCE_THRESHOLD", "0.7"))

        self.global_monthly_budget_usd: float = float(os.environ.get("GLOBAL_MONTHLY_BUDGET_USD", "100"))

        # Stage 1 hard invariant: no Shopify write scope, no write routes.
        self.shopify_writes_enabled: bool = False
        self.active_markets: list[str] = [m.strip().upper() for m in os.environ.get("ACTIVE_MARKETS", "AU,NZ").split(",")]
        self.schema_markets: list[str] = ["AU", "NZ", "US", "UK", "CA"]

    def missing_live_infra(self) -> list[str]:
        missing = []
        if not self.postgres_dsn:
            missing.append("POSTGRES_DSN")
        if not self.redis_url:
            missing.append("REDIS_URL")
        if not self.bigquery_project:
            missing.append("BIGQUERY_PROJECT")
        return missing

    def missing_live_sources(self) -> list[str]:
        missing = []
        if not (self.shopify_shop_domain and self.shopify_admin_token):
            missing.append("SHOPIFY")
        if not (self.gsc_site_url and self.gsc_service_account_json):
            missing.append("GSC")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
