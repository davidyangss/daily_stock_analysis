# 分析与策略数据源优先级

本文档是项目默认的数据能力路由说明。优先级是**按数据能力分别配置**，并非用一个全局顺序处理所有数据。可选数据源未开启、未配置凭据、超时、返回空数据或未通过字段校验时，运行时会 fail-open 尝试下一来源。

同花顺问财通过 SkillHub OpenAPI 接入，默认关闭。启用方式：

```env
IWENCAI_ENABLED=true
IWENCAI_API_KEY=在同花顺问财SkillHub取得的密钥
IWENCAI_TIMEOUT_SECONDS=8.0
```

密钥仅从环境变量读取，不得写入代码、日志、报告或数据来源元信息。

## 策略数据依赖与默认来源

| 分析环节 | 依赖数据 | 默认优先级 | 当前运行时状态 |
| --- | --- | --- | --- |
| 盘中价格与量价判断 | 最新价、涨跌、成交、换手、量比、估值 | TickFlow → 腾讯 → 问财 → Tushare → 东财浏览器 → 新浪/AkShare → Efinance/AkShare EM | 已路由；问财用于整源获取和缺失字段补充 |
| 趋势与技术面 | 日线、复权价格、MA、MACD、RSI、KDJ、BOLL | 本地日线优先；Tushare/TickFlow 更新 → 东财 → AkShare/Efinance → BaoStock/PyTDX | 技术指标以本地标准化日线计算为准；问财指标只适合交叉验证 |
| 主力行为 | 当日、5日、10日主力净流入及板块资金 | 问财 → 东财浏览器/API → AkShare 东财 → Efinance | 已路由并按字段补缺；不同供应商口径不得静默拼成同一历史序列 |
| 基本面质量 | 营收、利润、增长、ROE、毛利率、现金流、估值 | Tushare → 问财 → 东方财富/AkShare → Longbridge/YFinance（港美股） | A股归一化 bundle 已支持问财与 AkShare 补缺；港美股保留专用路径 |
| 股东与治理 | 股本、股东户数、十大股东、实控人、质押、高管 | 问财 → Tushare → 东方财富/AkShare | 优先级已配置；问财已归一化当前报告消费的股东变化字段 |
| 事件与风险 | 业绩预告、增减持、质押、解禁、监管、调研 | 问财 announcement-search → event-query → 东财公告 → 新闻 | 优先级已配置；搜索能力后续按独立内容契约接入，不能替代公告事实核验 |
| 行业、概念和板块 | 行业归属、估值、涨跌、资金、排名 | 问财 → 东方财富 → Tushare → AkShare/Efinance → 本地映射 | 优先级已配置；跨供应商行业分类不可直接混算 |
| 新闻情报 | 公司、行业、政策新闻 | 问财 news-search → 现有搜索聚合器 → 普通网页搜索 | 优先级已配置；事实可信度仍按公告/官方来源优先判断 |
| 公告检索 | 定期报告、分红、回购、重组等 | 问财 announcement-search → 东财公告 → 普通搜索 | 优先级已配置；原公告链接和发布日期必须保留 |
| 机构观点 | 研报、评级、目标价、盈利预测 | 问财 report-search → insresearch-query → 券商官网 → 新闻摘要 | 优先级已配置；仅作为观点和预期，不覆盖策略事实字段 |
| 宏观环境 | GDP、CPI、PPI、PMI、社融、利率、汇率 | 问财 → Tushare → 财经媒体 | 优先级已配置；应保留指标原始发布机构 |
| 筹码结构 | 获利盘、平均成本、集中度 | 东财原始接口 → AkShare 东财 → 问财指标 / 本地量价估算 | 东财与本地估算路径已存在；问财筹码字段需完成样本契约后再启用 |

“已配置”表示配置契约和推荐顺序已建立，不代表每个 provider 都已拥有相同的结构化适配器。运行时只调用已经实现对应能力契约的 provider，其他 token 会安全跳过。

## 质量排序与运行时排序

跨市场的数据质量参考顺序为：

```text
历史日线与技术指标：Tushare / TickFlow → Longbridge（港美股）
→ 本地数据库 → 腾讯/东方财富历史行情 → AkShare/Efinance
→ YFinance → 问财
```

项目实际分析运行优先读取本地已校验日线，以保证速度、复权口径和可复现性；本地缺失时才按更新链取数：

```text
本地数据库 → Tushare/TickFlow 更新 → 东方财富
→ AkShare/Efinance → BaoStock/PyTDX
```

这两种顺序并不冲突：前者评价上游数据产品质量，后者描述一次分析任务的运行时读取顺序。

## 配置键

| 能力 | 环境变量 | 默认值 |
| --- | --- | --- |
| 实时行情 | `REALTIME_SOURCE_PRIORITY` | `tickflow,tencent,iwencai,tushare,eastmoney_browser,akshare_sina,efinance,akshare_em` |
| 日线 | `DAILY_SOURCE_PRIORITY` | `local,tushare,tickflow,longbridge,tencent,eastmoney,akshare,efinance,yfinance,iwencai,baostock,pytdx` |
| 主力资金 | `CAPITAL_FLOW_SOURCE_PRIORITY` | `iwencai,eastmoney_browser,akshare_em,efinance` |
| 财务 | `FINANCIAL_SOURCE_PRIORITY` | `tushare,iwencai,akshare_em,longbridge,yfinance` |
| 股东治理 | `GOVERNANCE_SOURCE_PRIORITY` | `iwencai,tushare,akshare_em` |
| 公司事件 | `EVENT_SOURCE_PRIORITY` | `iwencai_announcement,iwencai_event,eastmoney,news` |
| 行业板块 | `SECTOR_SOURCE_PRIORITY` | `iwencai,eastmoney,tushare,akshare,efinance,local` |
| 新闻 | `NEWS_SOURCE_PRIORITY` | `iwencai_news,search_aggregators,web_search` |
| 公告 | `ANNOUNCEMENT_SOURCE_PRIORITY` | `iwencai_announcement,eastmoney,web_search` |
| 研报 | `RESEARCH_SOURCE_PRIORITY` | `iwencai_report,iwencai_insresearch,broker_website,news` |
| 宏观 | `MACRO_SOURCE_PRIORITY` | `iwencai,tushare,financial_media` |
| 筹码 | `CHIP_SOURCE_PRIORITY` | `eastmoney_browser,akshare_em,iwencai,local_estimate` |

## 问财数据契约和边界

- 结构化查询使用 `POST https://openapi.iwencai.com/v1/query2data`。
- 请求必须携带 SkillHub 规定的 Bearer 和 `X-Claw-*` headers，每次生成独立 trace ID。
- 返回列由自然语言 query 和查询日期动态决定；适配器必须校验证券代码、单位和字段语义。
- 日期后缀列只能映射到明确的 `as_of`，不能把当前查询结果直接用于历史回测。
- 主力资金属于供应商口径，问财与东方财富数据只能降级替换，不能被当作同一口径进行跨源累计。
- 问财关闭或失败时不得阻断分析主流程。

## 回滚

设置 `IWENCAI_ENABLED=false` 即可完全关闭问财请求。若需恢复旧实时顺序，可显式配置：

```env
REALTIME_SOURCE_PRIORITY=tencent,akshare_sina,efinance,akshare_em
```

其他能力可分别覆盖对应的 `*_SOURCE_PRIORITY`，无需修改代码。
