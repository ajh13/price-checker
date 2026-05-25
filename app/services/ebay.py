import asyncio
import time
import unicodedata
from datetime import datetime

import httpx

from app.models import SaleListing


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


def _ascii_keywords(text: str) -> str:
    """Normalize accented characters to ASCII equivalents (é→e, ñ→n, etc.)
    so eBay search handles them correctly."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


class APIAuthError(Exception):
    pass


class RateLimitError(Exception):
    pass


class UpstreamError(Exception):
    pass


_VALID_MAX_RESULTS = [60, 120, 240]


def _clamp_max_results(value: int) -> str:
    """Clamp to the nearest valid max_search_results value and return as string."""
    closest = min(_VALID_MAX_RESULTS, key=lambda v: abs(v - value))
    return str(closest)


def _parse_sale_date(date_str: str | None) -> "datetime.date":
    if not date_str:
        return datetime.now().date()
    # Try eBay's human-readable format first: "May 24, 2026"
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    # Fall back to ISO 8601
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return datetime.now().date()


_MAX_RETRIES = 4
_RETRY_BASE_WAIT = 1.0  # seconds to wait after first 429, doubles each retry


class EbayClient:
    BASE_URL = "https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems"

    def __init__(self, settings):
        self._settings = settings

    async def fetch_listings(
        self,
        keywords: str,
        excluded_keywords: list[str] = [],
        max_results: int | None = None,
        remove_outliers: bool = True,
        category_id: str | None = None,
    ) -> list[SaleListing]:
        effective_max = max_results if max_results is not None else self._settings.ebay_max_results
        max_results_str = _clamp_max_results(effective_max)

        headers = {
            "x-rapidapi-key": self._settings.rapidapi_key.get_secret_value(),
            "x-rapidapi-host": self._settings.rapidapi_host,
            "Content-Type": "application/json",
        }

        body: dict = {
            "keywords": _ascii_keywords(keywords),
            "max_search_results": max_results_str,
            "remove_outliers": remove_outliers,
        }

        if excluded_keywords:
            body["excluded_keywords"] = " ".join(excluded_keywords)

        if category_id is not None:
            body["category_id"] = category_id

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(self.BASE_URL, headers=headers, json=body)
            except httpx.TimeoutException as exc:
                raise UpstreamError("eBay API error: timeout") from exc

            status = response.status_code

            if status in (401, 403):
                raise APIAuthError("Invalid API key — check RAPIDAPI_KEY in .env")

            if status == 429:
                if attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BASE_WAIT * (2 ** attempt)  # 1s, 2s, 4s
                    await asyncio.sleep(wait)
                    continue
                raise RateLimitError("eBay API rate limit hit after retries")

            if status >= 500:
                raise UpstreamError(f"eBay API error: {status}")

            try:
                payload = response.json()
            except Exception as exc:
                raise UpstreamError("eBay API error: invalid JSON response") from exc

            # Response shape: listings are under "products", aggregates at top level
            raw_items: list = payload.get("products", []) if isinstance(payload, dict) else []

            listings: list[SaleListing] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue

                title = item.get("title") or ""

                try:
                    price = float(item.get("sale_price") or 0)
                except (TypeError, ValueError):
                    price = 0.0

                sale_date = _parse_sale_date(item.get("date_sold"))
                url = item.get("link") or None

                listings.append(
                    SaleListing(
                        title=title,
                        price=price,
                        sale_date=sale_date,
                        url=url,
                        source="eBay",
                    )
                )

            return listings

        raise UpstreamError("eBay API failed after all retries")
