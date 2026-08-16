"""Deterministic cannibalization detection (query x URL x market x position x CTR).

Obvious cases never reach the LLM. Only ambiguous / high-value cases are escalated.
"""
from datetime import datetime, timezone

MIN_IMPRESSIONS = 100
POSITION_PROXIMITY = 6.0


def detect(rows: list[dict]) -> list[dict]:
    """rows: gsc_performance rows with query, url, market, impressions, clicks, position, intent."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        grouped.setdefault((r["query"], r["market"]), []).append(r)

    findings = []
    for (query, market), urls in grouped.items():
        if len(urls) < 2:
            continue
        total_impr = sum(u["impressions"] for u in urls)
        if total_impr < MIN_IMPRESSIONS:
            continue
        urls = sorted(urls, key=lambda u: (u["position"], -u["impressions"]))
        primary, *rivals = urls
        competing = [u for u in rivals
                     if u["impressions"] >= MIN_IMPRESSIONS * 0.2
                     and abs(u["position"] - primary["position"]) <= POSITION_PROXIMITY]
        if not competing:
            continue
        primary_ctr = primary["clicks"] / primary["impressions"] if primary["impressions"] else 0
        rival_share = sum(u["impressions"] for u in competing) / total_impr
        severity_score = rival_share * 100 + (len(competing) - 1) * 5
        page_types = {u.get("page_type") for u in [primary] + competing}
        deterministic = len(page_types) > 1 or rival_share > 0.35
        findings.append({
            "query": query,
            "market": market,
            "total_impressions": total_impr,
            "primary_url": primary["url"],
            "primary_position": round(primary["position"], 1),
            "primary_ctr": round(primary_ctr, 4),
            "competing_urls": [
                {"url": u["url"], "position": round(u["position"], 1), "impressions": u["impressions"],
                 "clicks": u["clicks"], "page_type": u.get("page_type")} for u in competing
            ],
            "rival_impression_share": round(rival_share, 3),
            "severity": "high" if severity_score >= 45 else "medium" if severity_score >= 25 else "low",
            "verdict": "CANNIBALIZATION" if deterministic else "AMBIGUOUS",
            "resolution_method": "deterministic" if deterministic else "needs_llm_judge",
            "needs_llm_judge": not deterministic,
            "recommended_preferred_url": primary["url"],
            "evidence": {
                "rule": "same query x market, >=2 URLs within 6 positions, rival impression share",
                "min_impressions": MIN_IMPRESSIONS,
                "position_proximity": POSITION_PROXIMITY,
            },
            "detected_at": datetime.now(timezone.utc).isoformat(),
        })
    return sorted(findings, key=lambda f: -f["total_impressions"])
