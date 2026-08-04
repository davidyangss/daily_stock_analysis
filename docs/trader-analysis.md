# 交易员分析第一阶段

Web 端完整报告的模块标签栏在 PC 宽度下会随页面滚动吸顶，便于阅读长报告时切换角色报告。任务预检会先从本地股票名称缓存与索引解析 A 股名称；本地未命中且问财已启用并配置 API Key 时，再调用问财补全名称，确保后续报告使用明确的“股票代码 / 股票名称”。若两者都无法确认有效名称，任务会以 `instrument_name_unresolved` 在预检阶段结束，不生成身份不完整的报告。

基本面证据不再按“分析日期是否早于服务器当天”拦截，而是始终读取最近一期可用财报并展示报告期。报告期距分析日期不超过 365 天时，字段完整则为可用，字段缺失才为部分可用；超过 365 天时为不可用。若取得数据但上游未提供报告期，则按部分可用处理并明确提示报告期缺失。

交易员分析是独立于现有策略分析的实验性入口，面向 TradingAgents 风格的多角色分析链路。第一阶段默认关闭，并使用独立任务域、独立 API 和独立 Web 页面；不会读取、写入或比较现有策略分析结果，也不会写入 `analysis_history`。

## 配置

在 `.env` 中显式启用：

```env
TRADER_ANALYSIS_ENABLED=true
TRADER_ANALYSIS_MAX_CONCURRENCY=1
TRADER_ANALYSIS_QUEUE_LIMIT=8
TRADER_ANALYSIS_TASK_TIMEOUT_SECONDS=900
TRADER_ANALYSIS_PROVIDER_TIMEOUT_SECONDS=120
TRADER_ANALYSIS_RESULTS_DIR=data/trader_analysis
TRADER_ANALYSIS_CHECKPOINT_DB=data/trader_analysis/checkpoints.sqlite
TRADER_ANALYSIS_MIN_DAILY_BARS=30
TRADER_ANALYSIS_STALE_THRESHOLD_SECONDS=86400
TRADER_ANALYSIS_TRADINGAGENTS_VERSION=0.3.1
TRADER_ANALYSIS_TRADINGAGENTS_COMMIT=ab0909306075e413e2504deb85c9dc74b8650272
TRADER_ANALYSIS_LLM_PROVIDER=openai
TRADER_ANALYSIS_QUICK_MODEL=<与 provider 兼容的快速模型>
TRADER_ANALYSIS_DEEP_MODEL=<与 provider 兼容的深度模型>
TRADER_ANALYSIS_LLM_BACKEND_URL=<可选的兼容端点>
TRADER_ANALYSIS_MODEL_MARKET=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_SENTIMENT=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_NEWS=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_FUNDAMENTALS=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_RESEARCH_DEBATE=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_RESEARCH_MANAGER=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_TRADER=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_RISK_DEBATE=<LiteLLM deployment model_name，可选>
TRADER_ANALYSIS_MODEL_PORTFOLIO_MANAGER=<LiteLLM deployment model_name，可选>
LITELLM_FALLBACK_MODELS=<交易员角色共用的有序 fallback deployment，可选，逗号分隔>
TRADER_ANALYSIS_TRACE_CONTENT_MAX_CHARS=65536
TRADER_ANALYSIS_BROWSER_READER_ENABLED=false
TRADER_ANALYSIS_BROWSER_READER_COMMAND=agent-browser
TRADER_ANALYSIS_BROWSER_READER_MAX_PAGES=3
TRADER_ANALYSIS_BROWSER_READER_TIMEOUT_SECONDS=20
TRADER_ANALYSIS_BROWSER_READER_MAX_CHARS=12000
TRADER_ANALYSIS_BROWSER_READER_ALLOWED_DOMAINS=xueqiu.com,zhihu.com,weibo.com,sse.com.cn,szse.cn,cninfo.com.cn,cnstock.com,eastmoney.com,sina.com.cn
```

角色配置按 `model_name` 精确查找 DSA 已加载的 LiteLLM deployment，再使用其中的实际 `provider/model`、`api_base` 和凭据创建客户端。Market、Sentiment、News、Fundamentals、研究辩论、Research Manager、Trader、风险辩论和 Portfolio Manager 均可独立路由并允许跨 provider。留空角色继承 quick/deep 默认 deployment；deployment 不存在或不完整时任务返回 `configuration_error`，不会为配置错误静默换模型。凭据只进入内存客户端，不进入请求、报告、trace 或持久化元数据。

每个角色继续以显式角色模型或 quick/deep 继承模型作为 primary，并复用 DSA 已解析的 `LITELLM_FALLBACK_MODELS` 作为有序跨模型 fallback，不新增交易员专用配置。只有连接/超时、限流、临时 5xx、结构化 `service_unavailable`、上游流在终止事件前中断或上下文容量不足等可恢复错误才切换；参数、鉴权、权限和内容策略错误直接失败。工具调用、纯文本和 structured output 使用相同顺序，primary 与 fallback 重复时自动去重。每次实际切换写入 `llm.fallback` Trace，后续 `llm.started/completed/failed` 记录真实 deployment 和模型。fallback 列表的显式值、自动推导和清理规则继续沿用全局 LLM 配置语义；若需完全恢复本功能变更前的单角色单模型行为，应回退本次交易员 fallback 代码，而不是假设空值在所有配置模式下都表示禁用。

回滚方式：将 `TRADER_ANALYSIS_ENABLED=false` 后重启服务。该开关只拒绝新交易员分析运行，不影响现有股票分析、问股、选股、回测或历史记录。

完整工作流、每一阶段的输入输出、字段格式、时点规则、A 股技术口径和重建测试见 [TradingAgents A 股工作流与数据契约](trader-analysis-contract.md)。

## API

- `POST /api/v1/trader-analysis/runs`：创建单只 A 股交易员分析运行。
- `GET /api/v1/trader-analysis/runs?task_status=running&offset=0&limit=100`：按创建时间倒序查询持久化任务列表；`task_status` 可重复传入以筛选多个状态。
- `GET /api/v1/trader-analysis/runs/{run_id}`：查询状态、质量摘要、错误和报告。
- `GET /api/v1/trader-analysis/runs/{run_id}/events?after=0`：查询安全事件快照。
- `GET /api/v1/trader-analysis/runs/{run_id}/trace?after=0`：查询脱敏的分析过程时间线。
- `POST /api/v1/trader-analysis/runs/{run_id}/cancel`：幂等取消运行。

请求体示例：

```json
{
  "symbol": "600519",
  "trade_date": "2026-07-31"
}
```

第一阶段只接受沪深北普通 A 股六位代码及常见前后缀形式，例如 `600519`、`600519.SH`、`SH600519`、`000001.SZ`、`BJ920748`。港股、美股、ETF、指数、基金、可转债、B 股和交易所冲突代码会被拒绝为 `insufficient_evidence`，不会调用 LLM。

## TradingAgents 依赖

当前依赖锁定记录如下；分支用于说明补丁演进位置，部署和重建必须以不可变的完整 commit SHA 为准：

| 项目 | 固定值 |
| --- | --- |
| 官方上游 | `https://github.com/TauricResearch/TradingAgents.git` |
| DSA 实际依赖源 | `https://github.com/davidyangss/TradingAgents.git` |
| 兼容分支 | `feat/injectable-data-toolkit-role-llms` |
| 固定 commit | `ab0909306075e413e2504deb85c9dc74b8650272` |
| commit 标题 | `fix: support provider-neutral sentiment evidence` |
| Python distribution version | `0.3.1` |

可复现安装应直接引用完整 SHA：

```bash
pip install "git+https://github.com/davidyangss/TradingAgents.git@ab0909306075e413e2504deb85c9dc74b8650272"
```

本功能依赖带 `AgentDataToolkit` 和 `role_llms` 注入 seam 的 TradingAgents `0.3.1` 兼容构建。上游兼容补丁只增加可选注入点；未注入时仍使用原版工具、Graph 拓扑、Prompt、structured output、memory 和 checkpoint 行为。当前运行时严格检查 distribution version 和 seam，`TRADER_ANALYSIS_TRADINGAGENTS_COMMIT` 只进入审计 metadata，尚不能证明已安装代码的 Git commit。生产部署应发布带唯一 local version/capability metadata 的固定构建；禁止使用浮动 `main` 或 sibling 路径作为生产依赖，也不得把 metadata 值描述成已执行的 commit 校验。

服务启动环境未安装固定版本、版本不一致、缺少注入 seam 或未配置 quick/deep 模型时，任务会 fail-closed 返回 `configuration_error`，不会切换到海外默认数据工具或现有策略 pipeline。

## 数据与执行语义

- Market、News、Fundamentals Analyst 与对应 ToolNode 使用同一组 run-scoped DSA 工具对象。
- 日线、确定性指标、快照、新闻、情绪和财务均先进入 canonical evidence ledger；阻断问题不会作为正常工具文本进入 Graph。
- 交易员分析的 A 股日线优先选择 `qfq`/`auto_adjust` 连续价格来源，日线与技术指标工具通过 `adjustment` 字段向模型明确传递复权口径。只有复权来源不可用时才回退不复权日线；此时 canonical `pct_change` 一律按相邻收盘价重算，并保留 provider 原始涨跌幅供审计。若两者显著背离，系统标记疑似除权断点，所有指标只使用最后断点后的连续区间；连续历史不足时 200 日线明确不可用，不再把除权断点解释为长期空头压力。
- News 使用 DSA 新闻 provider/fallback 链；Sentiment 保留原版“新闻机构视角 + 快速零售观点 + 长文讨论”的多源逻辑，但数据改为国内新闻/公告以及 SearXNG 定向检索的雪球、知乎、微博观点。站点限定会在返回后再校验域名；无社区结果时独立降级，不用新闻伪装成社区观点。DSA 兼容构建通过可选 provider-neutral `sections` 读取真实国内标签和字段，并把外部证据放入独立 human evidence message；未注入 sections 时原版 Yahoo/StockTwits/Reddit 路径不变。
- 新闻和社区条目明确区分 `search_provider`、`publisher/source`、`source_domain`、`published_date` 与 `fetched_at`。工具按请求日期窗口过滤有日期条目，无日期条目只作为低置信度运行时证据保留。Sentiment 检索窗口固定为 7 天。
- 新闻分析和情绪分析的正式报告都会追加确定性证据表，逐条展示摘要、来源、内容时间、采集时间和原文链接；provider 未返回内容时间或链接时明确标记“未提供”，不自行推断。
- Sentiment 当前传给模型的社区证据是“标题 + 搜索摘要 + 来源 + 内容/采集时间 + URL”，不是网页完整正文。TradingAgents 0.3.1 的 Sentiment 节点没有浏览器或外部搜索工具；提示明确禁止模型声称已打开链接、自行联网或读取未提供的评论/正文，摘要截断、无日期或样本过少时必须降低置信度。
- 开启 `TRADER_ANALYSIS_BROWSER_READER_ENABLED` 后，News 和 Sentiment 会对各自搜索结果中最多 `MAX_PAGES` 条允许域名页面调用后端 `agent-browser read`，把受 `MAX_CHARS` 限制的公开正文摘录写入 canonical evidence。仅允许 HTTPS、配置白名单域名和公网 DNS 解析；不使用登录态、Cookie、点击、下载、JavaScript 执行或持久会话。浏览器超时、域名未允许或正文不可读时 fail-open 保留搜索摘要，报告的“证据类型”会区分“浏览器正文摘录”与“搜索摘要（正文不可用）”。
- 当分析日期为今天或最近已完成交易日时，新闻通过 DSA `SearchService` 的现有 provider/fallback 链按运行时间检索；最近交易日的运行时新闻标记为 `runtime_news_not_point_in_time` 并降级披露。最近交易日的基本面也明确标记为运行时聚合快照。更早历史日期的财务记录只有在 `announcement_date/available_at <= trade_date` 时才准入，并清除当前估值、资金、龙虎榜、机构和板块等运行时 blocks；缺公告可得日的数据不回填历史上下文。
- 问财无日期营收/利润会结合 `*来源说明` 识别报告期、公告日、业绩预告和区间中值口径；若同一响应混有正式报告字段，系统显式补查对应定期报告并把预告作为独立 supplemental report，禁止把 H1 预告与 Q1 现金流、毛利率跨期计算。前十大股东优先使用带报告期的直接人数统计；只有当前排名 1—10 完整时才允许从明细计数，截断明细不再输出部分人数或数量合计。
- 所有角色会收到已核验当前价、近 5 个交易日/当月最低价及其确定性反弹幅度、连续口径 200 日线、DIF 最近一次由非正转正日期和 A 股多头现货约束。涨跌幅必须标明起止日期、价格字段和端点，区间涨幅不得与区间最低价反弹幅度混写；资金流必须来自本次 canonical evidence 并保留来源/窗口语义。发布边界会纠正低点涨幅、DIF 穿越日期和价位比较关系，移除无证据资金流数值并将运行降级，原始模型输出仍保留在 Trace。Sell 表示减仓/退出，公开报告将其 `Entry Price` 展示为执行价格；若模型把不低于当前价的上方重评位写入 `Stop Loss`，发布边界会改列为重新评估价格并产生 `trader_stop_loss_reclassified` 警告。
- 新上市标的截至分析日已有至少 3 个有效交易日、但少于建议历史长度时，以 `limited_daily_history` 降级继续分析；报告必须明确短历史限制，不得把不成熟的技术指标解释成高置信度趋势。少于 3 个有效交易日仍阻断分析。
- 历史分析具备日线与核验价格且无阻断问题时，即使新闻、财务和情绪因 point-in-time 约束不可用，也会以 `degraded` 运行 Graph 并生成各角色报告；缺失能力必须保留在数据质量报告中，不得使用当前数据回填历史上下文。
- 运行、分角色报告、Debug 事件和脱敏后的 LLM/工具 trace 以 `run_id` 为外键持久化到 `TRADER_ANALYSIS_RESULTS_DIR/trader_analysis.sqlite3`；同时继续双写 `runs/<run_id>/` 下的 JSON 文件用于兼容回滚，升级时会把旧 JSON 任务懒迁移到 SQLite，不写入 `analysis_history`。
- 完成后的 Web 列表显示报告正文摘要，报告区以 Markdown 展示市场、情绪、新闻、基本面、多空研究、交易员、三类风险分析、组合经理、最终决策、投资建议、完整数据证据清单和数据质量。证据清单包含所有标准化日线/快照/基本面/新闻/社区 payload、provider、publisher、业务时点、采集时点和工具实际消费标记；数据质量的 API/Trace 保留英文稳定 code，Web 与 Markdown 报告展示中文名称和说明。正式角色报告采用中文主显示并为固定结构化术语保留英文对照，例如“评级（Rating）：低配（Underweight）”；MACD、RSI、PE、PB、ROE、ATR、VWMA、股票代码、数据源名和 URL 等必要缩写或专名保持原样。报告层会清理模型泄漏在首个中文标题之前的可识别英文分析草稿，并本地化上游固定英文交易建议，原始 LLM 响应仍完整保留在 Trace 中供审计。`GET /api/v1/trader-analysis/runs/{run_id}/download/markdown` 下载同一份合并中文 Markdown 报告。证据不足、Graph 失败或 Graph 内取消的运行也保留已加载证据清单。
- Web 的“交易员分析任务”列表会读取上述独立任务域；每个列表项可独立刷新，取消运行中的任务前必须由用户确认。数据质量、完整分析报告与运行流依次展示且默认折叠；运行流仅在展开后加载与该任务关联的轨迹并渲染完整流程图，展示证据预检、四类并行分析、研究辩论与裁决、交易计划、风险辩论、组合决策和报告输出状态；页面不再额外展示与运行流重复的角色流程摘要。运行流、完整分析报告、Debug 日志和 LLM 交互消息的展开标题在页面滚动时吸附于全局标题栏下方。Debug 日志仍按需加载。脱敏后的 LLM 与工具步骤按一次调用展示详细输入、输出、耗时或错误；完成后折叠同一次调用的“开始”记录，普通任务生命周期事件只保留在 Debug 日志中。当前任务列表只包含交易员分析，不合并现有策略分析任务。
- trace 记录阶段、角色 LLM 请求/响应、deployment 路由、跨模型 fallback、工具参数/结果、实际消费的 evidence、耗时和错误；敏感键及常见 token 会脱敏，单项内容按配置截断，且不会混入正式报告。
- 每次成功完成的角色 LLM 调用会按实际返回的 Prompt、Completion 和总 Token 写入全局模型用量统计，调用类型为“交易员分析”，并在 Web“用量”页面参与时间范围、模型和调用类型聚合；未返回用量信息的供应商调用不会生成虚假的零 Token 记录。
- checkpoint 与 decision memory 保持原版语义；历史决策收益回看不访问 yfinance。当前尚未加载与个股同日期口径的国内 benchmark 日线，因此返回 `(None, None, None)` 保持 memory entry pending，避免用 `alpha=None` 触发上游格式化错误或把缺失 benchmark 当成零超额收益。
- A 股全市场/宏观新闻当前没有独立 point-in-time envelope，`get_global_news` 明确返回不可用，不会把个股新闻冒充宏观背景。
- 队列达到 `TRADER_ANALYSIS_QUEUE_LIMIT` 时创建接口返回 HTTP 429。任务超时或取消后不会发布正常最终报告。

## 验证

后端最低验证：

```bash
python -m pytest tests/trader_analysis
python -m py_compile src/trader_analysis/*.py src/trader_analysis/*/*.py api/v1/endpoints/trader_analysis.py api/v1/schemas/trader_analysis.py
```

前端改动默认验证：

```bash
cd apps/dsa-web
npm run lint
npm run build
```

TradingAgents 上游兼容补丁最低验证：

```bash
python -m pytest tests/test_data_toolkit_injection.py tests/test_market_toolnode.py
```
