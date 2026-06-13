import dataclasses
import io
import json
import threading

import pytest

from world.blackboard import Blackboard, BlackboardSnapshot, Person
from world.logger import BlackboardLogger


def make_bb():
    stream = io.StringIO()
    bb = Blackboard(BlackboardLogger(stream))
    return bb, stream


def log_lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_person_frozen_immutable():
    p = Person(visible=True, last_seen_ts=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.visible = False


def test_snapshot_immutable():
    bb, _ = make_bb()
    snap = bb.snapshot()
    assert isinstance(snap, BlackboardSnapshot)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.mood = "happy"


def test_snapshot_consistent_pairs():
    # 写线程成对写 (mood, mood_ts)；任意快照里二者必须对应同一次写入（无撕裂）
    bb, _ = make_bb()
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            bb.set_mood(f"m{i}", "immediate", float(i))
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(2000):
            snap = bb.snapshot()
            assert snap.mood == f"m{int(snap.mood_ts)}"
    finally:
        stop.set()
        t.join()


def test_set_person_emits_visible_flip_log():
    bb, stream = make_bb()
    bb.set_person(Person(visible=True, last_seen_ts=1.5))
    bb.set_person(Person(visible=True, last_seen_ts=2.0))  # 未翻转，不出日志
    bb.set_person(Person(visible=False, last_seen_ts=2.0))
    events = [l for l in log_lines(stream) if l["event"] == "visible_changed"]
    assert [e["visible"] for e in events] == [True, False]
    assert events[0]["ts"] == 1.5


def test_set_mood_emits_mood_change_log():
    bb, stream = make_bb()
    bb.set_mood("surprise", "immediate", 3.0)
    bb.set_mood("surprise", "immediate", 3.1)  # 同 mood，不出日志
    bb.set_mood("calm", "immediate", 4.5)
    events = [l for l in log_lines(stream) if l["event"] == "mood_changed"]
    assert [(e["prev"], e["mood"]) for e in events] == [("calm", "surprise"), ("surprise", "calm")]
    assert events[1]["source"] == "immediate"
