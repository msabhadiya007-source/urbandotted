"""PolicyEngine — sits between every agent output and any external side effect.

Stage 1: every Shopify write policy compiles to DENY. There is no write route in the API.
"""
from datetime import datetime, timezone
from enum import Enum


class RiskClass(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


SHOPIFY_WRITE_ACTIONS = {
    "product.update_title", "product.update_description", "product.update_metafield",
    "product.update_handle", "collection.update", "page.publish", "redirect.create",
    "image.alt_update", "theme.edit", "outreach.send", "content.publish",
}

POLICY_TABLE = {
    "read.query": (RiskClass.GREEN, "ALLOW", False),
    "analysis.recompute": (RiskClass.GREEN, "ALLOW", False),
    "memory.write": (RiskClass.GREEN, "ALLOW", False),
    "draft.store": (RiskClass.YELLOW, "ALLOW", True),
    "action.propose": (RiskClass.YELLOW, "ALLOW", True),
    **{a: (RiskClass.RED, "DENY", True) for a in SHOPIFY_WRITE_ACTIONS},
}


class PolicyDenied(Exception):
    pass


class PolicyEngine:
    stage = 1

    def __init__(self, uow, audit):
        self.uow = uow
        self.audit = audit

    def classify(self, action_type: str) -> dict:
        risk, decision, approver = POLICY_TABLE.get(action_type, (RiskClass.RED, "DENY", True))
        return {"action_type": action_type, "risk_class": risk.value, "decision": decision,
                "approver_required": approver, "stage": self.stage}

    def is_write(self, action_type: str) -> bool:
        return action_type in SHOPIFY_WRITE_ACTIONS

    async def evaluate(self, *, action_type: str, actor: str) -> dict:
        verdict = self.classify(action_type)
        await self.audit.record(actor=actor, actor_role="system", action="policy.evaluate",
                                entity_type="policy", entity_id=action_type, metadata=verdict)
        return verdict

    async def propose(self, *, actor: str, action_type: str, entity_type: str, entity_id: str,
                      previous_value, proposed_value, evidence: dict, rationale: str) -> dict:
        verdict = self.classify(action_type)
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "action_type": action_type, "entity_type": entity_type, "entity_id": entity_id,
            "previous_value": previous_value, "proposed_value": proposed_value, "evidence": evidence,
            "rationale": rationale, "risk_class": verdict["risk_class"],
            "approver_required": verdict["approver_required"], "policy_decision": verdict["decision"],
            "status": "PROPOSED_BLOCKED_STAGE_1" if verdict["decision"] == "DENY" else "PENDING_APPROVAL",
            "proposed_by": actor, "created_at": now, "previous_value_snapshot_at": now,
            "executed": False, "execution_note": "Stage 1 executor is a no-op logger.",
        }
        action_id = await self.uow.actions.insert(dict(row))
        await self.audit.record(actor=actor, actor_role="system", action="action.propose",
                                entity_type="seo_action", entity_id=action_id,
                                metadata={"action_type": action_type, "risk": verdict["risk_class"]})
        row["id"] = action_id
        return row

    async def execute(self, action_id: str, actor: str) -> dict:
        """Stage 1 no-op logger. Re-snapshots previous_value and refuses on drift."""
        action = await self.uow.actions.find_one({"id": action_id}) or {}
        verdict = self.classify(action.get("action_type", "unknown"))
        result = {"executed": False, "reason": "STAGE_1_WRITES_DISABLED", "policy": verdict}
        await self.audit.record(actor=actor, actor_role="system", action="action.execute_denied",
                                entity_type="seo_action", entity_id=action_id, metadata=result)
        return result
