from perception.debouncer import VisibleDebouncer


def feed(db, seq):
    return [db.update(raw) for raw in seq]


def test_on_after_n_consecutive_true():
    db = VisibleDebouncer(on_frames=3, off_frames=3)
    edges = feed(db, [True, True, True, True])
    assert edges == [None, None, "rising", None]  # 第 3 帧翻转且只报一次
    assert db.visible is True


def test_interrupted_sequence_resets_counter():
    db = VisibleDebouncer(on_frames=3, off_frames=3)
    edges = feed(db, [True, True, False, True, True, True])
    assert edges[:5] == [None] * 5
    assert edges[5] == "rising"  # 中断清零后重新数 3 帧


def test_off_after_n_consecutive_false():
    db = VisibleDebouncer(on_frames=3, off_frames=3)
    feed(db, [True, True, True])
    edges = feed(db, [False, False, False])
    assert edges == [None, None, "falling"]
    assert db.visible is False


def test_single_frame_glitch_absorbed():
    db = VisibleDebouncer(on_frames=3, off_frames=3)
    feed(db, [True, True, True])
    edges = feed(db, [False, True, False, False, True])  # 毛刺不足 3 连
    assert edges == [None] * 5
    assert db.visible is True
