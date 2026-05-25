import statistics
from collections import defaultdict

from app.models import ConditionSummary, SaleListing
from app.services.classifier import CONDITION_ORDER, classify_condition

# Max individual sales shown in the low-data fallback
_RECENT_SALES_LIMIT = 5


def _filter_outliers(prices: list[float]) -> list[float]:
    """Two-pass outlier removal.

    Pass 1 — median cap: drop anything above 10x the median. This catches
    joke/test listings like $790,975 even with very few data points, since
    the median itself is unaffected by a single extreme value.

    Pass 2 — IQR: drop anything outside Q1-3*IQR .. Q3+3*IQR. Handles
    subtler outliers once the extreme values are already gone.
    """
    if len(prices) < 2:
        return prices

    # Pass 1: median cap
    med = statistics.median(prices)
    if med > 0:
        prices = [p for p in prices if p <= 10 * med]

    if not prices:
        return prices

    # Pass 2: IQR
    if len(prices) < 4:
        return prices
    sorted_p = sorted(prices)
    n = len(sorted_p)
    q1 = sorted_p[n // 4]
    q3 = sorted_p[(3 * n) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return prices
    lower = q1 - 3 * iqr
    upper = q3 + 3 * iqr
    filtered = [p for p in prices if lower <= p <= upper]
    return filtered if filtered else prices


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
                sales=group,
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
                sales=group,
            ))

    return results
