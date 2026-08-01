# 交易员分析第一阶段

交易员分析是独立于现有策略分析的实验性入口，面向 TradingAgents 风格的多角色分析链路。第一阶段默认关闭，并使用独立任务域、独立 API 和独立 Web 页面；不会读取、写入或比较现有策略分析结果，也不会写入 `analysis_history`。

## 配置

在 `.env` 中显式启用：

```env
TRADER_ANALYSIS_ENABLED=true
TRADER_ANALYSIS_MAX_CONCURRENCY=1
TRADER_ANALYSIS_QUEUE_LIMIT=8
TRADER_ANALYSIS_TASK_TIMEOUT_SECONDS=900
TRADER_ANALYSIS_PROVIDER_TIMEOUT_SECONDS=20
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
- Sentiment 第一阶段使用已核验新闻；StockTwits/Reddit 对 A 股明确标为不可用并降低置信度。
- 历史日期不会读取当前实时价、当前新闻或缺少公告可得日期的当前财务数据；当 point-in-time 证据不足时返回 `insufficient_evidence`。
- 运行、事件、分角色报告、质量摘要、版本元数据和独立 `trace.json` 持久化到 `TRADER_ANALYSIS_RESULTS_DIR/runs/<run_id>/`，不写入 `analysis_history`。
- Web 的“交易员分析任务”列表会读取上述独立任务域；选择历史任务后可继续查看当前阶段、角色进度、数据质量、关联报告及脱敏后的 LLM/工具交互。当前任务列表只包含交易员分析，不合并现有策略分析任务。
- trace 记录阶段、角色 LLM 请求/响应、deployment 路由、工具参数/结果、实际消费的 evidence、耗时和错误；敏感键及常见 token 会脱敏，单项内容按配置截断，且不会混入正式报告。
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
