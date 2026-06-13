"""装配点（FDS §9.3）：main --demo connect。

M1 启动序列（FDS §9.1）：读配置 → 构造黑板/HAL/感知/任务 → hal.connect() →
5s 内播苏醒动画 → 打印"连接成功"+电池电压 → 起感知/任务线程 → Ctrl-C 退出时
停轮 + 安全断开。

运行：uv run python src/main.py --demo connect
联调（无硬件）：uv run python src/main.py --demo connect --hal mock --duration 2
"""

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from world.blackboard import Blackboard
from world.logger import BlackboardLogger

from hal.interface import HalInterface
from perception.debouncer import VisibleDebouncer
from perception.loop import PerceptionLoop
from perception.pose_detector import GateConfig, PoseDetector, RawDetection
from task.loop import TaskLoop
from task.mood_translator import MoodTranslator

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent


def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path) if path else ROOT_DIR / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_mood_map(path: str | None = None) -> dict:
    map_path = Path(path) if path else SRC_DIR / "moods" / "moods.yaml"
    with open(map_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["moods"]


@dataclass
class App:
    cfg: dict
    logger: BlackboardLogger
    blackboard: Blackboard
    hal: HalInterface
    perception: PerceptionLoop
    task: TaskLoop


def build_m1(
    cfg: dict,
    hal: HalInterface | None = None,
    detector=None,
    mood_map: dict | None = None,
    logger: BlackboardLogger | None = None,
) -> App:
    """M1 装配；hal/detector 可注入 Mock/Fake（集成测试与 --hal mock 复用同一装配）。"""
    logger = logger or BlackboardLogger()
    blackboard = Blackboard(logger)
    if hal is None:
        from hal.pycozmo_hal import PycozmoHal  # 延迟导入：mock 模式不触碰 pycozmo

        hal = PycozmoHal(cfg, logger)
    if detector is None:
        gate = GateConfig(
            landmark_min_confidence=float(cfg["landmark_min_confidence"]),
            visible_min_landmarks=int(cfg["visible_min_landmarks"]),
            upper_body_core=tuple(cfg["upper_body_core"]),
            visible_core_min=int(cfg["visible_core_min"]),
        )
        model_path = Path(cfg["pose_model_path"])
        if not model_path.is_absolute():
            model_path = ROOT_DIR / model_path
        detector = PoseDetector(str(model_path), gate)
    mood_map = mood_map or load_mood_map()

    debouncer = VisibleDebouncer(
        on_frames=int(cfg["visible_on_frames"]), off_frames=int(cfg["visible_off_frames"])
    )
    perception = PerceptionLoop(hal, blackboard, detector, debouncer, logger, cfg)
    translator = MoodTranslator(blackboard, hal, mood_map, cfg)
    task = TaskLoop(blackboard, translator, logger, hz=float(cfg["task_hz"]))
    return App(cfg, logger, blackboard, hal, perception, task)


# 诊断阈值（排查"断电/掉线"用，可在 config.yaml 覆盖）
LOW_BATTERY_V = 3.6          # 离开充电座低于此电压接近耗尽（Cozmo ~3.5V 自动关机）
LINK_STALE_S = 3.0           # 遥测超过此秒数未更新 → 判链路可能已断
DIAG_INTERVAL_S = 2.0        # 诊断日志间隔


def _diagnostics_tick(app: App) -> None:
    """周期性记录电量/充电/链路心跳，使"断电/掉线/休眠"在日志中可辨（US4.5）。"""
    cfg = app.cfg
    voltage = app.hal.read_battery()
    on_charger = app.hal.is_on_charger()
    charging = app.hal.is_charging()
    low = (not on_charger) and 0.0 < voltage < float(cfg.get("low_battery_v", LOW_BATTERY_V))
    app.logger.battery_status(voltage, on_charger, charging, low)

    age = app.hal.link_age()
    if age > float(cfg.get("link_stale_s", LINK_STALE_S)):
        app.logger.link_stale(age)  # 遥测停更：机器人很可能已断电/掉线/在充电座休眠


def demo_connect(app: App, run_seconds: float | None = None) -> int:
    cfg = app.cfg
    try:
        app.hal.connect()
        app.hal.play_animation(cfg["wake_animation"])  # 连接建立后立即下发，满足 5s 内开始播放
        battery = app.hal.read_battery()
        on_charger = app.hal.is_on_charger()
        app.logger.connection("connected", battery=battery)
        print(f"连接成功，电池电压 {battery:.2f}V"
              + ("（在充电座上）" if on_charger else ""))
        if on_charger:
            print("⚠ Cozmo 仍在充电座上——充电座上会自动休眠，建议拿下充电座再运行。")
        if cfg.get("head_angle_on_start"):
            app.hal.set_head_angle(float(cfg["head_angle_on_start"]))

        app.perception.start()
        app.task.start()

        interval = float(cfg.get("diag_interval_s", DIAG_INTERVAL_S))
        deadline = None if run_seconds is None else time.monotonic() + run_seconds
        while deadline is None or time.monotonic() < deadline:
            time.sleep(interval)
            _diagnostics_tick(app)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        app.task.stop()
        app.perception.stop()
        app.hal.stop_wheels()
        app.hal.disconnect()
        app.logger.connection("disconnected")


class _AlwaysEmptyDetector:
    """--hal mock 用：无真模型，恒判无人。"""

    def detect(self, frame, ts: float) -> RawDetection:
        return RawDetection(raw_visible=False, infer_ms=0.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cozmo demo 启动入口")
    parser.add_argument("--demo", choices=["connect"], required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--hal", choices=["pycozmo", "mock"], default="pycozmo", help=argparse.SUPPRESS)
    parser.add_argument("--duration", type=float, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    hal = detector = None
    if args.hal == "mock":
        from hal.mock_hal import MockHal

        hal = MockHal()
        detector = _AlwaysEmptyDetector()

    app = build_m1(cfg, hal=hal, detector=detector)
    return demo_connect(app, run_seconds=args.duration)


if __name__ == "__main__":
    sys.exit(main())
