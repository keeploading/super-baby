import io
import json

from hal.mock_hal import MockHal
from task.mood_translator import MoodCtx, MoodTranslator
from world.blackboard import Blackboard
from world.logger import BlackboardLogger

MOOD_MAP = {
    "calm": {"animation": None, "face": "Neutral", "backpack_led": "dim_white"},
    "surprise": {"animation": "anim_surprise", "face": "Surprise", "backpack_led": "white"},
}
CFG = {"surprise_hold": 1.5}


def make_translator():
    stream = io.StringIO()
    bb = Blackboard(BlackboardLogger(stream))
    hal = MockHal()
    hal.connect()
    mt = MoodTranslator(bb, hal, MOOD_MAP, CFG)
    return mt, bb, hal, stream


def ctx(visible):
    return MoodCtx(following=False, visible=visible, moving=False)


def test_rising_edge_triggers_surprise():
    mt, bb, hal, _ = make_translator()
    mt.tick(bb.snapshot(), ctx(False), now=0.0)
    mt.tick(bb.snapshot(), ctx(True), now=0.1)
    snap = bb.snapshot()
    assert snap.mood == "surprise"
    assert snap.mood_source == "immediate"
    assert hal.commands_of("play_animation")[0][2] == ("anim_surprise",)
    assert hal.commands_of("set_face")[0][2] == ("Surprise",)
    assert hal.commands_of("set_backpack_led")[0][2] == ("white",)


def test_holding_ignores_new_rising_edge():
    mt, bb, hal, _ = make_translator()
    mt.tick(bb.snapshot(), ctx(True), now=0.0)  # 上升沿 → HOLDING，deadline=1.5
    mt.tick(bb.snapshot(), ctx(False), now=0.5)  # 保持期内 visible 抖动
    mt.tick(bb.snapshot(), ctx(True), now=0.6)  # 保持期内新上升沿 → 忽略，不重置计时
    mt.tick(bb.snapshot(), ctx(True), now=1.4)
    assert bb.snapshot().mood == "surprise"  # 仍在原 HOLD 内
    mt.tick(bb.snapshot(), ctx(False), now=1.6)  # 原 deadline(1.5) 已过 → 降级
    assert bb.snapshot().mood == "calm"


def test_hold_expiry_downgrades_to_calm_with_log():
    mt, bb, _, stream = make_translator()
    mt.tick(bb.snapshot(), ctx(True), now=0.0)
    mt.tick(bb.snapshot(), ctx(True), now=1.5)  # 到期
    assert bb.snapshot().mood == "calm"
    events = [
        json.loads(l) for l in stream.getvalue().splitlines()
        if json.loads(l)["event"] == "mood_changed"
    ]
    # M1 可观测验收锚点：surprise→calm 有结构化日志条目
    assert [(e["prev"], e["mood"]) for e in events] == [("calm", "surprise"), ("surprise", "calm")]


def test_no_redispatch_within_hold():
    mt, bb, hal, _ = make_translator()
    mt.tick(bb.snapshot(), ctx(True), now=0.0)
    for t in (0.2, 0.4, 0.6, 0.8):
        mt.tick(bb.snapshot(), ctx(True), now=t)
    assert len(hal.commands_of("play_animation")) == 1  # HOLD 期内仅 1 次整段动画


def test_calm_steady_no_redispatch():
    mt, bb, hal, _ = make_translator()
    mt.tick(bb.snapshot(), ctx(True), now=0.0)
    mt.tick(bb.snapshot(), ctx(True), now=1.5)  # 降级 calm，下发 1 次 calm 表现
    for t in (1.6, 1.7, 1.8):
        mt.tick(bb.snapshot(), ctx(True), now=t)  # visible 持续 true，无新上升沿
    assert [c[2] for c in hal.commands_of("set_face")] == [("Surprise",), ("Neutral",)]


def test_show_resting_dispatches_calm_face():
    # 启动静息脸：下发 calm 脸/LED、无动画（否则苏醒动画放完屏幕变黑，看着像断电）
    mt, _, hal, _ = make_translator()
    mt.show_resting()
    assert hal.commands_of("set_face")[0][2] == ("Neutral",)
    assert hal.commands_of("set_backpack_led")[0][2] == ("dim_white",)
    assert hal.commands_of("play_animation") == []  # calm 无整段动画


def test_moving_skips_wheel_animation():
    mt, bb, hal, _ = make_translator()
    mt.tick(bb.snapshot(), MoodCtx(following=False, visible=True, moving=True), now=0.0)
    assert hal.commands_of("play_animation") == []  # 移动期不播占轮整段动画
    assert len(hal.commands_of("set_face")) == 1  # 表情/LED 照发
