from perception.frame_slot import LatestFrameSlot


def test_overwrite_keeps_latest():
    slot = LatestFrameSlot()
    slot.put("f1", 1.0)
    slot.put("f2", 2.0)
    slot.put("f3", 3.0)
    assert slot.get_if_newer(0.0) == ("f3", 3.0)


def test_get_if_newer_filters_same_frame():
    slot = LatestFrameSlot()
    assert slot.get_if_newer(0.0) is None  # 空槽位
    slot.put("f1", 1.0)
    frame, ts = slot.get_if_newer(0.0)
    assert frame == "f1"
    assert slot.get_if_newer(ts) is None  # 同帧不重取
    slot.put("f2", 2.0)
    assert slot.get_if_newer(ts) == ("f2", 2.0)
