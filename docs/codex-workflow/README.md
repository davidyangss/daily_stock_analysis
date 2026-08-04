# Codex 多 SubAgent 股票分析工作流

> 文档状态：目标架构与现有能力映射。本文档不会声明目标工作流已经在运行时实现。

这组文档用于把本项目已有的数据、策略、选股、问股和交易员分析能力，整理成可被 Codex 按需装载的稳定上下文。目标不是让每个 SubAgent 重新阅读整个仓库，而是让它拿到明确的输入、逻辑、输出、证据边界和角色权限后，立即围绕一个报告段落或一个决策焦点展开工作。

## 1. 阅读入口

| 任务 | 必读文档 | 按需补充 |
| --- | --- | --- |
| 快速理解产品能力和 Agent 路由 | [产品功能图](product-capability-map.md) | 本页其他契约 |
| 获取行情、基本面或新闻 | [数据源与标准数据契约](data-contracts.md) | [数据源优先级](../data-source-priority.md)、[数据源稳定性](../data-source-stability.md) |
| 运行或解释一个策略 | [策略工具与角色决策契约](strategy-and-role-contracts.md) | 对应的 `strategies/<strategy_id>.yaml` |
| 候选股筛选后形成决策 | [策略工具与角色决策契约](strategy-and-role-contracts.md) | [AlphaSift 集成](../alphasift-integration.md) |
| 运行完整交易员分析 | [策略工具与角色决策契约](strategy-and-role-contracts.md) | [交易员分析](../trader-analysis.md)、[交易员重建契约](../trader-analysis-contract.md) |
| 质疑报告中的一段结论 | [报告挑战与多 SubAgent 协作协议](multi-agent-challenge-workflow.md) | 本页与被挑战策略的 YAML |
| 实现新的 Codex 专项工作流 | 本页全部文档 | [分析上下文包](../analysis-context-pack.md) |

建议 Codex 只装载当前任务需要的契约。例如，挑战“放量突破”结论时，装载本页、数据契约中的日线/实时字段、策略契约中的 `volume_breakout` 行，以及挑战协议；不必装载全部交易员内部实现。

## 2. 核心设计原则

### 2.1 策略是工具，交易员是决策角色

- **策略工具**回答“若采用这套规则，证据支持什么信号、哪些条件未满足”。它不能独立决定仓位，也不能假装自己知道用户的风险偏好。
- **交易员角色**回答“在当前市场、组合约束和证据质量下，采用、拒绝或降权哪些策略，并形成怎样的行动计划”。
- **风险与组合角色**挑战交易员的计划，决定是否降仓、延后、增加失效条件或否决。
- **报告编辑角色**只整合已经裁决的观点，不创造行情、新闻或财务事实。

因此目标关系是：

```text
候选生成工具
  -> 标准上下文与证据
  -> 多个策略工具并行分析
  -> 交易员选择/组合/拒绝策略
  -> 多空研究与风险角色挑战
  -> 组合经理裁决
  -> 带证据引用的报告
```

策略和交易员不能是两条互不相干的最终决策链。策略可独立运行以产出意见，但最终行动必须由交易员在组合和风险语境中解释。

### 2.2 数据先于观点

所有观点都必须引用同一次上下文修订中的证据。一个 SubAgent 如果没有拿到必需数据，应返回 `insufficient`，而不是用常识、过期记忆或其他来源的近似数据补齐。

### 2.3 原始报告不可被静默覆盖

用户对报告做标记后产生的是一次 `challenge`。挑战结论以 amendment/revision 追加到原报告，保留原文、数据截止时间、参与角色、接受和拒绝的论据。抓取新数据必须创建新的 context revision，不能用今天的数据悄悄改写历史报告。

### 2.4 角色权限小而明确

| 角色 | 可以做 | 不可以做 |
| --- | --- | --- |
| Data Context Builder | 获取、标准化、标注质量和来源 | 形成买卖建议 |
| Screener | 生成和排序候选 | 把排序直接表述为交易决策 |
| Strategy Tool Agent | 按指定策略解释证据和信号 | 决定最终仓位、伪造缺失数据 |
| Trader | 采用/拒绝策略，形成执行计划 | 隐去冲突策略和证据不足 |
| Bull/Bear Researcher | 构建支持或反对论证 | 直接修改主报告 |
| Risk Analyst | 评估回撤、失效和组合风险 | 创造新的市场事实 |
| Portfolio Manager | 对行动与仓位作最终裁决 | 绕过数据质量门 |
| Report Editor | 生成报告或 amendment | 改写未被裁决的事实与观点 |

## 3. 当前实现与目标状态

| 能力 | 当前实现 | 本工作流目标 |
| --- | --- | --- |
| 多 DataProvider | 已有，支持按市场和能力 fallback | 继续复用；上下文中统一保留 source、时点、复权和质量 |
| 多 NewsProvider | 已有按需搜索与本地资讯池两层 | 统一成可引用的 evidence item，但仍保留两层来源语义 |
| 标准数据层 | 已有标准日线、实时快照、基本面 envelope 和 `AnalysisContextPack` | 在其语义上构造可持久化的 `AgentContextPack` |
| 策略 | 15 个 YAML 自然语言 Skill，由 LLM 调用工具执行 | 封装成有严格证据门、统一 I/O 的策略工具 SubAgent |
| 股票筛选 | AlphaSift 外部适配层可产出候选和 LLM 排名 | 只作为候选生成器；候选需补齐标准上下文后再决策 |
| AI 问股 | 已有会话、股票消歧、策略选择和工具循环 | 作为面向用户的协调入口，调用上下文、策略、交易员和挑战流程 |
| 交易员分析 | 已有 TradingAgents 多角色链路和独立报告 | 接收策略综合结果，并显式声明采用/拒绝/冲突的策略 |
| 报告挑战 | 尚无稳定的段落级对抗与 amendment 契约 | 增加 section ID、ChallengeRequest、角色答辩、裁决和增补记录 |

### 3.1 最重要的现状缺口

当前 [交易员分析](../trader-analysis.md) 明确是独立实验入口，“不会读取、写入或比较现有策略分析结果”。这与本工作流的目标不同。后续实现应增加适配层，而不是删除现有四类分析、多空研究、风险辩论和 Portfolio Manager：

```text
strategy_results / strategy_synthesis
  -> Strategy-to-Trader Adapter
  -> Research Manager / Trader 上下文
  -> TraderProposal（附 adopted/rejected/conflicts）
  -> Risk Debate
  -> PortfolioDecision
```

另外，现有策略是自然语言 Skill，不是确定性 Python 函数。文档中的“策略逻辑”是 LLM 必须遵守的判定契约；可靠性来自工具证据校验、条件列表和质量门，而不是来自函数级可重复性。

## 4. 目标组件

```text
Codex Orchestrator
├── Context Builder
│   ├── DataProvider adapters
│   ├── NewsProvider adapters
│   └── AgentContextPack + Evidence Registry
├── Candidate Generator
│   └── AlphaSift adapter / 用户给定股票
├── Strategy Tool Agents (0..N)
├── Trader Team
│   ├── Market / Sentiment / News / Fundamentals Analysts
│   ├── Bull / Bear Researchers
│   ├── Research Manager
│   ├── Trader
│   ├── Aggressive / Conservative / Neutral Risk Analysts
│   └── Portfolio Manager
├── Report Composer
└── Challenge Orchestrator
    ├── 被挑战策略或角色
    ├── 反方与风险角色
    ├── Evidence Verifier
    └── Report Amendment Editor
```

Codex 主 Agent 负责任务拆分、上下文版本锁定、角色调度和最终交付。SubAgent 只获得完成其职责所需的 context slice，以降低上下文污染和角色越权。

## 5. 两条分析工作流

### 5.1 策略组合分析

适合快速验证技术形态、用户自定义策略或多策略共识：

1. 解析股票身份和市场；有歧义时返回候选，禁止猜测。
2. 构建带截止时间和质量状态的上下文。
3. 根据用户指定、市场状态或路由规则选择策略。
4. 并行运行策略工具 SubAgent。
5. 证据门将策略结果标为 `verified`、`limited` 或 `insufficient`。
6. 只聚合 `verified/limited` 结果；`insufficient` 进入 diagnostics。
7. 交给 Trader 解释策略冲突、执行条件和仓位约束。
8. 生成报告及可挑战的稳定段落 ID。

### 5.2 完整交易员分析

适合形成完整研究和风险决策：

1. 执行数据预检，形成 market/news/sentiment/fundamentals 证据。
2. Market、Sentiment、News、Fundamentals Analyst 生成分报告。
3. 在相同 context revision 上运行选定策略组合。
4. Bull/Bear Researcher 同时读取四类分报告和策略结果，构建对立论证。
5. Research Manager 输出研究计划，并标记策略冲突。
6. Trader 显式选择采用和拒绝的策略，形成行动、价格条件、仓位和失效条件。
7. 三类 Risk Analyst 进行风险辩论。
8. Portfolio Manager 作最终裁决，Report Composer 生成可审计报告。

### 5.3 目标 `WorkflowRequest` / `WorkflowResult`

Codex 专项入口建议统一接收：

```json
{
  "workflow": "strategy_analysis|trader_analysis|screen_and_analyze|challenge_report",
  "subjects": [{"code": "600519", "market": "cn"}],
  "as_of": "2026-08-04T15:00:00+08:00",
  "screener": {"strategy_id": null, "max_results": 20},
  "analysis_strategies": ["bull_trend", "growth_quality"],
  "trader_profile": {"style": "neutral"},
  "portfolio_constraints": {},
  "report_options": {"include_evidence": true},
  "challenge_request": null
}
```

目标输出：

```json
{
  "workflow_run_id": "workflow_01J...",
  "status": "complete|degraded|insufficient_evidence|failed",
  "context_refs": [],
  "candidates": [],
  "strategy_results": [],
  "strategy_synthesis": {},
  "trader_result": {},
  "portfolio_decision": {},
  "report_manifest": {},
  "diagnostics": []
}
```

调度边界：

- `screen_and_analyze` 先筛选，再为入围候选分别构建标准上下文；不能让所有候选共享一份个股 context。
- 同一股票的 Strategy Tool Agents 可在 context 锁定后并行运行。
- Market/Sentiment/News/Fundamentals Analysts 可读取同一 context 的不同 slice 并行运行。
- Research Manager 必须等待多空研究，Trader 必须等待研究计划和策略结果，Portfolio Manager 必须等待风险辩论。
- 任一必要前置步骤 `insufficient` 时，依赖它的角色进入受约束降级或停止，不能用调度并发掩盖依赖失败。

## 6. 用户发布自定义策略

用户策略应与内置策略使用同一最小契约：

```yaml
name: user_strategy_id
display_name: 用户可读名称
description: 一句话说明策略目的
category: trend|reversal|pattern|framework|custom
required_tools:
  - get_daily_history
  - analyze_trend
market_regimes: [trending_up]
instructions: |
  明确数据窗口、指标口径、入场条件、排除条件、风险边界和输出要求。
```

发布前至少补充：

- 适用市场、周期和复权口径；
- 依赖字段及缺失时行为；
- 可计算条件与需要 LLM 判断的条件；
- 信号、分数调整、置信度和失效条件；
- 避免未来函数的 point-in-time 规则；
- 至少一个正例、反例和边界例；
- 如用于真实筛选，提供回测摘要或明确标记“未回测”。

自定义策略只扩展“分析工具”层，不自动获得 Trader 或 Portfolio Manager 权限。

## 7. Codex 上下文装载规则

每个 SubAgent 的主要上下文按以下顺序组成：

1. **Role Contract**：身份、职责、禁止事项、输出 schema。
2. **Task Focus**：股票、报告段落、用户问题和本轮目标。
3. **Context Slice**：从同一 `AgentContextPack` 选择必要 blocks。
4. **Evidence Registry**：稳定 evidence ID、来源、时点和质量。
5. **Strategy Contract**：仅策略 Agent 或需要解释该策略的角色装载。
6. **Prior Claims**：原报告结论及其引用，不装载无关会话全文。

SubAgent 输出必须是结构化结果加简洁解释。Codex 主 Agent 不应依赖从自由文本中猜测 signal、证据 ID 或修改操作。

## 8. 非目标与安全边界

- 本文档不是自动交易、券商下单或收益保证设计。
- 策略信号、Trader action 和 PortfolioDecision 都是研究建议，不是自动执行指令。
- 不同 provider 的原始字段不能被假定一致；只有标准化层字段属于本契约。
- 缺失、陈旧、fallback 或估算数据必须显式传播，不能在摘要中消失。
- 历史报告只能使用当时已经可得的数据。
- 对抗分析的目标是发现假设、证据和逻辑问题，不是强制生成反对意见。

## 9. 实施顺序建议

1. 固化 `AgentContextPack`、evidence ID 和报告 section ID。
2. 把内置 YAML 策略包装成严格 I/O 的 Strategy Tool Agent。
3. 增加 Strategy-to-Trader Adapter，让 Trader 输出采用/拒绝/冲突策略。
4. 让报告生成器保存 claim-to-evidence 关系。
5. 实现 ChallengeRequest、答辩、裁决和 amendment 存储。
6. 最后再扩展用户策略发布、回测和策略版本管理。

实施前四步即可支持“读报告—标记段落—挑战 SubAgent—把裁决结果增补回报告”的最小闭环。
