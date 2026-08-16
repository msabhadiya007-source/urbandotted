from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import logging  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from fastapi import APIRouter, FastAPI, Request  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import close_db, ensure_indexes, get_db  # noqa: E402
from app.deps import audit, queue, uow  # noqa: E402
from app.routes_auth import router as auth_router  # noqa: E402
from app.routes_data import router as data_router  # noqa: E402
from app.security import hash_password, verify_password  # noqa: E402
from app.services.agents import AGENT_ROLES  # noqa: E402
from app.services.policy import SHOPIFY_WRITE_ACTIONS  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("urbandotted")
S = get_settings()

app = FastAPI(title="UrbanDotted SEO Intelligence Platform", version="1.0.0-stage1")
api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(data_router)


@api_router.get("/")
async def root():
    return {"service": "urbandotted-seo-intelligence", "stage": 1, "data_mode": S.data_mode,
            "shopify_writes_enabled": S.shopify_writes_enabled}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

SKIP_AUDIT_PREFIXES = ("/api/audit", "/docs", "/openapi.json")


@app.middleware("http")
async def audit_every_api_call(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api") and not path.startswith(SKIP_AUDIT_PREFIXES):
        try:
            await audit.record(actor=request.cookies.get("access_token", "anonymous")[:12] or "anonymous",
                               actor_role="request", action="api.call", entity_type="http",
                               method=request.method, path=path, status=response.status_code)
        except Exception:  # noqa: BLE001 - audit must never break a response
            logger.exception("audit write failed")
    return response


async def seed_admin():
    db = get_db()
    email = os.environ["ADMIN_EMAIL"].lower()
    password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({"email": email, "password_hash": hash_password(password),
                                   "name": "Stage 1 Admin", "role": "admin",
                                   "created_at": datetime.now(timezone.utc).isoformat()})
        logger.info("seeded admin %s", email)
    elif not verify_password(password, existing["password_hash"]):
        await db.users.update_one({"email": email},
                                  {"$set": {"password_hash": hash_password(password)}})


@app.on_event("startup")
async def startup():
    # Stage 1 invariant assertion: the API exposes no Shopify write route.
    write_routes = [r.path for r in app.routes if any(
        k in r.path for k in ("/shopify/write", "/publish", "/mutate"))]
    assert not write_routes, f"Stage 1 violation: write routes present {write_routes}"
    assert not S.shopify_writes_enabled

    if not S.demo_infra_mode:
        missing = S.missing_live_infra()
        if missing:
            raise RuntimeError(f"Production mode requires {missing}. Refusing to fall back to demo infra.")

    await ensure_indexes()
    await seed_admin()

    if await uow.agent_roles.count({}) == 0:
        await uow.agent_roles.insert_many([dict(r) for r in AGENT_ROLES])

    if S.demo_infra_mode and await uow.products.count({}) == 0:
        from app.seed import seed_demo_data
        stats = await seed_demo_data(uow, S.active_markets)
        logger.info("seeded demo fixtures: %s", stats)
        await queue.enqueue("recompute_opportunities", actor="startup")
        await queue.enqueue("detect_cannibalization", actor="startup")

    await audit.record(actor="system", actor_role="system", action="app.startup",
                       entity_type="system",
                       metadata={"data_mode": S.data_mode, "denied_actions": len(SHOPIFY_WRITE_ACTIONS)})


@app.on_event("shutdown")
async def shutdown():
    await close_db()
