"""感知层主循环（FDS §4.2.1/§4.4，线程 A ~30Hz）。

一拍：取最新帧（覆盖式槽位）→ Pose 推理 → 双闸原始判定 → 去抖 → 组装不可变
Person 整体原子写黑板 → 累计耗时；按固定间隔输出 FPS/耗时聚合日志（采样汇总，
不逐帧刷屏）；顺带 ~1Hz 把电量写黑板。
"""

import threading
import time
from typing import Callable

from world.blackboard import Blackboard, Person
from world.logger import BlackboardLogger

from perception.debouncer import VisibleDebouncer
from perception.frame_slot import LatestFrameSlot


class PerceptionLoop:
    def __init__(
        self,
        hal,
        blackboard: Blackboard,
        detector,
        debouncer: VisibleDebouncer,
        logger: BlackboardLogger,
        cfg: dict,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._hal = hal
        self._bb = blackboard
        self._detector = detector
        self._debouncer = debouncer
        self._logger = logger
        self._clock = clock
        self._period = 1.0 / float(cfg.get("perception_hz", 30))
        self._stats_interval = float(cfg.get("perception_fps_log_interval", 1.0))

        self._slot = LatestFrameSlot()
        hal.on_camera_frame(self._slot.put)

        self._last_frame_ts = float("-inf")
        self._last_seen_ts = 0.0
        self._infer_samples: list[float] = []
        self._stats_start: float | None = None
        self._battery_at = float("-inf")
        self._max_landmarks: int = 0  # 诊断：本聚合周期内单帧最多命中多少 landmark（0=从没检到人）
        self._diag_frame_saved = False  # 诊断：只保存一次摄像头帧到 /tmp/cozmo_frame.png

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── 线程生命周期 ──

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="perception", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._tick(self._clock())
            self._stop.wait(self._period)

    # ── 单拍逻辑（测试可手动驱动）──

    def _tick(self, now: float) -> None:
        got = self._slot.get_if_newer(self._last_frame_ts)
        if got is not None:
            frame, frame_ts = got
            self._last_frame_ts = frame_ts
            if not self._diag_frame_saved:
                self._diag_frame_saved = True
                try:
                    frame.save("/tmp/cozmo_frame.png")
                    self._logger.log("diag_frame_saved", path="/tmp/cozmo_frame.png",
                                     mode=getattr(frame, "mode", "?"),
                                     size=getattr(frame, "size", "?"))
                except Exception:
                    pass
            det = self._detector.detect(frame, frame_ts)
            edge = self._debouncer.update(det.raw_visible)
            visible = self._debouncer.visible
            # last_seen_ts：visible 期间每拍刷新；下降沿取去抖判定成立时刻（T1 计时基准，FDS §4.3）
            if visible or edge == "falling":
                self._last_seen_ts = now
            self._bb.set_person(Person(visible=visible, last_seen_ts=self._last_seen_ts))
            self._infer_samples.append(det.infer_ms)
            self._max_landmarks = max(self._max_landmarks, det.landmark_hits)

        self._maybe_log_stats(now)

        if now - self._battery_at >= 1.0:
            self._battery_at = now
            self._bb.set_battery(self._hal.read_battery())

    def _maybe_log_stats(self, now: float) -> None:
        if self._stats_start is None:
            self._stats_start = now
            return
        elapsed = now - self._stats_start
        if elapsed < self._stats_interval:
            return
        frames = len(self._infer_samples)
        if frames > 0:
            ordered = sorted(self._infer_samples)
            self._logger.perception_stats(
                fps=frames / elapsed,
                infer_ms_avg=sum(ordered) / frames,
                infer_ms_p95=ordered[int(0.95 * (frames - 1))],
                frames=frames,
                max_landmarks=self._max_landmarks,  # 诊断：0=整个周期没找到人体关键点
            )
        self._infer_samples = []
        self._max_landmarks = 0
        self._stats_start = now
