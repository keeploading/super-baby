"""PycozmoHal（FDS §9.1）：封装 pycozmo 的真实现。

行为契约落实：
- 非阻塞下发：pycozmo 的 drive_wheels/play_anim/display_image/set_all_backpack_lights
  本身均为异步提交（UDP 包/动画控制器队列），直调即满足 fire-and-forget。
- 断连 no-op：所有下发经 _safe() 守门——未连接直接返回，异常转结构化 warning 日志，
  不向调用方抛出。
- 悬崖硬闸：drive_wheels() 入口判 _cliff_active 即 no-op（置位接线 M2 安全反射做）。

M1 打通：connect/disconnect/play_animation/set_face/set_backpack_led/set_head_angle/
on_camera_frame/read_battery/stop_wheels；on_cliff/on_cube_event/set_cube_led 等
回调存根 M2 接线。
"""

import time
from typing import Any, Callable

from world.logger import BlackboardLogger

from hal.interface import HalInterface

RESOURCE_HINT = "运行 .venv/bin/pycozmo_resources.py download 下载 Cozmo 动画资源"


class PycozmoHal(HalInterface):
    def __init__(self, cfg: dict, logger: BlackboardLogger) -> None:
        self._cfg = cfg
        self._logger = logger
        self._cli = None
        self._connected = False
        self._cliff_active = False  # HAL 硬闸标志（M2 安全反射置位/清零）
        self._frame_cb: Callable[[Any, float], None] | None = None
        self._cliff_cb: Callable[[bool], None] | None = None
        self._cube_cb: Callable[[Any], None] | None = None
        self._disconnect_cb: Callable[[], None] | None = None
        self._last_state_ts: float | None = None  # 最近一次 RobotState 遥测时刻（链路心跳）
        self._last_face: str | None = None  # 最近一次 set_face 的表情；动画结束清屏后补回（见 _on_anim_completed）

    # ── 连接生命周期 ──

    def connect(self) -> None:
        import pycozmo

        cli = pycozmo.Client(enable_procedural_face=False)  # 自渲染待机脸与 set_face 冲突，必须关
        cli.start()
        cli.connect()
        cli.wait_for_robot()
        self._cli = cli
        self._connected = True

        cli.add_handler(pycozmo.event.EvtNewRawCameraImage, self._on_frame)
        cli.add_handler(pycozmo.event.EvtRobotStateUpdated, self._on_state)  # 链路心跳
        cli.add_handler(pycozmo.event.EvtAnimationCompleted, self._on_anim_completed)  # 动画后补脸
        cli.enable_camera(enable=True, color=bool(self._cfg.get("camera_color", False)))
        try:
            cli.load_anims()
        except Exception as e:
            self._logger.log("hal_warning", op="load_anims", error=str(e), hint=RESOURCE_HINT)

        # 连接瞬间 battery_voltage=0.0，等首个 RobotState（1.5s 超时兜底）
        t0 = time.monotonic()
        while cli.battery_voltage == 0.0 and time.monotonic() - t0 < 1.5:
            time.sleep(0.05)

    def disconnect(self) -> None:
        if self._cli is None:
            return
        self._connected = False
        try:
            self._cli.disconnect()
            self._cli.stop()
        except Exception as e:
            self._logger.log("hal_warning", op="disconnect", error=str(e))

    def is_connected(self) -> bool:
        return self._connected

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        self._disconnect_cb = callback  # M2 重连（US4.6）接 pycozmo 断连事件

    # ── 内部回调（pycozmo 接收线程，只做轻量转发）──

    def _on_frame(self, cli, image) -> None:
        del cli
        cb = self._frame_cb
        if cb is not None:
            cb(image, time.monotonic())

    def _on_state(self, cli) -> None:
        del cli
        self._last_state_ts = time.monotonic()  # RobotState ~30Hz：遥测停了即链路断/机器人关机

    def _on_anim_completed(self, cli) -> None:
        del cli
        # 动画结束后补脸（动画末帧清屏，禁用 procedural_face 不自补）
        face = self._last_face
        if face is not None:
            self._safe("reassert_face", lambda: self._display_expression(face))
        # 动画关键帧会覆盖头角度；结束后重置到配置值，确保摄像头朝向正确
        angle = float(self._cfg.get("head_angle_on_start", 0.0))
        if angle:
            self._safe("reassert_head_angle", lambda: self._cli.set_head_angle(angle))

    # ── 下发守门：断连 no-op、异常转 warning，不抛（FDS §9.1 契约 2/3）──

    def _safe(self, op: str, fn: Callable[[], None]) -> None:
        if not self._connected:
            return
        try:
            fn()
        except Exception as e:
            self._logger.log("hal_warning", op=op, error=str(e))

    # ── 运动 ──

    def drive_wheels(self, left_mmps: float, right_mmps: float) -> None:
        if self._cliff_active:
            return  # 硬闸：悬崖期间任何驱动 no-op（FDS §9.1 契约 1）
        self._safe("drive_wheels", lambda: self._cli.drive_wheels(left_mmps, right_mmps))

    def stop_wheels(self) -> None:
        self._safe("stop_wheels", lambda: self._cli.stop_all_motors())

    def move_lift(self, speed: float) -> None:
        self._safe("move_lift", lambda: self._cli.move_lift(speed))

    def move_head(self, speed: float) -> None:
        self._safe("move_head", lambda: self._cli.move_head(speed))

    def set_head_angle(self, angle_rad: float) -> None:
        self._safe("set_head_angle", lambda: self._cli.set_head_angle(angle_rad))

    # ── 表现 ──

    def play_animation(self, name: str) -> None:
        # 未加载/未知动画名 pycozmo 抛 ValueError，由 _safe 吸收为 warning
        self._safe("play_animation", lambda: self._cli.play_anim(name))

    def set_face(self, expr: str) -> None:
        self._last_face = expr  # 记住当前脸：动画结束清屏后由 _on_anim_completed 补回
        self._safe(f"set_face:{expr}", lambda: self._display_expression(expr))

    def _display_expression(self, expr: str) -> None:
        import numpy as np
        from PIL import Image
        from pycozmo import expressions

        face_cls = getattr(expressions, expr, None)
        if face_cls is None:
            raise ValueError(f"未知表情类 {expr}（见 pycozmo.expressions）")
        im = face_cls().render()  # 128x64
        np_im = np.array(im)[::2]  # 协议要求 128x32：取偶数行（同 pycozmo anim.py 做法）
        self._cli.display_image(Image.fromarray(np_im))

    def set_backpack_led(self, color: str) -> None:
        self._safe(f"set_backpack_led:{color}", lambda: self._set_backpack_led(color))

    def _set_backpack_led(self, color: str) -> None:
        self._cli.set_all_backpack_lights(_named_light(color))

    def set_cube_led(self, color: str) -> None:
        self._logger.log("hal_warning", op="set_cube_led", error="M1 未实现（M2 玩方块接线）")

    # ── 传感器/事件回调注册 ──

    def on_camera_frame(self, callback: Callable[[Any, float], None]) -> None:
        self._frame_cb = callback

    def on_cliff(self, callback: Callable[[bool], None]) -> None:
        self._cliff_cb = callback  # M2 安全反射接 pycozmo 悬崖事件

    def on_cube_event(self, callback: Callable[[Any], None]) -> None:
        self._cube_cb = callback  # M2 玩方块接线

    def read_battery(self) -> float:
        return float(self._cli.battery_voltage) if self._cli is not None else 0.0

    def is_on_charger(self) -> bool:
        from pycozmo.robot import RobotStatusFlag

        return bool(self._status_flag(RobotStatusFlag.IS_ON_CHARGER))

    def is_charging(self) -> bool:
        from pycozmo.robot import RobotStatusFlag

        return bool(self._status_flag(RobotStatusFlag.IS_CHARGING))

    def _status_flag(self, flag: int) -> int:
        status = getattr(self._cli, "robot_status", 0) if self._cli is not None else 0
        return (status or 0) & flag

    def link_age(self) -> float:
        if self._last_state_ts is None:
            return float("inf")
        return time.monotonic() - self._last_state_ts


def _named_light(color: str):
    """颜色名 → pycozmo LightState（moods.yaml 的 backpack_led 取值）。"""
    from pycozmo import lights, protocol_encoder

    preset = {
        "white": lights.white_light,
        "red": lights.red_light,
        "green": lights.green_light,
        "blue": lights.blue_light,
        "off": lights.off_light,
    }
    if color in preset:
        return preset[color]
    custom_rgb = {
        "dim_white": 0x404040,
        "cyan": 0x00FFFF,
        "amber": 0xFFBF00,
    }
    if color not in custom_rgb:
        raise ValueError(f"未知 LED 颜色名 {color}")
    c = lights.Color(int_color=(custom_rgb[color] << 8) | 0xFF)
    return protocol_encoder.LightState(on_color=c.to_int16(), off_color=c.to_int16())
