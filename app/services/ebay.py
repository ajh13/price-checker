from datetime import datetime

import httpx

from app.models import SaleListing


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
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return datetime.now().date()


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
            "keywords": keywords,
            "max_search_results": max_results_str,
            "remove_outliers": remove_outliers,
        }

        if excluded_keywords:
            body["excluded_keywords"] = " ".join(excluded_keywords)

        if category_id is not None:
            body["category_id"] = category_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.BASE_URL, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise UpstreamError(f"eBay API error: timeout") from exc

        status = response.status_code

        if status in (401, 403):
            raise APIAuthError("Invalid API key — check RAPIDAPI_KEY in .env")
        if status == 429:
            raise RateLimitError("eBay API rate limit hit")
        if status >= 500:
            raise UpstreamError(f"eBay API error: {status}")

        try:
            payload = response.json()
        except Exception as exc:
            raise UpstreamError(f"eBay API error: invalid JSON response") from exc

        # The RapidAPI eBay sold items endpoint returns results under various keys.
        # Try known candidates in order of likelihood.
        raw_items: list = []
        if isinstance(payload, list):
            raw_items = payload
        else:
            for candidate in ("results", "data", "items", "listings"):
                if candidate in payload and isinstance(payload[candidate], list):
                    raw_items = payload[candidate]
                    break

        listings: list[SaleListing] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            # Title
            title = item.get("title") or item.get("name") or ""

            # Price — may be nested under "price" dict or a flat float/string
            price_raw = item.get("sale_price") or item.get("price") or item.get("soldPrice") or 0
            if isinstance(price_raw, dict):
                price = float(price_raw.get("value") or price_raw.get("amount") or 0)
            else:
                try:
                    price = float(price_raw)
                except (TypeError, ValueError):
                    price = 0.0

            # Sale date
            date_str = (
                item.get("sold_date")
                or item.get("sale_date")
                or item.get("dateSold")
                or item.get("date")
            )
            sale_date = _parse_sale_date(date_str)

            # URL
            url = item.get("url") or item.get("itemUrl") or item.get("link") or None

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
