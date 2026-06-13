"""最新帧槽位（FDS §4.2.1）：覆盖式、带锁，丢旧帧只留最新，避免帧积压时延累积。"""

import threading
from typing import Any


class LatestFrameSlot:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Any | None = None
        self._ts: float | None = None

    def put(self, frame: Any, ts: float) -> None:
        with self._lock:
            self._frame = frame
            self._ts = ts

    def get_if_newer(self, than_ts: float) -> tuple[Any, float] | None:
        """返回比 than_ts 新的最新帧，否则 None（防止重复推理同一帧）。"""
        with self._lock:
            if self._ts is None or self._ts <= than_ts:
                return None
            return self._frame, self._ts
