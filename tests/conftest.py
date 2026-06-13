from perception.pose_detector import RawDetection


class FakeDetector:
    """帧内容即判定：frame == "person" 算检出有人。"""

    def __init__(self, infer_ms: float = 5.0) -> None:
        self.infer_ms = infer_ms

    def detect(self, frame, ts: float) -> RawDetection:
        return RawDetection(raw_visible=(frame == "person"), infer_ms=self.infer_ms)


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t
