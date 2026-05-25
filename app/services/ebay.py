import asyncio
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.models import SaleListing


@dataclass
class FetchResult:
    listings: list[SaleListing] = field(default_factory=list)
    api_average_price: float | None = None
    api_median_price: float | None = None


class RateLimiter:
    """Enforces a minimum interval between calls (token bucket, 1 token at a time)."""

    def __init__(self, calls_per_second: float):
        self._interval = 1.0 / calls_per_second
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()


def _clean_keywords(text: str) -> str:
    """Strip inventory-style annotations before sending to eBay search.

    Removes:
    - Parenthetical notes: (CIB), (missing manual), (Player's Choice edition), etc.
    - Price suffixes: : $55, : $140.00
    Then normalizes accented characters to ASCII (é→e, ñ→n, etc.).
    """
    text = re.sub(r'\s*:\s*\$[\d.,]+', '', text)
    text = re.sub(r'\s*\([^)]*\)', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


class APIAuthError(Exception):
    pass


class RateLimitError(Exception):
    pass


class UpstreamError(Exception):
    pass


# eBay Finding API — official, no intermediary
_BASE_URL = "https://svcs.ebay.com/services/search/FindingService/v1"
_MAX_PER_PAGE = 100
_MAX_RETRIES = 3
_RETRY_BASE_WAIT = 2.0


def _ebay_val(obj: dict, *keys: str) -> str | None:
    """Walk a chain of keys through eBay's list-wrapped JSON structure.

    eBay wraps every value in a single-element list, e.g.:
        item["title"][0]  instead of  item["title"]
    This helper navigates that safely and returns None if anything is missing.
    """
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        lst = cur.get(key)
        if not lst or not isinstance(lst, list):
            return None
        cur = lst[0]
    return cur if isinstance(cur, str) else None


def _parse_iso_date(date_str: str | None):
    if not date_str:
        return datetime.now().date()
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return datetime.now().date()


class EbayClient:
    def __init__(self, settings):
        self._settings = settings

    async def fetch_listings(
        self,
        keywords: str,
        excluded_keywords: list[str] = [],
        max_results: int | None = None,
        remove_outliers: bool = True,
        category_id: str | None = None,
    ) -> FetchResult:
        effective_max = max_results if max_results is not None else self._settings.ebay_max_results
        pages_needed = math.ceil(effective_max / _MAX_PER_PAGE)

        clean_kw = _clean_keywords(keywords)
        # eBay search supports -word exclusions directly in the keyword string
        if excluded_keywords:
            exclusions = " ".join(f"-{kw}" for kw in excluded_keywords)
            clean_kw = f"{clean_kw} {exclusions}"

        app_id = self._settings.ebay_app_id.get_secret_value()

        all_listings: list[SaleListing] = []

        for page in range(1, pages_needed + 1):
            per_page = min(_MAX_PER_PAGE, effective_max - len(all_listings))
            params = {
                "OPERATION-NAME": "findCompletedItems",
                "SERVICE-VERSION": "1.0.0",
                "SECURITY-APPNAME": app_id,
                "RESPONSE-DATA-FORMAT": "JSON",
                "REST-PAYLOAD": "",
                "keywords": clean_kw,
                "paginationInput.entriesPerPage": str(per_page),
                "paginationInput.pageNumber": str(page),
                # Only sold items, US site
                "itemFilter(0).name": "SoldItemsOnly",
                "itemFilter(0).value": "true",
                "itemFilter(1).name": "LocatedIn",
                "itemFilter(1).value": "US",
                "sortOrder": "EndTimeSoonest",
                "siteid": "0",
            }

            if category_id:
                params["categoryId"] = category_id

            for attempt in range(_MAX_RETRIES):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.get(_BASE_URL, params=params)
                except httpx.TimeoutException as exc:
                    raise UpstreamError("eBay API error: timeout") from exc

                status = response.status_code

                if status in (401, 403):
                    raise APIAuthError("Invalid eBay App ID — check EBAY_APP_ID in .env")

                if status == 429:
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(_RETRY_BASE_WAIT * (2 ** attempt))
                        continue
                    raise RateLimitError("eBay API rate limit hit after retries")

                if status >= 500:
                    raise UpstreamError(f"eBay API error: {status}")

                try:
                    payload = response.json()
                except Exception as exc:
                    raise UpstreamError("eBay API error: invalid JSON response") from exc

                break  # success — exit retry loop
            else:
                raise UpstreamError("eBay API failed after all retries")  # pragma: no cover

            # Navigate the Finding API response envelope
            try:
                resp = payload["findCompletedItemsResponse"][0]
            except (KeyError, IndexError, TypeError):
                raise UpstreamError("eBay API error: unexpected response shape")

            ack = _ebay_val(resp, "ack")
            if ack not in ("Success", "Warning"):
                error_msg = _ebay_val(resp, "errorMessage", "error", "message") or "unknown error"
                raise UpstreamError(f"eBay API error: {error_msg}")

            search_result = resp.get("searchResult", [{}])[0]
            items = search_result.get("item", [])

            for item in items:
                if not isinstance(item, dict):
                    continue

                title = _ebay_val(item, "title") or ""

                # Only include items that actually sold
                selling_state = _ebay_val(item, "sellingStatus", "sellingState")
                if selling_state != "EndedWithSales":
                    continue

                try:
                    price_str = _ebay_val(item, "sellingStatus", "convertedCurrentPrice", "__value__")
                    price = float(price_str or 0)
                except (TypeError, ValueError):
                    price = 0.0

                if price <= 0:
                    continue

                end_time = _ebay_val(item, "listingInfo", "endTime")
                sale_date = _parse_iso_date(end_time)
                url = _ebay_val(item, "viewItemURL")

                all_listings.append(SaleListing(
                    title=title,
                    price=price,
                    sale_date=sale_date,
                    url=url,
                    source="eBay",
                ))

            # Stop paginating if eBay returned fewer items than requested
            if len(items) < per_page:
                break

        return FetchResult(listings=all_listings)
