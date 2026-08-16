from fastapi import Depends, Request

from .config import get_settings
from .db import get_db
from .repositories import get_uow
from .security import require_permission, resolve_user
from .services.audit import AuditLog
from .services.cost import CostLedger
from .services.crawler import Crawler
from .services.gsc_ingest import GSCIngestService
from .services.jobs import JobQueue
from .services.llm_router import LLMRouter
from .services.pipelines import Pipelines
from .services.policy import PolicyEngine
from .services.shopify_sync import ShopifySyncService
from .services.webhooks import WebhookService

_settings = get_settings()

# Read view: excludes seeded fixtures whenever the platform is in LIVE data mode.
uow = get_uow(get_db(), exclude_fixtures=_settings.live_data_mode)

audit = AuditLog(uow)
ledger = CostLedger(uow, _settings.global_monthly_budget_usd)
llm_router = LLMRouter(uow, ledger)
policy = PolicyEngine(uow, audit)
queue = JobQueue(uow, audit)
pipelines = Pipelines(uow, ledger, llm_router, audit)
shopify_sync = ShopifySyncService(uow, audit, _settings)
webhooks = WebhookService(uow, audit, _settings, shopify_sync)
gsc_ingest = GSCIngestService(uow, audit, _settings, ledger)
crawler = Crawler(uow, audit, _settings)

for service in (pipelines, shopify_sync, gsc_ingest, crawler):
    service.register(queue)


async def current_user(request: Request) -> dict:
    return await resolve_user(request, get_db())


def permission(name: str):
    async def _dep(user: dict = Depends(current_user)) -> dict:
        require_permission(user, name)
        return user
    return _dep
