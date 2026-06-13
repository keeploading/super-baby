"""连接诊断（排查"断电/掉线/休眠"）：电量/充电/链路心跳日志。"""

import io
import json

from hal.mock_hal import MockHal
from main import build_m1, _diagnostics_tick

CFG = {
    "visible_on_frames": 3,
    "visible_off_frames": 3,
    "perception_fps_log_interval": 1.0,
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


def make_app(hal):
    return build_m1(
        CFG,
        hal=hal,
        detector=object(),  # 不驱动感知，仅测诊断
        mood_map=MOOD_MAP,
        logger=__import__("world.logger", fromlist=["BlackboardLogger"]).BlackboardLogger(
            make_app.stream
        ),
    )


def events(stream):
    return [json.loads(l) for l in stream.getvalue().splitlines()]


def test_diagnostics_logs_battery_status():
    make_app.stream = io.StringIO()
    hal = MockHal()
    hal.connect()
    hal.battery_voltage = 3.9
    app = make_app(hal)
    _diagnostics_tick(app)
    bat = [e for e in events(make_app.stream) if e["event"] == "battery_status"]
    assert bat and bat[0]["voltage"] == 3.9
    assert bat[0]["low"] is False
    assert bat[0]["on_charger"] is False


def test_low_battery_flagged_off_charger():
    make_app.stream = io.StringIO()
    hal = MockHal()
    hal.connect()
    hal.battery_voltage = 3.5  # 低于阈值且不在充电座
    app = make_app(hal)
    _diagnostics_tick(app)
    bat = [e for e in events(make_app.stream) if e["event"] == "battery_status"][0]
    assert bat["low"] is True


def test_low_battery_not_flagged_on_charger():
    make_app.stream = io.StringIO()
    hal = MockHal()
    hal.connect()
    hal.battery_voltage = 3.5
    hal.on_charger = True  # 在充电座上电压读数无意义，不应误报 low
    app = make_app(hal)
    _diagnostics_tick(app)
    bat = [e for e in events(make_app.stream) if e["event"] == "battery_status"][0]
    assert bat["low"] is False
    assert bat["on_charger"] is True


def test_link_stale_logged_when_telemetry_old():
    make_app.stream = io.StringIO()
    hal = MockHal()
    hal.connect()
    hal.link_age = lambda: 9.0  # 模拟遥测停更 9s
    app = make_app(hal)
    _diagnostics_tick(app)
    stale = [e for e in events(make_app.stream) if e["event"] == "link_stale"]
    assert stale and stale[0]["age"] == 9.0


def test_link_fresh_no_stale_log():
    make_app.stream = io.StringIO()
    hal = MockHal()
    hal.connect()
    app = make_app(hal)  # MockHal.link_age 恒 0.0
    _diagnostics_tick(app)
    assert not [e for e in events(make_app.stream) if e["event"] == "link_stale"]
