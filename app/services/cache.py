import hashlib
import json
import os
from datetime import datetime, timezone


class Cache:
    def __init__(self, cache_dir: str, ttl_hours: float):
        self.cache_dir = cache_dir
        self.ttl_hours = ttl_hours
        self._cache_path = os.path.join(cache_dir, "prices.json")
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        os.makedirs(self.cache_dir, exist_ok=True)
        if os.path.exists(self._cache_path):
            try:
                with open(self._cache_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}
        return self._data

    def _save(self) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f)

    def _cache_key(self, keywords: str, excluded: list[str]) -> str:
        normalized = keywords.lower().strip()
        sorted_excluded = sorted(kw.lower().strip() for kw in excluded)
        combined = normalized + "|" + ",".join(sorted_excluded)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def make_key(self, keywords: str, excluded: list[str]) -> str:
        return self._cache_key(keywords, excluded)

    def get(self, key: str) -> dict | None:
        cache = self._load()
        entry = cache.get(key)
        if entry is None:
            return None
        expires_at = datetime.fromisoformat(entry["expires_at"])
        now = datetime.now(tz=timezone.utc)
        if now >= expires_at:
            return None
        return entry["data"]

    def set(self, key: str, data: dict) -> None:
        cache = self._load()
        ttl_seconds = self.ttl_hours * 3600
        expires_at = datetime.now(tz=timezone.utc).timestamp() + ttl_seconds
        expires_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        cache[key] = {
            "data": data,
            "expires_at": expires_dt.isoformat(),
        }
        self._save()
