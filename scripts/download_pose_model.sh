#!/usr/bin/env bash
# 下载 MediaPipe PoseLandmarker lite 模型到 models/（约 5.8MB，一次性）
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p models
URL="https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
DEST="models/pose_landmarker_lite.task"

if [ -f "$DEST" ]; then
    echo "已存在：$DEST"
    exit 0
fi

curl -L --fail -o "$DEST" "$URL"
echo "已下载：$DEST"
