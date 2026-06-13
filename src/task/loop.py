"""任务层极简循环（FDS §14 S-9，线程 B ~10Hz）。

这就是 M2 任务层线程 B 的入口骨架：每拍先 snapshot() 再决策再经 HAL 下发。M2 在
同一循环内增加 FSM.tick()、M3 叠加视觉伺服——往同一循环里塞模块，不另起循环。
每拍记录实际间隔，超 1.5× 周期输出 jitter 日志（FDS §13.1 GIL 验证项数据来源）。
"""

import threading
import time
from typing import Callable

from world.blackboard import Blackboard
from world.logger import BlackboardLogger

from task.mood_translator import MoodCtx, MoodTranslator


class TaskLoop:
    def __init__(
        self,
        blackboard: Blackboard,
        mood_translator: MoodTranslator,
        logger: BlackboardLogger,
        hz: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bb = blackboard
        self._translator = mood_translator
        self._logger = logger
        self._period = 1.0 / hz
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._translator.show_resting()  # 先建立静息脸再起线程（见 MoodTranslator.show_resting）
        self._thread = threading.Thread(target=self._run, name="task", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        last: float | None = None
        while not self._stop.is_set():
            now = self._clock()
            if last is not None and (now - last) > 1.5 * self._period:
                self._logger.log("task_tick_jitter", interval=round(now - last, 4))
            last = now
            self._tick(now)
            self._stop.wait(self._period)

    def _tick(self, now: float) -> None:
        snap = self._bb.snapshot()
        ctx = MoodCtx(
            following=False,  # M1 无跟随；M2+ 由 FSM 据自身状态填实
            visible=bool(snap.person and snap.person.visible),
            moving=False,  # M1 不移动；M3 由控制律执行点填实
        )
        self._translator.tick(snap, ctx, now)
