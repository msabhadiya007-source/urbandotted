"""Mongo development adapter. Production target is PostgreSQL 16 (see /app/migrations/postgres)."""
from typing import Annotated, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from .config import get_settings


def _to_str_id(v: Any) -> Any:
    if isinstance(v, ObjectId):
        return str(v)
    return v


PyObjectId = Annotated[str, BeforeValidator(_to_str_id)]


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: PyObjectId | None = Field(default=None, alias="_id")

    def to_mongo(self) -> dict:
        doc = self.model_dump(by_alias=True, exclude_none=True)
        doc.pop("_id", None)
        return doc

    @classmethod
    def from_mongo(cls, doc: dict | None):
        if not doc:
            return None
        return cls.model_validate(doc)


_settings = get_settings()
_client = AsyncIOMotorClient(_settings.mongo_url)
db = _client[_settings.db_name]


def get_db():
    return db


async def close_db():
    _client.close()


COLLECTIONS = [
    "users", "login_attempts", "products", "product_market", "seo_collections", "pages",
    "page_market", "keywords", "gsc_performance", "opportunity_scores", "technical_issues",
    "agent_roles", "agent_activity", "agent_memories", "decisions", "seo_actions",
    "audit_log", "cost_ledger", "competitors", "serp_snapshots", "cannibalization",
    "experiments", "sync_runs", "budgets",
]


async def ensure_indexes():
    await db.users.create_index("email", unique=True)
    await db.login_attempts.create_index("identifier")
    await db.products.create_index("handle")
    await db.products.create_index("shopify_id", unique=True, sparse=True)
    await db.product_market.create_index([("product_handle", 1), ("market", 1)])
    await db.product_market.create_index([("product_shopify_id", 1), ("market", 1)])
    await db.pages.create_index("url")
    await db.page_market.create_index([("url", 1), ("market", 1)])
    await db.keywords.create_index([("query", 1), ("market", 1)], unique=True)
    await db.gsc_performance.create_index([("market", 1), ("query", 1)])
    await db.gsc_performance.create_index([("url", 1), ("market", 1)])
    await db.opportunity_scores.create_index([("market", 1), ("score", -1)])
    await db.opportunity_scores.create_index([("entity_type", 1), ("tier", 1)])
    await db.technical_issues.create_index([("severity", 1), ("issue_type", 1)])
    await db.audit_log.create_index([("created_at", -1)])
    await db.cost_ledger.create_index([("month", 1), ("provider", 1)])
    await db.agent_activity.create_index([("started_at", -1)])
    await db.agent_memories.create_index([("memory_type", 1), ("confidence", -1)])
    await db.webhook_events.create_index("webhook_id")
    await db.webhook_events.create_index([("status", 1), ("received_at", 1)])
    await db.product_variants.create_index("shopify_id", unique=True)
    await db.sitemap_urls.create_index("url", unique=True)
    await db.url_reconciliation.create_index([("category", 1), ("impressions", -1)])
    await db.crawl_runs.create_index([("started_at", -1)])
