<!-- BEGIN pm-architect-workflow -->
## 文档协作流程（触发路由）

本项目通过两个 skill 编排三个专家 agent（product-manager / architect / developer）完成文档协作。**完整流程剧本写在各 skill 里（按需加载，不常驻上下文）；此处只保留触发路由。**

- 用户说"写需求 / 做需求 / 生成需求设计文档 / PRD"，或描述待定义的新功能诉求 → **必须**调用 **`prd`** skill（流程一：需求设计文档，product-manager 主笔、architect 评审）。
- 用户说"写功能设计 / 技术设计 / 根据需求文档生成功能设计文档" → **必须**调用 **`fds`** skill（流程二：功能设计文档，architect 主笔、developer 评审）。
- 不要在主线程里自己手搓这两类文档；一律走对应 skill，由它编排 agent 往返。

需求文档存 `docs/requirements/`，设计文档存 `docs/design/`；默认中文产出。编排细则（多轮评审、终轮整体复审、问题分类路由、文件即单一事实来源）见 `.claude/skills/prd/SKILL.md` 与 `.claude/skills/fds/SKILL.md`。
<!-- END pm-architect-workflow -->
