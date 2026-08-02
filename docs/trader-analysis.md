# 交易员分析第一阶段

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
TRADER_ANALYSIS_TRADINGAGENTS_COMMIT=
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
TRADER_ANALYSIS_TRACE_CONTENT_MAX_CHARS=65536
```

角色配置按 `model_name` 精确查找 DSA 已加载的 LiteLLM deployment，再使用其中的实际 `provider/model`、`api_base` 和凭据创建客户端。Market、Sentiment、News、Fundamentals、研究辩论、Research Manager、Trader、风险辩论和 Portfolio Manager 均可独立路由并允许跨 provider。留空角色继承 quick/deep 默认 deployment；deployment 不存在或不完整时任务返回 `configuration_error`，不会静默换模型。凭据只进入内存客户端，不进入请求、报告、trace 或持久化元数据。

回滚方式：将 `TRADER_ANALYSIS_ENABLED=false` 后重启服务。该开关只拒绝新交易员分析运行，不影响现有股票分析、问股、选股、回测或历史记录。

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

本功能依赖带 `AgentDataToolkit` 注入 seam 的 TradingAgents `0.3.1` 精确 commit。上游兼容补丁只增加可选 `data_toolkit` 参数；未注入时仍使用原版工具、Graph 拓扑、Prompt、structured output、memory 和 checkpoint 行为。生产部署必须先发布该上游 commit，再将它作为固定依赖安装，并把 commit 写入 `TRADER_ANALYSIS_TRADINGAGENTS_COMMIT`；禁止使用浮动 `main` 或 sibling 路径作为生产依赖。

服务启动环境未安装固定版本、版本不一致、缺少注入 seam 或未配置 quick/deep 模型时，任务会 fail-closed 返回 `configuration_error`，不会切换到海外默认数据工具或现有策略 pipeline。

## 数据与执行语义

- Market、News、Fundamentals Analyst 与对应 ToolNode 使用同一组 run-scoped DSA 工具对象。
- 日线、确定性指标、快照、新闻、情绪和财务均先进入 canonical evidence ledger；阻断问题不会作为正常工具文本进入 Graph。
- News 使用 DSA 新闻 provider/fallback 链；Sentiment 独立使用 SearXNG 定向检索雪球、知乎和微博的可核验社区观点，不再把新闻重复包装为社交情绪。站点限定会在返回后再校验域名；无社区结果时明确降级，不使用 Anspire 新闻兜底。StockTwits/Reddit 对 A 股仍明确标为不可用。
- 新闻分析和情绪分析的正式报告都会追加确定性证据表，逐条展示摘要、来源、内容时间、采集时间和原文链接；provider 未返回内容时间或链接时明确标记“未提供”，不自行推断。
- Sentiment 当前传给模型的社区证据是“标题 + 搜索摘要 + 来源 + 内容/采集时间 + URL”，不是网页完整正文。TradingAgents 0.3.1 的 Sentiment 节点没有浏览器或外部搜索工具；提示明确禁止模型声称已打开链接、自行联网或读取未提供的评论/正文，摘要截断、无日期或样本过少时必须降低置信度。
- 当分析日期为今天或最近已完成交易日时，新闻通过 DSA `SearchService` 的现有 provider/fallback 链按运行时间检索；最近交易日的运行时新闻标记为 `runtime_news_not_point_in_time` 并降级披露。更早的历史日期不会读取当前实时价、当前新闻或缺少公告可得日期的当前财务数据；当 point-in-time 证据不足时返回 `insufficient_evidence`。
- 新上市标的截至分析日已有至少 3 个有效交易日、但少于建议历史长度时，以 `limited_daily_history` 降级继续分析；报告必须明确短历史限制，不得把不成熟的技术指标解释成高置信度趋势。少于 3 个有效交易日仍阻断分析。
- 历史分析具备日线与核验价格且无阻断问题时，即使新闻、财务和情绪因 point-in-time 约束不可用，也会以 `degraded` 运行 Graph 并生成各角色报告；缺失能力必须保留在数据质量报告中，不得使用当前数据回填历史上下文。
- 运行、分角色报告、Debug 事件和脱敏后的 LLM/工具 trace 以 `run_id` 为外键持久化到 `TRADER_ANALYSIS_RESULTS_DIR/trader_analysis.sqlite3`；同时继续双写 `runs/<run_id>/` 下的 JSON 文件用于兼容回滚，升级时会把旧 JSON 任务懒迁移到 SQLite，不写入 `analysis_history`。
- 完成后的 Web 列表显示报告正文摘要，报告区以 Markdown 展示市场、情绪、新闻、基本面、多空研究、交易员、三类风险分析、组合经理、最终决策和投资建议；`GET /api/v1/trader-analysis/runs/{run_id}/download/markdown` 下载同一份合并中文 Markdown 报告。
- Web 的“交易员分析任务”列表会读取上述独立任务域；每个列表项可独立刷新，取消运行中的任务前必须由用户确认。数据质量、完整分析报告与运行流依次展示且默认折叠；运行流仅在展开后加载与该任务关联的轨迹并渲染完整流程图，展示证据预检、四类并行分析、研究辩论与裁决、交易计划、风险辩论、组合决策和报告输出状态；页面不再额外展示与运行流重复的角色流程摘要。运行流、完整分析报告、Debug 日志和 LLM 交互消息的展开标题在页面滚动时吸附于全局标题栏下方。Debug 日志仍按需加载。脱敏后的 LLM 与工具步骤按一次调用展示详细输入、输出、耗时或错误；完成后折叠同一次调用的“开始”记录，普通任务生命周期事件只保留在 Debug 日志中。当前任务列表只包含交易员分析，不合并现有策略分析任务。
- trace 记录阶段、角色 LLM 请求/响应、deployment 路由、工具参数/结果、实际消费的 evidence、耗时和错误；敏感键及常见 token 会脱敏，单项内容按配置截断，且不会混入正式报告。
- 每次成功完成的角色 LLM 调用会按实际返回的 Prompt、Completion 和总 Token 写入全局模型用量统计，调用类型为“交易员分析”，并在 Web“用量”页面参与时间范围、模型和调用类型聚合；未返回用量信息的供应商调用不会生成虚假的零 Token 记录。
- checkpoint 与 decision memory 保持原版语义；历史决策收益回看使用 DSA canonical 日线，不访问 yfinance。
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
