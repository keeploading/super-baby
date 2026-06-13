"""visible 双向多帧去抖（FDS §4.3）：迟滞计数器，M1 与 M3 共用同一实现。

- 稳态 false：原始判定连续 true 达 on_frames → 翻 true（上升沿，下游触发 surprise）。
- 稳态 true：原始判定连续 false 达 off_frames → 翻 false（下降沿，T1 计时基准）。
- 计数序列被打断即清零；单帧漏检/误检不翻转 visible。
"""


class VisibleDebouncer:
    def __init__(self, on_frames: int = 3, off_frames: int = 3) -> None:
        self._on_frames = on_frames
        self._off_frames = off_frames
        self.visible = False
        self._on_count = 0
        self._off_count = 0

    def update(self, raw: bool) -> str | None:
        """喂入单帧原始判定，返回 "rising" / "falling" / None（翻转那一帧报一次）。"""
        if not self.visible:
            if raw:
                self._on_count += 1
                if self._on_count >= self._on_frames:
                    self.visible = True
                    self._on_count = 0
                    self._off_count = 0
                    return "rising"
            else:
                self._on_count = 0
        else:
            if not raw:
                self._off_count += 1
                if self._off_count >= self._off_frames:
                    self.visible = False
                    self._on_count = 0
                    self._off_count = 0
                    return "falling"
            else:
                self._off_count = 0
        return None
