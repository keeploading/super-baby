# pm-architect-workflow（产品经理 + 架构师 + 研发 文档协作模板）

一套可复制的 Claude Code 协作能力：三个专家 agent 在"需求文档"和"功能设计文档"两个阶段互相主笔/评审，由两个 skill 作为可靠入口编排流程，最终把结论交给你拍板。

## 包含内容

```
pm-architect-workflow/
├── agents/
│   ├── product-manager.md   # 产品经理 agent（需求定义，user story 视角）
│   ├── architect.md         # 架构师 agent（功能设计 + 评审需求）
│   └── developer.md         # 研发 agent（从代码实现角度评审功能设计）
├── skills/
│   ├── prd/SKILL.md         # 流程一入口 /prd（编排需求文档）
│   └── fds/SKILL.md         # 流程二入口 /fds（编排功能设计文档）
├── CLAUDE.snippet.md        # 协作流程编排规范（合并进项目 CLAUDE.md）
├── install.sh               # 一键安装到目标项目
└── README.md
```

> 目录名沿用 `pm-architect-workflow`（历史命名），现已是三角色 + 双 skill 协作。

## 架构说明（为什么这么设计）

- **skill 做入口+剧本**：`/prd`、`/fds` 既能显式触发，也能在你描述需求时被自动识别，解决"新会话里流程触发不了"。skill 内容仅在调用时加载（渐进披露），不常驻上下文。
- **subagent 做重活**：三个 agent 各自跑在**隔离上下文**里，其往返推敲**不污染主会话**，不影响你后续写代码/问答。
- **文件即单一事实来源**：agent 之间、与主线程之间上下文互不可见，跨轮/跨会话记忆只靠落盘文档。因此每次调用都先 Read 最新文档。

## 两条协作流程

| 流程 | 入口 | 主笔 | 评审 | 结束方式 |
|------|------|------|------|----------|
| 生成《需求设计文档》 | `/prd` | product-manager | architect | 往返修订 + 终轮整体复审 → 交你**确认** |
| 生成《功能设计文档》 | `/fds` | architect | **developer** | 往返修订 + 终轮整体复审 → 交你**决策** |

每条流程都包含：
- **多轮逐条评审**直至无"必须改"意见；
- **终轮整体复审**：逐条意见解决后，评审方再通读全文一次，专抓"局部改完、全局却出问题"；
- **问题中转协议**：agent 抛出的疑问按【技术/设计→对方 agent】【业务→用户】分类路由，不丢弃；
- 需求文档以 **user story** 视角定义；功能设计**以架构设计开头**、文字+图表为主、聚焦变化点；
- 两份文档均遵循**奥卡姆剃刀原则**。

## 安装到一个新项目

**方式一：脚本（推荐）**

```bash
# 在本模板目录下执行，参数为目标项目根目录
./install.sh /path/to/your-project
```

脚本会：
1. 把三个 agent 复制到 `<目标>/.claude/agents/`
2. 把 `/prd`、`/fds` 两个 skill 复制到 `<目标>/.claude/skills/`
3. 把协作流程片段合并进 `<目标>/CLAUDE.md`（已存在则去重追加）
4. 建好 `docs/requirements/` 与 `docs/design/` 目录

**方式二：手动复制**

```bash
mkdir -p your-project/.claude/agents your-project/.claude/skills
cp -r agents/*.md your-project/.claude/agents/
cp -r skills/*   your-project/.claude/skills/
cat CLAUDE.snippet.md >> your-project/CLAUDE.md   # 没有 CLAUDE.md 就先创建
```

> 想跨所有项目复用：把 `agents/` 与 `skills/` 放到用户级 `~/.claude/agents/`、`~/.claude/skills/` 即可（无需每个项目安装）。

## 怎么用（安装后）

在目标项目里输入：

- 触发流程一：**`/prd 我想做……（你的诉求）`**
- 触发流程二：**`/fds docs/requirements/xxx-需求定义.md`**

或直接自然语言描述（"帮我写需求……"），Claude 会自动识别并走对应 skill。每轮结束都会告诉你进展、是否达成一致、以及需要你确认/决策的事项。

## 升级

模板更新后，重新跑一次 `install.sh` 即可覆盖 `agents/`、`skills/` 下的文件（CLAUDE.md 片段有去重标记，不会重复追加）。
