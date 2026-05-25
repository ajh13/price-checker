from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field


class PriceRequest(BaseModel):
    items: Annotated[list[str], Field(min_length=1, max_length=20)]
    excluded_keywords: list[str] = ["lot", "bundle", "repair", "broken", "parts", "for parts"]
    max_results: int | None = None
    remove_outliers: bool = True
    category_id: str | None = None


class SaleListing(BaseModel):
    title: str
    price: float
    sale_date: date
    url: str | None = None
    source: str = "eBay"


class ConditionSummary(BaseModel):
    condition: str
    count: int
    average_price: float | None = None
    median_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    recent_sales: list[SaleListing] | None = None  # low-data fallback (< threshold)
    sales: list[SaleListing] = []                   # all individual sales, always populated


class ItemResult(BaseModel):
    query: str
    conditions: list[ConditionSummary]
    total_results_fetched: int
    source: str = "eBay"
    cached: bool = False
    cached_at: datetime | None = None
    error: str | None = None


class PriceResponse(BaseModel):
    results: list[ItemResult]
    requested_at: datetime
