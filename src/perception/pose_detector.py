"""单帧人体检测（FDS §4.2.2）：MediaPipe Tasks PoseLandmarker 封装 + 双闸 visible 原始判定。

双闸（接受局部人体、控假阳，US1.2/US3.6）：
  单帧原始 visible = (达到 landmark_min_confidence 的关键点数 ≥ visible_min_landmarks)
                  且 (上半身核心子集 upper_body_core 中达置信度的点数 ≥ visible_core_min)

该原始 bool 喂给 VisibleDebouncer，不直接写黑板。M1 不计算 cx/size（M3 在同一帧
landmark 上增算，不改本模块调用结构）。
"""

import time
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class GateConfig:
    landmark_min_confidence: float = 0.5
    visible_min_landmarks: int = 6
    upper_body_core: tuple[int, ...] = (0, 11, 12, 23, 24)
    visible_core_min: int = 2


@dataclass(frozen=True)
class RawDetection:
    raw_visible: bool
    infer_ms: float
    landmark_hits: int = 0  # 达置信度的 landmark 数（诊断用，双闸判定的第一闸值）


def landmark_score(lm: Any) -> float:
    """取 landmark 置信度：visibility 为 None 退 presence，再退 0.0。"""
    score = getattr(lm, "visibility", None)
    if score is None:
        score = getattr(lm, "presence", None)
    return score if score is not None else 0.0


def gate_visible(landmarks: Sequence[Any], cfg: GateConfig) -> bool:
    """纯函数双闸判定；landmarks 为单人 33 点列表（可为空）。"""
    hits = {
        i for i, lm in enumerate(landmarks) if landmark_score(lm) >= cfg.landmark_min_confidence
    }
    if len(hits) < cfg.visible_min_landmarks:
        return False
    core_hits = hits & set(cfg.upper_body_core)
    return len(core_hits) >= cfg.visible_core_min


class PoseDetector:
    """MediaPipe Tasks PoseLandmarker（VIDEO 模式）封装。

    detect_for_video 要求 timestamp 严格单调递增，封装内对同毫秒自动 +1。
    """

    def __init__(self, model_path: str, gate_cfg: GateConfig, num_poses: int = 1) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        self._gate_cfg = gate_cfg
        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=num_poses,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._last_ts_ms = -1

    def detect(self, frame: Any, ts: float) -> RawDetection:
        """frame 为 PIL.Image（灰度"L"或彩色均可），ts 为单调时钟秒。"""
        import numpy as np

        rgb = np.ascontiguousarray(np.asarray(frame.convert("RGB"), dtype=np.uint8))
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        ts_ms = max(int(ts * 1000), self._last_ts_ms + 1)
        self._last_ts_ms = ts_ms

        t0 = time.perf_counter()
        result = self._landmarker.detect_for_video(mp_image, ts_ms)
        infer_ms = (time.perf_counter() - t0) * 1000.0

        landmarks = result.pose_landmarks[0] if result.pose_landmarks else []
        hits = sum(1 for lm in landmarks if landmark_score(lm) >= self._gate_cfg.landmark_min_confidence)
        return RawDetection(raw_visible=gate_visible(landmarks, self._gate_cfg), infer_ms=infer_ms, landmark_hits=hits)

    def close(self) -> None:
        self._landmarker.close()
