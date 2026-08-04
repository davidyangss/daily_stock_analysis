# Codex 工作流数据源与标准数据契约

> 文档状态：现有实现总结，并给出供 Codex SubAgent 使用的目标封装。字段以仓库标准化输出为准，不承诺每个 provider 都能返回全部字段。

## 1. 契约范围

本项目的数据分为三层：

1. **原始 provider**：第三方 SDK、HTTP API、搜索引擎、RSS/Atom 或 NewsNow。
2. **标准化/适配层**：统一股票代码、列名、类型、来源、时点和质量。
3. **Agent 上下文层**：把同一次分析所需的数据组织成可引用、可裁剪、可审计的 context pack。

SubAgent 不应直接依赖 provider 私有字段。provider 增删或 fallback 顺序变化时，标准字段和质量语义应保持稳定。

## 2. 所有数据共同的元数据

建议进入 Codex 上下文的每个 evidence item 至少包含：

| 字段 | 含义 |
| --- | --- |
| `evidence_id` | 当前 context revision 内稳定且唯一的引用 ID |
| `data_type` | `quote`、`daily_bar`、`news`、`fundamental` 等标准类型 |
| `subject` | 股票、指数、板块、市场或全局主题 |
| `source` | 实际产出该项数据的 provider/publisher |
| `source_chain` | 尝试过的来源及 fallback 顺序 |
| `observed_at` | 数据本身对应的交易日、发布时间或报告期 |
| `available_at` | 该信息对分析者可得的时间 |
| `fetched_at` | 系统抓取时间 |
| `as_of` | 本次分析允许使用数据的截止时间 |
| `quality` | `available`、`fallback`、`stale`、`partial` 等状态 |
| `adjustment` | 日线复权口径；不适用时省略 |
| `currency` / `unit` | 币种和数量单位，适用时必须保留 |

时间字段不能互相替代：财报的 `report_date` 是报告期，`announcement_date/available_at` 才决定历史时点能否使用；新闻的发布时间也不能用采集时间代替。

## 3. DataProvider 能力矩阵

底层管理入口为 `data_provider/base.py` 中的 `BaseFetcher` 和 `DataFetcherManager`。下表总结标准能力，不代表单个来源在所有时点、市场和网络环境下均可用。

| Provider / adapter | 市场 | 日线 | 实时 | 名称/列表 | 指数/宽度/板块 | 基本面/资金/其他 |
| --- | --- | --- | --- | --- | --- | --- |
| AkShare | A、H | 是 | A/H/ETF | 部分 | 指数、宽度、行业、概念、人气、涨停池 | 基本面、资金、龙虎榜、筹码适配来源 |
| Efinance | A、ETF | 是 | 是 | 基础信息 | 指数、宽度、行业 | 基础信息、板块归属 |
| Tushare | A、H | 是 | A | 名称、列表 | 指数、宽度、行业 | 基本面、筹码 |
| TickFlow | A | 是 | 是 | 名称、股票池 | 指数、宽度、申万一级行业 | — |
| PyTDX | A | 是 | 是 | 名称 | — | — |
| BaoStock | A | 是 | — | 名称、列表 | — | — |
| Tencent | A | 日线兜底 | — | — | — | — |
| YFinance | A、H、美、日、韩、台 | 是 | 是 | 部分 | 海外指数 | 港美日台韩基本面、分红、行业归属 |
| Longbridge | H、美 | 是 | 是 | 名称 | — | — |
| Finnhub | 美 | 是 | 是 | 名称 | — | — |
| AlphaVantage | 美 | 是 | 是 | 名称 | — | — |
| iWencai adapter | A | — | 是 | 名称 | — | 主力资金、基本面 |
| EastMoney MX adapter | A | — | 是 | — | — | 主力资金 |
| TW official institutional fetcher | 台 | — | — | — | — | 三大法人净买卖 |

`DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT` 当前日线市场映射为：

| Provider | `cn` | `hk` | `us` | `jp` | `kr` | `tw` |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| Efinance | ✓ |  |  |  |  |  |
| Tencent | ✓ |  |  |  |  |  |
| AkShare | ✓ | ✓ |  |  |  |  |
| Tushare | ✓ | ✓ |  |  |  |  |
| TickFlow | ✓ |  |  |  |  |  |
| PyTDX | ✓ |  |  |  |  |  |
| BaoStock | ✓ |  |  |  |  |  |
| YFinance | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Longbridge |  | ✓ | ✓ |  |  |  |
| Finnhub |  |  | ✓ |  |  |  |
| AlphaVantage |  |  | ✓ |  |  |  |

配置 token 或 provider 名称出现，只说明来源可被尝试，不等于每项能力都有结构化实现。实际优先级、禁用、超时与 fallback 规则见 [数据源优先级](../data-source-priority.md) 和 [数据源稳定性](../data-source-stability.md)。

## 4. 标准市场数据类型与字段

### 4.1 股票身份与股票列表

- `DataFetcherManager.get_stock_name(stock_code, allow_realtime=True)` 聚合各来源名称查询，标准结果是 `str | None`。
- 多个 fetcher 还实现 `get_stock_list()`，但当前返回的是 provider-specific `DataFrame`，尚无跨来源统一列契约；它适合内部名称索引和股票池构建，不应原样成为 SubAgent 输入。
- 进入 Agent 上下文时，身份应统一为 `code`, `stock_name`, `market`；如需扩展可增加 `exchange`, `asset_type`，但必须由解析器明确给出，不能让模型从代码猜市场。

股票名称和代码可能跨市场重名或歧义。身份解析失败时应返回候选列表，不应继续抓取一个猜测的标的。

### 4.2 历史日线 `daily_bars`

标准行字段：

| 字段 | 含义 |
| --- | --- |
| `date` | 交易日 |
| `open` | 开盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `close` | 收盘价 |
| `volume` | 成交量；单位必须由来源或适配层说明 |
| `amount` | 成交额；来源不支持时可缺失 |
| `pct_chg` | 当日涨跌幅，百分数口径 |

`BaseFetcher.get_daily_data()` 还会派生：

| 字段 | 逻辑 |
| --- | --- |
| `ma5` | 5 个交易日收盘价均线 |
| `ma10` | 10 个交易日收盘价均线 |
| `ma20` | 20 个交易日收盘价均线 |
| `volume_ratio` | 当日成交量 / 前 5 日平均成交量 |

这里的 `volume_ratio` 是日线派生量比，不是严格的盘中分时量比。

日线序列还必须携带序列级元数据：

```text
code, market, source, requested_days, actual_records
start_date, end_date, adjustment, currency, unit
cache_hit, partial_cache, quality, source_chain
```

关键约束：

- 一段 OHLCV 序列必须以 provider 为单位原子 fallback，禁止把不同来源的 open/high/low/close 拼成一根 K 线。
- 复权口径可能为 `qfq`、`auto_adjust`、`none` 或 `unknown`，必须随证据传递。
- 历史不足可标为 `partial`，但不能把较短窗口伪装成完整窗口。
- 今日未收盘数据与历史收盘 K 线应区分。

### 4.3 实时行情 `quote`

`data_provider/realtime_types.py` 的 `UnifiedRealtimeQuote` 字段分组如下：

| 分组 | 字段 |
| --- | --- |
| 身份与来源 | `code`, `name`, `source`, `market`, `currency` |
| 时点与质量 | `fetched_at`, `provider_timestamp`, `is_stale`, `stale_seconds`, `fallback_from`, `data_quality`, `missing_fields` |
| 当前价格 | `price`, `change_pct`, `change_amount` |
| 量价活跃度 | `volume`, `amount`, `volume_ratio`, `turnover_rate`, `amplitude` |
| 当日 OHLC | `open_price`, `high`, `low`, `pre_close` |
| 估值与市值 | `pe_ratio`, `pb_ratio`, `total_mv`, `circ_mv` |
| 中长期参考 | `change_60d`, `high_52w`, `low_52w` |

实时来源可以只返回子集；`missing_fields` 和 `data_quality` 是契约的一部分。实时对象的 `data_quality` 当前取 `ok/partial/unavailable`，进入 `AnalysisContextPack` 后再映射到 context 质量枚举。`provider_timestamp` 缺失时不能假设 `fetched_at` 就是交易所行情时间。

### 4.4 筹码分布 `chip`

`ChipDistribution` 标准字段：

```text
code, date, source
profit_ratio, avg_cost
cost_90_low, cost_90_high, concentration_90
cost_70_low, cost_70_high, concentration_70
```

筹码不是所有市场和来源都支持。缺失应标为 `not_supported` 或 `missing`，不能用均线或成交密集区静默替代。

当前 `ChipDistribution` dataclass 具备全部上述字段，但其 `to_dict()` 没有序列化 `cost_70_low/cost_70_high`；`get_chip_distribution` Agent 工具会显式补回这两个字段。直接消费 dataclass 序列化结果的后续实现必须注意这一现状差异。

### 4.5 主要指数 `market_indices`

标准字段：

```text
code, name, current, change, change_pct, volume, amount
```

部分实现还会提供：

```text
open, high, low, prev_close, amplitude
```

### 4.6 市场宽度 `market_breadth`

```text
up_count, down_count, flat_count
limit_up_count, limit_down_count
total_amount
```

计数范围必须与来源的市场股票池一致；不同来源的宽度不应在没有口径说明时直接比较。

### 4.7 行业、概念与资金排名

行业/概念强弱项：

```text
name, change_pct
```

资金排名项：

```text
name, net_inflow
```

排序结果应附 `source`、`as_of`、市场、榜单方向和数量单位。`top` 与 `bottom` 应作为不同列表保存。

### 4.8 人气股 `popular_stocks`

```text
rank, code, name, price, change_pct, source
```

人气排名反映来源平台的热度口径，不等同于资金净流入、市场全样本排名或推荐。

### 4.9 涨停池 `limit_up_pool`

```text
code, name, change_pct, price, amount, turnover_rate
seal_amount, first_limit_time, last_limit_time
break_count, limit_stat, consecutive_boards, industry
```

涨跌停制度与字段语义具有市场特异性，当前主要面向 A 股，不能直接推广到港美市场。

## 5. 标准基本面与资金数据

基本面聚合结果顶层 envelope：

```text
market, status, coverage, source_chain, errors, elapsed_ms
valuation, growth, earnings, institution
capital_flow, dragon_tiger, boards
```

每个 block 使用统一形式：

```json
{
  "status": "ok|partial|failed|not_supported",
  "coverage": {"status": "..."},
  "source_chain": [],
  "errors": [],
  "data": {}
}
```

### 5.1 估值 `valuation.data`

```text
pe_ratio, pb_ratio, total_mv, circ_mv
```

估值必须对应明确时点；历史分析不能使用当前估值冒充历史估值。

### 5.2 成长质量 `growth.data`

```text
revenue_yoy, net_profit_yoy, roe, gross_margin
```

字段需保留报告期和来源。不同报告期的数据不得拼成同一组“最新财务指标”。

### 5.3 财务报告 `earnings.data.financial_report`

通用字段：

```text
report_date, announcement_date, available_at
report_type, document_type, currency
revenue, net_profit_parent, operating_cash_flow, roe
```

Tushare 等来源还可提供：

```text
total_assets, total_liabilities, equity_parent
```

多来源合并时用于追踪字段血缘：

```text
field_periods, field_report_types
field_announcement_dates, field_sources
period_consistency
```

不同报告期或不同文档类型的数据进入：

```text
earnings.data.supplemental_financial_reports[]
```

不得为了补空值把业绩预告、快报、季度报告和年度报告跨期拼接。

### 5.4 分红 `earnings.data.dividend`

```text
events[], ttm_event_count, ttm_cash_dividend_per_share
ttm_dividend_yield_pct, coverage, currency, as_of
```

### 5.5 机构持仓 `institution.data`

通用字段：

```text
institution_holding_change, top10_holder_change
```

台股三大法人字段：

```text
foreign_net, trust_net, dealer_net, total_net
unit, date, source
```

### 5.6 个股和板块资金 `capital_flow.data`

个股资金：

```text
stock_flow.main_net_inflow
stock_flow.inflow_5d
stock_flow.inflow_10d
```

板块资金排名：

```text
sector_rankings.top[]
sector_rankings.bottom[]
```

资金字段的算法和单位依赖来源，必须保留来源，不应把不同 provider 的“主力资金”视为同一精确定义。

### 5.7 龙虎榜 `dragon_tiger.data`

```text
is_on_list, recent_count, latest_date
```

### 5.8 板块 `boards`

强弱排名：

```text
boards.data.top[]
boards.data.bottom[]
```

个股所属板块：

```text
belong_boards[].name
belong_boards[].code   # 可选
belong_boards[].type   # 可选
```

## 6. NewsProvider 与资讯字段

项目存在两类情报层，它们用途不同。

### 6.1 按需搜索

`src/search_service.py` 中 `SearchResult`：

```text
title, snippet, url, source, published_date
relevance_score, relevance_category, relevance_reasons
```

`SearchResponse`：

```text
query, results[], provider, success
error_message, search_time
```

当前搜索 provider 顺序：

1. Anspire（配置后插入队首）
2. Bocha
3. Tavily
4. Brave
5. SerpAPI
6. MiniMax
7. SearXNG

标准搜索能力：

```text
search_stock_news
search_stock_events
search_community_sentiment
search_comprehensive_intel
```

综合情报维度：

```text
latest_news, announcements, market_analysis
risk_check, earnings, industry
```

`provider` 是检索服务，`source` 通常是内容发布者或结果来源，两者不可混写。`snippet` 是搜索摘要，不等于已经读取原文。

### 6.2 本地资讯池

`src/services/intelligence_service.py` 支持 `rss`、`atom` 和 `newsnow`，按以下 scope 组织：

```text
scope_type: symbol|market|sector
market: cn|hk|us|jp|kr|tw|global
```

资讯条目字段：

```text
id, source_id, source_name, source_type
title, summary, url, source
published_at, fetched_at
scope_type, scope_value, market
```

NewsNow 内置源：

```text
cls-hot, xueqiu-hotstock, wallstreetcn-quick, jin10, gelonghui
```

本地资讯池用于持续抓取、去重和按 scope 查询；按需搜索用于围绕当前股票或问题检索。Codex 可以在一个上下文中同时使用两者，但必须保留来源类型和抓取方式。

## 7. 现有 `AnalysisContextPack`

`src/schemas/analysis_context_pack.py` 定义的核心结构：

```text
subject: code, stock_name, market
pack_version: "1.0"
phase
blocks
data_quality
metadata
created_at
```

固定核心 blocks：

```text
quote, daily_bars, technical, news, fundamentals, chip
```

可选辅助 block：

```text
portfolio
```

质量状态：

```text
available, missing, not_supported, fallback
stale, estimated, partial, fetch_failed
```

当前质量评分权重：

| Block | 权重 |
| --- | ---: |
| quote | 25 |
| daily_bars | 25 |
| technical | 25 |
| news | 10 |
| fundamentals | 10 |
| chip | 5 |

这是可复用的内部底座；当前公共面只暴露低敏 overview，不能假设公共 API 已返回完整 pack。

## 8. 目标 `AgentContextPack`

Codex 工作流建议在现有语义上增加版本、证据注册表、策略和报告关联：

```json
{
  "context_id": "ctx_600519_20260804_r1",
  "revision": 1,
  "subject": {"code": "600519", "name": "贵州茅台", "market": "cn"},
  "as_of": "2026-08-04T15:00:00+08:00",
  "data_cutoff": "2026-08-04T15:00:00+08:00",
  "pack_version": "1.0",
  "blocks": {
    "quote": {},
    "daily_bars": {},
    "technical": {},
    "news": {},
    "fundamentals": {},
    "chip": {},
    "portfolio": {}
  },
  "data_quality": {},
  "evidence_registry": {},
  "selected_strategies": [],
  "strategy_results": [],
  "trader_profile": {},
  "portfolio_constraints": {},
  "report_sections": []
}
```

### 8.1 Evidence ID 约定

建议使用稳定前缀：

```text
quote.current
bars.daily.2026-08-04
technical.ma.2026-08-04
technical.volume.2026-08-04
fundamental.annual.2025
news.<content-hash>
sector.rank.2026-08-04
strategy.volume_breakout.result
```

ID 在同一 context revision 内不可改变。新抓取数据产生 `revision + 1`；旧报告继续绑定旧 revision。

### 8.2 Context slice

主 Agent 不必把完整 pack 复制给每个 SubAgent。例如：

- 均线策略：`daily_bars + technical + quote`；
- 事件驱动：`news + quote + technical`；
- 成长质量：`fundamentals + news + quote + technical`；
- 风险角色：策略结果、Trader plan、质量摘要和关键原始证据；
- 报告编辑：裁决结果和已经接受的 evidence refs，不需要 provider 原始响应。

## 9. Fallback、质量与时点硬规则

1. 高优先级有效字段不被低优先级来源覆盖。
2. 日线序列按完整 provider 原子 fallback。
3. 财报只有报告期与文档类型一致时才可补缺。
4. 不同报告期进入 supplemental 列表，禁止跨期补值。
5. `report_date` 不等于 `announcement_date/available_at`。
6. 历史分析必须按当时可得日做 point-in-time 过滤。
7. `fallback/partial/estimated/stale` 必须传播给策略置信度和报告。
8. `missing/fetch_failed/not_supported` 不得由 LLM 自行补齐。
9. 搜索摘要、社区观点和新闻正文必须明确区分。
10. 币种、成交量单位、资金流算法不明时，不做跨来源绝对值比较。

## 10. 给 SubAgent 的最小数据摘要

不要只给一段自然语言。最小摘要应同时包含机器字段和可读说明：

```json
{
  "context_id": "ctx_xxx_r1",
  "as_of": "...",
  "subject": {"code": "...", "market": "..."},
  "required_blocks": ["daily_bars", "technical", "quote"],
  "quality_gate": "verified|limited|insufficient",
  "quality_issues": [],
  "evidence": [
    {
      "evidence_id": "technical.volume.2026-08-04",
      "value": {"volume_ratio_5d": 1.3},
      "source": "...",
      "observed_at": "...",
      "quality": "available"
    }
  ]
}
```

这样策略、交易员和挑战角色可以直接聚焦规则与证据，不必再次询问“量比是什么口径、数据来自哪里、是哪一天”。

## 11. 源码锚点

| 契约 | 主要源码/文档 |
| --- | --- |
| provider 管理与标准日线 | `data_provider/base.py` |
| 实时行情与筹码 | `data_provider/realtime_types.py` |
| 上下文 schema | `src/schemas/analysis_context_pack.py` |
| 上下文构建 | `src/services/analysis_context_builder.py` |
| 按需搜索 | `src/search_service.py` |
| 本地资讯池 | `src/services/intelligence_service.py` |
| 基本面聚合 | `data_provider/fundamental_adapter.py` 及各市场 provider adapters |
| 详细优先级 | [数据源优先级](../data-source-priority.md) |
| 稳定性与 fallback | [数据源稳定性](../data-source-stability.md) |

实现变动时以实际源码为准，并同步修订本契约，避免 SubAgent 继续依赖已经漂移的字段。
