"""MockHal（FDS §9.1 Mock 测试策略）：无硬件联调/测试用。

- 记录全部下发指令到 commands：(monotonic_ts, method_name, args)。
- 断连状态下下发记录到 dropped（验证"断连 no-op"契约），不入 commands、不抛异常。
- 可注入摄像头帧、触发悬崖/方块/断连事件，驱动上层链路。
"""

import time
from typing import Any, Callable

from hal.interface import HalInterface


class MockHal(HalInterface):
    def __init__(self) -> None:
        self.commands: list[tuple[float, str, tuple]] = []
        self.dropped: list[tuple[float, str, tuple]] = []
        self._connected = False
        self._frame_cb: Callable[[Any, float], None] | None = None
        self._cliff_cb: Callable[[bool], None] | None = None
        self._cube_cb: Callable[[Any], None] | None = None
        self._disconnect_cb: Callable[[], None] | None = None
        self.battery_voltage = 3.9
        self.on_charger = False
        self.charging = False

    def _record(self, name: str, *args) -> None:
        entry = (time.monotonic(), name, args)
        if self._connected:
            self.commands.append(entry)
        else:
            self.dropped.append(entry)

    def commands_of(self, name: str) -> list[tuple[float, str, tuple]]:
        return [c for c in self.commands if c[1] == name]

    # ── 连接生命周期 ──

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        self._disconnect_cb = callback

    # ── 运动 ──

    def drive_wheels(self, left_mmps: float, right_mmps: float) -> None:
        self._record("drive_wheels", left_mmps, right_mmps)

    def stop_wheels(self) -> None:
        self._record("stop_wheels")

    def move_lift(self, speed: float) -> None:
        self._record("move_lift", speed)

    def move_head(self, speed: float) -> None:
        self._record("move_head", speed)

    def set_head_angle(self, angle_rad: float) -> None:
        self._record("set_head_angle", angle_rad)

    # ── 表现 ──

    def play_animation(self, name: str) -> None:
        self._record("play_animation", name)

    def set_face(self, expr: str) -> None:
        self._record("set_face", expr)

    def set_backpack_led(self, color: str) -> None:
        self._record("set_backpack_led", color)

    def set_cube_led(self, color: str) -> None:
        self._record("set_cube_led", color)

    # ── 传感器/事件 ──

    def on_camera_frame(self, callback: Callable[[Any, float], None]) -> None:
        self._frame_cb = callback

    def on_cliff(self, callback: Callable[[bool], None]) -> None:
        self._cliff_cb = callback

    def on_cube_event(self, callback: Callable[[Any], None]) -> None:
        self._cube_cb = callback

    def read_battery(self) -> float:
        return self.battery_voltage

    def is_on_charger(self) -> bool:
        return self.on_charger

    def is_charging(self) -> bool:
        return self.charging

    def link_age(self) -> float:
        return 0.0  # Mock 链路恒新鲜

    # ── 测试驱动入口 ──

    def inject_frame(self, frame: Any, ts: float | None = None) -> None:
        if self._frame_cb is not None:
            self._frame_cb(frame, ts if ts is not None else time.monotonic())

    def trigger_cliff(self, detected: bool) -> None:
        if self._cliff_cb is not None:
            self._cliff_cb(detected)

    def trigger_cube_event(self, evt: Any) -> None:
        if self._cube_cb is not None:
            self._cube_cb(evt)

    def trigger_disconnect(self) -> None:
        self._connected = False
        if self._disconnect_cb is not None:
            self._disconnect_cb()
