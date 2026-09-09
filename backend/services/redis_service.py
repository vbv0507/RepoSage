import os
import time
import json
import logging
from typing import Any, Optional

logger = logging.getLogger("redis_service")

class CacheService:
    def __init__(self):
        self.redis_client = None
        self.is_redis_available = False
        self.memory_store = {}
        self.memory_expiries = {}
        self._connect()

    def _connect(self):
        redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_url = os.getenv("REDIS_URL")

        try:
            import redis
            if redis_url:
                self.redis_client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
            else:
                self.redis_client = redis.Redis(host=redis_host, port=redis_port, socket_connect_timeout=1, socket_timeout=1)
            
            self.redis_client.ping()
            self.is_redis_available = True
            logger.info("Connected to Redis cache layer.")
        except Exception:
            self.is_redis_available = False
            self.redis_client = None
            logger.info("Redis not reachable. Operating with in-memory caching.")

    def get_status(self) -> dict:
        return {
            "connected": self.is_redis_available,
            "type": "redis" if self.is_redis_available else "in-memory"
        }

    async def get(self, key: str) -> Optional[Any]:
        if self.is_redis_available and self.redis_client:
            try:
                raw = self.redis_client.get(key)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.warning(f"Redis get error: {e}")
        
        # Memory fallback
        if key in self.memory_store:
            expiry = self.memory_expiries.get(key)
            if expiry and time.time() > expiry:
                del self.memory_store[key]
                del self.memory_expiries[key]
                return None
            return self.memory_store[key]
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 86400) -> bool:
        if self.is_redis_available and self.redis_client:
            try:
                payload = json.dumps(value)
                self.redis_client.setex(key, ttl_seconds, payload)
                return True
            except Exception as e:
                logger.warning(f"Redis set error: {e}")

        # Memory fallback
        self.memory_store[key] = value
        if ttl_seconds:
            self.memory_expiries[key] = time.time() + ttl_seconds
        return True

    async def delete(self, key: str) -> bool:
        if self.is_redis_available and self.redis_client:
            try:
                self.redis_client.delete(key)
            except Exception:
                pass
        self.memory_store.pop(key, None)
        self.memory_expiries.pop(key, None)
        return True

cache_service = CacheService()
