"""Small, bounded, defensive cache of read-only workspace projections."""
from collections import OrderedDict
from copy import deepcopy
import json
from threading import Lock
from time import monotonic


class ProjectionCache:
    def __init__(self, *, capacity=2, max_bytes=64 * 1024 * 1024, ttl=20, clock=monotonic):
        self.capacity, self.max_bytes, self.ttl, self.clock = capacity, max_bytes, ttl, clock
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = Lock()
        self.hits = self.misses = 0

    def get(self, key):
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                self.misses += 1
                return None
            created, size, value = item
            if self.clock() - created >= self.ttl:
                del self._entries[key]
                self._bytes -= size
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
        return deepcopy(value)

    def put(self, key, value):
        # Estimate retained payload size before keeping a defensive copy.
        size = len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
        if size > self.max_bytes:
            return False
        saved = deepcopy(value)
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous:
                self._bytes -= previous[1]
            while self._entries and (len(self._entries) >= self.capacity or self._bytes + size > self.max_bytes):
                _, item = self._entries.popitem(last=False)
                self._bytes -= item[1]
            self._entries[key] = (self.clock(), size, saved)
            self._bytes += size
        return True
