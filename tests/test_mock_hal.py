from hal.mock_hal import MockHal


def test_records_all_commands():
    hal = MockHal()
    hal.connect()
    hal.play_animation("anim_x")
    hal.set_backpack_led("white")
    hal.drive_wheels(10.0, 20.0)
    names = [c[1] for c in hal.commands]
    assert names == ["play_animation", "set_backpack_led", "drive_wheels"]
    assert hal.commands_of("play_animation")[0][2] == ("anim_x",)
    assert hal.commands_of("drive_wheels")[0][2] == (10.0, 20.0)


def test_inject_frame_invokes_callback():
    hal = MockHal()
    received = []
    hal.on_camera_frame(lambda frame, ts: received.append((frame, ts)))
    hal.inject_frame("frame-1", ts=42.0)
    assert received == [("frame-1", 42.0)]


def test_disconnected_downlink_is_safe_noop():
    hal = MockHal()
    hal.connect()
    hal.trigger_disconnect()
    hal.play_animation("anim_x")  # 不抛异常
    assert hal.commands == []
    assert [c[1] for c in hal.dropped] == ["play_animation"]


def test_trigger_cliff_and_cube_event():
    hal = MockHal()
    cliffs, cubes = [], []
    hal.on_cliff(cliffs.append)
    hal.on_cube_event(cubes.append)
    hal.trigger_cliff(True)
    hal.trigger_cube_event({"type": "tapped"})
    assert cliffs == [True]
    assert cubes == [{"type": "tapped"}]


def test_disconnect_callback_fired():
    hal = MockHal()
    fired = []
    hal.on_disconnect(lambda: fired.append(True))
    hal.connect()
    hal.trigger_disconnect()
    assert fired == [True]
    assert not hal.is_connected()
