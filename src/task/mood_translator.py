"""mood-translator（FDS §7.1/§7.5）：心情翻译/计时单元，mood 字段唯一写者。

归任务层职责、非完整 FSM——不持状态机状态、不读写 intention；场景上下文（following/
moving）由调用方每拍经 MoodCtx 传入。M1 形态：visible 上升沿 → surprise → HOLD →
降级 calm（ctx.following 恒 False）；M2 起作为 FSM 子模块原样复用，接口不变。

surprise 时序边界四点（FDS §7.5）：
① HOLDING 期内同级即时事件丢弃（M2 接入被拍事件时在本单元丢弃）；
② 不冻结 T1——T1 由 last_seen_ts 独立驱动，本单元不参与；
③ 到期按落点单调升级链降级：following 且 visible → happy，否则 calm（M1 恒 calm）；
④ 边沿触发不重入——HOLDING 期内新上升沿忽略、不重置 hold_deadline。
"""

import time
from dataclasses import dataclass
from typing import Mapping

from world.blackboard import Blackboard, BlackboardSnapshot

from hal.interface import HalInterface


@dataclass(frozen=True)
class MoodCtx:
    """调用方每拍构造的场景上下文（任务层内部瞬态对象，不入黑板，FDS §7.1.4）。"""

    following: bool  # M1 恒 False
    visible: bool    # 去抖后 visible（取自快照 person）
    moving: bool     # M1 恒 False；True 时不下发占轮整段动画（FDS §7.1.3）


class MoodTranslator:
    def __init__(
        self,
        blackboard: Blackboard,
        hal: HalInterface,
        mood_map: Mapping[str, Mapping],
        cfg: Mapping,
    ) -> None:
        self._bb = blackboard
        self._hal = hal
        self._mood_map = mood_map
        self._hold = float(cfg.get("surprise_hold", 1.5))
        self._state = "IDLE"  # IDLE / HOLDING（surprise 子状态，FDS §7.5）
        self._hold_deadline = 0.0
        self._prev_visible = False
        self._dispatched_mood: str | None = None

    def show_resting(self) -> None:
        """启动时建立初始静息表现（calm 脸/LED）。

        tick() 只在 mood 切换沿下发表现；启动时无沿、且苏醒动画放完会被 pycozmo 清屏
        （PycozmoHal._on_anim_completed 兜底补回需先有 _last_face），故须显式下发一次
        静息脸，否则无人入画时屏幕变黑（看着像断电）。calm 无动画，仅下发脸/LED。
        """
        self._dispatch("calm", MoodCtx(following=False, visible=False, moving=False))

    def tick(self, snap: BlackboardSnapshot, ctx: MoodCtx, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        rising = ctx.visible and not self._prev_visible
        self._prev_visible = ctx.visible

        if self._state == "IDLE":
            if rising:
                self._state = "HOLDING"
                self._hold_deadline = now + self._hold
                self._set_mood("surprise", "immediate", now, ctx)
        else:  # HOLDING：期内上升沿忽略不重置计时（④）；同级即时事件 M2 起在此丢弃（①）
            if now >= self._hold_deadline:
                self._state = "IDLE"
                target = "happy" if (ctx.following and ctx.visible) else "calm"  # ③，M1 恒 calm
                self._set_mood(target, "immediate", now, ctx)

    def _set_mood(self, mood: str, source: str, now: float, ctx: MoodCtx) -> None:
        self._bb.set_mood(mood, source, now)  # 黑板在实际切换时输出 mood_changed 日志
        self._dispatch(mood, ctx)

    def _dispatch(self, mood: str, ctx: MoodCtx) -> None:
        if mood == self._dispatched_mood:
            return  # 同一心情不重复下发整段动画/表现（FDS §7.1.2 防抖）
        self._dispatched_mood = mood
        entry = self._mood_map.get(mood) or {}
        animation = entry.get("animation")
        if animation and not ctx.moving:  # 移动期不播占轮整段动画（FDS §7.1.3）
            self._hal.play_animation(animation)
        face = entry.get("face")
        if face:
            self._hal.set_face(face)
        led = entry.get("backpack_led")
        if led:
            self._hal.set_backpack_led(led)
