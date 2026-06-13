import os
from types import SimpleNamespace

import pytest

from perception.pose_detector import GateConfig, gate_visible, landmark_score

CFG = GateConfig()  # 默认：conf 0.5 / 最少 6 点 / 核心 {0,11,12,23,24} 至少 2


def lm(visibility=None, presence=None):
    return SimpleNamespace(visibility=visibility, presence=presence)


def make_landmarks(hit_indices, total=33, conf=0.9):
    """构造 33 点列表，hit_indices 处置信度 conf，其余 0.1。"""
    return [lm(visibility=conf if i in hit_indices else 0.1) for i in range(total)]


def test_pass_both_gates():
    # 6 个达标点，其中核心点 11/12 两个 → 双闸通过
    assert gate_visible(make_landmarks({11, 12, 13, 14, 15, 16}), CFG) is True


def test_fail_min_landmarks():
    # 仅 5 个达标点（含 2 核心）→ 第一闸拦截
    assert gate_visible(make_landmarks({11, 12, 13, 14, 15}), CFG) is False


def test_fail_core_subset():
    # 8 个达标点但核心仅 1 个 → 第二闸拦截（控假阳）
    assert gate_visible(make_landmarks({11, 1, 2, 3, 4, 5, 6, 7}), CFG) is False


def test_none_visibility_falls_back_to_presence():
    assert landmark_score(lm(visibility=None, presence=0.9)) == 0.9
    assert landmark_score(lm(visibility=None, presence=None)) == 0.0
    marks = [lm(visibility=None, presence=0.9) for _ in range(33)]
    assert gate_visible(marks, CFG) is True


def test_empty_landmarks():
    assert gate_visible([], CFG) is False


MODEL = "models/pose_landmarker_lite.task"


@pytest.mark.skipif(not os.path.exists(MODEL), reason="pose 模型未下载（scripts/download_pose_model.sh）")
def test_pose_detector_smoke_on_synthetic_image():
    from PIL import Image

    from perception.pose_detector import PoseDetector

    det = PoseDetector(MODEL, CFG)
    try:
        frame = Image.new("L", (320, 240), color=128)  # 纯灰图，无人
        r1 = det.detect(frame, ts=1.0)
        r2 = det.detect(frame, ts=1.0)  # 同 ts，验证内部时间戳严格递增不抛
        assert r1.raw_visible is False
        assert r1.infer_ms > 0
        assert r2.raw_visible is False
    finally:
        det.close()
