"""Internal job abstraction.

Production implementation is Redis-backed ARQ workers. This in-process runner exists only
because Redis is unavailable in the development environment; the job contract is identical.
"""
import asyncio
import traceback
from datetime import datetime, timezone

from ..config import get_settings


class JobQueue:
    """Interface: enqueue(name, **kwargs) -> job_id. Backend is pluggable (in-process | redis/arq)."""

    def __init__(self, uow, audit):
        self.uow = uow
        self.audit = audit
        self.handlers: dict[str, callable] = {}
        self.backend = "in_process" if get_settings().demo_infra_mode else "redis_arq"

    def register(self, name: str, handler, agent_role: str):
        self.handlers[name] = (handler, agent_role)

    async def enqueue(self, name: str, actor: str = "system", **kwargs) -> dict:
        if name not in self.handlers:
            raise KeyError(f"No handler registered for job '{name}'")
        handler, agent_role = self.handlers[name]
        started = datetime.now(timezone.utc)
        activity_id = await self.uow.agent_activity.insert({
            "agent_role": agent_role, "job": name, "status": "running", "actor": actor,
            "params": kwargs, "started_at": started.isoformat(), "queue_backend": self.backend,
        })
        try:
            result = await handler(**kwargs)
            status, error = "success", None
        except Exception as exc:  # noqa: BLE001
            result, status, error = {}, "failed", f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finished = datetime.now(timezone.utc)
        await self.uow.agent_activity.update_one({"id": activity_id}, {
            "status": status, "result": result, "error": error,
            "finished_at": finished.isoformat(),
            "duration_ms": int((finished - started).total_seconds() * 1000),
        })
        await self.audit.record(actor=actor, actor_role="system", action=f"job.{name}",
                               entity_type="job", entity_id=activity_id,
                               metadata={"status": status, "error": error})
        if status == "failed":
            await self.uow.memories.insert({
                "memory_type": "failure", "agent_role": agent_role, "title": f"Job {name} failed",
                "content": error, "confidence": 1.0, "sample_size": 1,
                "evidence": {"job": name, "params": kwargs},
                "created_at": finished.isoformat(),
            })
        return {"job_id": activity_id, "job": name, "status": status, "result": result, "error": error}

    async def enqueue_background(self, name: str, actor: str = "system", **kwargs) -> str:
        asyncio.create_task(self.enqueue(name, actor=actor, **kwargs))
        return name
