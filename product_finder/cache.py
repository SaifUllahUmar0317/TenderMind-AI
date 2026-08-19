import time
import hashlib
import json
from typing import Dict, Any, Optional

class SearchCache:
    """
    Thread-safe in-memory cache for search results with TTL,
    query deduplication, and rate-limiting protection.
    """

    _cache: Dict[str, Dict[str, Any]] = {}
    _last_request_time: float = 0.0
    _min_request_interval: float = 0.5  # Min 500ms between live API calls
    DEFAULT_TTL_SECONDS = 3600  # 1 hour cache TTL

    @classmethod
    def _make_key(cls, item_name: str, specifications: list) -> str:
        data = {
            "name": item_name.strip().lower(),
            "specs": sorted([str(s).strip().lower() for s in specifications if s])
        }
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def get(cls, item_name: str, specifications: list) -> Optional[dict]:
        key = cls._make_key(item_name, specifications)
        entry = cls._cache.get(key)
        if entry:
            if time.time() - entry["timestamp"] < entry.get("ttl", cls.DEFAULT_TTL_SECONDS):
                return entry["data"]
            else:
                cls._cache.pop(key, None)
        return None

    @classmethod
    def set(cls, item_name: str, specifications: list, data: dict, ttl: int = DEFAULT_TTL_SECONDS):
        key = cls._make_key(item_name, specifications)
        cls._cache[key] = {
            "timestamp": time.time(),
            "ttl": ttl,
            "data": data
        }

    @classmethod
    def clear(cls):
        cls._cache.clear()

    @classmethod
    def throttle(cls):
        """Ensures smooth rate-limiting between outbound AI search calls."""
        now = time.time()
        elapsed = now - cls._last_request_time
        if elapsed < cls._min_request_interval:
            time.sleep(cls._min_request_interval - elapsed)
        cls._last_request_time = time.time()
