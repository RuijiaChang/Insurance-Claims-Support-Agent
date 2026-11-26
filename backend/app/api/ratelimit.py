"""In-process sliding-window limiter for server-key turns (spec §10 cost protection)."""

import threading
from collections import deque

MINUTE = 60.0
DAY = 86_400.0


def _trim(window: deque[float], now: float, span: float) -> None:
    while window and now - window[0] >= span:
        window.popleft()


class SlidingWindowLimiter:
    def __init__(self, per_ip_per_min: int, per_ip_per_day: int, global_per_day: int) -> None:
        self.per_ip_per_min = per_ip_per_min
        self.per_ip_per_day = per_ip_per_day
        self.global_per_day = global_per_day
        self._ip_day: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self, ip: str, now: float) -> bool:
        """Record one request for ``ip`` at ``now`` if every window allows it."""
        with self._lock:
            _trim(self._global, now, DAY)
            day = self._ip_day.setdefault(ip, deque())
            _trim(day, now, DAY)
            last_minute = sum(1 for t in day if now - t < MINUTE)
            if (
                last_minute >= self.per_ip_per_min
                or len(day) >= self.per_ip_per_day
                or len(self._global) >= self.global_per_day
            ):
                if not day:
                    del self._ip_day[ip]
                return False
            day.append(now)
            self._global.append(now)
            return True
