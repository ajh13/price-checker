import statistics
from collections import defaultdict

from app.models import ConditionSummary, SaleListing
from app.services.classifier import CONDITION_ORDER, classify_condition

# Max individual sales shown in the low-data fallback
_RECENT_SALES_LIMIT = 5
# Outlier filter: drop listings beyond this many std deviations from the mean
_OUTLIER_STD_MULTIPLIER = 2.5


def _filter_outliers(prices: list[float]) -> list[float]:
    """Remove prices more than 2.5 std deviations from the mean."""
    if len(prices) < 4:
        return prices
    mean = statistics.mean(prices)
    stdev = statistics.stdev(prices)
    if stdev == 0:
        return prices
    return [p for p in prices if abs(p - mean) <= _OUTLIER_STD_MULTIPLIER * stdev]


def aggregate(listings: list[SaleListing], threshold: int) -> list[ConditionSummary]:
    """Group listings by condition and compute per-condition price summaries.

    For conditions with >= threshold sales: returns avg/median/min/max.
    For conditions with < threshold sales: returns the most recent individual
    sales so the user can judge recency and trend themselves.
    """
    groups: dict[str, list[SaleListing]] = defaultdict(list)
    for listing in listings:
        condition = classify_condition(listing.title)
        groups[condition].append(listing)

    results: list[ConditionSummary] = []
    for condition in CONDITION_ORDER:
        if condition not in groups:
            continue

        # Sort newest-first for consistent fallback display
        group = sorted(groups[condition], key=lambda x: x.sale_date, reverse=True)
        count = len(group)

        if count >= threshold:
            raw_prices = [l.price for l in group]
            prices = _filter_outliers(raw_prices)
            if not prices:
                prices = raw_prices  # fallback if outlier filter removes everything

            results.append(ConditionSummary(
                condition=condition,
                count=count,
                average_price=round(statistics.mean(prices), 2),
                median_price=round(statistics.median(prices), 2),
                min_price=round(min(prices), 2),
                max_price=round(max(prices), 2),
                recent_sales=None,
            ))
        else:
            results.append(ConditionSummary(
                condition=condition,
                count=count,
                average_price=None,
                median_price=None,
                min_price=None,
                max_price=None,
                recent_sales=group[:_RECENT_SALES_LIMIT],
            ))

    return results
