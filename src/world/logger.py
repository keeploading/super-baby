"""结构化日志（FDS §11）：逐条 JSON 行，可被人工查看或后续工具消费。

M1 用到的条目：visible 翻转、mood 切换（surprise→calm 为验收锚点）、
感知层耗时/FPS 聚合、连接/电量。
"""

import json
import sys
import time
from typing import TextIO


class BlackboardLogger:
    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def log(self, event: str, **fields) -> None:
        line = {"mono": time.monotonic(), "wall": time.time(), "event": event, **fields}
        self._stream.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._stream.flush()

    # ── 便捷封装（全部走 log()）──

    def visible_changed(self, visible: bool, ts: float) -> None:
        self.log("visible_changed", visible=visible, ts=ts)

    def mood_changed(self, mood: str, prev: str, source: str, ts: float) -> None:
        self.log("mood_changed", mood=mood, prev=prev, source=source, ts=ts)

    def perception_stats(
        self, fps: float, infer_ms_avg: float, infer_ms_p95: float, frames: int,
        max_landmarks: int = 0,
    ) -> None:
        self.log(
            "perception_stats",
            fps=round(fps, 1),
            infer_ms_avg=round(infer_ms_avg, 1),
            infer_ms_p95=round(infer_ms_p95, 1),
            frames=frames,
            max_landmarks=max_landmarks,
        )

    def connection(self, status: str, battery: float | None = None) -> None:
        self.log("connection", status=status, battery=battery)

    def battery_status(
        self, voltage: float, on_charger: bool, charging: bool, low: bool
    ) -> None:
        self.log(
            "battery_status",
            voltage=round(voltage, 2),
            on_charger=on_charger,
            charging=charging,
            low=low,
        )

    def link_stale(self, age: float) -> None:
        """底层遥测（RobotState）长时间未更新——机器人可能已断电/掉线/休眠。"""
        self.log("link_stale", age=round(age, 1))
