# super-baby

Cozmo「感知—任务—认知」三层架构机器人应用（follow-me）。需求与设计见
`docs/requirements/follow-me/`（PRD v11 / FDS v5.2）。当前已实现 **M1**：
连接 + 苏醒动画 + 最小人体识别（visible 级）+ 见人 surprise 反应。

## 环境准备（一次性）

```bash
uv sync                                      # Python 3.12 虚拟环境 + 依赖
bash scripts/download_pose_model.sh          # MediaPipe pose 模型（~5.8MB → models/）
uv run python .venv/bin/pycozmo_resources.py download   # Cozmo 动画资源（~572MB → ~/.pycozmo/assets）
```

## 运行 M1 demo

前置：Cozmo 放充电座唤醒 → 抬放叉臂显示 Wi-Fi PSK → Mac 连接 Cozmo 热点。

```bash
uv run python src/main.py --demo connect
```

验收点（PRD §7 M1 行）：连接后 5s 内播苏醒动画；控制台打印电压；人进入画面 ≈1.5s 内
播惊讶动画/表情/背包 LED；保持 1.5s 后降级 calm（结构化日志出现 `mood_changed`
surprise→calm 条目）；每秒一条感知 FPS/耗时日志；Ctrl-C 安全断开。

无硬件联调（MockHal，跑通启动序列与日志）：

```bash
uv run python src/main.py --demo connect --hal mock --duration 2
```

## 测试

```bash
uv run pytest        # 全程无硬件（MockHal + FakeDetector）
```

## 结构

```
src/world/        黑板（单写者+不可变整体替换+同锁快照）+ 结构化日志
src/hal/          HAL 抽象接口 + PycozmoHal 真实现 + MockHal
src/perception/   帧槽位 → MediaPipe Pose → 双闸 visible 判定 → 多帧去抖（线程 A ~30Hz）
src/task/         mood-translator（surprise HOLD 计时/翻译下发）+ 极简任务循环（线程 B ~10Hz）
src/moods/        心情→动画/表情/LED 映射（纯数据）
src/tools/        list_anims.py：离线列动画名选 .bin
config.yaml       全部阈值/动画名/周期（FDS §3.4 键名）
```

阈值与动画名全部在 `config.yaml` / `src/moods/moods.yaml`，不改代码即可联调更换。
