import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models import ItemResult, PriceRequest, PriceResponse
from app.services.aggregator import aggregate
from app.services.cache import Cache
from app.services.ebay import APIAuthError, EbayClient, RateLimitError, UpstreamError

router = APIRouter()

_cache: Cache | None = None


def _get_cache(settings: Settings) -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache(settings.cache_dir, settings.cache_ttl_hours)
    return _cache


async def _fetch_item(
    item: str,
    request: PriceRequest,
    ebay_client: EbayClient,
    cache: Cache,
    settings: Settings,
    semaphore: asyncio.Semaphore,
) -> ItemResult:
    excluded = request.excluded_keywords
    cache_key = cache.make_key(item, excluded)

    # Cache hit
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        result = ItemResult.model_validate(cached_data["result"])
        result.cached = True
        result.cached_at = datetime.fromisoformat(cached_data["fetched_at"])
        return result

    # Cache miss — call eBay API (rate-limited by semaphore)
    async with semaphore:
        try:
            listings = await ebay_client.fetch_listings(
                keywords=item,
                excluded_keywords=excluded,
                max_results=request.max_results,
                remove_outliers=request.remove_outliers,
                category_id=request.category_id,
            )
        except APIAuthError as e:
            return ItemResult(query=item, conditions=[], total_results_fetched=0, error=str(e))
        except RateLimitError as e:
            return ItemResult(query=item, conditions=[], total_results_fetched=0, error=str(e))
        except UpstreamError as e:
            return ItemResult(query=item, conditions=[], total_results_fetched=0, error=str(e))
        except Exception as e:
            return ItemResult(query=item, conditions=[], total_results_fetched=0, error=f"Unexpected error: {e}")

    conditions = aggregate(listings, settings.low_data_threshold)
    result = ItemResult(
        query=item,
        conditions=conditions,
        total_results_fetched=len(listings),
    )

    # Only cache successful results with actual data
    if result.error is None and result.total_results_fetched > 0:
        cache.set(cache_key, {
            "result": result.model_dump(mode="json"),
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        })

    return result


@router.post("/prices", response_model=PriceResponse)
async def check_prices(
    request: PriceRequest,
    settings: Settings = Depends(get_settings),
) -> PriceResponse:
    ebay_client = EbayClient(settings)
    cache = _get_cache(settings)
    semaphore = asyncio.Semaphore(settings.ebay_concurrency_limit)

    tasks = [
        _fetch_item(item, request, ebay_client, cache, settings, semaphore)
        for item in request.items
    ]
    results = await asyncio.gather(*tasks)

    return PriceResponse(
        results=list(results),
        requested_at=datetime.now(tz=timezone.utc),
    )
