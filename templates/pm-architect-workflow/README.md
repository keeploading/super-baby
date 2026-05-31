# pm-architect-workflow（产品经理 + 架构师 + 研发 文档协作模板）

一套可复制的 Claude Code 协作能力：三个专家 agent 在"需求文档"和"功能设计文档"两个阶段互相主笔/评审，最终把结论交给你拍板。

## 包含内容

```
pm-architect-workflow/
├── agents/
│   ├── product-manager.md   # 产品经理 agent（需求定义，user story 视角）
│   ├── architect.md         # 架构师 agent（功能设计 + 评审需求）
│   └── developer.md         # 研发 agent（从代码实现角度评审功能设计）
├── CLAUDE.snippet.md        # 协作流程编排规范（合并进项目 CLAUDE.md）
├── install.sh               # 一键安装到目标项目
└── README.md
```

> 目录名沿用 `pm-architect-workflow`（历史命名），现已是三角色协作。

## 两条协作流程

| 流程 | 主笔 | 评审 | 结束方式 |
|------|------|------|----------|
| 生成《需求设计文档》 | product-manager | architect | 双方往返修订 → 交你**确认** |
| 生成《功能设计文档》 | architect | **developer** | 双方往返直至一致 → 交你**决策** |

- 需求文档以 **user story** 视角定义；功能设计文档**以架构设计开头**、以文字+图表为主、聚焦变化点。
- developer 评审功能设计时**同时参考需求文档**，并显式检查每条需求/user story 的覆盖度。
- 两份文档撰写均遵循**奥卡姆剃刀原则**：言简意赅，如无必要、勿增实体。
- agent 之间不互相直接调用，往返由 Claude（主控）协调。

## 安装到一个新项目

**方式一：脚本（推荐）**

```bash
# 在本模板目录下执行，参数为目标项目根目录
./install.sh /path/to/your-project
```

脚本会：
1. 把三个 agent 复制到 `<目标>/.claude/agents/`
2. 把协作流程片段合并进 `<目标>/CLAUDE.md`（已存在则去重追加）
3. 建好 `docs/requirements/` 与 `docs/design/` 目录

**方式二：手动复制**

```bash
mkdir -p your-project/.claude/agents
cp agents/*.md your-project/.claude/agents/
cat CLAUDE.snippet.md >> your-project/CLAUDE.md   # 没有 CLAUDE.md 就先创建
```

## 怎么用（安装后）

在目标项目里直接对 Claude 说：

- 触发流程一：**"帮我生成需求设计文档：<你的诉求>"**
- 触发流程二：**"根据需求设计文档生成功能设计文档"**

Claude 会自动按上表编排 agent，每轮结束都会告诉你进展、是否达成一致、以及需要你确认/决策的事项。

## 升级

模板更新后，重新跑一次 `install.sh` 即可覆盖 `agents/` 下的文件（CLAUDE.md 片段有去重标记，不会重复追加）。
