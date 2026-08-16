"""Repository abstraction.

Every service, agent, API route and scoring function talks to these interfaces only.
Swapping the Mongo dev adapter for the PostgreSQL 16 production adapter means adding
`PostgresRepository` implementations here - no changes anywhere else in the codebase.
"""
from abc import ABC, abstractmethod
from typing import Any

from bson import ObjectId


class Repository(ABC):
    """Relational-shaped access contract. Table/collection name maps 1:1 to the Postgres table."""

    @abstractmethod
    async def insert(self, row: dict) -> str: ...

    @abstractmethod
    async def insert_many(self, rows: list[dict]) -> int: ...

    @abstractmethod
    async def find(self, where: dict, order_by: list[tuple[str, int]] | None = None,
                   limit: int = 100, offset: int = 0, select: list[str] | None = None) -> list[dict]: ...

    @abstractmethod
    async def find_one(self, where: dict) -> dict | None: ...

    @abstractmethod
    async def count(self, where: dict) -> int: ...

    @abstractmethod
    async def update_one(self, where: dict, values: dict, upsert: bool = False) -> int: ...

    @abstractmethod
    async def delete(self, where: dict) -> int: ...

    @abstractmethod
    async def aggregate(self, pipeline: list[dict]) -> list[dict]: ...


class MongoRepository(Repository):
    """Temporary development adapter. NOT the production source of truth."""

    def __init__(self, db, table: str, base_filter: dict | None = None):
        self._c = db[table]
        self.table = table
        self._base = base_filter or {}

    def _where(self, where: dict | None) -> dict:
        w = {**self._base, **(where or {})}
        if "id" in w:
            v = w.pop("id")
            w["_id"] = ObjectId(v) if isinstance(v, str) and ObjectId.is_valid(v) else v
        return w

    @staticmethod
    def _clean(doc: dict) -> dict:
        if doc and "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return doc

    async def insert(self, row: dict) -> str:
        res = await self._c.insert_one(dict(row))
        return str(res.inserted_id)

    async def insert_many(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        res = await self._c.insert_many([dict(r) for r in rows])
        return len(res.inserted_ids)

    async def find(self, where: dict, order_by=None, limit: int = 100, offset: int = 0,
                   select: list[str] | None = None) -> list[dict]:
        projection = {k: 1 for k in select} if select else None
        cur = self._c.find(self._where(where), projection)
        if order_by:
            cur = cur.sort(order_by)
        if offset:
            cur = cur.skip(offset)
        if limit:
            cur = cur.limit(limit)
        return [self._clean(d) for d in await cur.to_list(length=limit or 1000)]

    async def find_one(self, where: dict) -> dict | None:
        return self._clean(await self._c.find_one(self._where(where)))

    async def count(self, where: dict) -> int:
        return await self._c.count_documents(self._where(where))

    async def update_one(self, where: dict, values: dict, upsert: bool = False) -> int:
        res = await self._c.update_one(self._where(where), {"$set": values}, upsert=upsert)
        return res.modified_count

    async def delete(self, where: dict) -> int:
        res = await self._c.delete_many(self._where(where))
        return res.deleted_count

    async def aggregate(self, pipeline: list[dict]) -> list[dict]:
        if self._base:
            first = pipeline[0] if pipeline else {}
            if "$match" in first:
                pipeline = [{"$match": {**self._base, **first["$match"]}}, *pipeline[1:]]
            else:
                pipeline = [{"$match": dict(self._base)}, *pipeline]
        out = []
        for d in await self._c.aggregate(pipeline).to_list(length=200000):
            if isinstance(d.get("_id"), ObjectId):
                d["_id"] = str(d["_id"])
            out.append(d)
        return out


class UnitOfWork:
    """Named repositories for the Stage 1 relational domain.

    In LIVE data mode every intelligence table read is scoped to exclude seeded fixtures, so a
    live dashboard can never render demo rows.
    """

    FIXTURE_SCOPED = {
        "products", "product_market", "collections", "pages", "page_market", "keywords",
        "gsc_performance", "opportunity_scores", "technical_issues", "competitors",
        "serp_snapshots", "cannibalization", "cost_ledger", "sync_runs",
    }

    TABLES = {
        "products": "products",
        "product_market": "product_market",
        "collections": "seo_collections",
        "pages": "pages",
        "page_market": "page_market",
        "keywords": "keywords",
        "gsc_performance": "gsc_performance",
        "opportunity_scores": "opportunity_scores",
        "technical_issues": "technical_issues",
        "agent_roles": "agent_roles",
        "agent_activity": "agent_activity",
        "memories": "agent_memories",
        "decisions": "decisions",
        "actions": "seo_actions",
        "audit_log": "audit_log",
        "cost_ledger": "cost_ledger",
        "competitors": "competitors",
        "serp_snapshots": "serp_snapshots",
        "cannibalization": "cannibalization",
        "experiments": "experiments",
        "sync_runs": "sync_runs",
        "budgets": "budgets",
        "users": "users",
        "login_attempts": "login_attempts",
        "product_variants": "product_variants",
        "connection_state": "connection_state",
        "webhook_events": "webhook_events",
        "url_reconciliation": "url_reconciliation",
        "reports": "reports",
        "crawl_config": "crawl_config",
        "sitemap_urls": "sitemap_urls",
        "crawl_runs": "crawl_runs",
    }

    def __init__(self, db, exclude_fixtures: bool = False):
        self._db = db
        self._exclude_fixtures = exclude_fixtures
        self._cache: dict[str, Repository] = {}

    def __getattr__(self, name: str) -> Repository:
        if name not in self.TABLES:
            raise AttributeError(name)
        if name not in self._cache:
            base = ({"data_mode": {"$ne": "DEMO"}}
                    if self._exclude_fixtures and name in self.FIXTURE_SCOPED else None)
            self._cache[name] = MongoRepository(self._db, self.TABLES[name], base)
        return self._cache[name]

    def repo(self, name: str) -> Repository:
        return getattr(self, name)

    def unscoped(self) -> "UnitOfWork":
        """Writer view that can see and replace fixture rows (used by ingest + purge)."""
        return UnitOfWork(self._db, exclude_fixtures=False)


def get_uow(db, exclude_fixtures: bool = False) -> UnitOfWork:
    return UnitOfWork(db, exclude_fixtures=exclude_fixtures)


_ANY: Any = None
