"""Deterministic opportunity scoring (0-100) + dynamic A/B/C/D tiering."""
from datetime import datetime, timezone

WEIGHTS = {
    "demand": 0.30,        # impression volume potential
    "position_gap": 0.25,  # distance from page-1 / top-3
    "ctr_gap": 0.20,       # underperformance vs expected CTR curve
    "intent": 0.15,        # commercial/transactional value
    "health": 0.10,        # technical health headroom
}

EXPECTED_CTR = {1: 0.286, 2: 0.157, 3: 0.110, 4: 0.080, 5: 0.061, 6: 0.049, 7: 0.040,
                8: 0.033, 9: 0.028, 10: 0.025}
INTENT_VALUE = {"transactional": 1.0, "commercial": 0.85, "navigational": 0.45, "informational": 0.35}


def expected_ctr(position: float) -> float:
    p = max(1, int(round(position)))
    if p in EXPECTED_CTR:
        return EXPECTED_CTR[p]
    return max(0.004, 0.025 * (10 / p) ** 1.2)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def score_entity(*, impressions: int, clicks: int, position: float, intent: str,
                 technical_issues: int = 0, max_impressions: int = 100000) -> dict:
    demand = _clamp((impressions / max_impressions) ** 0.5) if max_impressions else 0.0
    if position <= 3:
        pos_gap = _clamp((3 - position) / 3 * 0.3)
    elif position <= 20:
        pos_gap = _clamp((position - 3) / 17)
    else:
        pos_gap = 0.35
    ctr = (clicks / impressions) if impressions else 0.0
    exp = expected_ctr(position)
    ctr_gap = _clamp((exp - ctr) / exp) if exp else 0.0
    intent_v = INTENT_VALUE.get(intent, 0.5)
    health = _clamp(technical_issues / 5)
    components = {
        "demand": round(demand * 100, 1),
        "position_gap": round(pos_gap * 100, 1),
        "ctr_gap": round(ctr_gap * 100, 1),
        "intent": round(intent_v * 100, 1),
        "health": round(health * 100, 1),
    }
    total = sum(WEIGHTS[k] * (components[k] / 100) for k in WEIGHTS) * 100
    return {
        "score": round(min(100.0, total), 1),
        "components": components,
        "weights": WEIGHTS,
        "ctr": round(ctr, 4),
        "expected_ctr": round(exp, 4),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def assign_tiers(scored: list[dict]) -> list[dict]:
    """Dynamic tiering by percentile rank: A top 5%, B next 15%, C next 40%, D remainder."""
    ordered = sorted(scored, key=lambda r: -r["score"])
    n = len(ordered) or 1
    for i, row in enumerate(ordered):
        pct = i / n
        row["tier"] = "A" if pct < 0.05 else "B" if pct < 0.20 else "C" if pct < 0.60 else "D"
        row["rank"] = i + 1
        row["percentile"] = round((1 - pct) * 100, 1)
    return ordered


RECOMMENDED_ACTION = {
    ("keyword", "A"): "Build/optimise dedicated preferred landing page; expand keyword cluster",
    ("keyword", "B"): "Rewrite title + meta to close CTR gap; add internal links from Tier A pages",
    ("keyword", "C"): "Monitor; fold into an existing cluster",
    ("keyword", "D"): "No action - insufficient demand",
    ("product", "A"): "Rewrite PDP copy + structured data; resolve technical issues; internal-link boost",
    ("product", "B"): "Title/meta rewrite; add FAQ schema; check market availability",
    ("product", "C"): "Batch template improvement",
    ("product", "D"): "Consider consolidation or noindex if thin",
    ("collection", "A"): "Expand collection intro copy; fix faceted-URL canonicals; add curated internal links",
    ("collection", "B"): "Improve collection title/meta; review pagination canonicals",
    ("collection", "C"): "Template-level improvement",
    ("collection", "D"): "Review for consolidation",
    ("page", "A"): "Content refresh with evidence-backed outline; fix indexability",
    ("page", "B"): "Metadata + internal link improvements",
    ("page", "C"): "Monitor",
    ("page", "D"): "No action",
}


def recommend(entity_type: str, tier: str) -> str:
    return RECOMMENDED_ACTION.get((entity_type, tier), "Monitor")
