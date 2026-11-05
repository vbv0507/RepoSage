"""Small in-process TTL cache used when no external cache service is deployed."""

from typing import Any, Optional

from cachetools import TTLCache


class CacheService:
    """Async-compatible wrapper that keeps the existing cache call pattern."""

    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 3600):
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=maxsize, ttl=ttl_seconds)

    def get_status(self) -> dict:
        return {"connected": True, "type": "in-memory", "maxsize": self._cache.maxsize}

    async def get(self, key: str) -> Optional[Any]:
        return self._cache.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        # TTLCache has one expiry policy for the process. Keeping this signature
        # avoids changing existing callers that supplied custom TTL values.
        self._cache[key] = value
        return True

    async def delete(self, key: str) -> bool:
        self._cache.pop(key, None)
        return True


cache_service = CacheService()
