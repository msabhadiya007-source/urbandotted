"""Source connectors built against the REAL API contracts.

`DemoShopifyAdapter` / `DemoGSCDataSource` are development fixtures only. They implement the
same interface as the live connectors so no application code depends on the demo dataset.
Production mode requires live credentials and fails closed - never a silent demo fallback.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

from .config import get_settings


class SourceUnavailable(Exception):
    pass


# ----------------------------------------------------------------------------- Shopify
class ShopifyCatalogSource(ABC):
    @abstractmethod
    def iter_products(self) -> AsyncIterator[dict]: ...

    @abstractmethod
    def iter_collections(self) -> AsyncIterator[dict]: ...

    @abstractmethod
    async def market_config(self) -> list[dict]: ...


PRODUCTS_QUERY = """
query Products($cursor: String) {
  products(first: 100, after: $cursor, sortKey: UPDATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id handle title descriptionHtml productType vendor status updatedAt onlineStoreUrl
      seo { title description }
      featuredImage { url altText }
      variants(first: 50) { nodes { id sku price inventoryQuantity availableForSale } }
      collections(first: 10) { nodes { handle title } }
      metafields(first: 20) { nodes { namespace key value } }
    }
  }
}
"""


class LiveShopifyAdapter(ShopifyCatalogSource):
    """Admin GraphQL API. Stage 1 requires read_products, read_inventory, read_markets ONLY.

    No mutation is ever constructed in this class; there is no write method to call.
    """

    read_only_scopes = ["read_products", "read_inventory", "read_markets", "read_online_store_pages"]

    def __init__(self):
        s = get_settings()
        if not (s.shopify_shop_domain and s.shopify_admin_token):
            raise SourceUnavailable("Shopify credentials not configured")
        self.endpoint = f"https://{s.shopify_shop_domain}/admin/api/{s.shopify_api_version}/graphql.json"
        self.headers = {"X-Shopify-Access-Token": s.shopify_admin_token, "Content-Type": "application/json"}

    async def _gql(self, query: str, variables: dict) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(self.endpoint, headers=self.headers,
                                  json={"query": query, "variables": variables})
            r.raise_for_status()
            body = r.json()
        if body.get("errors"):
            raise SourceUnavailable(str(body["errors"]))
        return body["data"]

    async def iter_products(self):
        cursor = None
        while True:
            data = await self._gql(PRODUCTS_QUERY, {"cursor": cursor})
            page = data["products"]
            for node in page["nodes"]:
                yield node
            if not page["pageInfo"]["hasNextPage"]:
                return
            cursor = page["pageInfo"]["endCursor"]

    async def iter_collections(self):
        cursor = None
        q = ("query C($cursor:String){collections(first:100,after:$cursor){pageInfo{hasNextPage endCursor}"
             "nodes{id handle title descriptionHtml updatedAt seo{title description} productsCount{count}}}}")
        while True:
            data = await self._gql(q, {"cursor": cursor})
            page = data["collections"]
            for node in page["nodes"]:
                yield node
            if not page["pageInfo"]["hasNextPage"]:
                return
            cursor = page["pageInfo"]["endCursor"]

    async def market_config(self) -> list[dict]:
        q = ("{markets(first:20){nodes{id name handle enabled primary "
             "webPresences(first:5){nodes{rootUrls{url locale}subfolderSuffix}}}}}")
        data = await self._gql(q, {})
        return data["markets"]["nodes"]


# ----------------------------------------------------------------------------- GSC
class GSCDataSource(ABC):
    """BigQuery bulk export is primary in production; Search Analytics API is bootstrap/backfill."""

    @abstractmethod
    async def fetch_performance(self, *, start_date: str, end_date: str, markets: list[str]) -> list[dict]: ...


class BigQueryGSCSource(GSCDataSource):
    """Reads daily-partitioned searchdata_url_impression tables via a service account."""

    def __init__(self):
        s = get_settings()
        if not (s.bigquery_project and s.bigquery_dataset):
            raise SourceUnavailable("BigQuery project/dataset not configured")
        self.project, self.dataset = s.bigquery_project, s.bigquery_dataset

    def sql(self, start_date: str, end_date: str, markets: list[str]) -> str:
        countries = ", ".join(f"'{m.lower()}'" for m in markets)
        return f"""
        SELECT url, query, country, device,
               SUM(impressions) AS impressions, SUM(clicks) AS clicks,
               SAFE_DIVIDE(SUM(sum_top_position), SUM(impressions)) + 1 AS position, data_date
        FROM `{self.project}.{self.dataset}.searchdata_url_impression`
        WHERE data_date BETWEEN '{start_date}' AND '{end_date}'
          AND country IN ({countries}) AND query IS NOT NULL
        GROUP BY url, query, country, device, data_date
        """

    async def fetch_performance(self, *, start_date, end_date, markets):
        raise SourceUnavailable(
            "BigQuery client not provisioned in this environment. SQL contract is defined and ready.")


class SearchAnalyticsAPISource(GSCDataSource):
    """POST /webmasters/v3/sites/{site}/searchAnalytics/query - bootstrap + pre-BigQuery window."""

    def __init__(self):
        s = get_settings()
        if not (s.gsc_site_url and s.gsc_service_account_json):
            raise SourceUnavailable("GSC site URL / service account not configured")
        self.site_url = s.gsc_site_url

    def request_body(self, start_date: str, end_date: str, market: str) -> dict:
        return {
            "startDate": start_date, "endDate": end_date,
            "dimensions": ["page", "query", "country", "device"],
            "dimensionFilterGroups": [{"filters": [
                {"dimension": "country", "operator": "equals", "expression": market.lower()}]}],
            "rowLimit": 25000, "dataState": "final",
        }

    async def fetch_performance(self, *, start_date, end_date, markets):
        raise SourceUnavailable("GSC service account not provisioned. Request contract is defined and ready.")


def get_shopify_source() -> ShopifyCatalogSource:
    s = get_settings()
    if not s.demo_infra_mode:
        return LiveShopifyAdapter()
    raise SourceUnavailable("DEMO_INFRA_MODE: catalogue served from seeded fixtures")


def get_gsc_source() -> GSCDataSource:
    s = get_settings()
    if not s.demo_infra_mode:
        try:
            return BigQueryGSCSource()
        except SourceUnavailable:
            return SearchAnalyticsAPISource()
    raise SourceUnavailable("DEMO_INFRA_MODE: GSC served from seeded fixtures")
