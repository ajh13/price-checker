import statistics
from collections import defaultdict

from app.models import ConditionSummary, SaleListing
from app.services.classifier import CONDITION_ORDER, classify_condition

# Max individual sales shown in the low-data fallback
_RECENT_SALES_LIMIT = 5


def _filter_outliers(prices: list[float], reference: float | None = None) -> list[float]:
    """Three-pass outlier removal.

    Pass 0 — gap detection: find the largest proportional jump between
    consecutive sorted prices. A jump > 5x signals a bimodal distribution
    caused by API price corruption where some (or most) individual prices are
    inflated by 10-100x while the lower cluster is legitimate. We keep only
    the lower cluster. This fires even when the API's own aggregate is also
    corrupted (e.g. Chibi Robo, Wario World), because the real prices are
    always anchored at the low end.

    Pass 1 — median cap: drop anything above 10x the median. When the API
    corrupts ALL prices uniformly (e.g. Animal Crossing returning $1.5M when
    the true price is ~$48), the median is also corrupted but the API's own
    reported average_price (reference) is still correct. In that case we use
    the reference for the cap so everything gets filtered and the caller falls
    back to the API aggregate.

    Pass 2 — IQR: drop anything outside Q1-3*IQR .. Q3+3*IQR. Handles
    subtler remaining outliers.
    """
    if len(prices) < 2:
        return prices

    # Pass 0: gap detection — cuts bimodal corrupt distributions at the cluster boundary
    sorted_all = sorted(prices)
    max_ratio = 1.0
    cut_idx = len(sorted_all)
    for i in range(len(sorted_all) - 1):
        if sorted_all[i] > 0:
            ratio = sorted_all[i + 1] / sorted_all[i]
            if ratio > max_ratio:
                max_ratio = ratio
                cut_idx = i + 1
    # Only cut if the gap is large AND the lower cluster has real substance.
    # min_cluster prevents cutting on a single cheap mislist at the bottom.
    min_cluster = max(2, int(0.05 * len(sorted_all)))
    if max_ratio > 5.0 and cut_idx >= min_cluster:
        prices = sorted_all[:cut_idx]

    if not prices:
        return prices

    # Pass 1: median cap (with API corruption fallback for all-corrupted case)
    med = statistics.median(prices)
    if reference and reference > 0 and med > 100 * reference:
        cap_base = reference
    else:
        cap_base = med

    if cap_base > 0:
        prices = [p for p in prices if p <= 10 * cap_base]

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


def aggregate(
    listings: list[SaleListing],
    threshold: int,
    api_average_price: float | None = None,
    api_median_price: float | None = None,
) -> list[ConditionSummary]:
    """Group listings by condition and compute per-condition price summaries.

    For conditions with >= threshold sales: returns avg/median/min/max.
    For conditions with < threshold sales: returns the most recent individual
    sales so the user can judge recency and trend themselves.

    When api_average_price is provided it is used as the reference for the
    outlier cap (Pass 1). If all individual prices are corrupted and get
    filtered out, we fall back to the API's reported aggregate values so the
    user still sees a useful price rather than nothing.
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
            prices = _filter_outliers(raw_prices, reference=api_average_price)

            if not prices and api_average_price:
                # All individual prices were corrupted (known API data quality issue).
                # Fall back to the API's own reported aggregate — it is computed
                # server-side from the real data before corruption occurs.
                results.append(ConditionSummary(
                    condition=condition,
                    count=count,
                    average_price=round(api_average_price, 2),
                    median_price=round(api_median_price, 2) if api_median_price else round(api_average_price, 2),
                    min_price=None,
                    max_price=None,
                    recent_sales=None,
                    sales=[],
                    data_note="Individual sale prices appear corrupted in the API response; showing API-reported aggregate.",
                ))
                continue

            if not prices:
                prices = raw_prices  # last resort: show unfiltered rather than nothing

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
