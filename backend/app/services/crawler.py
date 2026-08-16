"""Read-only technical crawler.

A single shared token bucket caps the COMBINED request rate across all workers (3 workers do not
mean 3x the rate). Adaptive backoff halves the rate on 429/5xx/latency spikes and recovers slowly.
"""
import asyncio
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .secrets import redact

USER_AGENT = "UrbanDottedSEOBot/1.0 (+read-only technical audit; contact seo@urbandotted.com)"


class SharedRateLimiter:
    """Global leaky bucket. Combined ceiling for every worker."""

    def __init__(self, rate_per_sec: float, floor: float):
        self.rate = rate_per_sec
        self.floor = floor
        self.ceiling = rate_per_sec
        self._lock = asyncio.Lock()
        self._next = time.monotonic()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            interval = 1.0 / max(self.rate, 0.05)
            self._next = max(now, self._next) + interval
            wait = self._next - now
        if wait > 0:
            await asyncio.sleep(wait)

    def slow_down(self, reason: str) -> float:
        self.rate = max(self.floor, self.rate / 2)
        return self.rate

    def recover(self):
        self.rate = min(self.ceiling, self.rate * 1.15)


ISSUE_DEFS = {
    "noindex_on_indexable": ("critical", "Indexability", "meta robots noindex on a revenue page"),
    "http_error": ("critical", "Indexability", "URL returned a non-200 status"),
    "canonical_mismatch": ("high", "Canonicals", "Canonical points away from this URL"),
    "canonical_missing": ("medium", "Canonicals", "No canonical tag present"),
    "hreflang_missing": ("high", "Hreflang", "No hreflang cluster on a multi-market URL"),
    "hreflang_missing_return": ("high", "Hreflang", "hreflang cluster missing the return tag for a sibling market"),
    "redirect_chain": ("medium", "Redirects", "More than one redirect hop before the final URL"),
    "missing_product_schema": ("medium", "Schema", "Product structured data missing or incomplete"),
    "invalid_schema_json": ("low", "Schema", "JSON-LD block failed to parse"),
    "title_missing": ("high", "Metadata", "Title tag missing or empty"),
    "title_too_long": ("low", "Metadata", "Title tag over 60 characters"),
    "meta_description_missing": ("medium", "Metadata", "Meta description missing"),
    "image_alt_missing": ("low", "Content", "Images missing alt text"),
    "thin_content": ("medium", "Content", "Fewer than 100 words of body copy"),
    "broken_internal_link": ("high", "Links", "Internal link returned 404"),
    "sitemap_orphan": ("medium", "Sitemaps", "Indexable URL absent from the sitemap"),
    "robots_blocked": ("critical", "Robots", "robots.txt disallows this URL"),
}


class Crawler:
    def __init__(self, uow, audit, settings):
        self.uow = uow
        self.audit = audit
        self.s = settings
        self.limiter = SharedRateLimiter(settings.crawl_requests_per_sec,
                                        settings.crawl_min_requests_per_sec)
        self.state = {"running": False}

    def register(self, queue):
        queue.register("crawl_batch", self.crawl_batch, "crawler")
        queue.register("crawl_full", self.crawl_full, "crawler")
        queue.register("fetch_robots_and_sitemaps", self.fetch_robots_and_sitemaps, "crawler")

    # ------------------------------------------------------------------ robots / sitemaps
    async def fetch_robots_and_sitemaps(self) -> dict:
        uow = self.uow.unscoped()
        hosts = {urlparse(p["url"]).netloc for p in
                 await uow.pages.find({"data_mode": "LIVE"}, limit=5000, select=["url"])}
        out = []
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT},
                                     follow_redirects=True) as client:
            for host in list(hosts)[:5]:
                base = f"https://{host}"
                await self.limiter.acquire()
                try:
                    robots = await client.get(f"{base}/robots.txt")
                    disallow = re.findall(r"(?im)^\s*Disallow:\s*(\S+)", robots.text or "")
                    sitemaps = re.findall(r"(?im)^\s*Sitemap:\s*(\S+)", robots.text or "")
                except httpx.HTTPError as exc:
                    out.append({"host": host, "error": redact(str(exc))})
                    continue

                sitemap_urls: set[str] = set()
                for sm in sitemaps[:6]:
                    await self.limiter.acquire()
                    try:
                        r = await client.get(sm)
                        locs = re.findall(r"<loc>([^<]+)</loc>", r.text or "")
                        for loc in locs:
                            if loc.endswith(".xml") and len(sitemap_urls) < 200000:
                                await self.limiter.acquire()
                                child = await client.get(loc)
                                sitemap_urls.update(re.findall(r"<loc>([^<]+)</loc>", child.text or ""))
                            else:
                                sitemap_urls.add(loc)
                    except httpx.HTTPError:
                        continue

                await uow.repo("crawl_config").update_one({"host": host}, {
                    "host": host, "robots_status": robots.status_code,
                    "disallow_rules": disallow[:200], "sitemap_index": sitemaps,
                    "sitemap_url_count": len(sitemap_urls),
                    "fetched_at": datetime.now(timezone.utc).isoformat(), "data_mode": "LIVE",
                }, upsert=True)
                for i, url in enumerate(list(sitemap_urls)[:100000]):
                    if i % 1 == 0:
                        await uow.repo("sitemap_urls").update_one({"url": url}, {
                            "url": url, "host": host, "data_mode": "LIVE"}, upsert=True)
                out.append({"host": host, "robots_status": robots.status_code,
                            "disallow_rules": len(disallow), "sitemaps": sitemaps,
                            "urls_in_sitemaps": len(sitemap_urls)})
        return {"hosts": out}

    async def _robots_blocked(self, url: str) -> bool:
        host = urlparse(url).netloc
        cfg = await self.uow.unscoped().repo("crawl_config").find_one({"host": host})
        path = urlparse(url).path or "/"
        for rule in (cfg or {}).get("disallow_rules", []):
            if rule and rule != "/" and path.startswith(rule):
                return True
        return False

    # ------------------------------------------------------------------ fetch + analyse
    async def _fetch(self, client: httpx.AsyncClient, url: str, metrics: dict) -> dict | None:
        await self.limiter.acquire()
        started = time.monotonic()
        try:
            r = await client.get(url)
        except httpx.HTTPError as exc:
            metrics["failures"] += 1
            metrics["errors"].append(redact(str(exc))[:160])
            self.limiter.slow_down("transport_error")
            return None
        latency_ms = int((time.monotonic() - started) * 1000)
        metrics["requests"] += 1
        metrics["latency_ms"].append(latency_ms)
        metrics["status_codes"][str(r.status_code)] = metrics["status_codes"].get(str(r.status_code), 0) + 1
        if r.status_code == 429 or r.status_code >= 500:
            metrics["throttled" if r.status_code == 429 else "server_errors"] += 1
            new_rate = self.limiter.slow_down(f"status_{r.status_code}")
            metrics["rate_adjustments"].append({"url": url, "status": r.status_code, "new_rate": new_rate})
            return None
        if latency_ms > 4000:
            metrics["rate_adjustments"].append(
                {"url": url, "latency_ms": latency_ms, "new_rate": self.limiter.slow_down("latency")})
        else:
            self.limiter.recover()
        return {"status": r.status_code, "html": r.text, "final_url": str(r.url),
                "redirects": len(r.history), "latency_ms": latency_ms,
                "headers": {k.lower(): v for k, v in r.headers.items()}}

    def _analyse(self, url: str, page: dict, market: str, page_type: str) -> tuple[dict, list[dict]]:
        soup = BeautifulSoup(page["html"], "html.parser")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        meta_robots = ""
        for tag in soup.find_all("meta"):
            if (tag.get("name") or "").lower() == "robots":
                meta_robots = (tag.get("content") or "").lower()
        description = ""
        for tag in soup.find_all("meta"):
            if (tag.get("name") or "").lower() == "description":
                description = (tag.get("content") or "").strip()
        canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in v)
        canonical = urljoin(url, canonical_tag.get("href")) if canonical_tag and canonical_tag.get("href") else None
        hreflangs = {(l.get("hreflang") or "").lower(): urljoin(url, l.get("href") or "")
                     for l in soup.find_all("link", rel=lambda v: v and "alternate" in v)
                     if l.get("hreflang")}
        images = soup.find_all("img")
        alt_missing = sum(1 for i in images if not (i.get("alt") or "").strip())
        body_words = len((soup.body.get_text(" ", strip=True) if soup.body else "").split())

        schema_types, schema_errors, product_schema_ok = [], 0, False
        for block in soup.find_all("script", type="application/ld+json"):
            try:
                parsed = json.loads(block.string or "{}")
            except (ValueError, TypeError):
                schema_errors += 1
                continue
            for item in (parsed if isinstance(parsed, list) else [parsed]):
                if not isinstance(item, dict):
                    continue
                stype = item.get("@type")
                types = stype if isinstance(stype, list) else [stype]
                schema_types.extend([t for t in types if t])
                if "Product" in types:
                    offers = item.get("offers") or {}
                    offers = offers[0] if isinstance(offers, list) and offers else offers
                    product_schema_ok = bool(isinstance(offers, dict) and offers.get("price"))

        record = {
            "url": url, "market": market, "page_type": page_type,
            "status_code": page["status"], "final_url": page["final_url"],
            "redirect_hops": page["redirects"], "latency_ms": page["latency_ms"],
            "title": title, "title_length": len(title), "meta_description": description,
            "meta_robots": meta_robots, "indexable": "noindex" not in meta_robots and page["status"] == 200,
            "canonical_url": canonical, "canonical_self": canonical == url if canonical else None,
            "hreflang_map": hreflangs, "hreflang_complete": bool(hreflangs),
            "schema_types": sorted(set(schema_types)), "product_schema_valid": product_schema_ok,
            "images": len(images), "images_missing_alt": alt_missing, "body_words": body_words,
            "last_crawled_at": datetime.now(timezone.utc).isoformat(),
            "data_mode": "LIVE", "source": "crawler",
        }

        found = []
        def flag(code, evidence):
            severity, group, desc = ISSUE_DEFS[code]
            found.append({"issue_type": code, "severity": severity, "group": group,
                          "description": desc, "url": url, "market": market,
                          "page_type": page_type, "status": "open", "detected_by": "crawler",
                          "evidence": evidence, "data_mode": "LIVE", "source": "crawler",
                          "first_detected_at": record["last_crawled_at"],
                          "last_seen_at": record["last_crawled_at"]})

        if page["status"] != 200:
            flag("http_error", {"status_code": page["status"], "final_url": page["final_url"]})
        if "noindex" in meta_robots:
            flag("noindex_on_indexable", {"meta_robots": meta_robots})
        if not canonical:
            flag("canonical_missing", {"title": title})
        elif canonical != url:
            flag("canonical_mismatch", {"canonical_url": canonical, "requested_url": url})
        if not hreflangs:
            flag("hreflang_missing", {"markets_active": self.s.active_markets})
        else:
            expected = {"AU": "en-au", "NZ": "en-nz"}
            missing = [m for m in self.s.active_markets
                       if expected.get(m) and expected[m] not in hreflangs]
            if missing:
                flag("hreflang_missing_return", {"present": sorted(hreflangs), "missing_markets": missing})
        if page["redirects"] > 1:
            flag("redirect_chain", {"hops": page["redirects"], "final_url": page["final_url"]})
        if page_type == "product" and not product_schema_ok:
            flag("missing_product_schema", {"schema_types": record["schema_types"]})
        if schema_errors:
            flag("invalid_schema_json", {"unparseable_blocks": schema_errors})
        if not title:
            flag("title_missing", {})
        elif len(title) > 60:
            flag("title_too_long", {"title_length": len(title)})
        if not description:
            flag("meta_description_missing", {})
        if alt_missing:
            flag("image_alt_missing", {"images": len(images), "missing_alt": alt_missing})
        if body_words < 100:
            flag("thin_content", {"body_words": body_words})
        return record, found

    # ------------------------------------------------------------------ queue
    async def _select_urls(self, limit: int, only_stale_hours: int | None, page_types: list[str] | None):
        uow = self.uow.unscoped()
        where: dict = {"data_mode": "LIVE"}
        if page_types:
            where["page_type"] = {"$in": page_types}
        pages = await uow.pages.find(where, limit=limit * 4,
                                    select=["url", "market", "page_type", "entity_handle"])
        if not only_stale_hours:
            return pages[:limit]
        crawled = {c["url"]: c.get("last_crawled_at") for c in
                   await uow.page_market.find({"data_mode": "LIVE"}, limit=200000,
                                              select=["url", "last_crawled_at"])}
        cutoff = (datetime.now(timezone.utc).timestamp() - only_stale_hours * 3600)
        stale = []
        for p in pages:
            seen = crawled.get(p["url"])
            if not seen:
                stale.append(p)
            else:
                try:
                    if datetime.fromisoformat(seen).timestamp() < cutoff:
                        stale.append(p)
                except ValueError:
                    stale.append(p)
        return stale[:limit]

    async def crawl_batch(self, limit: int = 50, page_types: list[str] | None = None,
                          only_stale_hours: int | None = None, tier_a_first: bool = True) -> dict:
        uow = self.uow.unscoped()
        targets = await self._select_urls(limit, only_stale_hours, page_types)
        if tier_a_first:
            tiers = {o["entity_id"]: o["tier"] for o in await uow.opportunity_scores.find(
                {"tier": {"$in": ["A", "B"]}}, limit=5000, select=["entity_id", "tier"])}
            targets.sort(key=lambda p: {"A": 0, "B": 1}.get(tiers.get(p["url"]), 2))

        metrics = {"requests": 0, "failures": 0, "throttled": 0, "server_errors": 0,
                   "status_codes": {}, "latency_ms": [], "errors": [], "rate_adjustments": []}
        sitemap_urls = {s["url"] for s in await uow.repo("sitemap_urls").find({}, limit=200000,
                                                                             select=["url"])}
        started = datetime.now(timezone.utc)
        self.state = {"running": True, "queue_depth": len(targets), "completed": 0,
                      "started_at": started.isoformat()}
        semaphore = asyncio.Semaphore(self.s.crawl_workers)
        crawled, issues_written, blocked = 0, 0, 0

        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT},
                                     follow_redirects=True) as client:
            async def worker(target):
                nonlocal crawled, issues_written, blocked
                async with semaphore:
                    if await self._robots_blocked(target["url"]):
                        blocked += 1
                        return
                    page = await self._fetch(client, target["url"], metrics)
                    if not page:
                        return
                    record, issues = self._analyse(target["url"], page, target.get("market") or "AU",
                                                   target.get("page_type") or "other")
                    if record["indexable"] and sitemap_urls and target["url"] not in sitemap_urls:
                        severity, group, desc = ISSUE_DEFS["sitemap_orphan"]
                        issues.append({"issue_type": "sitemap_orphan", "severity": severity,
                                       "group": group, "description": desc, "url": target["url"],
                                       "market": target.get("market"), "page_type": target.get("page_type"),
                                       "status": "open", "detected_by": "crawler",
                                       "evidence": {"sitemap_urls_known": len(sitemap_urls)},
                                       "data_mode": "LIVE", "source": "crawler",
                                       "first_detected_at": record["last_crawled_at"],
                                       "last_seen_at": record["last_crawled_at"]})
                    record["in_sitemap"] = target["url"] in sitemap_urls if sitemap_urls else None
                    await uow.page_market.update_one(
                        {"url": target["url"], "market": record["market"]}, record, upsert=True)
                    open_codes = {i["issue_type"] for i in issues}
                    existing = await uow.technical_issues.find(
                        {"url": target["url"], "status": "open"}, limit=50)
                    for e in existing:
                        if e["issue_type"] not in open_codes:
                            await uow.technical_issues.update_one({"id": e["id"]}, {
                                "status": "resolved",
                                "resolved_at": datetime.now(timezone.utc).isoformat()})
                    for issue in issues:
                        prior = await uow.technical_issues.find_one(
                            {"url": issue["url"], "issue_type": issue["issue_type"]})
                        if prior:
                            await uow.technical_issues.update_one({"id": prior["id"]}, {
                                "status": "open", "severity": issue["severity"],
                                "evidence": issue["evidence"], "last_seen_at": issue["last_seen_at"]})
                        else:
                            await uow.technical_issues.insert(issue)
                        issues_written += 1
                    crawled += 1
                    self.state["completed"] = crawled

            await asyncio.gather(*(worker(t) for t in targets))

        finished = datetime.now(timezone.utc)
        latencies = sorted(metrics["latency_ms"])
        duration = max(0.001, (finished - started).total_seconds())
        report = {
            "urls_selected": len(targets), "urls_crawled": crawled,
            "robots_blocked_skipped": blocked, "issues_written": issues_written,
            "requests": metrics["requests"], "failures": metrics["failures"],
            "retries": len(metrics["rate_adjustments"]), "throttled_429": metrics["throttled"],
            "server_errors_5xx": metrics["server_errors"],
            "status_code_distribution": metrics["status_codes"],
            "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
            "p95_latency_ms": latencies[int(len(latencies) * 0.95) - 1] if latencies else 0,
            "throughput_urls_per_sec": round(crawled / duration, 2),
            "duration_seconds": round(duration, 1),
            "configured_rate_per_sec": self.s.crawl_requests_per_sec,
            "effective_rate_per_sec": round(self.limiter.rate, 2),
            "workers": self.s.crawl_workers,
            "rate_adjustments": metrics["rate_adjustments"][:10],
            "errors": metrics["errors"][:10],
        }
        self.state = {"running": False, "last_report": report}
        await uow.repo("crawl_runs").insert({**report, "data_mode": "LIVE",
                                            "started_at": started.isoformat(),
                                            "finished_at": finished.isoformat()})
        return report

    async def crawl_full(self, batch_size: int = 200, max_batches: int = 5) -> dict:
        """Progressive expansion after a validation batch passes."""
        uow = self.uow.unscoped()
        total = await uow.pages.count({"data_mode": "LIVE"})
        reports = []
        for _ in range(max_batches):
            report = await self.crawl_batch(limit=batch_size, only_stale_hours=24)
            reports.append(report)
            if report["urls_crawled"] == 0:
                break
            if report["throttled_429"] or report["server_errors_5xx"]:
                break  # storefront is under stress: stop expanding
        crawled = await uow.page_market.count({"data_mode": "LIVE"})
        return {"batches": len(reports), "url_inventory": total, "urls_with_crawl_data": crawled,
                "coverage_pct": round(crawled / total * 100, 2) if total else 0.0,
                "batch_reports": reports}
