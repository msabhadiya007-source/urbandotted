"""Provider-agnostic LLM router with per-task budget, token accounting and escalation.

No business logic references a model name. Models, thresholds and escalation rules come
from configuration (see app/config.py).
"""
import json
import re
from datetime import datetime, timedelta, timezone

from ..config import get_settings
from .cost import BudgetExceeded

# USD per 1M tokens, used for ledger accounting.
PRICING = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "gpt-5.4-mini": (0.25, 2.0),
}

TASK_BUDGETS_USD = {
    "intent_classification": 5.0,
    "cannibalization_judge": 4.0,
    "competitor_delta": 4.0,
    "learning_summary": 3.0,
    "content_outline": 6.0,
}


class LLMUnavailable(Exception):
    pass


def _price(model: str, tin: int, tout: int) -> float:
    pin, pout = PRICING.get(model, (1.0, 5.0))
    return (tin / 1_000_000) * pin + (tout / 1_000_000) * pout


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("model returned no JSON object")
    return json.loads(match.group(0))


class LLMRouter:
    def __init__(self, uow, ledger):
        self.uow = uow
        self.ledger = ledger
        self.s = get_settings()

    def route(self, task: str, escalate: bool = False) -> tuple[str, str]:
        if escalate:
            return self.s.llm_escalation_provider, self.s.llm_escalation_model
        return self.s.llm_default_provider, self.s.llm_default_model

    async def _cached(self, task: str, cache_key: str) -> dict | None:
        row = await self.uow.memories.find_one({"memory_type": "llm_cache", "cache_key": cache_key,
                                                "task": task})
        if not row:
            return None
        if row.get("revalidate_at") and row["revalidate_at"] < datetime.now(timezone.utc).isoformat():
            return None
        return row

    async def complete_json(self, *, task: str, agent_role: str, system: str, prompt: str,
                            cache_key: str, escalate: bool = False, cache_days: int = 30) -> dict:
        cached = await self._cached(task, cache_key)
        if cached:
            await self.ledger.record_cache_hit(provider="anthropic", operation=task,
                                               avoided_usd=0.0012, agent_role=agent_role)
            return {**cached["result"], "_cached": True, "_model": cached.get("model")}

        provider, model = self.route(task, escalate)
        try:
            await self.ledger.check(provider, 0.002, critical=False)
        except BudgetExceeded as e:
            raise LLMUnavailable(str(e))
        if not self.s.emergent_llm_key:
            raise LLMUnavailable("No LLM key configured")

        from emergentintegrations.llm.chat import LlmChat, UserMessage

        chat = LlmChat(api_key=self.s.emergent_llm_key, session_id=f"{task}:{cache_key}",
                       system_message=system).with_model(provider, model)
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        tin, tout = len(system + prompt) // 4, max(1, len(text) // 4)
        await self.ledger.charge(provider=provider, operation=task, cost_usd=_price(model, tin, tout),
                                 agent_role=agent_role, model=model, tokens_in=tin, tokens_out=tout)
        result = _extract_json(text)

        confidence = float(result.get("confidence", 1.0) or 0)
        if confidence < self.s.llm_confidence_threshold and not escalate:
            return await self.complete_json(task=task, agent_role=agent_role, system=system, prompt=prompt,
                                            cache_key=cache_key, escalate=True, cache_days=cache_days)

        await self.uow.memories.insert({
            "memory_type": "llm_cache", "task": task, "cache_key": cache_key, "result": result,
            "model": model, "provider": provider, "agent_role": agent_role,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "revalidate_at": (datetime.now(timezone.utc) + timedelta(days=cache_days)).isoformat(),
        })
        return {**result, "_cached": False, "_model": model}


INTENT_SYSTEM = (
    "You are an SEO search-intent classifier for an e-commerce catalogue. "
    "Respond with ONLY a JSON object: {\"intent\": one of transactional|commercial|informational|navigational, "
    "\"confidence\": 0-1 float, \"reasoning\": short string, \"recommended_page_type\": one of product|collection|blog|home, "
    "\"ambiguous\": boolean}."
)

JUDGE_SYSTEM = (
    "You are an SEO cannibalization judge. Deterministic rules already ran and were inconclusive. "
    "Respond with ONLY JSON: {\"verdict\": CANNIBALIZATION|NOT_CANNIBALIZATION, \"preferred_url\": string, "
    "\"confidence\": 0-1 float, \"reasoning\": short string, \"recommended_fix\": short string}."
)
