"""A 60 second cache for analytics responses. Redis when `CACHE_URL` is set, otherwise memory in the
process. A cache that cannot be reached is a miss, never an error. Bumping the version drops every
entry at once (done when the snapshots are rebuilt)."""

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from app.core.config import Settings

TTL_SECONDS = 60
VERSION_KEY = "analytics:version"


class Cache(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes, ttl: int = TTL_SECONDS) -> None: ...
    def version(self) -> int: ...
    def bump(self) -> int: ...


class MemoryCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, tuple[float, bytes]] = {}
        self._version = 1

    def get(self, key: str) -> bytes | None:
        item = self._items.get(key)
        if item is None or item[0] <= self._clock():
            self._items.pop(key, None)
            return None
        return item[1]

    def set(self, key: str, value: bytes, ttl: int = TTL_SECONDS) -> None:
        self._items[key] = (self._clock() + ttl, value)

    def version(self) -> int:
        return self._version

    def bump(self) -> int:
        self._version += 1
        self._items.clear()
        return self._version


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)

    def get(self, key: str) -> bytes | None:
        try:
            value = self._redis.get(key)
            return value if isinstance(value, bytes) else None
        except Exception:
            return None

    def set(self, key: str, value: bytes, ttl: int = TTL_SECONDS) -> None:
        try:
            self._redis.set(key, value, ex=ttl)
        except Exception:
            return None

    def version(self) -> int:
        try:
            return int(self._redis.get(VERSION_KEY) or 1)
        except Exception:
            return 1

    def bump(self) -> int:
        try:
            return int(self._redis.incr(VERSION_KEY))
        except Exception:
            return 1


def build_cache(settings: Settings) -> Cache:
    return RedisCache(settings.cache_url) if settings.cache_url else MemoryCache()


def cache_key(cache: Cache, scope: str, endpoint: str, params: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[
        :24
    ]
    return f"analytics:v{cache.version()}:{scope}:{endpoint}:{digest}"
