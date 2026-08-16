"""Development fixtures ONLY.

Every row written here carries data_mode="DEMO" and source="seed_fixture" so the API and UI
can label it. When live connectors are enabled these fixtures are never generated.
"""
import random
from datetime import datetime, timedelta, timezone

BRAND = "urbandotted.com"

CATEGORIES = {
    "Outdoor Furniture": ["Teak Outdoor Dining Table", "Acacia Bench Seat", "Rattan Lounge Chair",
                          "Bistro Set", "Sunlounger with Canopy", "Woven Egg Chair"],
    "Planters & Pots": ["Fibreclay Tall Planter", "Terracotta Bowl Pot", "Concrete Cube Planter",
                        "Self-Watering Trough", "Glazed Ceramic Pot", "Hanging Basket Planter"],
    "Outdoor Lighting": ["Solar Bollard Light", "Festoon String Lights", "Spike Spotlight",
                         "Rechargeable Table Lantern", "Wall Downlight", "Pathway Stake Light"],
    "Rugs & Textiles": ["Flatweave Outdoor Rug", "Recycled PET Runner", "Linen Cushion Cover",
                        "Jute Round Rug", "Ottoman Cover", "Striped Deck Throw"],
    "Shade & Umbrellas": ["Cantilever Umbrella", "Market Umbrella with Base", "Retractable Awning",
                          "Sail Shade Triangle", "Beach Umbrella", "Umbrella Cover"],
    "BBQ & Outdoor Kitchen": ["Charcoal Kettle BBQ", "Portable Gas Grill", "Prep Trolley",
                              "Countertop Pizza Oven", "Cast Iron Grill Plate", "BBQ Tool Set"],
    "Indoor Living": ["Oak Sideboard", "Boucle Accent Chair", "Marble Coffee Table",
                      "Fluted Console Table", "Arched Floor Mirror", "Nesting Side Tables"],
    "Garden Tools": ["Stainless Hand Trowel", "Telescopic Pruning Saw", "Copper Watering Can",
                     "Garden Kneeler Stool", "Bypass Secateurs", "Soil pH Meter"],
}

MATERIALS = ["Teak", "Acacia", "Powder-Coated", "Recycled", "Ceramic", "Brass", "Rattan", "Concrete"]
COLOURS = ["Charcoal", "Natural", "Sand", "Sage", "Terracotta", "Off-White", "Slate", "Ochre"]
VENDORS = ["UrbanDotted", "Northerly", "Halcyon Outdoor", "Kowhai Living", "Marlo & Field"]

COMPETITORS = {
    "AU": ["templeandwebster.com.au", "freedom.com.au", "bunnings.com.au", "adairs.com.au",
           "kmart.com.au", "earlysettler.com.au"],
    "NZ": ["mocka.co.nz", "freedomfurniture.co.nz", "kmart.co.nz", "briscoes.co.nz",
           "mitre10.co.nz", "danskemobler.co.nz"],
}

CITIES = {"AU": ["melbourne", "sydney", "brisbane", "perth"], "NZ": ["auckland", "wellington", "christchurch"]}

ISSUE_TYPES = [
    ("noindex_on_indexable", "critical", "meta robots noindex present on a revenue page", "Indexability"),
    ("canonical_mismatch", "high", "Canonical points to a different market URL", "Canonicals"),
    ("hreflang_missing_return", "high", "hreflang cluster missing return tag", "Hreflang"),
    ("broken_internal_link", "high", "Internal link returns 404", "Links"),
    ("cwv_lcp_poor", "high", "LCP above 4.0s on mobile", "Core Web Vitals"),
    ("hreflang_wrong_region", "medium", "hreflang region code does not match market subfolder", "Hreflang"),
    ("redirect_chain", "medium", "Three or more hop redirect chain from legacy URL", "Redirects"),
    ("missing_product_schema", "medium", "Product structured data missing offers.price", "Schema"),
    ("sitemap_orphan", "medium", "URL indexable but absent from sitemap", "Sitemaps"),
    ("duplicate_title", "medium", "Title tag duplicated across market variants", "Metadata"),
    ("cwv_cls_poor", "medium", "CLS above 0.25 on collection template", "Core Web Vitals"),
    ("invalid_breadcrumb_schema", "low", "BreadcrumbList itemListElement out of order", "Schema"),
    ("robots_blocked_asset", "low", "robots.txt blocks CSS required for rendering", "Robots"),
    ("thin_collection", "low", "Collection has fewer than three indexable products", "Content"),
]

MARKET_META = {
    "AU": {"country": "aus", "subfolder": "", "currency": "AUD", "hreflang": "en-AU"},
    "NZ": {"country": "nzl", "subfolder": "/en-nz", "currency": "NZD", "hreflang": "en-NZ"},
    "US": {"country": "usa", "subfolder": "/en-us", "currency": "USD", "hreflang": "en-US"},
    "UK": {"country": "gbr", "subfolder": "/en-gb", "currency": "GBP", "hreflang": "en-GB"},
    "CA": {"country": "can", "subfolder": "/en-ca", "currency": "CAD", "hreflang": "en-CA"},
}

DEVICES = ["MOBILE", "DESKTOP", "TABLET"]

INTENT_RULES = [
    (("buy", "sale", "cheap", "price", "order", "for sale"), "transactional"),
    (("best", "vs", "review", "reviews", "top", "compare"), "commercial"),
    (("how", "what", "clean", "care", "guide", "ideas", "dimensions"), "informational"),
    (("urbandotted",), "navigational"),
]


def classify_intent_deterministic(query: str) -> tuple[str, float]:
    q = query.lower()
    for tokens, intent in INTENT_RULES:
        if any(t in q for t in tokens):
            return intent, 0.92
    return "commercial", 0.55


def _slug(text: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


async def seed_demo_data(uow, markets: list[str], product_count: int = 1200) -> dict:
    rnd = random.Random(20260601)
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    base = {"data_mode": "DEMO", "source": "seed_fixture"}

    # ---------------------------------------------------------------- catalogue
    collections = []
    for cat in CATEGORIES:
        collections.append({**base, "handle": _slug(cat), "title": cat,
                            "shopify_id": f"gid://shopify/Collection/{rnd.randint(10**9, 10**10)}",
                            "seo_title": f"{cat} | Outdoor & Garden | UrbanDotted",
                            "seo_description": f"Shop {cat.lower()} built for Australian and New Zealand conditions.",
                            "product_count": 0, "updated_at": stamp})

    products, product_market, pages, page_market = [], [], [], []
    cat_keys = list(CATEGORIES.keys())
    for i in range(product_count):
        cat = cat_keys[i % len(cat_keys)]
        name = rnd.choice(CATEGORIES[cat])
        colour, material = rnd.choice(COLOURS), rnd.choice(MATERIALS)
        title = f"{material} {name} - {colour}"
        handle = f"{_slug(title)}-{i + 1000}"
        price_aud = round(rnd.choice([49, 89, 129, 199, 279, 349, 499, 699, 899, 1299]) + 0.95, 2)
        products.append({
            **base, "handle": handle, "shopify_id": f"gid://shopify/Product/{7000000000 + i}",
            "title": title, "product_type": cat, "vendor": rnd.choice(VENDORS),
            "collection_handle": _slug(cat), "status": "ACTIVE",
            "seo_title": f"{title} | UrbanDotted",
            "seo_description": f"{title}. Weather-tested {material.lower()} construction.",
            "description_words": rnd.randint(40, 420), "image_count": rnd.randint(1, 8),
            "image_alt_missing": rnd.random() < 0.22, "variant_count": rnd.randint(1, 6),
            "created_at": stamp, "updated_at": (now - timedelta(days=rnd.randint(0, 120))).isoformat(),
        })
        for m in markets:
            meta = MARKET_META[m]
            fx = 1.0 if m == "AU" else 1.12
            url = f"https://{BRAND}{meta['subfolder']}/products/{handle}"
            product_market.append({
                **base, "product_handle": handle, "market": m, "url": url,
                "price": round(price_aud * fx, 2), "currency": meta["currency"],
                "available": rnd.random() > 0.08, "inventory_quantity": rnd.randint(0, 240),
                "published": True, "hreflang": meta["hreflang"], "updated_at": stamp,
            })
            pages.append({**base, "url": url, "page_type": "product", "entity_handle": handle,
                          "market": m, "title": title, "status_code": 200, "last_crawled_at": stamp})

    for c in collections:
        c["product_count"] = sum(1 for p in products if p["collection_handle"] == c["handle"])
        for m in markets:
            url = f"https://{BRAND}{MARKET_META[m]['subfolder']}/collections/{c['handle']}"
            pages.append({**base, "url": url, "page_type": "collection", "entity_handle": c["handle"],
                          "market": m, "title": c["title"], "status_code": 200, "last_crawled_at": stamp})

    for p in pages:
        page_market.append({**base, "url": p["url"], "market": p["market"], "page_type": p["page_type"],
                            "indexable": rnd.random() > 0.04,
                            "canonical_url": p["url"] if rnd.random() > 0.06 else p["url"].replace("/en-nz", ""),
                            "hreflang_complete": rnd.random() > 0.11, "in_sitemap": rnd.random() > 0.05,
                            "status_code": 200, "lcp_ms": rnd.randint(1500, 5200),
                            "cls": round(rnd.uniform(0.01, 0.34), 3), "inp_ms": rnd.randint(80, 420),
                            "last_crawled_at": (now - timedelta(hours=rnd.randint(1, 168))).isoformat()})

    # ---------------------------------------------------------------- keywords + GSC
    keywords, gsc = [], []
    seen: set[tuple[str, str]] = set()
    for m in markets:
        meta = MARKET_META[m]
        product_pages = [pm for pm in product_market if pm["market"] == m]
        for cat in CATEGORIES:
            heads = [cat.lower(), f"{cat.lower()} {m.lower()}", f"outdoor {cat.lower()}"]
            heads += [f"{cat.lower()} {city}" for city in CITIES[m]]
            for q in heads:
                if (q, m) in seen:
                    continue
                seen.add((q, m))
                url = f"https://{BRAND}{meta['subfolder']}/collections/{_slug(cat)}"
                keywords.append((q, m, url, "collection", cat))
        for pm in rnd.sample(product_pages, min(340, len(product_pages))):
            prod = next(p for p in products if p["handle"] == pm["product_handle"])
            core = prod["title"].split(" - ")[0].lower()
            for tmpl in rnd.sample(["{p}", "buy {p}", "{p} " + m.lower(), "best {p}", "{p} reviews",
                                    "how to clean {p}", "{p} sale", "cheap {p}"], 3):
                q = tmpl.format(p=core)
                if (q, m) in seen:
                    continue
                seen.add((q, m))
                keywords.append((q, m, pm["url"], "product", prod["product_type"]))

    keyword_rows = []
    for q, m, url, page_type, cat in keywords:
        intent, conf = classify_intent_deterministic(q)
        impressions_total = int(abs(rnd.gauss(2600, 3200))) + 40
        avg_pos = round(rnd.choice([rnd.uniform(1, 3), rnd.uniform(3, 10), rnd.uniform(10, 30),
                                   rnd.uniform(30, 70)]), 1)
        keyword_rows.append({
            **base, "query": q, "market": m, "preferred_url": url, "preferred_page_type": page_type,
            "category": cat, "intent": intent, "intent_confidence": conf,
            "intent_method": "deterministic_rules", "impressions_30d": impressions_total,
            "avg_position": avg_pos, "source": "gsc_query", "cluster": cat,
            "expansion_provider": None, "updated_at": stamp,
        })
        # url x device split, sometimes multiple URLs to create cannibalization signal
        urls = [url]
        if rnd.random() < 0.18:
            rival = rnd.choice([pm for pm in product_market if pm["market"] == m])["url"]
            if rival != url:
                urls.append(rival)
        for u in urls:
            share = 1.0 if len(urls) == 1 else rnd.uniform(0.35, 0.65)
            for device in DEVICES:
                dshare = {"MOBILE": 0.62, "DESKTOP": 0.31, "TABLET": 0.07}[device]
                impr = int(impressions_total * share * dshare)
                if impr < 3:
                    continue
                pos = max(1.0, round(avg_pos + rnd.uniform(-2.5, 3.5), 1))
                exp_ctr = 0.28 if pos <= 1.5 else max(0.004, 0.25 / pos)
                ctr = max(0.0, exp_ctr * rnd.uniform(0.25, 1.35))
                gsc.append({
                    **base, "query": q, "url": u, "market": m, "country": MARKET_META[m]["country"],
                    "device": device, "impressions": impr, "clicks": int(impr * ctr),
                    "position": pos, "page_type": "product" if "/products/" in u else "collection",
                    "period_start": (now - timedelta(days=30)).date().isoformat(),
                    "period_end": now.date().isoformat(),
                    "prev_impressions": int(impr * rnd.uniform(0.6, 1.4)),
                    "prev_clicks": int(impr * ctr * rnd.uniform(0.5, 1.5)),
                    "prev_position": max(1.0, round(pos + rnd.uniform(-6, 6), 1)),
                    "ingested_via": "bigquery_bulk_export_fixture",
                })

    # ---------------------------------------------------------------- technical issues
    issues = []
    crawled = rnd.sample(page_market, min(900, len(page_market)))
    for pm in crawled:
        if rnd.random() > 0.34:
            continue
        itype, severity, desc, group = rnd.choice(ISSUE_TYPES)
        issues.append({
            **base, "issue_type": itype, "severity": severity, "group": group, "description": desc,
            "url": pm["url"], "market": pm["market"], "page_type": pm["page_type"],
            "status": "open" if rnd.random() > 0.18 else "resolved",
            "detected_by": "crawler" if group not in ("Core Web Vitals",) else "cwv_monitor",
            "evidence": {"status_code": pm["status_code"], "canonical_url": pm["canonical_url"],
                         "indexable": pm["indexable"], "in_sitemap": pm["in_sitemap"],
                         "lcp_ms": pm["lcp_ms"], "cls": pm["cls"], "hreflang_complete": pm["hreflang_complete"]},
            "first_detected_at": (now - timedelta(days=rnd.randint(1, 45))).isoformat(),
            "last_seen_at": stamp,
        })

    # ---------------------------------------------------------------- competitors + SERP
    competitors, serp = [], []
    for m in markets:
        for domain in COMPETITORS[m]:
            competitors.append({**base, "domain": domain, "market": m,
                                "visibility_share": round(rnd.uniform(3, 27), 1),
                                "share_delta_30d": round(rnd.uniform(-4, 5), 1),
                                "queries_overlapping": rnd.randint(120, 2400),
                                "avg_position": round(rnd.uniform(3, 18), 1), "updated_at": stamp})
    top_keywords = sorted(keyword_rows, key=lambda k: -k["impressions_30d"])[:60]
    for k in top_keywords:
        results = []
        pool = COMPETITORS[k["market"]]
        for pos in range(1, 8):
            is_us = pos == max(1, min(7, int(k["avg_position"])))
            results.append({"position": pos, "domain": BRAND if is_us else rnd.choice(pool),
                            "url": k["preferred_url"] if is_us else f"https://{rnd.choice(pool)}/x",
                            "is_us": is_us})
        serp.append({**base, "query": k["query"], "market": k["market"], "device": "MOBILE",
                     "results": results, "provider": "dataforseo",
                     "captured_at": (now - timedelta(days=rnd.randint(0, 6))).isoformat(),
                     "budget_gate": "tier_a_only", "cost_usd": 0.0006})

    # ---------------------------------------------------------------- memory / decisions / cost
    memories = [
        {"memory_type": "seo_knowledge", "title": "NZ subfolder pages need explicit en-NZ hreflang return tags",
         "content": "NZ market pages served on /en-nz lose impressions when the AU page omits the return tag. "
                    "Restoring return tags recovered 18% of NZ impressions on 24 monitored collection URLs.",
         "confidence": 0.86, "sample_size": 24, "agent_role": "learning_summarizer",
         "evidence": {"metric": "impressions", "delta_pct": 18.0, "window_days": 28, "market": "NZ"}},
        {"memory_type": "business", "title": "Shade & Umbrellas demand peaks Sep-Dec in AU",
         "content": "AU impressions for shade queries rise 3.1x between September and December. "
                    "Tier A budget should shift to this category from August.",
         "confidence": 0.91, "sample_size": 3, "agent_role": "orchestrator",
         "evidence": {"metric": "impressions", "multiplier": 3.1, "seasons_observed": 3, "market": "AU"}},
        {"memory_type": "failure", "title": "DataForSEO SERP calls for Tier C wasted 12% of monthly budget",
         "content": "Unbounded SERP capture on Tier C keywords consumed budget with no ranking movement. "
                    "Gate raised to Tier A plus opportunity score >= 70.",
         "confidence": 0.95, "sample_size": 418, "agent_role": "cost_ledger",
         "evidence": {"provider": "dataforseo", "wasted_usd": 11.6, "calls": 418}},
        {"memory_type": "seo_knowledge", "title": "CTR gap on positions 4-8 is the highest-yield lever",
         "content": "Title and meta rewrites on queries ranking 4-8 with CTR below half of expected produced "
                    "a median +34% clicks within 21 days across 31 URLs.",
         "confidence": 0.79, "sample_size": 31, "agent_role": "learning_summarizer",
         "evidence": {"metric": "clicks", "median_delta_pct": 34.0, "positions": "4-8"}},
        {"memory_type": "business", "title": "AU and NZ share one catalogue; price and availability differ",
         "content": "Canonical strategy keeps market URLs self-canonical with hreflang clusters. Do not "
                    "cross-canonical AU to NZ; it de-indexed 9 NZ collection pages in a prior attempt.",
         "confidence": 0.97, "sample_size": 9, "agent_role": "memory_store",
         "evidence": {"incident": "nz_deindexation", "pages_affected": 9}},
        {"memory_type": "decision", "title": "Stage 1 is read-only: all Shopify write policies compile to DENY",
         "content": "PolicyEngine has no execute path. Proposals are logged with previous_value and evidence "
                    "for Stage 2 activation.",
         "confidence": 1.0, "sample_size": 1, "agent_role": "policy_engine",
         "evidence": {"stage": 1, "write_routes": 0}},
    ]
    memory_rows = [{**base, **m, "status": "active", "created_at": stamp,
                    "recheck_at": (now + timedelta(days=rnd.randint(14, 90))).isoformat()} for m in memories]

    decisions = [
        {"title": "Default LLM for classification is the cheap tier via LLMRouter", "outcome": "adopted",
         "rationale": "High-volume structured classification. Escalates to the reasoning tier below the "
                      "confidence threshold or for Tier A entities.",
         "decided_by": "orchestrator", "evidence": {"threshold": 0.7, "escalation": "reasoning_tier"}},
        {"title": "SERP snapshots gated to Tier A and opportunity score >= 70", "outcome": "adopted",
         "rationale": "Keeps DataForSEO spend inside its monthly cap while covering all revenue-relevant queries.",
         "decided_by": "cost_ledger", "evidence": {"cap_usd": 40.0, "gate": "tier_a_or_score_70"}},
        {"title": "US/UK/CA schema present, ingestion disabled", "outcome": "deferred",
         "rationale": "product_market and page_market carry the market column for all five markets; only "
                      "AU and NZ are ingested in Stage 1.",
         "decided_by": "orchestrator", "evidence": {"schema_markets": 5, "active_markets": 2}},
    ]
    decision_rows = [{**base, **d, "created_at": stamp} for d in decisions]

    cost_rows = []
    month = now.strftime("%Y-%m")
    for provider, op, unit, calls in [("dataforseo", "serp_snapshot", 0.0006, 640),
                                      ("anthropic", "intent_classification", 0.0021, 380),
                                      ("anthropic", "cannibalization_judge", 0.0034, 46),
                                      ("openai", "fallback_classification", 0.0004, 55),
                                      ("pagespeed", "cwv_sample", 0.0, 210),
                                      ("bigquery", "gsc_rollup_query", 0.014, 62)]:
        for _ in range(min(calls, 90)):
            cost_rows.append({
                **base, "month": month, "provider": provider, "operation": op,
                "agent_role": {"serp_snapshot": "serp_snapshotter",
                               "intent_classification": "intent_classifier",
                               "cannibalization_judge": "cannibalization_judge",
                               "fallback_classification": "intent_classifier",
                               "cwv_sample": "cwv_monitor", "gsc_rollup_query": "gsc_ingest"}[op],
                "model": "cheap_tier" if provider in ("anthropic", "openai") else None,
                "cost_usd": round(unit * (calls / 90), 6), "tokens_in": rnd.randint(200, 900) if provider in ("anthropic", "openai") else 0,
                "tokens_out": rnd.randint(60, 260) if provider in ("anthropic", "openai") else 0,
                "status": "charged", "created_at": (now - timedelta(days=rnd.randint(0, min(now.day, 27)))).isoformat(),
            })
    for _ in range(40):
        cost_rows.append({**base, "month": month, "provider": "dataforseo", "operation": "serp_snapshot",
                          "agent_role": "serp_snapshotter", "cost_usd": 0.0006, "tokens_in": 0, "tokens_out": 0,
                          "status": "cache_hit", "created_at": stamp})

    activity = []
    for role, job, status, mins in [("shopify_sync", "shopify_full_sync", "success", 6),
                                    ("gsc_ingest", "gsc_ingest", "success", 34),
                                    ("crawler", "incremental_crawl", "success", 92),
                                    ("opportunity_scoring", "recompute_opportunities", "success", 12),
                                    ("tiering", "recompute_tiers", "success", 11),
                                    ("intent_classifier", "classify_intents", "success", 47),
                                    ("cannibalization_judge", "detect_cannibalization", "success", 44),
                                    ("serp_snapshotter", "capture_serps", "success", 120),
                                    ("cwv_monitor", "sample_cwv", "success", 180),
                                    ("schema_validator", "validate_schema", "success", 95),
                                    ("anomaly_detector", "detect_anomalies", "success", 8),
                                    ("backlink_diff", "diff_backlinks", "failed", 240),
                                    ("orchestrator", "plan_nightly_run", "success", 300)]:
        started = now - timedelta(minutes=mins)
        activity.append({**base, "agent_role": role, "job": job, "status": status,
                         "actor": "scheduler", "params": {}, "queue_backend": "in_process",
                         "started_at": started.isoformat(),
                         "finished_at": (started + timedelta(seconds=rnd.randint(4, 400))).isoformat(),
                         "duration_ms": rnd.randint(4000, 400000),
                         "error": "ProviderTimeout: referring-domain feed unavailable" if status == "failed" else None,
                         "result": {} if status == "failed" else {"rows": rnd.randint(40, 9000)}})

    experiments = [{**base, "name": "Title rewrite: CTR gap cohort, AU collections", "hypothesis":
                    "Adding price-anchor + market qualifier to title tags lifts CTR on positions 4-8.",
                    "status": "SCHEMA_ONLY_STAGE_1", "market": "AU", "metric": "ctr",
                    "control_size": 18, "variant_size": 18, "created_at": stamp}]

    actions = [{**base, "action_type": "product.update_title", "entity_type": "product",
                "entity_id": products[3]["handle"], "previous_value": products[3]["seo_title"],
                "proposed_value": f"{products[3]['title']} | Free AU Delivery | UrbanDotted",
                "evidence": {"position": 6.2, "ctr": 0.018, "expected_ctr": 0.049, "impressions_30d": 4120},
                "rationale": "CTR is 63% below the positional expectation for a Tier A query cluster.",
                "risk_class": "RED", "approver_required": True, "policy_decision": "DENY",
                "status": "PROPOSED_BLOCKED_STAGE_1", "proposed_by": "content_outline_agent",
                "executed": False, "execution_note": "Stage 1 executor is a no-op logger.",
                "created_at": stamp, "previous_value_snapshot_at": stamp}]

    await uow.products.insert_many(products)
    await uow.product_market.insert_many(product_market)
    await uow.collections.insert_many(collections)
    await uow.pages.insert_many(pages)
    await uow.page_market.insert_many(page_market)
    await uow.keywords.insert_many(keyword_rows)
    for i in range(0, len(gsc), 5000):
        await uow.gsc_performance.insert_many(gsc[i:i + 5000])
    await uow.technical_issues.insert_many(issues)
    await uow.competitors.insert_many(competitors)
    await uow.serp_snapshots.insert_many(serp)
    await uow.memories.insert_many(memory_rows)
    await uow.decisions.insert_many(decision_rows)
    await uow.cost_ledger.insert_many(cost_rows)
    await uow.agent_activity.insert_many(activity)
    await uow.experiments.insert_many(experiments)
    await uow.actions.insert_many(actions)
    await uow.sync_runs.insert({**base, "kind": "shopify_full_sync", "products": len(products),
                                "collections": len(collections), "markets": markets,
                                "started_at": stamp, "finished_at": stamp, "status": "success",
                                "note": "Seeded development fixture, not a live Shopify pull."})

    return {"products": len(products), "product_market": len(product_market),
            "collections": len(collections), "pages": len(pages), "keywords": len(keyword_rows),
            "gsc_rows": len(gsc), "technical_issues": len(issues), "competitors": len(competitors),
            "serp_snapshots": len(serp), "memories": len(memory_rows)}
