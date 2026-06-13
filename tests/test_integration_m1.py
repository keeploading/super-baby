"""M1 全链路集成（无硬件）：帧序列 → 感知去抖 → 黑板 → 任务层 → surprise 下发 → HOLD → calm。"""

import io
import json
import time

from conftest import FakeClock, FakeDetector
from hal.mock_hal import MockHal
from main import build_m1
from perception.debouncer import VisibleDebouncer
from perception.loop import PerceptionLoop
from task.loop import TaskLoop
from task.mood_translator import MoodTranslator
from world.blackboard import Blackboard
from world.logger import BlackboardLogger

CFG = {
    "visible_on_frames": 3,
    "visible_off_frames": 3,
    "perception_fps_log_interval": 0.5,
    "landmark_min_confidence": 0.5,
    "visible_min_landmarks": 6,
    "upper_body_core": [0, 11, 12, 23, 24],
    "visible_core_min": 2,
    "surprise_hold": 1.5,
    "surprise_response_latency": 1.5,
    "perception_hz": 30,
    "task_hz": 10,
    "wake_animation": "anim_wake",
    "head_angle_on_start": 0.0,
    "pose_model_path": "models/pose_landmarker_lite.task",
}

MOOD_MAP = {
    "calm": {"animation": None, "face": "Neutral", "backpack_led": "dim_white"},
    "surprise": {"animation": "anim_surprise", "face": "Surprise", "backpack_led": "white"},
}


def test_frame_sequence_to_surprise_latency():
    # FakeClock 手动驱动两个 _tick：模拟时延从首个"有人"帧到 surprise 下发 ≤ 1.5s
    clock = FakeClock()
    stream = io.StringIO()
    logger = BlackboardLogger(stream)
    bb = Blackboard(logger)
    hal = MockHal()
    hal.connect()
    perception = PerceptionLoop(
        hal, bb, FakeDetector(), VisibleDebouncer(3, 3), logger, CFG, clock=clock
    )
    translator = MoodTranslator(bb, hal, MOOD_MAP, CFG)
    task = TaskLoop(bb, translator, logger, hz=CFG["task_hz"], clock=clock)

    first_frame_at = clock.t
    # 30Hz 注入"有人"帧并驱动感知拍；每拍后驱动任务拍（10Hz 粒度内等价）
    while not bb.snapshot().mood == "surprise":
        hal.inject_frame("person", ts=clock.t)
        perception._tick(clock.t)
        task._tick(clock.t)
        clock.advance(1 / 30)
        assert clock.t - first_frame_at < 5.0, "surprise 未在合理模拟时间内触发"

    latency = clock.t - first_frame_at
    assert latency <= CFG["surprise_response_latency"], f"模拟响应时延 {latency:.3f}s 超限"
    assert hal.commands_of("play_animation")[0][2] == ("anim_surprise",)

    # HOLD 到期 → calm（M1 落点）
    clock.advance(CFG["surprise_hold"] + 0.1)
    task._tick(clock.t)
    assert bb.snapshot().mood == "calm"
    events = [json.loads(l) for l in stream.getvalue().splitlines()]
    moods = [(e["prev"], e["mood"]) for e in events if e["event"] == "mood_changed"]
    assert moods == [("calm", "surprise"), ("surprise", "calm")]


def test_task_start_establishes_resting_face():
    # TaskLoop.start() 须先建立静息脸：起线程前同步下发 calm 脸，避免苏醒动画后屏幕变黑
    stream = io.StringIO()
    hal = MockHal()
    hal.connect()
    translator = MoodTranslator(Blackboard(BlackboardLogger(stream)), hal, MOOD_MAP, CFG)
    task = TaskLoop(Blackboard(BlackboardLogger(stream)), translator, BlackboardLogger(stream),
                    hz=CFG["task_hz"])
    task.start()
    task.stop()
    assert hal.commands_of("set_face")[0][2] == ("Neutral",)


def test_full_m1_lifecycle_real_threads():
    # build_m1 同一装配 + 真线程：mood 轨迹 calm→surprise→calm，日志含三类条目
    cfg = dict(CFG, surprise_hold=0.4, perception_fps_log_interval=0.2)
    stream = io.StringIO()
    hal = MockHal()
    app = build_m1(cfg, hal=hal, detector=FakeDetector(), mood_map=MOOD_MAP,
                   logger=BlackboardLogger(stream))
    hal.connect()
    app.perception.start()
    app.task.start()
    try:
        deadline = time.monotonic() + 3.0
        while app.blackboard.snapshot().mood != "surprise" and time.monotonic() < deadline:
            hal.inject_frame("person", ts=time.monotonic())
            time.sleep(1 / 30)
        assert app.blackboard.snapshot().mood == "surprise"

        deadline = time.monotonic() + 3.0
        while app.blackboard.snapshot().mood != "calm" and time.monotonic() < deadline:
            hal.inject_frame("person", ts=time.monotonic())  # 人持续可见，HOLD 到期仍应降级 calm
            time.sleep(1 / 30)
        assert app.blackboard.snapshot().mood == "calm"
    finally:
        app.task.stop()
        app.perception.stop()

    events = [json.loads(l) for l in stream.getvalue().splitlines()]
    kinds = {e["event"] for e in events}
    assert "visible_changed" in kinds
    assert "perception_stats" in kinds
    moods = [(e["prev"], e["mood"]) for e in events if e["event"] == "mood_changed"]
    assert moods[:2] == [("calm", "surprise"), ("surprise", "calm")]
