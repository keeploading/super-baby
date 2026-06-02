# Cozmo「跟人走」第一阶段 —— 功能设计文档（FDS）

> 状态：v1 草案（待 developer 评审）
> 上游需求：`docs/requirements/follow-me/follow-me-prd.md`（PRD v8，已定稿）
> 背景构想：`docs/ideas/follow-me-idea.md`
> 平台：Mac mini（Apple Silicon / 32GB）+ 实体 Cozmo，底层 [pycozmo](https://github.com/zayfod/pycozmo)
> 本文聚焦"怎么做"——把 PRD 的需求落成可实现的模块/机制/接口/数据契约，并按 M1→M4 增量演进。
> 编写原则：以文字 + 图表表达为主，契约性内容（接口签名、数据结构、枚举、配置项）用代码块精确表达；遵循奥卡姆剃刀，PRD 标 Out of Scope 的不设计进来。

---

## 1. 架构设计（总体骨架）

### 1.1 三层 + 黑板 + HAL 的总体结构

系统遵循 Gat 1998 三层模型（Reactive / Sequencer / Deliberator），各层**独立周期**运行，**只通过共享黑板（Blackboard）交换状态**，层间不互相直接调用。安全反射在感知层内闭环，绝不上送等待决策。

```
                          进程内（单进程多线程）
┌───────────────────────────────────────────────────────────────────────┐
│  认知层 Deliberator (cognition/)        线程 C  ~秒级 / 事件驱动（M4 接入）  │
│   读 world_summary（黑板快照摘要）→ 本地 Gemma agent loop / 规则兜底         │
│   产出 {intention, mood} + cog_decision_ts → 写黑板                        │
│   不下发任何电机指令；模型决策永不进实时控制环                                  │
└──────────────▲─────────────────────────────────────────┬────────────────┘
        world_summary 摘要 │                          intention / mood（低频）│
┌──────────────┴─────────────────────────────────────────▼────────────────┐
│  任务层 Sequencer (task/)               线程 B  ~10Hz（M2 起完整 FSM）       │
│   ① FSM：FREE_ROAM / PLAY_CUBE / FOLLOW / SEARCH（读 intention + 事实迁移） │
│   ② mood-translator：心情仲裁 + SURPRISE_HOLD 计时 + 翻译为动画/表情/LED      │
│   ③ 视觉伺服控制律（M3）：cx_norm→转向，size_norm→进退                       │
│   每周期对黑板取一次快照后再决策；经 HAL 下发电机/表情/LED/动画              │
└──────────────▲─────────────────────────────────────────┬────────────────┘
          facts 事实（读快照）│                          电机/表情/声音/LED 指令 │
┌──────────────┴─────────────────────────────────────────▼────────────────┐
│  感知层 Reactive (perception/)          线程 A  ~30Hz / 回调                │
│   摄像头帧 → MediaPipe Pose → person.visible（M1）+ cx/size（M3）           │
│   方块加速度计/连接、悬崖、电池、姿态 → 写黑板"事实"                          │
│   ★ 安全反射（safety/）：悬崖/碰撞→本层立即停轮，不等上层                     │
└───────────────────────────────────▲─────────────────────────────────────┘
                                     │ 帧/传感器回调 + 电机/LED 下发
                          ┌──────────┴──────────┐
                          │  HAL (hal/) 封装 pycozmo │  ← 唯一触达硬件的边界，便于 mock
                          └──────────┬──────────┘
                                     │ UDP / pycozmo 协议
                                ┌────▼────┐
                                │  Cozmo  │
                                └─────────┘
```

**数据流向（单向、解耦）**：下层向黑板写"事实"，上层从黑板读事实、写"目标/心情"。任何一层都不跨黑板直接调用另一层。唯一例外是安全反射——它在感知层内部直接经 HAL 停轮（见 §6.1），这是 PRD US4.4「不可绕过」的硬性要求。

### 1.2 各模块职责与周期一览

| 模块（目录） | 层 | 周期 | 核心职责 | 写黑板字段 | 读黑板字段 |
|---|---|---|---|---|---|
| `perception/` | 感知 | ~30Hz/回调 | 摄像头帧→Pose；方块/悬崖/电池/姿态采集；visible 去抖 | person*, cube, cliff_detected, battery | —（安全反射读 cliff，但在本层内） |
| `safety/` | 感知内 | 与传感器回调同步 | 悬崖/碰撞→立即停轮（必要时后退）；连接中断停车 | cliff_detected（标志） | —（直达 HAL） |
| `task/` | 任务 | ~10Hz | FSM 状态迁移；mood-translator（仲裁+计时+翻译）；视觉伺服控制律 | mood, intention(兜底时) | person*, cube, mood, intention, cliff, battery |
| `cognition/` | 认知 | 秒级/事件（M4） | Gemma agent loop + 规则兜底，产出 {intention, mood} | intention, mood, cog_decision_ts | world_summary（黑板摘要） |
| `world/` | 共享 | — | 黑板：线程安全的字段存储 + 快照 + 结构化日志 | （存储载体） | （存储载体） |
| `hal/` | 底层 | — | 封装 pycozmo：连接/电机/表情/动画/LED/方块/传感器回调；mock 可替换 | — | — |
| `moods/` | 配置/数据 | — | 心情→动画/表情/LED 映射表（数据，不含逻辑） | — | — |

> 注：`safety/` 在物理上运行于感知层线程（与悬崖/碰撞回调同步），逻辑上是"感知层内闭环的反射"，故归入感知层周期。

### 1.3 关键架构决策（需评审重点看）

1. **单进程多线程，而非多进程**：三层共享黑板是高频读写的核心耦合点，进程内共享内存 + 锁的成本远低于跨进程 IPC/序列化；MediaPipe 与 pycozmo 均为进程内库；Gemma 经 Ollama 走本地 HTTP（本身就是跨进程的模型服务，认知层只持有 client）。故主程序为单进程，感知/任务/认知各起一个线程（认知层 M4 才启）。详见 §7.1。
2. **黑板并发模型 = 单写者 + 整体原子替换 + 周期快照**：直接落实 PRD US4.1 并发契约。详见 §4.2。
3. **mood-translator 从 M1 的独立轻量单元，到 M2 长成任务层 FSM 的一个子模块**——同一份代码增量演进、接口不变、不推翻。详见 §3.3 与 §8。
4. **安全维度仲裁固定 安全反射 > 规则 > 模型；心情维度固定 事件即时心情 > 防抖窗口最新有效来源**。仲裁逻辑集中在任务层（mood）与感知层（safety），不分散。详见 §3.4。

---

## 2. 需求 → 设计映射

下表逐条把 PRD 的 User Story / 心情 / 阈值常量 / 黑板字段映射到本设计的落点，证明覆盖无遗漏。

| PRD 条目 | 设计落点（模块/机制/接口） | 里程碑 |
|---|---|---|
| US1.1 连接+苏醒动画 | `hal.connect()` + `hal.play_animation(wake)`；main.py `--demo connect`；§5.1 启动序列；电量经黑板日志 | M1 |
| US1.2 最小人体识别 visible | `perception.PoseDetector`（§3.1）+ `VisibleDebouncer`（§3.2）；person 复合对象预留 cx/size 子字段；感知层耗时/帧率日志（§3.1.3） | M1 |
| US1.3 见人 surprise | `mood-translator`（§3.3）：visible 上升沿→mood=surprise→HOLD→降级 calm；§3.4 仲裁；§3.5 时序边界 | M1 |
| US2.1 自由活动+遇崖停 | `task.FreeRoamState`（§3.6.1）随机游走；`safety`（§6.1）悬崖停轮+CLIFF_BACKOFF_MAX 后退 | M2 |
| US2.2 玩方块 | `task.PlayCubeState`（§3.6.2）；cube 事件→即时心情；PLAY_CUBE_IDLE_TIMEOUT 回退 | M2 |
| US2.3 自由活动心情 | mood-translator 翻译认知/规则心情；最短保持防抖（§3.4） | M2 |
| US3.1 转向居中 | 视觉伺服转向律（§3.7.1）：cx_norm→差动转向，TURN_DEADZONE 死区+迟滞 | M3 |
| US3.2 进退距离 | 视觉伺服距离律（§3.7.2）：size_norm 分区 + 迟滞 + size_max_hard | M3 |
| US3.3 跟随心情 | FOLLOW 态心情：calm/happy；移动期心情走表情/LED 不占轮（§3.7.3） | M3 |
| US3.4 丢人升级+搜索 | `task.SearchState`（§3.6.3）+ T1/T2 计时（mood-translator/FSM 共用单调时钟）；复见 surprise→happy | M3 |
| US3.5 长时间收尾 T3 | SEARCH 态 anxious 起计 T3 → calm + FREE_ROAM（§3.6.3） | M3 |
| US3.6 去抖+多人选择 | `VisibleDebouncer`（M1/M3 共用）+ 多人选 size_norm 最大者（§3.1.2，M3 起生效） | M1/M3 |
| US4.1 三层周期+黑板解耦 | §1 架构；§4.2 并发契约；§7 并发模型 | M2 |
| US4.2 认知决策意图/心情 | `cognition.decide()`（§3.8）结构化输出；解析失败/非法枚举→兜底 | M4 |
| US4.3 规则兜底+仲裁 | `cognition.rule_fallback()`（§3.8.3）；COG_DECISION_TTL stale 失效；§3.4 仲裁 | M4（仲裁框架 M2 起） |
| US4.4 安全反射不可绕过 | `safety`（§6.1）感知层内闭环，仲裁最高优先级 | M2 |
| US4.5 结构化日志 | `world.BlackboardLogger`（§3.9）逐字段/事件 JSON 行 | M2（M1 已用于 visible/帧率/mood 日志） |
| US4.6 断连重连恢复 | `hal` 连接监控 + `task` 重连恢复（§6.2）；RECONNECT_MAX_RETRIES；重连回 FREE_ROAM | M2 |
| 七种心情 calm/happy/playful/curious/confused/anxious/surprise | `moods/` 映射表（§4.3）+ mood 枚举（§4.1） | M1（surprise/calm）→ M2/M3 全量 |
| 阈值常量 T1/T2/T3/SURPRISE_HOLD/VISIBLE_ON·OFF_FRAMES/TURN_DEADZONE/size_*·size_max_hard/CLIFF_BACKOFF_MAX/COG_DECISION_TTL/RECONNECT_MAX_RETRIES/PLAY_CUBE_IDLE_TIMEOUT | `config.yaml`（§4.4）集中管理 | 各 M |
| 黑板字段契约（PRD §11） | §4.1 数据模型 + §4.2 读写契约 | 字段按 M1/M3 启用时机 |

---

## 3. 功能设计详述

### 3.1 感知层：帧获取与人体识别

#### 3.1.1 帧管线结构

感知层主循环（线程 A）以"拉取最新帧 → Pose 推理 → 去抖 → 写黑板"为一拍。pycozmo 以回调推送摄像头帧，HAL 维护"最新帧"槽位（覆盖式，丢旧帧只留最新），感知层主循环从槽位取最新帧推理——**避免帧积压导致时延累积**（低帧率设备宁可丢帧也不排队）。

```
HAL 帧回调 ──写──► [latest_frame 槽位(带锁,覆盖式)] ──读──► 感知主循环
                                                          │
              ┌───────────────────────────────────────────┘
              ▼
   MediaPipe Pose 推理（拿到完整 landmark）
              │
     ┌────────┴─────────┐
   landmark 检出?        landmark→（M3 才算）cx_norm/size_norm
     │                   （M1：cx/size = None，不计算）
     ▼
  VisibleDebouncer（多帧确认）
     │
     ▼
  组装 person 复合对象 → 整体原子写入黑板（§4.2）
     │
     ▼
  记录逐帧耗时/帧率 → 结构化日志（§3.9）
```

#### 3.1.2 visible 判定与多人选择

- **visible 原始判定**：单帧内 MediaPipe Pose 是否检出有效人体 landmark（达到关键点置信度门限即记为"本帧有人"）。该原始 bool 喂给去抖器，**不直接写黑板**。
- **多人选择（M3 起生效）**：若单帧检出多组 pose，选 `size_norm` 最大者（最近）作为跟随目标，其 landmark 用于算 cx/size。M1 只需"有没有人"，不做选择。该规则在感知层落地，使黑板 person 始终代表"当前跟随目标"。

#### 3.1.3 感知层性能可观测（M1 即需）

M1 无 Gemma，"可观测"下沉到感知层自身：每帧记录 Pose 推理耗时；按滑动窗口估算达成帧率（FPS）；经 §3.9 结构化日志按固定间隔（如每秒一条）输出。这是 visible 去抖窗口/时延阈值联调调参的数据来源（PRD Q6）。

> 设计取舍：耗时/FPS 日志按"采样汇总"输出（每秒一条聚合），而非逐帧刷屏，避免日志 I/O 反噬感知层帧率。

#### 3.1.4 感知层输出对象（预留 M3 扩展点）

感知层产出的 person 对象设计为**可承载子字段的复合结构**，M1 时 cx/size 为 None，M3 仅填充子字段，不改帧获取与 Pose 调用结构。数据结构见 §4.1。这样黑板 person「整体原子替换」契约在 M1/M3 都成立。

### 3.2 visible 双向多帧去抖（VisibleDebouncer）

落实 US1.2 / US3.6，M1 与 M3 **共用同一实现**，不在 M3 重定义。

- **状态**：当前去抖后的 `visible`（稳定值）、连续命中计数、连续未命中计数。
- **规则（迟滞计数器）**：
  - 当稳定值为 false 时：原始判定连续 true 达 `VISIBLE_ON_FRAMES`（默认 3）→ 翻转为 true（**上升沿**，下游据此触发 surprise）；其间任一帧原始为 false 则 ON 计数清零。
  - 当稳定值为 true 时：原始判定连续 false 达 `VISIBLE_OFF_FRAMES`（默认 3）→ 翻转为 false（下降沿，T1 计时基准）；其间任一帧原始为 true 则 OFF 计数清零。
- **关键产物**：
  - 翻转为 true 的瞬间 → 记录上升沿事件（mood-translator 消费）。
  - 翻转为 false 的瞬间 → 更新 `person.last_seen_ts` 并记录下降沿时刻（T1 计时起点）。
- **去抖时刻的时间基准**：`last_seen_ts` 与 T1 起点均取**去抖判定成立的那一帧时刻**（单调时钟），而非原始单帧时刻——保证 PRD「T1 基于去抖后 visible 由 true→false 时刻起算」。

> 单帧漏检/误检在 ON/OFF 计数窗口内被吸收，不翻转 visible，不触发状态切换（US3.6）。

### 3.3 mood-translator（心情翻译/计时单元）

PRD 的核心设计落点之一。它**归任务层职责**（是 mood 的合法写者），但 M1 时**不是完整 FSM**（不持状态机状态、不读写 intention）。

#### 3.3.1 职责（贯穿 M1→M2 增量演进）

| 能力 | M1（轻量形态，独立单元） | M2+（任务层 FSM 的子模块） |
|---|---|---|
| 消费 visible 上升沿 → 触发 surprise | ✓ | ✓ |
| SURPRISE_HOLD 计时 + 到期降级 | ✓（降级落点固定 calm） | ✓（降级落点按场景：跟随→happy，否则 calm） |
| 心情仲裁（即时 > 防抖窗口最新有效） | ✓（仅 surprise vs 默认 calm） | ✓（全量来源仲裁，§3.4） |
| 最短保持防抖 | ✓（仅 SURPRISE_HOLD） | ✓（所有心情最短保持） |
| 把 mood 翻译为动画/表情/LED → HAL | ✓ | ✓ |
| 读写 intention / 状态迁移 | ✗（不碰） | ✗（仍由 FSM 主体负责；mood-translator 只管 mood） |

**增量演进要点**：M1 的 mood-translator 是一个独立的 `MoodTranslator` 对象，由 M1 的极简任务层循环每拍调用。M2 引入完整 FSM 时，`MoodTranslator` 原样作为 FSM 的协作对象被复用——FSM 负责 intention/状态，`MoodTranslator` 仍负责 mood 仲裁/计时/翻译。**接口与内部计时逻辑不变，不推翻**。

#### 3.3.2 心情翻译

mood 翻译是"查表 + 下发"：从 `moods/` 映射表（§4.3）按当前 mood 取得 {动画名/表情参数/LED 颜色}，经 HAL 下发。**最短保持期内不重复下发同一心情的整段动画**（防抖，避免动画被频繁打断 US2.3/US3.3）；仅在 mood 实际切换时下发新表现。

#### 3.3.3 跟随移动期的心情表达约束（US3.3）

FOLLOW 态移动中，心情**只走表情/眼睛/LED**；占用车轮的整段 `.bin` 动作动画在移动期不播放或被打断，避免抢占转向/距离控制。mood-translator 据"当前是否处于移动控制中"（由任务层提供的一个标志）决定下发"轮式动画"还是"仅表情/LED"。

### 3.4 心情仲裁（统一框架）

落实 US4.3 / US1.3 / 第 5 节。仲裁集中在 mood-translator，**两个维度**：

**安全维度（不在 mood-translator，在 safety + 上层目标）**：安全反射 > 规则 > 模型。安全反射停车不可被任何心情/意图覆盖（§6.1）。

**心情维度**（mood-translator 内）：

```
优先级（高 → 低）：
  ① 事件驱动即时心情（surprise / 被拍 happy / 被移动 playful）
        其中 surprise 在 SURPRISE_HOLD 内享有"最短保持"，期内不被同级或更低打断
  ② 通过防抖窗口的最新有效来源（认知层低频心情 / 规则兜底心情）
```

- **即时心情来源**：由任务层据感知事实直接触发（visible 上升沿、cube.tapped、cube.moved）。
- **低频心情来源**：认知层写入 mood（M4）或规则兜底写入 mood（M2 起）。
- **来源区分**：mood-translator 内部维护即时心情的"是否处于保持期"状态，无需把"来源"持久化到黑板。但为支撑 US4.3 仲裁与可观测，黑板 mood 配套写入 `mood_source`（immediate/cognitive/rule）与 `mood_ts`（见 §4.1）——满足 PRD §11「心情需可区分来源」。

> 仲裁结果的最终产物只有一个：当前生效 mood（写黑板 + 翻译下发）。

### 3.5 surprise 时序边界四点的实现（US1.3 / US4.3）

这是 PRD 反复强调的无歧义点，逐点给出状态/计时实现。mood-translator 维护一个 surprise 子状态：`IDLE / HOLDING`，并持有 `hold_deadline`（单调时钟）。

```
                visible 上升沿
        IDLE ─────────────────────► HOLDING（mood=surprise, hold_deadline=now+SURPRISE_HOLD）
         ▲                              │  到 hold_deadline
         │                              ▼
         │                     按"落点单调升级链"决定降级 mood：
         │                       · 跟随场景且人仍可见 → happy
         │                       · 人不可见且未到 T1   → calm
         │                       · (随后 T1 到→confused, T2 到→anxious 由 FSM/规则推进)
         │                       · M1 无跟随 → 一律 calm
         └──────────────────────────────┘
```

**四点实现**：

1. **同层处理（不被同级打断）**：HOLDING 态收到同级即时事件（被拍/被移动）→ **丢弃**（设计选定"丢弃"而非"延后"，理由见下）。surprise 保持不变直到 hold_deadline。
   - 选"丢弃"理由：被拍/被移动是瞬时事件，延后到 HOLD 结束（最多 1.5s 后）再补播，语义上已是过期反应、易造成"动作迟到"的违和；而 surprise 本就是强反应，期内丢弃同级瞬时事件对体验影响小、实现也最简（无需事件队列）。PRD 允许二选一，此处定为**丢弃**。
2. **不冻结 T1**：T1 计时由 `last_seen_ts`（去抖下降沿时刻）独立驱动，**不读 surprise 子状态**——即 surprise 在 HOLD 与否完全不影响 T1。安全反射可随时打断 surprise（§6.1 优先级最高）。
3. **空窗心情归属（单调升级链）**：hold_deadline 到达时，mood-translator 按当下事实查"落点"：跟随场景+可见→happy；不可见+未到 T1→calm；M1 无跟随→calm。此后 confused/anxious 由 T1/T2 计时单调推进，calm→confused→anxious **不回退**（升级链由 FSM/规则单向推进，mood-translator 不做反向降级）。
4. **边沿触发不重入**：HOLDING 态再次收到 visible 上升沿（边界抖动）→ **忽略**，不重置 hold_deadline、不叠加新一轮。仅 IDLE 态的上升沿才进入 HOLDING。保持期内 visible 抖动只通过 `last_seen_ts` 影响 T1 基准（以最后一次去抖后的 false 起算），不影响 surprise。

### 3.6 任务层 FSM（M2 起）

状态机状态（大写）：`FREE_ROAM / PLAY_CUBE / FOLLOW / SEARCH`。读黑板 `intention`（小写枚举）+ 感知事实做迁移。FSM 主体负责 intention/状态/行为原语，mood 全权交给协作的 mood-translator。

```
                         intention=play_cube 且 cube.connected
        ┌──────────────────────────────────────────────┐
        │                                                ▼
   ┌─────────┐  intention=follow / visible 去抖=true  ┌──────────┐
   │FREE_ROAM│◄───────────────────────────────────────│PLAY_CUBE │
   └────┬────┘   PLAY_CUBE_IDLE_TIMEOUT 无互动回退      └──────────┘
        │  visible 去抖=true（且意图允许跟随）
        ▼
   ┌─────────┐  visible 去抖丢失 > T1                 ┌──────────┐
   │ FOLLOW  │───────────────────────────────────────►│  SEARCH  │
   └─────────┘◄───────────────────────────────────────└────┬─────┘
        ▲   visible 去抖重见（复见→surprise→happy→FOLLOW）   │
        │                                                    │
        └────────────────────────────────────────────────────┘
                  SEARCH 中 anxious 起 T3 超时 → FREE_ROAM + calm

   （任意状态）悬崖/碰撞/连接中断 → 安全反射立即停（§6.1），不经 FSM
```

#### 3.6.1 FREE_ROAM（US2.1 / US2.3）

随机游走：周期性生成随机的前进/转向原语（非固定路径），受悬崖反射约束。心情由认知/规则写入、mood-translator 翻译。悬崖反射在感知层内闭环，FSM 无需轮询悬崖即可保证安全（但 FSM 也会读 `cliff_detected` 决定恢复时机）。

#### 3.6.2 PLAY_CUBE（US2.2）

进入条件：`cube.connected` 且 `intention=play_cube`（认知/规则给出；无认知时规则可周期性按概率选 play_cube）。
- 点亮方块 LED：颜色/节奏随当前 mood（查 `moods/` 表）。
- 监听 cube 事件：`tapped`/`moved` → 任务层**事件驱动直接触发**即时心情（happy/playful），1s 内切心情（§6.3 时延口径），**不经认知层**。
- 退出：持续 `PLAY_CUBE_IDLE_TIMEOUT`（默认 12s）无 tapped/moved → 回 FREE_ROAM。

#### 3.6.3 FOLLOW / SEARCH（US3.1~US3.5）

- **FOLLOW**：执行视觉伺服（§3.7）。稳定跟随 mood=calm；靠近到目标区间 mood=happy；复见经 surprise→happy。visible 去抖丢失 > T1 → 进 SEARCH。
- **SEARCH**：
  - 进入即 mood=confused，原地慢转/左右张望扫描。
  - 自丢失起 > T2 → mood=anxious，加快/扩大搜索 + 黄/红 LED。
  - 去抖重见 → surprise（短暂保持）→ happy → 回 FOLLOW。
  - 自进入 anxious 起 > T3（默认 30s）仍未重见 → mood=calm，回 FREE_ROAM（US3.5）。
- **T1/T2/T3 计时**：基于单调时钟。T1/T2 以 `last_seen_ts`（去抖下降沿）为基准；T3 以"进入 anxious 时刻"为基准。

### 3.7 视觉伺服控制律（M3）

输入 `cx_norm∈[-1,1]`、`size_norm∈[0,1]`，输出差动轮速。**转向与距离两路解耦叠加**：左右轮速 = 基础前进速度（距离律） ± 转向修正（转向律）。

#### 3.7.1 转向律（US3.1）

- **死区 + 迟滞**：`|cx_norm| ≤ TURN_DEADZONE`（默认 0.15）→ 不发转向指令（稳态判据，避免静止往复）。
- 出死区后，转向角速度与 `cx_norm` 成比例（P 控制，比例系数可配置），并设速度上限。
- **迟滞**：进入死区与离开死区用不同阈值（离开阈值略大于进入阈值），防止边界抖动反复触发。
- cx_norm 已在感知层做时间滤波平滑（§3.7.4）。

#### 3.7.2 距离律（US3.2）

按 size_norm 分区，区间边界带迟滞：

```
 size_norm <  size_min                       → 前进（人远）
 size_min  ≤ size_norm ≤ size_max            → 维持/停（目标区间，不蠕动）
 size_max  <  size_norm ≤ size_max_hard      → 停车不后退（偏近）
 size_norm >  size_max_hard                   → 后退（过近）
```

- **稳态判据**：人静止在目标区间内 → 停住，不反复前后蠕动（区间内不发进退指令）。
- **迟滞**：进入/离开各区间的阈值不同（如"远→维持"的进入阈值高于"维持→远"的离开阈值），防边界抖动。

#### 3.7.3 移动期心情解耦（US3.3）

移动控制期间，mood-translator 收到"移动中"标志，只下发表情/眼睛/LED 心情表达，不下发占轮整段动画（§3.3.3）。

#### 3.7.4 信号平滑

cx_norm / size_norm 在感知层做时间滤波（如指数滑动平均，系数可配置），输出平滑值写黑板。接受"平滑滞后跟随、非紧跟"（PRD 第 6 节检测鲁棒性）。控制律消费平滑后的值。

### 3.8 认知层 agent loop（M4）

统一接口，本地 Gemma（Ollama）为默认 provider，云端为可选 fallback（本期不交付云端实现，仅保留切换能力）。

#### 3.8.1 统一接口

```python
# cognition 对外统一接口（provider 无关）
def decide(world_summary: dict, image: bytes | None = None) -> dict:
    """返回 {"intention": <枚举>, "mood": <枚举>}；解析失败/非法枚举时返回 None。"""
```

- **运行模式**：事件驱动 + 低频轮询（每 1–2s 或关键事件），非每帧（US4.2）。
- **thinking**：高频意图/心情决策关 thinking 求快；偶发复杂看图理解才开 thinking，多模态看图低频（≥5s 或关键事件），不与高频决策叠加（PRD 第 6 节，控 CPU/内存带宽，不抢 MediaPipe）。
- **输入**：`world_summary`（黑板摘要：电池、是否见人/方块、当前 mood/intention、关键事件）+ 可选图像快照。
- **输出处理**：模型返回 JSON → 解析 → 校验 intention/mood 是否合法枚举。
  - 合法 → 写黑板 intention/mood + `cog_decision_ts`。
  - 解析失败或非法枚举 → **等同模型未返回，走规则兜底，绝不写非法值**（US4.2）。

> PRD 明确本期不依赖模型原生 function calling（US4.2 说明），以"模型输出 JSON 字段 → 任务层读取执行"实现。下述 function calling 工具集（PRD 构想第 7 节）作为**接口层语义定义**保留，第一阶段以 JSON 字段映射等价实现：`set_intention`/`set_mood` 等价于输出 JSON 的 intention/mood 字段；`get_world_state` 等价于把 world_summary 作为输入喂入；`play_animation` 不暴露给模型（动画下发是任务层职责，模型不直接控硬件）。这样 M4 后续若启用原生 function calling，可平滑切换而不改上层。

#### 3.8.2 stale 失效（COG_DECISION_TTL）

任务层读 intention/mood 时校验 `now - cog_decision_ts ≤ COG_DECISION_TTL`（默认 2× 认知层决策周期）。超期的（stale）模型决策作废，不得覆盖更新的规则状态（US4.3，防止模型晚到把已升级到 anxious 的状态拉回旧值）。stale 时任务层使用规则兜底结果。

#### 3.8.3 规则兜底（US4.3）

确定性规则，模型未返回/超时/不可达/stale 时给出默认 intention/mood：

- 看见人（visible 去抖=true）→ intention=follow。
- 人丢 > T1 → confused / 意图 search_person；> T2 → anxious。
- 低电量 → stop。
- 自由活动默认 → free_roam，并可周期性按概率选 play_cube（cube.connected 时）。

规则兜底**自 M2 起就独立可跑**（M2~M3 全程用规则跑通），M4 才叠加 Gemma；模型返回且未 stale 时覆盖规则结果（仲裁见 §3.4，安全反射永不可覆盖）。

### 3.9 结构化日志（US4.5，M2 起；M1 已部分使用）

`world.BlackboardLogger` 输出逐条 JSON/键值行：
- 黑板关键字段（person/cube/mood/intention/battery/cliff）的当前值与变化。
- 关键事件条目：状态机迁移、心情切换（含 surprise→calm/happy）、丢人/复见、模型覆盖/兜底生效、连接中断/重连。
- M1 专用：感知层逐帧耗时/达成帧率（聚合）、mood 由 surprise→calm 的切换条目（M1 可观测验收锚点）。

> 图形面板 Out of Scope，本期只交付结构化日志，可被人工查看或后续工具消费。

---

## 4. 数据设计

### 4.1 黑板数据模型（落实 PRD §11 字段契约）

黑板是层间唯一共享状态。字段表（单写者 + 类型 + 启用里程碑）：

```python
# person 复合对象（感知层单写，整体原子替换）
# M1：visible/last_seen_ts 有效；cx_norm/size_norm = None
# M3：填充 cx_norm/size_norm 子字段
person = {
    "visible": bool,            # 经多帧确认（US3.6），M1 起
    "cx_norm": float | None,    # [-1,1]，0=画面中央，M3 起
    "size_norm": float | None,  # [0,1]，近似远近，M3 起
    "last_seen_ts": float,      # 单调时钟，最近一次稳定可见时刻，M1 起
}  # 或整体为 None（从未见过人时）

cube = {                        # 感知层单写
    "connected": bool,
    "tapped": bool,             # 加速度计，瞬时事件（消费后清）
    "moved": bool,
}  # 或 None

# 标量/枚举字段
cliff_detected: bool            # 感知层单写，驱动安全反射
battery: float                  # 感知层单写，电压 V
mood: str                       # 任务层(即时)/认知层(低频)写，§3.4 仲裁；七种枚举
mood_source: str                # 任务层写，immediate/cognitive/rule，支撑 US4.3 仲裁 + 可观测
mood_ts: float                  # 任务层写，mood 最近更新时刻（单调时钟）
intention: str                  # 认知层写，无返回时规则兜底写；意图枚举
cog_decision_ts: float          # 认知层写，最近决策时刻，用于 COG_DECISION_TTL stale 判定
```

**枚举集合**：

```python
MOOD = {"calm", "happy", "playful", "curious", "confused", "anxious", "surprise"}   # 七种
INTENTION = {"free_roam", "play_cube", "follow", "search_person", "stop"}
FSM_STATE = {"FREE_ROAM", "PLAY_CUBE", "FOLLOW", "SEARCH"}   # 状态机状态，不写黑板，任务层内部
```

> PRD 术语表强调：状态机状态（大写）≠ intention（小写）。FSM_STATE 是任务层内部状态，不进黑板；intention 是认知/规则写入黑板的决策意图。二者不混为一谈。

**时钟基准**：所有时间戳（last_seen_ts/mood_ts/cog_decision_ts、T1/T2/T3/SURPRISE_HOLD 计时）统一用**单调时钟**（如 `time.monotonic()`），全系统同一基准，避免墙钟回拨影响计时。

### 4.2 黑板读写并发契约（落实 US4.1）

黑板是高频多线程读写点，落实 PRD「单写者 / 整体原子替换 / 周期快照」三条契约：

| 契约 | 实现机制 |
|---|---|
| 单写者 | 每个字段只有注明的那一层写（见 §4.1）；评审/代码组织上强制（写方法按层分组，禁止越层写） |
| 整体原子替换 | 复合字段（person/cube）以**不可变对象整体替换引用**：写者构造好完整新对象，一次赋值替换旧引用（引用赋值原子）；读者拿到的要么是旧完整对象、要么是新完整对象，永不读到半更新中间态 |
| 周期快照 | 黑板提供 `snapshot()`：在锁内一次性拷贝当前所有字段引用，返回一个不可变快照；任务层每周期先 `snapshot()` 再决策，整周期内字段一致（不会一周期内字段彼此打架） |

**锁粒度**：黑板内部一把读写锁（或对每字段引用赋值依赖 GIL/原子引用 + snapshot 时短临界区拷贝）。因 person/cube 已是"整体替换"，写临界区极短（只换引用），快照临界区只做浅拷贝引用，锁竞争小。

```python
class Blackboard:
    def set_person(self, person: dict | None) -> None: ...   # 感知层调
    def set_cube(self, cube: dict | None) -> None: ...       # 感知层调
    def set_mood(self, mood, source, ts) -> None: ...        # 任务层调
    def set_intention(self, intention, ts) -> None: ...      # 认知/规则调
    def snapshot(self) -> "BlackboardSnapshot": ...          # 任务层/认知层每周期调
```

### 4.3 心情映射表（moods/，纯数据）

`moods/` 是数据而非逻辑——一张 mood → 表现的映射表，供 mood-translator 查表下发。

```yaml
moods:
  calm:     { animation: <bin名>, face: idle_blink,   backpack_led: dim_white }
  happy:    { animation: <bin名>, face: happy,        backpack_led: green }
  playful:  { animation: <bin名>, face: playful,      backpack_led: cyan,   cube_led: cyan }
  curious:  { animation: <bin名>, face: curious,      backpack_led: blue }
  confused: { animation: <bin名>, face: confused,     backpack_led: amber }
  anxious:  { animation: <bin名>, face: anxious,      backpack_led: red }
  surprise: { animation: <bin名>, face: surprise,     backpack_led: white }
```

> 具体 `.bin` 动画名/LED 颜色实现时从 pycozmo 资源选定并填入，全部可配置（PRD 风险项：动画名待实现选定）。

### 4.4 配置项（config.yaml，集中管理全部阈值常量）

PRD 所有阈值常量集中于 config.yaml，标默认值，全部可配置、联调可调：

```yaml
# ── 感知/去抖 ──
visible_on_frames: 3            # 连续命中翻 true（US1.2/US3.6）
visible_off_frames: 3           # 连续未命中翻 false
perception_fps_log_interval: 1.0  # 感知层耗时/FPS 日志聚合间隔(s)

# ── 心情/计时 ──
surprise_hold: 1.5              # surprise 最短保持(s)（US1.3）；与"1.5s 响应时延上限"正交独立
surprise_response_latency: 1.5  # 从 visible 翻转到开始播 surprise 的响应时延上限(s)；独立于 surprise_hold

# ── 丢人升级 ──
t1_confused: 2.0                # 丢人→confused(s)（US3.4）
t2_anxious: 5.0                 # 丢人→anxious(s)
t3_giveup: 30.0                 # anxious 起→放弃回 calm/FREE_ROAM(s)（US3.5）

# ── 视觉伺服（M3）──
turn_deadzone: 0.15             # 转向死区（US3.1）
turn_deadzone_exit: 0.18        # 死区离开阈值（迟滞，>进入阈值）
size_min: <实测定>              # 目标尺寸区间下界（US3.2）
size_max: <实测定>              # 目标尺寸区间上界
size_max_hard: <略大于 size_max> # 触发后退的硬阈值
size_hysteresis: <实测定>       # 区间边界迟滞量

# ── 安全/玩方块 ──
cliff_backoff_max: 20           # 悬崖后退最大距离(mm)（US2.1）
play_cube_idle_timeout: 12.0    # 玩方块无互动回退(s)（US2.2）

# ── 认知层（M4）──
cognition_period: 1.5           # 认知层决策周期(s)
cog_decision_ttl: 3.0           # 模型决策有效期(s)，默认 2× cognition_period（US4.3）
cognition_provider: ollama      # 默认本地；保留 cloud 切换能力（本期不交付）
cognition_thinking_highfreq: false  # 高频意图决策关 thinking
multimodal_min_interval: 5.0    # 多模态看图最小间隔(s)

# ── 连接/重连 ──
reconnect_max_retries: 3        # 重连上限(US4.6)

# ── 动画/链路 ──
wake_animation: <bin名>         # 苏醒动画（US1.1，可配置）
animation_names: 见 moods/ 映射

# ── 三层周期 ──
perception_hz: 30
task_hz: 10
```

---

## 5. 接口设计

### 5.1 HAL 对 pycozmo 的封装边界（便于 mock）

HAL 是上层与 pycozmo 之间唯一边界，对外暴露**稳定的能力接口**，对内封装 pycozmo 细节。上层只依赖 HAL 抽象接口，测试时注入 MockHal。

```python
class HalInterface:                 # 抽象接口，上层只依赖它
    # 连接生命周期
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def on_disconnect(self, callback) -> None: ...   # 断连通知（驱动 §6.2 重连）

    # 运动
    def drive_wheels(self, left_mmps: float, right_mmps: float) -> None: ...
    def stop_wheels(self) -> None: ...               # 安全反射直达
    def move_lift(self, ...) / move_head(self, ...): ...

    # 表现
    def play_animation(self, name: str) -> None: ...
    def set_face(self, expr) -> None: ...
    def set_backpack_led(self, color) -> None: ...
    def set_cube_led(self, color) -> None: ...

    # 传感器/事件回调（HAL→感知层）
    def on_camera_frame(self, callback) -> None: ...  # 覆盖式最新帧
    def on_cliff(self, callback) -> None: ...         # 驱动安全反射
    def on_cube_event(self, callback) -> None: ...    # tapped/moved/connected
    def read_battery(self) -> float: ...

class PycozmoHal(HalInterface): ...   # 真实实现，封装 pycozmo
class MockHal(HalInterface): ...      # 测试实现，喂假帧/假事件，断言下发指令
```

**Mock 测试策略**：
- MockHal 可注入预制摄像头帧序列（含/不含人）→ 驱动感知层去抖、surprise、视觉伺服的单元/集成测试，无需实体 Cozmo。
- MockHal 记录所有下发指令（drive_wheels/play_animation/led）→ 断言"悬崖触发后是否 stop_wheels""surprise 是否在响应时延内下发 surprise 动画"等验收点。
- MockHal 可主动触发 on_cliff/on_cube_event/on_disconnect → 测试安全反射、玩方块、断连重连路径。
- 因 HAL 是唯一硬件边界，三层逻辑可在无硬件下全程 mock 联调（CI 友好）。

### 5.2 层间接口（经黑板，非直接调用）

层间不直接调用，统一经黑板读写（§4.2 接口）。唯一直达是安全反射经 HAL stop_wheels（§6.1）。

### 5.3 main.py 启动接线与 demo 命令

```
main.py --demo connect   # M1：连接 + 苏醒动画 + 最小 visible 感知 + 见人 surprise
main.py --demo roam      # M2：三层 + FREE_ROAM/PLAY_CUBE + 安全反射 + 重连
main.py --demo follow    # M3：+ FOLLOW/SEARCH 视觉伺服 + 丢人情绪
```

启动序列（以 `--demo connect` 为例，US1.1/US1.2/US1.3）：

```
1. 读 config.yaml → 构造 Blackboard、HAL（PycozmoHal）、moods 映射
2. hal.connect()（前置：用户已唤醒 Cozmo + 连其 Wi-Fi）
   └ 连接建立后 5s 内 hal.play_animation(wake_animation)
   └ 打印"连接成功" + read_battery() 电压
3. 启动感知层线程：注册 on_camera_frame/on_cliff/on_cube_event；逐帧 Pose→visible 去抖→写黑板
4. 启动任务层线程（M1 为极简循环，仅驱动 mood-translator）
   └ mood-translator 消费 visible 上升沿→surprise→HOLD→calm，经 HAL 下发表现
   └ 结构化日志输出 visible 变化 / 帧率 / mood 切换
5. 退出（Ctrl-C）：停轮 → hal.disconnect()，安全断开不残留
```

> `--demo roam`/`--demo follow` 在此基础上增启完整 FSM、安全反射、重连、（M4）认知层线程。各 demo 通过开关装配不同层，main.py 是装配点。

---

## 6. 异常与边界处理

### 6.1 安全反射（US4.4，感知层内闭环）

- **触发**：HAL 的 `on_cliff` 回调（悬崖）、碰撞/急停姿态。回调运行在感知层线程上下文。
- **动作**：回调内**直接** `hal.stop_wheels()`，不写黑板等上层、不经 FSM/认知层。随后置 `cliff_detected=true` 供上层观测与恢复决策。
- **悬崖后退（US2.1，可选）**：停车后可执行小幅后退脱离，距离 ≤ `CLIFF_BACKOFF_MAX`（默认 20mm）；后退方向无传感器覆盖，若该方向也触发悬崖则立即再停、不再后退。
- **不可绕过**：任何上层 mood/intention/伺服指令都不能覆盖停车。仲裁上"安全反射 > 规则 > 模型"在此落地——上层下发的 drive_wheels 在 cliff_detected 期间被 HAL/感知层拦截或上层据 cliff_detected 自行不下发（设计选定：上层读 cliff_detected 暂停下发 + 反射已停轮双保险）。

### 6.2 断连与重连恢复（US4.6）

```
hal.on_disconnect 触发
   ▼
立即 hal.stop_wheels()（安全停车，类比安全反射）
   ▼
自动重连循环：尝试 hal.connect()，最多 RECONNECT_MAX_RETRIES 次（默认 3）
   ├─ 成功 → 恢复运行：默认回 FREE_ROAM（随后凭 US3.6 去抖见人即自动进 FOLLOW，复用既有路径）
   │         若重连瞬间画面稳定可见人，可直接进 FOLLOW（设计选定：先回 FREE_ROAM，由统一去抖路径接管，简化恢复逻辑、避免特例）
   └─ 超上限 → 安全退出：停轮 + disconnect + 打印明确失败提示，不残留异常状态
```

- 重连不要求恢复中断前精确状态（PRD 允许回 FREE_ROAM 或重新进跟随）。
- 模型不可达由 §3.8.3 规则兜底处理，与底层断连互不替代（US4.6 说明）。

### 6.3 时延口径与并发边界

- **"1s 内切心情"口径**（US2.2/US2.3）：从黑板事件写入（tapped 置位/mood 更新）到对应动画开始播放 ≤ 1s（软件内部可保证项）。端到端（含方块无线电上报）尽力而为，目标 ≤ 1.5s，不作硬验收。
- **surprise 两个 1.5s**：`surprise_response_latency`（visible 翻转→开始播 surprise 表现的响应时延上限）与 `surprise_hold`（surprise 进入后最短保持）物理含义正交、各自可配、默认同值、互不联动（§4.4 两个独立配置项落实）。
- **幂等/防重复下发**：mood-translator 最短保持期内不重复下发同一心情整段动画（§3.3.2）；视觉伺服死区/区间内不发指令（§3.7），天然防抖动。
- **cube 瞬时事件消费**：tapped/moved 为瞬时事件，任务层消费后清标志（写者感知层置位、读后由约定机制清零，避免重复触发）。

> 注：tapped/moved 的"置位—消费—清零"跨越感知层（写者）与任务层（读者），与「单写者」契约存在张力，是 §10 列出的待确认设计点 D-2。

---

## 7. 非功能性设计

### 7.1 并发模型（三层不同周期调度）

- **线程划分**：感知层线程 A（~30Hz / 帧回调驱动）、任务层线程 B（~10Hz 定时）、认知层线程 C（秒级 / 事件，M4 起）。HAL 的 pycozmo 回调在其自身 I/O 线程，经覆盖式槽位 + 黑板与三层解耦。
- **周期实现**：B 用固定步长循环（每拍 ~100ms，先 snapshot 再决策再下发）；A 由帧回调驱动 + 自身节流到 ~30Hz；C 用定时器/事件触发，决策走子线程不阻塞 B。
- **线程安全**：全部跨线程状态经黑板（§4.2 锁 + 原子替换 + 快照）；HAL 下发指令线程安全（pycozmo 调用经 HAL 串行化或其内部队列）。
- **不阻塞实时环**：认知层 Gemma 推理可能数百 ms~秒级，运行在线程 C，**绝不阻塞 A/B**；任务层只读黑板里"已就绪"的 intention/mood（带 stale 校验），从不等模型（US4.1/US4.2）。

### 7.2 资源与可观测（PRD 第 6 节）

- Gemma 26B-A4B（4-bit，约 13–18GB）与 MediaPipe、pycozmo 同台 32GB 共存。多模态看图低频（≥5s），不与高频意图决策叠加，避免抢 CPU/内存带宽拖慢 MediaPipe。
- **可观测**：内存占用峰值、认知层首字延迟纳入 §3.9 结构化日志（M4）；M1 阶段感知层耗时/帧率纳入日志（§3.1.3）。
- **降级**：本期人工切换配置（改 config 切更小模型/降多模态频率/关 thinking），不做自动降级（Out of Scope）。

### 7.3 检测鲁棒性

低分辨率灰度（~320×240, ~15fps）下 Pose 仅用粗特征（检出 + 肩/髋水平中心 + 肩宽）；出现/消失双向多帧确认（§3.2）；cx/size 时间滤波平滑（§3.7.4）；接受平滑滞后跟随。最小可用分辨率/帧率 M3 实测确认。

---

## 8. 按里程碑的演进（增量、后续不推翻前面）

| 里程碑 | 新增/演进模块 | 交付能力 | 接口演进（不推翻前者） |
|---|---|---|---|
| **M1** | perception(最小 visible 管线 + 去抖)、world(黑板最小子集 + 日志)、hal、moods(calm/surprise)、mood-translator(独立单元)、main(`--demo connect`) | 连接+苏醒+visible 感知+见人 surprise→calm；感知耗时/帧率日志 | 黑板 person 复合对象（cx/size=None 预留）；HAL 全接口就位；VisibleDebouncer 定型（M3 复用） |
| **M2** | task(完整 FSM: FREE_ROAM/PLAY_CUBE) + 把 M1 的 mood-translator **作为 FSM 子模块复用**、safety、cognition(规则兜底先行)、重连、可观测日志全量 | 自由活动+遇崖停+玩方块+心情+断连重连 | mood-translator 长成 FSM 子模块（接口/计时不变）；仲裁框架就位；规则兜底独立可跑 |
| **M3** | perception 增算 cx_norm/size_norm（同一帧 landmark，不改帧获取）、task(FOLLOW/SEARCH + 视觉伺服控制律)、丢人 T1/T2/T3 计时 | 转向跟随+远近反应+丢人情绪+复见+收尾+多人选最近 | person 子字段填充（黑板契约不变）；VisibleDebouncer 原样复用；mood-translator 降级落点扩展为 happy/calm |
| **M4** | cognition(Gemma agent loop) 叠加到规则兜底之上 | 模型下发意图/心情；超时/不可达/stale 由兜底维持 | `decide()` 接口就位，模型结果经仲裁/stale 覆盖规则；上层零改动 |

**演进保证**：黑板 person「整体原子替换」契约 M1 即成立，M3 只填子字段；mood-translator 接口贯穿 M1→M4 不变；VisibleDebouncer M1 定型 M3 复用；规则兜底先于模型，M4 叠加不推翻。落地顺序 M1→M2→M3→M4。

---

## 9. 技术选型与权衡

| 决策点 | 选型 | 替代方案 | 取舍理由 |
|---|---|---|---|
| 进程模型 | 单进程多线程 | 多进程 + IPC | 黑板高频共享，进程内共享内存+锁成本远低于 IPC 序列化；MediaPipe/pycozmo 进程内库；Gemma 已经 Ollama 跨进程 |
| 黑板并发 | 整体原子替换 + 周期快照 + 单写者 | 字段级细粒度锁 / 无锁队列 | 直接满足 PRD 契约；复合对象整体替换使写临界区极短；快照保证任务层整周期一致 |
| 帧管线 | 覆盖式最新帧槽位（丢旧帧） | 帧队列 | 低帧率设备宁丢帧不排队，避免时延累积；跟随容忍滞后 |
| surprise 同级事件处理 | 丢弃（非延后） | 延后到 HOLD 结束 | 瞬时事件延后已过期、易违和；丢弃实现最简无需队列（PRD 允许二选一） |
| 重连恢复 | 统一回 FREE_ROAM，由去抖路径接管 | 重连瞬间直接进 FOLLOW | 复用既有去抖→跟随路径，避免恢复特例，简化逻辑（PRD 允许由设计定） |
| 认知层接口 | JSON 字段映射（function calling 语义保留） | 依赖模型原生 function calling | PRD 明确本期不依赖原生 FC；JSON 字段更可控、配约束解码；保留 FC 语义便于后续平滑切换 |
| mood-translator 形态 | M1 独立单元 → M2 成长为 FSM 子模块 | M1 直接做最小 FSM | PRD Q4/Q8 已确认轻量形态；独立单元最小、增量演进不推翻 |

---

## 10. 风险、依赖与未决问题

### 风险与依赖（承自 PRD 第 9 节，本设计无新增技术风险）

- 单目测距不精确、低质画面漏检 → 靠多帧去抖 + 时间滤波缓解（§3.2/§3.7.4）。
- Gemma 结构化输出成熟度（最大不确定项）→ 解析失败/非法枚举走兜底（§3.8.1），M4 实测验证。
- 本地模型资源峰值、pycozmo 稳定性、动画名待选定 → 见 §7.2 / §6.2 / §4.3。

### 开放问题（请评审与路由）

**【设计疑问·待确认】D-1 安全反射停车的拦截层落点**
- 是什么：安全反射停轮后，上层若仍在下发 drive_wheels，如何确保不被覆盖？本设计采取"双保险"——感知层反射 stop_wheels + 上层读 cliff_detected 暂停下发。
- 为什么：纯靠"上层自觉读 cliff_detected 不下发"有竞态窗口（反射停轮后、上层下一拍前若已下发指令）；是否需要在 HAL 层加一道"cliff_detected 期间拦截 drive_wheels"的硬闸更稳妥。
- 倾向建议：倾向在 HAL 内加轻量硬闸（cliff_detected 为真时 drive_wheels 变 no-op），作为最后防线，与上层自觉双保险。请评审确认是否接受 HAL 承担这点安全语义（HAL 本应是薄封装，加此逻辑略增其职责）。

**【设计疑问·待确认】D-2 cube 瞬时事件（tapped/moved）的"置位—消费—清零"与单写者契约**
- 是什么：tapped/moved 由感知层置位、任务层读取后需清零以防重复触发，但"清零"是对感知层字段的写，与「cube 单写者=感知层」存在张力。
- 为什么：若任务层清零则破坏单写者；若感知层自行按"上报一次即清"则任务层可能漏读（10Hz 任务层与 30Hz 感知层周期不齐）。
- 倾向建议：倾向把瞬时事件设计为"感知层维护一个自增事件序号/边沿计数，任务层记录上次消费的序号，靠比对消费"——感知层仍是唯一写者，任务层只读不写，靠序号差识别新事件，彻底规避清零写冲突。请评审确认该机制是否纳入黑板契约。

**【设计疑问·待确认】D-3 任务层线程数（伺服控制 vs 心情翻译是否同拍）**
- 是什么：M3 视觉伺服（转向/距离，需要稳定 ~10Hz）与 mood-translator（计时/翻译）是否同一任务层线程顺序执行。
- 为什么：mood-translator 下发整段动画可能耗时（HAL 调用），若与伺服同拍，动画下发会拖慢伺服周期，影响转向跟随的实时性。
- 倾向建议：倾向同一线程但严格区分——移动期 mood 只走表情/LED（轻量、§3.3.3），整段轮式动画只在非移动期下发；HAL 动画下发本身设计为非阻塞（提交即返回）。如此可单线程满足 10Hz。请评审确认无需为 mood 单开线程。

**【需求澄清·待 PM 确认】N-1 多模态看图快照的来源帧与对 MediaPipe 的影响**
- 是什么：认知层低频（≥5s）多模态看图需要一张摄像头快照。该快照是复用感知层"最新帧槽位"（§3.1.1），还是另取一帧？
- 为什么：复用槽位最省（不额外占摄像头带宽），但快照是低分辨率灰度（320×240），对 Gemma 看图理解的有效性 PRD 未明确；若需更高质量帧则需 HAL 额外能力。本期多模态是"可选"。
- 倾向建议：倾向复用感知层最新帧槽位（零额外成本、不抢 MediaPipe），接受低质快照——本期多模态仅"可选辅助决策"，不作硬验收。请 PM 确认这一理解与 PRD「低频抓一张摄像头快照」一致、无更高画质期望。

> 以上未决问题不影响 M1/M2/M3 主链路落地（D-1/D-2 仅在 M2 安全/玩方块路径需先定，D-3 在 M3 前需定，N-1 在 M4 前需定）。我已按倾向建议给出默认实现方向，评审确认或推翻后我会据此更新文档。
