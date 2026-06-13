"""黑板（FDS §3）：层间唯一共享状态。

并发契约（FDS §3.3，不可违背）：
- 单写者：每个字段只有注明的那一层写（person/cube/cliff/battery=感知层，mood=任务层
  mood-translator，intention/cog_decision_ts=认知层）。
- 整体原子替换：复合字段（person/cube）为构造后不可变对象，写者构造全新对象一次替换引用。
- 周期快照：所有 set_* 与 snapshot() 走同一把 threading.Lock；snapshot() 在锁内一次性
  拷贝全部字段引用，读者永不读到撕裂快照。
- 时间戳一律 time.monotonic()。
"""

import threading
from dataclasses import dataclass
from typing import Any

from world.logger import BlackboardLogger


@dataclass(frozen=True)
class Person:
    """感知层产出的复合对象；M1 仅 visible/last_seen_ts 有效，cx/size 预留 M3。"""

    visible: bool
    cx_norm: float | None = None
    size_norm: float | None = None
    cxsize_stale: bool = False
    last_seen_ts: float = 0.0


@dataclass(frozen=True)
class BlackboardSnapshot:
    person: Person | None
    cube: Any | None
    cliff_detected: bool
    battery: float
    mood: str
    mood_source: str
    mood_ts: float
    intention: str
    cog_decision_ts: float


class Blackboard:
    def __init__(self, logger: BlackboardLogger) -> None:
        self._lock = threading.Lock()
        self._logger = logger
        self._person: Person | None = None
        self._cube: Any | None = None  # M1 恒 None，M2 启用
        self._cliff_detected = False
        self._battery = 0.0
        self._mood = "calm"
        self._mood_source = "immediate"
        self._mood_ts = 0.0
        self._intention = "free_roam"  # M1 占位，M2 起认知层写
        self._cog_decision_ts = 0.0

    # ── 感知层写 ──

    def set_person(self, person: Person | None) -> None:
        with self._lock:
            prev_visible = self._person.visible if self._person else False
            self._person = person
        new_visible = person.visible if person else False
        if prev_visible != new_visible:
            ts = person.last_seen_ts if person else 0.0
            self._logger.visible_changed(new_visible, ts)

    def set_battery(self, voltage: float) -> None:
        with self._lock:
            self._battery = voltage

    def set_cliff_detected(self, flag: bool) -> None:
        with self._lock:
            self._cliff_detected = flag

    # ── 任务层（mood-translator）写 ──

    def set_mood(self, mood: str, source: str, ts: float) -> None:
        with self._lock:
            prev = self._mood
            self._mood = mood
            self._mood_source = source
            self._mood_ts = ts
        if prev != mood:
            self._logger.mood_changed(mood, prev, source, ts)

    # ── 快照 ──

    def snapshot(self) -> BlackboardSnapshot:
        with self._lock:
            return BlackboardSnapshot(
                person=self._person,
                cube=self._cube,
                cliff_detected=self._cliff_detected,
                battery=self._battery,
                mood=self._mood,
                mood_source=self._mood_source,
                mood_ts=self._mood_ts,
                intention=self._intention,
                cog_decision_ts=self._cog_decision_ts,
            )
