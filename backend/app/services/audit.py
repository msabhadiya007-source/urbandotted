"""Append-only, hash-chained audit log (chained per UTC day)."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone

GENESIS = "0" * 64


def _hash(prev: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, uow):
        self.uow = uow
        self._lock = asyncio.Lock()

    async def record(self, *, actor: str, actor_role: str, action: str, entity_type: str = "system",
                     entity_id: str | None = None, method: str | None = None, path: str | None = None,
                     status: int | None = None, metadata: dict | None = None) -> dict:
        async with self._lock:
            now = datetime.now(timezone.utc)
            day = now.date().isoformat()
            prev = await self.uow.audit_log.find({"chain_day": day}, order_by=[("seq", -1)], limit=1)
            prev_hash = prev[0]["entry_hash"] if prev else GENESIS
            seq = (prev[0]["seq"] + 1) if prev else 1
            payload = {
                "chain_day": day, "seq": seq, "actor": actor, "actor_role": actor_role, "action": action,
                "entity_type": entity_type, "entity_id": entity_id, "method": method, "path": path,
                "status": status, "metadata": metadata or {}, "created_at": now.isoformat(),
            }
            payload["prev_hash"] = prev_hash
            payload["entry_hash"] = _hash(prev_hash, payload)
            await self.uow.audit_log.insert(payload)
            return payload

    async def verify_chain(self, day: str | None = None) -> dict:
        day = day or datetime.now(timezone.utc).date().isoformat()
        rows = await self.uow.audit_log.find({"chain_day": day}, order_by=[("seq", 1)], limit=5000)
        prev = GENESIS
        for r in rows:
            expected = _hash(prev, {k: v for k, v in r.items() if k not in ("id", "entry_hash")})
            if expected != r["entry_hash"]:
                return {"day": day, "valid": False, "broken_at_seq": r["seq"], "entries": len(rows)}
            prev = r["entry_hash"]
        return {"day": day, "valid": True, "entries": len(rows), "head_hash": prev}
