"""CostLedger: intercepts every paid call. Per-provider caps + global monthly ceiling."""
from datetime import datetime, timezone

DEFAULT_PROVIDER_CAPS = {
    "dataforseo": 40.0,
    "anthropic": 30.0,
    "openai": 10.0,
    "pagespeed": 5.0,
    "bigquery": 15.0,
}
FREE_PIPELINES = {"shopify", "gsc_api", "crawler", "internal"}
ALERT_THRESHOLDS = [50, 75, 90, 100]


class BudgetExceeded(Exception):
    def __init__(self, provider: str, scope: str):
        super().__init__(f"Budget exhausted for {scope} ({provider}); non-critical paid call blocked")
        self.provider = provider
        self.scope = scope


class CostLedger:
    def __init__(self, uow, global_cap: float):
        self.uow = uow
        self.global_cap = global_cap

    @staticmethod
    def month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    async def caps(self) -> dict:
        row = await self.uow.budgets.find_one({"month": self.month()})
        if not row:
            row = {
                "month": self.month(), "global_cap_usd": self.global_cap,
                "provider_caps": dict(DEFAULT_PROVIDER_CAPS), "overrides": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.uow.budgets.insert(dict(row))
        return row

    async def spend_summary(self) -> dict:
        month = self.month()
        budget = await self.caps()
        rows = await self.uow.cost_ledger.aggregate([
            {"$match": {"month": month}},
            {"$group": {"_id": {"provider": "$provider", "agent": "$agent_role", "status": "$status"},
                        "cost": {"$sum": "$cost_usd"}, "calls": {"$sum": 1},
                        "tokens_in": {"$sum": "$tokens_in"}, "tokens_out": {"$sum": "$tokens_out"}}},
        ])
        by_provider: dict[str, dict] = {}
        by_agent: dict[str, dict] = {}
        total = 0.0
        cached_saved = 0.0
        blocked = 0
        for r in rows:
            key = r["_id"] or {}
            provider = key.get("provider", "unknown")
            agent = key.get("agent") or "unassigned"
            status = key.get("status", "charged")
            if status == "cache_hit":
                cached_saved += r["cost"]
                continue
            if status == "blocked":
                blocked += r["calls"]
                continue
            total += r["cost"]
            p = by_provider.setdefault(provider, {"provider": provider, "spend_usd": 0.0, "calls": 0,
                                                  "cap_usd": budget["provider_caps"].get(provider, 0.0)})
            p["spend_usd"] += r["cost"]
            p["calls"] += r["calls"]
            a = by_agent.setdefault(agent, {"agent_role": agent, "spend_usd": 0.0, "calls": 0,
                                            "tokens_in": 0, "tokens_out": 0})
            a["spend_usd"] += r["cost"]
            a["calls"] += r["calls"]
            a["tokens_in"] += r.get("tokens_in") or 0
            a["tokens_out"] += r.get("tokens_out") or 0
        cap = budget["global_cap_usd"]
        pct = round(total / cap * 100, 2) if cap else 0.0
        day = datetime.now(timezone.utc).day
        forecast = round(total / day * 30, 2) if day else total
        return {
            "month": month, "global_cap_usd": cap, "spend_usd": round(total, 4), "pct_used": pct,
            "forecast_month_end_usd": forecast, "remaining_usd": round(max(cap - total, 0), 4),
            "alert_level": max([t for t in ALERT_THRESHOLDS if pct >= t], default=0),
            "halted": pct >= 100, "blocked_calls": blocked, "saved_by_cache_usd": round(cached_saved, 4),
            "by_provider": sorted(by_provider.values(), key=lambda x: -x["spend_usd"]),
            "by_agent": sorted(by_agent.values(), key=lambda x: -x["spend_usd"]),
            "thresholds": ALERT_THRESHOLDS,
            "overrides": budget.get("overrides", []),
        }

    async def check(self, provider: str, estimated_usd: float, critical: bool = False) -> None:
        if provider in FREE_PIPELINES:
            return
        summary = await self.spend_summary()
        budget = await self.caps()
        if summary["halted"] and not critical:
            await self._log(provider, estimated_usd, status="blocked", reason="global_cap_reached")
            raise BudgetExceeded(provider, "global")
        cap = budget["provider_caps"].get(provider)
        if cap is not None:
            spent = next((p["spend_usd"] for p in summary["by_provider"] if p["provider"] == provider), 0.0)
            if spent + estimated_usd > cap and not critical:
                await self._log(provider, estimated_usd, status="blocked", reason="provider_cap_reached")
                raise BudgetExceeded(provider, "provider")

    async def _log(self, provider: str, cost: float, *, status: str, reason: str | None = None,
                   agent_role: str | None = None, operation: str = "unknown",
                   tokens_in: int = 0, tokens_out: int = 0, model: str | None = None):
        await self.uow.cost_ledger.insert({
            "month": self.month(), "provider": provider, "operation": operation, "agent_role": agent_role,
            "model": model, "cost_usd": round(cost, 6), "tokens_in": tokens_in, "tokens_out": tokens_out,
            "status": status, "reason": reason, "created_at": datetime.now(timezone.utc).isoformat(),
        })

    async def charge(self, *, provider: str, operation: str, cost_usd: float, agent_role: str | None = None,
                     model: str | None = None, tokens_in: int = 0, tokens_out: int = 0):
        await self._log(provider, cost_usd, status="charged", operation=operation, agent_role=agent_role,
                        model=model, tokens_in=tokens_in, tokens_out=tokens_out)

    async def record_cache_hit(self, *, provider: str, operation: str, avoided_usd: float,
                               agent_role: str | None = None):
        await self._log(provider, avoided_usd, status="cache_hit", operation=operation, agent_role=agent_role)

    async def set_override(self, *, actor: str, reason: str, new_global_cap: float | None = None,
                           provider_caps: dict | None = None) -> dict:
        budget = await self.caps()
        entry = {"actor": actor, "reason": reason, "at": datetime.now(timezone.utc).isoformat(),
                 "new_global_cap": new_global_cap, "provider_caps": provider_caps}
        values = {"overrides": budget.get("overrides", []) + [entry]}
        if new_global_cap is not None:
            values["global_cap_usd"] = new_global_cap
        if provider_caps:
            values["provider_caps"] = {**budget["provider_caps"], **provider_caps}
        await self.uow.budgets.update_one({"month": self.month()}, values, upsert=True)
        return entry
