<!-- BEGIN pm-architect-workflow -->
## 文档协作流程（product-manager + architect）

本项目定义了两个专家 agent（位于 `.claude/agents/`）：

- **product-manager**：产品经理，负责需求定义与从产品视角评审。
- **architect**：系统架构师，负责功能/技术设计与从技术视角评审。

主控（orchestrator）负责在两个 agent 之间协调往返，agent 之间不互相直接调用。

### 流程一：生成《需求设计文档》

当用户要求"生成需求设计文档 / 帮我做需求"时：

1. 调用 **product-manager** 撰写《需求定义文档》。
2. 调用 **architect** 评审该文档，产出评审意见清单。
3. 把评审意见交回 **product-manager** 逐条回应并修订；如仍有分歧，再次往返（一般不超过 2~3 轮）。
4. 将最终的需求定义文档 + 双方意见汇总 **提交用户确认**，由用户拍板。

主笔：product-manager；评审：architect。

### 流程二：生成《功能设计文档》

当用户要求"根据需求设计文档生成功能设计文档"时：

1. 调用 **architect** 基于《需求定义文档》撰写《功能设计文档》。
2. 调用 **product-manager** 评审该文档，产出评审意见清单。
3. 把评审意见交回 **architect** 逐条回应并修订；往返直至双方达成一致（一般不超过 2~3 轮）。
4. 双方达成一致后，向用户汇报"已达成一致 + 文档摘要 + 任何遗留权衡点"，**让用户做最终决策**。

主笔：architect；评审：product-manager。

### 通用约定

- 文档默认保存：需求文档放 `docs/requirements/`，设计文档放 `docs/design/`。
- 所有产出默认使用中文。
- 两个 agent 都不替用户做最终决策，只负责把方案与分歧讲清楚。
- 每轮往返结束后，主控需明确告诉用户：当前进展、是否达成一致、待用户确认/决策的事项。
<!-- END pm-architect-workflow -->
