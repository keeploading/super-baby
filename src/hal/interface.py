"""HAL 抽象接口（FDS §9.1）：唯一触达硬件的边界，上层只依赖它。

行为契约（三条强约束）：
1. 悬崖硬闸：drive_wheels() 在 _cliff_active 时 no-op（PycozmoHal 实现，M2 起接线）。
2. 非阻塞下发：所有下发类方法 fire-and-forget，不阻塞调用线程。
3. 断连 no-op：连接断开状态下，所有下发类方法为安全 no-op、不抛异常。

M1 全量接口就位；on_cliff/on_cube_event/set_cube_led 等 M2 起才被调用。
"""

from abc import ABC, abstractmethod
from typing import Any, Callable


class HalInterface(ABC):
    # ── 连接生命周期 ──

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def on_disconnect(self, callback: Callable[[], None]) -> None: ...

    # ── 运动（下发类：非阻塞、断连 no-op）──

    @abstractmethod
    def drive_wheels(self, left_mmps: float, right_mmps: float) -> None: ...

    @abstractmethod
    def stop_wheels(self) -> None: ...

    @abstractmethod
    def move_lift(self, speed: float) -> None: ...

    @abstractmethod
    def move_head(self, speed: float) -> None: ...

    @abstractmethod
    def set_head_angle(self, angle_rad: float) -> None: ...

    # ── 表现（下发类：非阻塞、断连 no-op）──

    @abstractmethod
    def play_animation(self, name: str) -> None: ...

    @abstractmethod
    def set_face(self, expr: str) -> None: ...

    @abstractmethod
    def set_backpack_led(self, color: str) -> None: ...

    @abstractmethod
    def set_cube_led(self, color: str) -> None: ...

    # ── 传感器/事件回调注册（HAL→感知层）──

    @abstractmethod
    def on_camera_frame(self, callback: Callable[[Any, float], None]) -> None:
        """callback(frame, monotonic_ts)；回调运行在 HAL/pycozmo 线程，只许做轻量转发。"""

    @abstractmethod
    def on_cliff(self, callback: Callable[[bool], None]) -> None: ...

    @abstractmethod
    def on_cube_event(self, callback: Callable[[Any], None]) -> None: ...

    @abstractmethod
    def read_battery(self) -> float: ...

    # ── 链路/充电诊断（遥测读，与 read_battery 同性质；用于排查"断电/掉线"）──

    @abstractmethod
    def is_on_charger(self) -> bool: ...

    @abstractmethod
    def is_charging(self) -> bool: ...

    @abstractmethod
    def link_age(self) -> float:
        """距最近一次底层遥测（RobotState）的秒数；越大表示链路越可能已断/机器人无响应。
        从未收到遥测返回 inf；Mock 恒返回 0.0（视为永远新鲜）。"""
