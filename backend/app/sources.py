"""Source connectors built against the real API contracts.

Nothing in this module can mutate a Shopify resource: no mutation string is ever constructed
and no write method exists. Credentials come from the environment only and are never logged.
"""
import asyncio
import json
import time
from abc import ABC, abstractmethod
from datetime import date, timedelta

import httpx

from .config import get_settings
from .services.secrets import redact


class SourceUnavailable(Exception):
    pass


# ============================================================== Shopify
PRODUCTS_QUERY = """
query Products($cursor: String) {
  products(first: 50, after: $cursor, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id handle title descriptionHtml productType vendor status updatedAt createdAt
      onlineStoreUrl tags
      seo { title description }
      featuredImage { url altText }
      images(first: 10) { nodes { url altText } }
      variants(first: 100) {
        nodes { id sku title price compareAtPrice inventoryQuantity availableForSale }
      }
      collections(first: 20) { nodes { handle title } }
      metafields(first: 20) { nodes { namespace key value } }
    }
  }
}
"""

COLLECTIONS_QUERY = """
query Collections($cursor: String) {
  collections(first: 50, after: $cursor, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id handle title descriptionHtml updatedAt sortOrder
      seo { title description }
      image { url altText }
      productsCount { count }
    }
  }
}
"""

MARKETS_QUERY = """
{
  markets(first: 50) {
    nodes {
      id name handle enabled primary
      regions(first: 50) { nodes { ... on MarketRegionCountry { code name } } }
      webPresence { id defaultLocale rootUrls { url locale } subfolderSuffix domain { host } }
    }
  }
}
"""

SHOP_QUERY = "{ shop { name myshopifyDomain primaryDomain { host url } currencyCode } }"


class ShopifyCatalogSource(ABC):
    @abstractmethod
    def iter_products(self, cursor: str | None = None): ...

    @abstractmethod
    def iter_collections(self, cursor: str | None = None): ...

    @abstractmethod
    async def market_config(self) -> list[dict]: ...

    @abstractmethod
    async def shop(self) -> dict: ...


class LiveShopifyAdapter(ShopifyCatalogSource):
    """Admin GraphQL API, read-only. Cost-aware throttling with exponential backoff + jitter."""

    read_only_scopes = ["read_products", "read_inventory", "read_markets",
                        "read_online_store_pages", "read_content"]

    def __init__(self, shop_domain: str | None = None, admin_token: str | None = None):
        s = get_settings()
        domain = shop_domain or s.shopify_shop_domain
        token = admin_token or s.shopify_admin_token
        if not (domain and token):
            raise SourceUnavailable("Shopify credentials are not configured")
        domain = domain.replace("https://", "").replace("http://", "").strip("/")
        self.domain = domain
        self.endpoint = f"https://{domain}/admin/api/{s.shopify_api_version}/graphql.json"
        self._headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
        self.stats = {"requests": 0, "retries": 0, "throttled": 0, "errors": []}

    async def _gql(self, query: str, variables: dict | None = None, attempt: int = 0) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(self.endpoint, headers=self._headers,
                                      json={"query": query, "variables": variables or {}})
            self.stats["requests"] += 1
            if r.status_code in (429, 502, 503, 504):
                raise httpx.HTTPStatusError("throttled", request=r.request, response=r)
            if r.status_code == 401:
                raise SourceUnavailable("Shopify rejected the access token (401)")
            if r.status_code == 403:
                raise SourceUnavailable(
                    "Shopify returned 403 - the app is missing a required read scope")
            if r.status_code == 404:
                raise SourceUnavailable(
                    "Shopify returned 404 - check the store domain and API version")
            if 400 <= r.status_code < 500 and r.status_code != 429:
                raise SourceUnavailable(f"Shopify rejected the request ({r.status_code})")
            r.raise_for_status()
            body = r.json()
        except httpx.HTTPStatusError as exc:
            if attempt >= 5:
                raise SourceUnavailable(f"Shopify request failed after retries: {exc.response.status_code}")
            self.stats["retries"] += 1
            self.stats["throttled"] += 1
            await asyncio.sleep(min(30, 2 ** attempt) + (time.time() % 1))
            return await self._gql(query, variables, attempt + 1)
        except httpx.HTTPError as exc:
            if attempt >= 5:
                raise SourceUnavailable(f"Shopify transport error: {redact(str(exc))}")
            self.stats["retries"] += 1
            await asyncio.sleep(min(30, 2 ** attempt))
            return await self._gql(query, variables, attempt + 1)

        if body.get("errors"):
            messages = json.dumps(body["errors"])[:400]
            if "THROTTLED" in messages.upper() and attempt < 5:
                self.stats["retries"] += 1
                self.stats["throttled"] += 1
                await asyncio.sleep(min(30, 2 ** attempt))
                return await self._gql(query, variables, attempt + 1)
            raise SourceUnavailable(f"Shopify GraphQL error: {redact(messages)}")

        cost = (body.get("extensions") or {}).get("cost", {})
        status = cost.get("throttleStatus") or {}
        available = status.get("currentlyAvailable")
        restore = status.get("restoreRate") or 50
        if available is not None and available < 200:
            await asyncio.sleep(min(4.0, (300 - available) / max(restore, 1)))
        return body["data"]

    async def _paginate(self, query: str, root: str, cursor: str | None):
        while True:
            data = await self._gql(query, {"cursor": cursor})
            page = data[root]
            for node in page["nodes"]:
                yield node, page["pageInfo"]["endCursor"]
            if not page["pageInfo"]["hasNextPage"]:
                return
            cursor = page["pageInfo"]["endCursor"]

    def iter_products(self, cursor: str | None = None):
        return self._paginate(PRODUCTS_QUERY, "products", cursor)

    def iter_collections(self, cursor: str | None = None):
        return self._paginate(COLLECTIONS_QUERY, "collections", cursor)

    async def market_config(self) -> list[dict]:
        return (await self._gql(MARKETS_QUERY))["markets"]["nodes"]

    async def shop(self) -> dict:
        return (await self._gql(SHOP_QUERY))["shop"]

    async def verify(self) -> dict:
        shop = await self.shop()
        markets = await self.market_config()
        return {"shop_name": shop.get("name"), "primary_domain": (shop.get("primaryDomain") or {}).get("host"),
                "myshopify_domain": shop.get("myshopifyDomain"),
                "markets": [{"handle": m["handle"], "name": m["name"], "enabled": m["enabled"],
                             "primary": m.get("primary"),
                             "countries": [r["code"] for r in (m.get("regions") or {}).get("nodes", []) if r],
                             "root_urls": [u["url"] for u in ((m.get("webPresence") or {}).get("rootUrls") or [])],
                             "subfolder_suffix": (m.get("webPresence") or {}).get("subfolderSuffix")}
                            for m in markets]}


# ============================================================== GSC
class GSCDataSource(ABC):
    name = "abstract"

    @abstractmethod
    async def fetch_performance(self, *, start_date: str, end_date: str, markets: list[str]) -> list[dict]: ...


COUNTRY_CODE = {"AU": "aus", "NZ": "nzl", "US": "usa", "UK": "gbr", "CA": "can"}
MARKET_BY_COUNTRY = {v: k for k, v in COUNTRY_CODE.items()}


def _google_credentials(scopes: list[str], raw_json: str | None = None):
    s = get_settings()
    raw = raw_json or s.gsc_service_account_json
    if not raw:
        raise SourceUnavailable("Google service account is not configured")
    from google.oauth2 import service_account
    try:
        info = json.loads(raw)
    except ValueError:
        raise SourceUnavailable("The service account credential is not valid JSON")
    try:
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    except (ValueError, KeyError) as exc:
        raise SourceUnavailable(f"The service account credential is incomplete: {type(exc).__name__}")


class SearchAnalyticsAPISource(GSCDataSource):
    """searchAnalytics/query with page+query+country+device, 25k pagination, AU/NZ only."""

    name = "gsc_search_analytics_api"
    ROW_LIMIT = 25000

    def __init__(self, site_url: str | None = None, service_account_json: str | None = None):
        s = get_settings()
        self.site_url = site_url or s.gsc_site_url
        if not self.site_url:
            raise SourceUnavailable("GSC property is not configured")
        self._creds = _google_credentials(["https://www.googleapis.com/auth/webmasters.readonly"],
                                         service_account_json)

    def _client(self):
        from googleapiclient.discovery import build
        return build("searchconsole", "v1", credentials=self._creds, cache_discovery=False)

    def request_body(self, start_date: str, end_date: str, market: str, start_row: int = 0) -> dict:
        return {
            "startDate": start_date, "endDate": end_date, "type": "web",
            "dimensions": ["page", "query", "country", "device"],
            "dimensionFilterGroups": [{"groupType": "and", "filters": [
                {"dimension": "country", "operator": "equals", "expression": COUNTRY_CODE[market]}]}],
            "rowLimit": self.ROW_LIMIT, "startRow": start_row, "dataState": "final",
        }

    async def verify(self) -> dict:
        def _run():
            service = self._client()
            sites = service.sites().list().execute().get("siteEntry", [])
            return sites
        sites = await asyncio.to_thread(_run)
        match = next((s for s in sites if s.get("siteUrl") == self.site_url), None)
        if not match:
            raise SourceUnavailable(
                f"The service account can see {len(sites)} propertie(s) but not {self.site_url}. "
                "Add the service account email to that property in Search Console.")
        return {"site_url": match["siteUrl"], "permission_level": match.get("permissionLevel"),
                "visible_properties": len(sites)}

    async def fetch_performance(self, *, start_date: str, end_date: str, markets: list[str]) -> list[dict]:
        def _run():
            service = self._client()
            rows = []
            for market in markets:
                start_row = 0
                while True:
                    body = self.request_body(start_date, end_date, market, start_row)
                    resp = service.searchanalytics().query(siteUrl=self.site_url, body=body).execute()
                    batch = resp.get("rows", [])
                    for r in batch:
                        keys = r.get("keys", [])
                        rows.append({
                            "url": keys[0], "query": keys[1],
                            "country": keys[2], "device": (keys[3] or "").upper(),
                            "market": MARKET_BY_COUNTRY.get(keys[2], market),
                            "clicks": int(r.get("clicks", 0)),
                            "impressions": int(r.get("impressions", 0)),
                            "position": float(r.get("position", 0)),
                        })
                    if len(batch) < self.ROW_LIMIT:
                        break
                    start_row += self.ROW_LIMIT
            return rows
        return await asyncio.to_thread(_run)

    async def available_range(self) -> dict:
        """Probes the oldest and newest dates with data inside the configured bootstrap window."""
        s = get_settings()
        today = date.today()
        oldest_probe = today - timedelta(days=int(s.gsc_bootstrap_months * 30.5))

        def _run(start, end):
            service = self._client()
            body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
                    "dimensions": ["date"], "rowLimit": 25000, "type": "web"}
            resp = service.searchanalytics().query(siteUrl=self.site_url, body=body).execute()
            return [r["keys"][0] for r in resp.get("rows", [])]

        dates = await asyncio.to_thread(_run, oldest_probe, today)
        return {"days_with_data": len(dates), "first_date": min(dates) if dates else None,
                "last_date": max(dates) if dates else None,
                "requested_window_start": oldest_probe.isoformat(),
                "requested_window_end": today.isoformat()}


class BigQueryGSCSource(GSCDataSource):
    """Preferred ongoing production pipeline: searchdata_url_impression, partition-pruned."""

    name = "gsc_bigquery_bulk_export"

    def __init__(self, project: str | None = None, dataset: str | None = None,
                 location: str | None = None, service_account_json: str | None = None):
        s = get_settings()
        self.project = project or s.bigquery_project
        self.dataset = dataset or s.bigquery_dataset
        if not (self.project and self.dataset):
            raise SourceUnavailable("BigQuery project/dataset are not configured")
        self.location = location or s.bigquery_location
        self.site_url = s.gsc_site_url
        self._creds = _google_credentials(["https://www.googleapis.com/auth/cloud-platform"],
                                         service_account_json)

    def sql(self) -> str:
        return f"""
        SELECT url, query, country, device,
               SUM(impressions) AS impressions, SUM(clicks) AS clicks,
               SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) + 1 AS position
        FROM `{self.project}.{self.dataset}.searchdata_url_impression`
        WHERE data_date BETWEEN @start_date AND @end_date
          AND country IN UNNEST(@countries)
          AND search_type = 'WEB'
          AND query IS NOT NULL
        GROUP BY url, query, country, device
        """

    async def fetch_performance(self, *, start_date: str, end_date: str, markets: list[str]) -> list[dict]:
        from google.cloud import bigquery

        def _run():
            client = bigquery.Client(project=self.project, credentials=self._creds)
            job = client.query(self.sql(), location=self.location, job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                    bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
                    bigquery.ArrayQueryParameter("countries", "STRING",
                                                 [COUNTRY_CODE[m] for m in markets]),
                ]))
            out = []
            for row in job.result():
                out.append({"url": row["url"], "query": row["query"], "country": row["country"],
                            "device": (row["device"] or "").upper(),
                            "market": MARKET_BY_COUNTRY.get(row["country"], markets[0]),
                            "clicks": int(row["clicks"] or 0),
                            "impressions": int(row["impressions"] or 0),
                            "position": float(row["position"] or 0)})
            return out
        return await asyncio.to_thread(_run)

    async def verify(self) -> dict:
        from google.cloud import bigquery

        def _run():
            client = bigquery.Client(project=self.project, credentials=self._creds)
            table = client.get_table(f"{self.project}.{self.dataset}.searchdata_url_impression")
            return {"rows": table.num_rows, "modified": table.modified.isoformat() if table.modified else None}
        info = await asyncio.to_thread(_run)
        return {"dataset": f"{self.project}.{self.dataset}", **info}


def get_shopify_source() -> ShopifyCatalogSource:
    if not get_settings().live_data_mode:
        raise SourceUnavailable("DEMO data mode: the catalogue is served from seeded fixtures")
    return LiveShopifyAdapter()


def get_gsc_source(prefer: str = "auto") -> GSCDataSource:
    """BigQuery is preferred for ongoing production ingestion; the API covers bootstrap/backfill."""
    s = get_settings()
    if not s.live_data_mode:
        raise SourceUnavailable("DEMO data mode: GSC performance is served from seeded fixtures")
    if prefer == "api":
        return SearchAnalyticsAPISource()
    if prefer == "bigquery":
        return BigQueryGSCSource()
    try:
        return BigQueryGSCSource()
    except SourceUnavailable:
        return SearchAnalyticsAPISource()
