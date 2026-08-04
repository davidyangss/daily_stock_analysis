# Codex 策略工具与角色决策契约

> 文档状态：总结当前策略、筛选、问股和交易员实现，并定义“策略是工具、交易员是决策角色”的目标衔接契约。

## 1. 语义边界

本项目当前的内置策略位于 `strategies/*.yaml`。它们是由 LLM 执行的自然语言 Skill，不是输入相同就必然逐字输出相同的 Python 纯函数。因此这里的“逻辑”表示 Strategy Tool Agent 必须遵守的规则，“输出”表示结构化意见，不表示自动交易指令。

目标分工：

```text
Screener = 找候选
Strategy Tool Agent = 按一套策略检查候选
Trader = 选择、组合或拒绝策略，形成行动计划
Risk / Portfolio = 挑战并裁决行动与仓位
Ask = 面向用户协调上述能力
```

## 2. 策略定义和运行时契约

### 2.1 YAML 定义

策略定义支持：

```text
name, display_name, description, instructions
category, core_rules, required_tools
aliases, enabled, source, entrypoint
default_active, default_router, default_priority
market_regimes, execution_context, subagent_type, preferred_model
```

`required_tools` 是硬证据声明，不只是工具建议。Strategy Tool Agent 必须调用全部 required tools，运行时再根据实际返回判定证据是否足够。

### 2.2 Strategy Tool Agent 输入

```json
{
  "strategy_id": "volume_breakout",
  "strategy_version": "content-hash-or-version",
  "context_id": "ctx_xxx_r1",
  "subject": {"code": "...", "name": "...", "market": "..."},
  "as_of": "...",
  "market_regime": "trending_up",
  "required_tools": ["get_daily_history", "analyze_trend"],
  "context_slice": {},
  "portfolio_constraints": {},
  "task_focus": "验证报告中的放量突破结论"
}
```

当前运行时不会完整接受以上目标 envelope，但已经具备股票上下文、策略 YAML、技术意见和工具调用循环。目标封装用于 Codex 工作流稳定传递上下文版本和焦点。

### 2.3 当前策略输出

`src/agent/skills/skill_agent.py` 要求只返回：

```json
{
  "skill_id": "volume_breakout",
  "signal": "strong_buy|buy|hold|sell|strong_sell",
  "confidence": 0.0,
  "conditions_met": [],
  "conditions_missed": [],
  "score_adjustment": 0,
  "reasoning": "2-3 sentence evaluation"
}
```

其中 `confidence` 必须在 0..1，`score_adjustment` 约束在 -20..20。运行时附加：

```text
tool_evidence
required_tool_evidence
missing_required_tools
limited_required_tools
evidence_status
```

`evidence_status` 规则：

| 必需工具实际状态 | 策略证据状态 | 聚合行为 |
| --- | --- | --- |
| 全部 `available` | `verified` | 可进入综合投票 |
| 任一 `fallback/partial/estimated/stale`，无硬缺失 | `limited` | 可进入综合，但必须降置信度并披露限制 |
| 任一 `missing/fetch_failed/not_supported` 或未调用 | `insufficient` | 不进入投票，只进入 diagnostics |

### 2.4 Codex 包装后的推荐输出

保留现有字段并增加可审计字段：

```json
{
  "strategy_id": "volume_breakout",
  "strategy_version": "...",
  "context_id": "ctx_xxx_r1",
  "signal": "hold",
  "confidence": 0.62,
  "score_adjustment": 0,
  "conditions_met": [],
  "conditions_missed": ["成交量未达到 5 日均量 2 倍"],
  "evidence_status": "verified",
  "evidence_refs": ["technical.volume.2026-08-04"],
  "assumptions": [],
  "invalidation_conditions": [],
  "reasoning": "..."
}
```

## 3. 策略工具可用的数据函数

主要工具：

```text
get_daily_history
get_realtime_quote
get_chip_distribution
get_stock_info
get_capital_flow
get_analysis_context
analyze_trend
calculate_ma
get_volume_analysis
analyze_pattern
search_stock_news
search_comprehensive_intel
get_market_indices
get_sector_rankings
get_skill_backtest_summary
get_strategy_backtest_summary
get_stock_backtest_summary
```

### 3.1 `get_daily_history`

主要输出：

```text
code, source, cache_hit, requested_days, effective_days
actual_records, partial_cache, total_records, data[]
```

`data[]` 使用 [数据契约](data-contracts.md) 中的标准日线字段。策略必须检查 `actual_records` 是否满足自己的窗口，并保留复权和 partial 状态。

### 3.2 `analyze_trend`

主要输出：

| 分组 | 字段 |
| --- | --- |
| 趋势 | `trend_status`, `ma_alignment`, `trend_strength` |
| 均线 | `ma5`, `ma10`, `ma20`, `ma60` |
| 乖离 | `bias_ma5`, `bias_ma10`, `bias_ma20` |
| 量能 | `volume_status`, `volume_ratio_5d`, `volume_trend` |
| 支撑阻力 | `support_ma5`, `support_ma10`, `support_levels`, `resistance_levels` |
| MACD | `macd_dif`, `macd_dea`, `macd_bar`, `macd_status`, `macd_signal` |
| RSI | `rsi_6`, `rsi_12`, `rsi_24`, `rsi_status`, `rsi_signal` |
| 综合 | `buy_signal`, `signal_score`, `signal_reasons`, `risk_factors` |

工具已经给出的综合信号只是证据之一，策略 Agent 仍须按自身规则列出满足和未满足条件。

### 3.3 `get_stock_info`

主要输出：

```text
code, name
pe_ratio, pb_ratio, total_mv, circ_mv
revenue_yoy, net_profit_yoy, roe, gross_margin
fundamental_context
belong_boards, boards
sector_rankings
```

`boards` 是 `belong_boards` 的兼容别名。财务字段必须结合报告期、可得日和质量状态解释。

### 3.4 搜索、板块和回测工具

- `search_stock_news` / `search_comprehensive_intel`：提供新闻、事件、公告、风险、财报和行业情报；搜索摘要不等于正文。
- `get_sector_rankings` / `get_market_indices`：提供市场环境、板块共振和相对强弱证据。
- `get_capital_flow`：提供来源相关的资金字段，不得跨来源假定相同算法。
- `get_chip_distribution`：提供获利盘、平均成本与 70%/90% 成本区间，仅在支持的市场使用。
- 三类 backtest summary：只能作为历史辅助证据，不能替代当前条件，也不能把无回测记录解释为负面信号。

## 4. 15 个内置策略：输入—逻辑—输出

以下评分为 YAML 中对 `sentiment_score` 的调整建议，最终仍被统一限制在策略输出的 -20..20。表中的“失效/限制”既包括策略本身的否定条件，也包括证据不足条件。

### 4.1 `bull_trend` — 默认多头趋势

- **适用状态**：`trending_up`；常规个股默认策略。
- **必需工具**：`get_daily_history`, `analyze_trend`。
- **主要输入**：MA5/10/20 排列、MA20 方向、价格对均线的乖离、成交量、关键支撑阻力。
- **逻辑**：确认 `MA5 >= MA10 >= MA20` 且中期均线向上；偏好回踩均线企稳或有量能确认的阻力突破，避免高乖离追涨。
- **输出调整**：多头排列且趋势强 `+12`；回踩关键均线企稳 `+8`；放量突破 `+10`；跌破 MA20 或趋势转弱 `-12`。
- **失效/限制**：MA20 下行、关键支撑破位、历史窗口不足或均线/量能证据缺失。

### 4.2 `ma_golden_cross` — 均线金叉

- **适用状态**：`trending_up`。
- **必需工具**：`get_daily_history`, `analyze_trend`。
- **主要输入**：最近至少三日 MA5/10/20、MACD、量比、短期乖离。
- **逻辑**：优先确认 MA5 在三日内上穿 MA10、MA10 上穿 MA20；量比大于约 1.2 且乖离率小于约 5%更可信。
- **输出调整**：MA5×MA10 金叉配合量能 `+10`；MA10×MA20 金叉 `+8`；MACD 零轴上方金叉额外 `+5`。
- **失效/限制**：只有静态均线顺序、无法证明发生交叉；缩量或高乖离形成假金叉；历史不足。

### 4.3 `volume_breakout` — 放量突破

- **适用状态**：`trending_up`。
- **必需工具**：`get_daily_history`, `analyze_trend`, `get_realtime_quote`, `search_stock_news`, `get_stock_info`。
- **主要输入**：阻力位、收盘位置、5 日均量、当前/当日成交量、乖离、板块和新闻催化。
- **逻辑**：价格突破明确阻力，成交量通常达到 5 日均量 2 倍附近，收盘站稳且乖离不过高；板块共振提高可信度。
- **输出调整**：放量突破确认 `+12`；板块同步走强额外 `+5`；理想买点在突破位附近，参考止损在突破位下方约 3%。
- **失效/限制**：盘中触及但收盘回落、量比不足、没有可复核阻力、突破后乖离过高、新闻或基本面风险抵消。

### 4.4 `shrink_pullback` — 缩量回踩

- **适用状态**：`trending_up`, `sideways`。
- **必需工具**：`get_daily_history`, `analyze_trend`, `get_realtime_quote`, `search_stock_news`, `get_chip_distribution`。
- **主要输入**：多头排列、价格距 MA5/MA10/MA20、回调成交量、筹码成本区和新闻风险。
- **逻辑**：趋势仍向上，价格距 MA5 约 1%或距 MA10 约 2%，回调量通常低于 5 日均量 70%，且未破坏 MA20 趋势。
- **输出调整**：缩量回踩 MA5 `+10`；回踩 MA10 且量能低于 0.6 倍均量 `+8`；MA20 作为重要失效参考。
- **失效/限制**：放量下跌、跌破中期支撑、筹码上方压力明显、负面事件改变原趋势。

### 4.5 `event_driven` — 事件驱动

- **适用状态**：`sector_hot`, `volatile`。
- **必需工具**：`search_stock_news`, `get_realtime_quote`, `analyze_trend`。
- **主要输入**：事件类型、来源可信度、发布时间、兑现周期、影响路径、价格反应和趋势。
- **逻辑**：区分业绩、政策、并购、订单、产品、处罚、诉讼等；判断短期催化或长期基本面影响，以及价格是否已兑现。
- **输出调整**：高可信正向事件且未充分反映 `+14`；正向事件已大幅兑现 `-6`；负面事件仍发酵 `-15`；冲突或不清晰则中性并降置信度。
- **失效/限制**：只有搜索摘要无可靠原文、事件时间晚于分析截止点、传闻未确认、事件与公司缺少实质关系。

### 4.6 `box_oscillation` — 箱体震荡

- **适用状态**：`sideways`。
- **必需工具**：`get_daily_history`, `analyze_trend`, `get_realtime_quote`。
- **主要输入**：60–120 日高低点、支撑/阻力触碰次数、箱体宽度、量能与收盘确认。
- **逻辑**：顶部和底部各至少触碰 2–3 次；距支撑或阻力 5%内分别视作箱底/箱顶区域；连续两日收盘越界并放量才转为趋势策略。
- **输出调整**：箱底企稳缩量 `+10`；箱底放量攻顶 `+12`；向上有效突破 `+15`；箱顶区域 `-5`；箱底有效跌破 `-15`。
- **失效/限制**：箱体宽度小于 5%、边界只由单个极值决定、假突破、趋势已经单边化。

### 4.7 `growth_quality` — 成长质量

- **适用状态**：`trending_up`，但核心是中长期基本面。
- **必需工具**：`get_stock_info`, `get_realtime_quote`, `search_stock_news`, `analyze_trend`。
- **主要输入**：收入、归母利润、经营现金流、ROE、毛利率、估值、行业景气、趋势和财报可得日。
- **逻辑**：区分高质量成长、验证中、放缓和证伪；识别增长来自收入扩张、利润率、行业景气还是一次性因素。
- **输出调整**：收入、利润、现金流、ROE 同向改善 `+15`；行业和公司新闻互证额外 `+6`；高估值未验证 `-8`；增收不增利或现金流恶化 `-12`。
- **失效/限制**：跨期财务拼接、历史分析使用未来财报、只看 YoY 不看现金流、估值字段缺失却给出估值结论。

### 4.8 `bottom_volume` — 底部放量

- **适用状态**：`trending_down`。
- **必需工具**：`get_daily_history`, `analyze_trend`, `get_realtime_quote`, `search_stock_news`, `get_chip_distribution`。
- **主要输入**：20 日高低点跌幅、量比、阳阴线、近期低点、筹码和催化。
- **逻辑**：先确认经历明显下跌（策略规则参考 20 日高点至低点跌幅超过约 15%），再检查量比约大于 3、收阳并守住近期低点。
- **输出调整**：底部放量确认 `+8`；阳线且有新闻催化额外 `+5`；止损参考近期低点。
- **失效/限制**：下降趋势中继、放量长阴、跌破近期低点、所谓底部没有足够历史窗口。

### 4.9 `expectation_repricing` — 预期重估

- **适用状态**：`volatile`, `sector_hot`。
- **必需工具**：`search_stock_news`, `get_stock_info`, `get_realtime_quote`, `analyze_trend`。
- **主要输入**：财报/政策/行业/竞争信息、估值、市场原预期、价格和量能确认。
- **逻辑**：区分正向预期差、预期兑现、负向预期差和预期不明；硬信息与软信息分层，明确待验证节点。
- **输出调整**：正向预期差未充分反映 `+15`；连续大涨已兑现 `-5`；负向预期差或核心假设证伪 `-15`；信息不足时中性并降置信度。
- **失效/限制**：无法说明“原预期”基线、用价格上涨反推基本面、将传闻当作硬信息。

### 4.10 `chan_theory` — 缠论

- **适用状态**：`volatile`。
- **必需工具**：`get_daily_history`, `analyze_trend`, `get_realtime_quote`。
- **主要输入**：至少约 60 日日线、高低点序列、MACD、支撑阻力。
- **逻辑**：识别分型、笔、线段、中枢、趋势、背驰和一二三买卖点；价格创新低/高与 MACD 柱面积背离是关键证据。
- **输出调整**：底背驰加一买 `+15`；二买/三买共振 `+10`；中枢震荡维持基准；顶背驰或趋势向下 `-15`。
- **失效/限制**：结构划分有主观性；不能从简单均线自动声称完整缠论结构；级别或波段划分不清时必须降置信度。

### 4.11 `wave_theory` — 波浪理论

- **适用状态**：`volatile`。
- **必需工具**：`get_daily_history`, `analyze_trend`, `get_realtime_quote`。
- **主要输入**：波段高低点、量能、MACD、Fib 0.382/0.618/1.618 位置。
- **逻辑**：尝试识别 1–5 推动浪与 A–C 调整浪；第 3 浪不能最短，第 4 浪原则上不得侵入第 1 浪价格区；规则被破坏须重新计数。
- **输出调整**：第 2 浪底部企稳 `+15`；第 3 浪突破 `+12`；第 5 浪末端/顶背离 `-10`；C 浪下跌中 `-12`。
- **失效/限制**：波浪计数高度主观，必须给高/中/低置信度和备选计数；不能把 Fib 目标写成确定价格事实。

### 4.12 `dragon_head` — 龙头策略

- **适用状态**：`sector_hot`。
- **必需工具**：`get_realtime_quote`, `get_sector_rankings`, `search_stock_news`, `get_stock_info`, `analyze_trend`。
- **主要输入**：板块排名、个股相对板块强度、换手率、量比、实质题材关系和催化。
- **逻辑**：板块处于主动轮动，个股领涨且实质受益；规则参考换手率大于约 5%、量比大于约 1.5、个股跑赢板块约 2%。
- **输出调整**：确认龙头 `+10`；板块主动轮动额外 `+5`。
- **失效/限制**：只按涨幅称为龙头、板块已退潮、蹭概念、过高换手对应出货而非接力。

### 4.13 `emotion_cycle` — 情绪周期

- **适用状态**：`sector_hot`。
- **必需工具**：`get_daily_history`, `get_realtime_quote`, `analyze_trend`, `search_stock_news`。
- **主要输入**：换手率、成交量变化、均线收缩、波动率、新闻和社区情绪。
- **逻辑**：识别冷淡底部、平稳、升温、过热和狂热顶部；换手率低于约 0.5%偏冷淡，2%–5%偏活跃，高于 5%偏热，高于 10%需警惕极热，并结合相对历史而非单阈值判断。
- **输出调整**：底部特征满足 3 项以上 `+14`、全部 5 项 `+20`；顶部特征 3 项以上 `-12`、全部 5 项 `-20`；平稳不调整。
- **失效/限制**：缺少历史换手基线、把搜索摘要当全市场情绪样本、忽视制度和市值导致的换手差异。

### 4.14 `hot_theme` — 热点题材

- **适用状态**：`sector_hot`。
- **必需工具**：`get_sector_rankings`, `search_stock_news`, `get_realtime_quote`, `analyze_trend`。
- **主要输入**：政策/产业热点、板块强度、个股与题材实质关系、相对强弱、量能和热点阶段。
- **逻辑**：把热点分为启动、扩散、分化、退潮；只有实质受益且强于板块时才增强信号。
- **输出调整**：启动/扩散且实质受益 `+12`；强于板块且量能确认额外 `+6`；分化/退潮 `-8`；蹭概念且高乖离 `-12`。
- **失效/限制**：题材来源不可靠、个股关联仅名称匹配、用单日板块涨幅判断完整阶段。

### 4.15 `one_yang_three_yin` — 一阳夹三阴

- **适用状态**：形态策略。
- **必需工具**：`get_daily_history`, `analyze_trend`。
- **主要输入**：最近 5 根完整日 K、成交量、第一日开盘、第五日突破、上级趋势。
- **逻辑**：第一日大阳，随后三根缩量小阴且不破第一日开盘，第五日阳线突破整理区；必须用完整 OHLCV 验证每根 K 线。
- **输出调整**：形态成立且趋势看多 `+15`；形态成立但趋势不明 `+5`；参考止损在第一日开盘下方。
- **失效/限制**：任一阴线破位、三日未缩量、第五日未突破、使用盘中未收盘 K 线冒充确认。

## 5. 多策略组合逻辑

现有 specialist 流程：

```text
Technical
-> Intel
-> Risk
-> 并发 SkillAgent
-> StrategyEngine 分区/聚合
-> DecisionAgent
-> 风险 override
-> dashboard / strategy_synthesis / strategy_data_evidence
```

模式：

| 模式 | 角色链 |
| --- | --- |
| `quick` | technical → decision |
| `standard` | technical → intel → decision |
| `full` | technical → intel → risk → decision |
| `specialist` | technical → intel → risk → skill agents → decision |

组合时应保留：

- 每个策略独立的 evidence status；
- 满足与未满足条件；
- 同一证据被多个策略重复使用的关系；
- 趋势、反转、事件和基本面策略之间的冲突；
- `insufficient` 策略为何没有进入投票；
- 聚合意见不覆盖逐策略原始意见。

## 6. 股票筛选：候选生成工具

AlphaSift 是独立外部适配层，主要入口为 `src/services/alphasift_service.py` 和 `api/v1/endpoints/alphasift.py`。

### 6.1 输入

```json
{
  "market": "cn",
  "strategy": "dual_low",
  "max_results": 20
}
```

这里的 AlphaSift `strategy` 是候选筛选规则 ID，不保证与本仓库 `strategies/*.yaml` 的 Strategy Tool ID 相同。两层同名时也必须用 `screener_strategy_id` 和 `analysis_strategy_id` 分开保存。

稳定 adapter 能力：

```python
get_status()
list_strategies()
screen(strategy, market="cn", max_results=20, use_llm=True, context=None)
```

### 6.2 输出

顶层主要字段：

```text
run_id, strategy, market
snapshot_count, snapshot_source, after_filter_count
llm_ranked, llm_market_view, llm_selection_logic
llm_portfolio_risk, llm_coverage, llm_parse_errors
warnings, source_errors
candidates, candidate_count
dsa_enrichment
post_analyzers, daily_enriched, daily_enrich_count
risk_enabled, portfolio_diversity_enabled
portfolio_concentration_notes
```

候选字段：

```text
code, name, score, reason, risk_level, risk_flags
price, change_pct, amount, industry, factor_scores
llm_score, llm_confidence, llm_thesis
llm_catalysts, llm_risks, llm_watch_items
dsa_context
```

### 6.3 工作流定位

```text
候选生成
-> 股票身份与市场标准化
-> 为每个候选构建 AgentContextPack
-> 策略组合评分
-> Trader 决策
```

候选排名不是 Buy 信号。筛选快照、日线和后续策略分析若处于不同截止时点，必须先升级到同一 context revision。

## 7. AI 问股：面向用户的协调入口

当前入口包括 `bot/commands/ask.py`、`src/agent/chat_executor.py`、`src/agent/executor.py` 和 `src/agent/chat_context.py`。

输入上下文可指定：

```json
{
  "stock_code": "...",
  "skills": ["..."],
  "strategies": ["..."]
}
```

`/ask` 支持单股和最多 5 股对比，可解析策略 ID、显示名和 alias。当前流程：

```text
股票身份/歧义解析
-> system prompt + 会话历史 + stock_scope + skill instructions
-> Agent backend 工具循环
-> 自由文本或 dashboard
-> 保存会话及 provider trace
```

有股票歧义时应返回候选，不允许模型猜市场。目标 Codex 流程把 Ask 定义为 orchestrator，而不是另一名 Trader：

```text
Ask
-> Context Builder
-> Strategy Tool(s)
-> Trader Role
-> Challenge / Follow-up
```

## 8. 当前交易员决策过程

交易员分析位于 `src/trader_analysis/`，当前与策略分析隔离。现有 TradingAgents 角色链：

```text
Market Analyst + Sentiment Analyst + News Analyst + Fundamentals Analyst
-> Bull Researcher / Bear Researcher
-> Research Manager
-> Trader
-> Aggressive / Conservative / Neutral Risk Analysts
-> Portfolio Manager
-> Final Decision
```

核心 state：

```text
market_report, sentiment_report, news_report, fundamentals_report
investment_debate_state, investment_plan
trader_investment_plan, risk_debate_state
final_trade_decision, past_context
```

### 8.1 预检输入和质量门

预检证据：

```text
market_daily_bars
verified_market_snapshot
fundamentals
news
sentiment
```

质量状态：

| 状态 | 含义 |
| --- | --- |
| `complete` | 核心证据和足够 optional 能力可用，无 warning |
| `degraded` | 核心证据可用，但 optional 缺失或有 warning；可受约束继续 |
| `insufficient_evidence` | 日线/快照等核心证据不足；不得启动正常完整决策 |

### 8.2 各研究和风险角色的输入—逻辑—输出

| 角色 | 输入 | 决策/分析逻辑 | 输出与失败边界 |
| --- | --- | --- | --- |
| Market Analyst | instrument context、trade_date、日线、指标、快照 | 分析趋势、动量、波动、量价、支撑阻力 | `market_report`；历史不足须降置信度，不得补造指标 |
| Sentiment Analyst | 国内新闻、近 7 日社区预取 bundle、instrument context | 区分来源、样本量、内容时间和情绪方向 | structured `SentimentReport` 渲染为 `sentiment_report`；来源稀疏/无日期时低置信度，不得虚构社区统计 |
| News Analyst | instrument context、个股新闻和全市场/宏观工具 | 区分公司事件、行业影响、宏观背景和发布时间 | `news_report`；宏观不可用时披露，不能用个股新闻冒充宏观 |
| Fundamentals Analyst | instrument context、point-in-time 财务工具 | 按报告期、公告日、文档类型分析估值、成长和财务质量 | `fundamentals_report`；缺字段返回 unavailable，不得跨期计算 |
| Bull Researcher | 四类报告、debate state、past context | 构建最强多头论证，同时只能使用已有报告证据 | 更新 `bull_history/history/current_response/count` |
| Bear Researcher | 四类报告、debate state、past context | 构建最强空头/风险论证，同时只能使用已有报告证据 | 更新 `bear_history/history/current_response/count` |
| Research Manager | 完整多空辩论历史 | 裁决多空证据并形成可交给 Trader 的战略行动 | `ResearchPlan` → `investment_plan` |
| Trader | 四类报告、investment plan、past context、核验价格/近 5 日低点/200 日 SMA | 把研究计划转为行动、价格条件和仓位建议 | `TraderProposal` → `trader_investment_plan`；价格方向须确定性校验 |
| Aggressive Risk | Trader plan、四类报告、risk state | 强调上行机会和可承受风险的进攻方案 | aggressive response/history/count；不直接成为最终决策 |
| Conservative Risk | 同上 | 强调下行情景、失效条件和资本保护 | conservative response/history/count；不直接成为最终决策 |
| Neutral Risk | 同上 | 平衡收益、回撤和证据不确定性 | neutral response/history/count；不直接成为最终决策 |
| Portfolio Manager | Trader plan、完整 risk debate、past context | 综合三类风险观点作最终 rating、期限和目标裁决 | `PortfolioDecision` → `final_trade_decision` |

`ResearchPlan` 的当前结构化核心字段为：

```text
recommendation: Buy|Overweight|Hold|Underweight|Sell
rationale: string
strategic_actions: 交给 Trader 的可执行动作
```

这条链路的关键价值是让事实分析、多空研究、行动提案和组合裁决分层。目标 Strategy-to-Trader Adapter 只在相应节点注入策略意见，不应绕过这些层级。

### 8.3 Trader 输入、逻辑、输出

**输入**：四类分析报告、Research Manager 的 `investment_plan`、`past_context`，以及已核验当前价、近 5 日低点、200 日 SMA 等确定性证据。

**逻辑**：把研究计划转换为可执行行动，确保方向、价格和止损语义一致。A 股不支持裸卖空，因此 `Sell` 表示减仓或退出已有多头。

**当前 `TraderProposal` 输出**：

```text
action: Buy|Hold|Sell
reasoning: string
entry_price: number|null
stop_loss: number|null
position_sizing: string|null
```

结构化 `stop_loss` 必须低于已核验当前价；上方 EMA、阻力或重新入场位不能伪装成止损。

### 8.4 Portfolio Manager 输入、逻辑、输出

**输入**：Trader plan、完整风险辩论、past context 和数据质量。

**逻辑**：综合激进、保守和中性风险观点，对行动、仓位、期限和目标作最终裁决。

**当前 `PortfolioDecision` 输出**：

```text
rating: Buy|Overweight|Hold|Underweight|Sell
executive_summary: string
investment_thesis: string
price_target: number|null
time_horizon: string|null
```

报告模块：

```text
market, sentiment, news, fundamentals
bull_researcher, bear_researcher, research_decision
trader_plan
aggressive_analyst, conservative_analyst, neutral_analyst
portfolio_manager, final_decision
data_evidence, data_quality
```

## 9. 目标 Strategy-to-Trader Adapter

后续实现不应让 Trader 只读四类报告，也不应让策略综合直接越权成为最终决策。Adapter 输入：

```json
{
  "context_id": "ctx_xxx_r1",
  "strategy_results": [],
  "strategy_synthesis": {},
  "market_report": "...",
  "sentiment_report": "...",
  "news_report": "...",
  "fundamentals_report": "...",
  "investment_plan": "...",
  "portfolio_constraints": {},
  "trader_profile": {}
}
```

目标 Trader 输出在现有字段上增加：

```json
{
  "action": "Buy|Hold|Sell",
  "reasoning": "...",
  "entry_price": null,
  "stop_loss": null,
  "position_sizing": null,
  "adopted_strategies": [
    {"strategy_id": "bull_trend", "weight": 0.6, "reason": "..."}
  ],
  "rejected_strategies": [
    {"strategy_id": "volume_breakout", "reason": "量能条件未满足"}
  ],
  "strategy_conflicts": [],
  "execution_plan": [],
  "invalidation_conditions": [],
  "position_plan": {},
  "evidence_refs": []
}
```

约束：

1. Trader 可以采纳、降权或拒绝策略，但必须说明理由。
2. `insufficient` 策略不得被采纳为正向依据。
3. 多个策略引用同一证据时，不能把它误算为多份独立证据。
4. 策略冲突必须保留到风险辩论，不能在综合摘要中静默消失。
5. 仓位来自 Trader profile、Portfolio constraints 和风险裁决，不来自单个策略 YAML 的示例仓位。
6. Trader 的 action 不自动触发交易。

## 10. 用户策略发布契约

用户可以新增自己的技术或市场策略，但发布物应包含：

```text
strategy_id / version / author
supported_markets / timeframe / adjustment
required_tools / required_fields
deterministic_rules
llm_judgement_rules
signal_mapping / score_adjustments
invalidation_conditions
quality_degradation_rules
examples: positive / negative / boundary
backtest_status / backtest_summary
```

推荐把确定性指标计算放在工具函数中，把解释性判断放在策略 instructions 中。例如“MA5 上穿 MA10”应由数据函数计算交叉事实；“这次交叉是否得到事件和板块共振”可由 Strategy Tool Agent 解释。

策略升级必须改变 `strategy_version`。历史报告和 challenge 继续引用原版本，避免新规则重新解释旧输出却没有审计记录。

## 11. 源码锚点

| 能力 | 主要源码/文档 |
| --- | --- |
| 策略定义 | `strategies/*.yaml` |
| 策略装载 | `src/agent/skills/base.py` |
| 策略 Agent | `src/agent/skills/skill_agent.py` |
| 策略聚合 | `src/agent/skills/engine.py`, `aggregator.py`, `synthesis.py` |
| 多 Agent 编排 | `src/agent/orchestrator.py` |
| 策略工具 | `src/agent/tools/` |
| AlphaSift | `src/services/alphasift_service.py` |
| AI 问股 | `bot/commands/ask.py`, `src/agent/chat_executor.py` |
| 交易员分析 | `src/trader_analysis/` |
| 交易员完整契约 | [交易员重建契约](../trader-analysis-contract.md) |
