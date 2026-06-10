# 工作准则与项目协作规范

本文件包含两部分：**通用工作准则** + **本项目的文档协作路由**（务必遵守）。

本仓库通过两个 skill 编排三个专家 agent 完成文档协作。完整流程剧本写在各 skill 里（按需加载，不常驻上下文）；本文件只保留通用准则与触发路由。

---

## 一、通用工作准则

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

> **These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 二、文档协作（务必遵守）

### 触发路由

- 用户说"写需求 / 做需求 / 生成需求设计文档 / PRD"，或描述一个待定义的新功能诉求 → **必须**调用 **`prd`** skill（流程一：需求设计文档）。
- 用户说"写功能设计 / 技术设计 / 根据需求文档生成功能设计文档" → **必须**调用 **`fds`** skill（流程二：功能设计文档）。
- 不要在主线程里自己手搓这两类文档；一律走对应 skill，由它编排 agent 往返。

### 角色与产物

- **product-manager**（需求主笔）、**architect**（设计主笔 / 需求评审）、**developer**（设计评审）。三者上下文隔离，不互相直接调用，往返由 skill 内的主控协调。
- 需求与设计文档默认同放 `docs/requirements/<feature>/` 下（`<feature>-prd.md`、`<feature>-fds.md`）；默认中文产出。

> 编排细则（多轮评审、终轮整体复审、问题分类路由、文件即单一事实来源等）见 `.claude/skills/prd/SKILL.md` 与 `.claude/skills/fds/SKILL.md`，调用时自动加载。

### 设计变更时同步 PRD/FDS

改动若动到了 `docs/requirements/<feature>/` 下 PRD/FDS 所描述的设计决策、对外可见行为或边界，对应文档必须同步——但**同样不在主线程手搓**：需求层面的变更走 **`prd`** skill，设计层面的变更走 **`fds`** skill，由 skill 编排对应 agent 评审、收敛后落盘，与上文「文件即单一事实来源」「不在主线程手搓这两类文档」一致。

常规工作（bug 修复、重构、实现细节）不触及设计，无需读改文档。按改动性质判断，不要每次都回头重读文档。
