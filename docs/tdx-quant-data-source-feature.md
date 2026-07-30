# 通达信 TdxQuant A 股数据源 Feature 设计

## 1. 背景与目标

当前项目已经通过 `DataFetcherManager` 为 A 股日线、实时行情和股票名称提供多数据源 fallback，并包含基于传统通达信行情服务器的 `PytdxFetcher`。通达信官方 TdxQuant 则是另一套基于通达信金融终端的量化 API：它通过 `tqcenter` 或终端本地 HTTP 接口提供实时与历史行情、复权因子、证券信息和金融数据库数据。

本 Feature 计划新增独立的 `TdxQuantFetcher`，将 TdxQuant 作为可选的高质量 A 股数据源接入现有 fallback 体系。首期只读取行情和证券主数据，不提供下单、撤单、账户、持仓或任意公式执行能力。

本 Feature 不替换 `PytdxFetcher`：前者依赖已授权且正在运行的 TdxQuant 终端，后者继续作为免费、免凭据的传统行情协议 fallback。

## 2. 官方运行边界

TdxQuant 官方 Python 入口由支持 TQ 的通达信客户端安装并分发，典型调用需要：

1. 在 64 位 Windows 上安装并登录支持 TQ 的通达信终端；
2. 保持终端运行；
3. 通过终端目录中的 `tqcenter.py` 和配套 DLL 调用，或访问终端提供的 `POST http://127.0.0.1:17709/`；
4. 使用 `method` 和 `params` 组成 JSON 请求。

因此，TdxQuant 不是安装一个普通 Python 包后即可在 Linux 服务器直接联网取数的云 API。本项目的标准 Linux 部署不应加载 Windows DLL，也不应假定可以直接访问终端的 loopback 端口。

官方资料：

- [TdxQuant 简介](https://help.tdx.com.cn/quant/)
- [安装通达信终端并获取数据](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1cfsjkbf8f3is/mindoc-1d00kk3jsibbc.html)
- [HTTP 方式调用](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hdhbmi50d038.html)
- [常见问题：外部 Python 文件调用](https://help.tdx.com.cn/quant/docs/markdown/mindoc-tdxpy.html)

## 3. 建议架构

```text
daily_stock_analysis（Linux）
          │
          │ 经过认证的内网 HTTP(S)
          ▼
Windows TdxQuant Bridge
          │
          │ POST http://127.0.0.1:17709/
          ▼
支持 TQ 的通达信客户端
```

Windows Bridge 负责把官方 loopback HTTP 接口转换为受控的只读服务。它必须：

- 只监听受信任内网，或置于带认证和 TLS 的反向代理之后；
- 只开放明确的只读方法白名单；
- 禁止调用方传入任意 TdxQuant `method`；
- 禁止暴露下单、撤单、账户、持仓和客户端控制类方法；
- 提供连接状态、登录状态和数据权限健康检查；
- 实施请求超时、并发限制、响应大小限制和日志脱敏；
- 将官方错误码转换为稳定、可诊断的 HTTP 错误。

不得将 `127.0.0.1:17709` 直接映射到公网。官方文档没有为该接口声明面向公网的认证协议。

## 4. 首期范围

### 4.1 支持能力

- 沪深北 A 股；
- A 股 ETF；
- 日 K 线；
- 不复权、前复权和后复权；
- 复权因子；
- 实时行情快照及五档价格；
- 证券名称和基础信息；
- 交易日历；
- 请求超时、失败降级和 provider 运行诊断。

日线结果应转换为项目统一字段：

```text
date, open, high, low, close, volume, amount, pct_chg
```

实时行情至少应转换为现有统一行情对象所需字段：

```text
code, name, price, open, high, low, pre_close,
volume, amount, bid_prices, ask_prices, timestamp
```

### 4.2 暂不支持

- 模拟或实盘交易；
- 下单、撤单、账户和持仓查询；
- 执行任意通达信公式；
- L2 和其他需单独评估授权的数据；
- 全市场选股；
- 分钟线和 Tick 数据；
- 港股、美股等非 A 股市场；
- 将第三方 SDK 作为未经审计的强制运行依赖。

分钟线、Tick、板块、财务和特色数据应在日线及实时契约稳定后分别评估，不在首期顺手扩展。

## 5. 配置草案

实现时建议通过现有配置入口增加：

```dotenv
TDX_QUANT_ENABLED=false
TDX_QUANT_BASE_URL=
TDX_QUANT_API_KEY=
TDX_QUANT_PRIORITY=0
TDX_QUANT_TIMEOUT_SECONDS=10
TDX_QUANT_ADJUST=none
```

配置语义：

- 未启用或缺少必要配置时不实例化 `TdxQuantFetcher`；
- `BASE_URL` 指向受控 Bridge，不直接填写官方 loopback 地址；
- `API_KEY` 属于敏感配置，不得进入日志、API 响应或运行诊断；
- 优先级数值越小越先尝试，不在代码中强制成为首选；
- `ADJUST` 只接受 `none`、`front`、`back`；
- 关闭 Feature 后恢复现有 provider 顺序和行为。

新增配置时必须同步 `.env.example`、配置注册表、设置帮助和相关专题文档；若 Web 设置页可编辑这些配置，还要复用现有敏感字段遮罩与保存机制。

## 6. Provider 契约

新增文件建议为：

```text
data_provider/tdx_quant_fetcher.py
```

`TdxQuantFetcher` 应复用 `BaseFetcher`、统一行情类型、市场识别、provider diagnostics 和现有 fallback 机制，避免建立平行管理器。

首期对外能力：

```python
class TdxQuantFetcher(BaseFetcher):
    name = "TdxQuantFetcher"

    def get_daily_data(...): ...
    def get_realtime_quote(...): ...
    def get_stock_name(...): ...
    def get_trading_calendar(...): ...
```

证券代码需转换为官方后缀形式，例如：

```text
600519 -> 600519.SH
000001 -> 000001.SZ
300750 -> 300750.SZ
688981 -> 688981.SH
920xxx -> 920xxx.BJ
```

代码归属必须复用或扩展项目现有市场判断工具，不能在新 fetcher 中长期维护另一套易漂移规则。

## 7. Bridge 最小契约

建议由 Bridge 提供领域化的只读端点，而不是透传任意 RPC 方法：

```text
GET  /health
POST /v1/market-data
POST /v1/market-snapshot
GET  /v1/instruments/{symbol}
GET  /v1/trading-calendar
```

健康检查应至少区分：

```json
{
  "status": "ok",
  "terminal_running": true,
  "terminal_authenticated": true,
  "tdx_http_reachable": true,
  "data_permission": "available"
}
```

数据端点需要稳定返回错误类别，例如：

- `terminal_unavailable`；
- `terminal_not_authenticated`；
- `permission_denied`；
- `upstream_timeout`；
- `upstream_error`；
- `empty_data`；
- `invalid_response`；
- `partial_data`。

DSA 只消费稳定契约，不依赖官方错误文案进行流程判断。

## 8. Fallback 和数据质量语义

TdxQuant 是否排在第一位由 `TDX_QUANT_PRIORITY` 决定。完成样本验收后的推荐逻辑为：

```text
TdxQuant
  -> 已配置的 Tushare / TickFlow
  -> Efinance / Akshare
  -> Pytdx
  -> Baostock
  -> 其余 A 股兜底源
```

出现以下情况时必须记录失败原因并继续 fallback：

- Bridge 不可达；
- 通达信终端未启动、未登录或连接中断；
- 请求超时；
- 官方错误码非成功状态；
- 当前账户没有对应数据权限；
- 返回空结果；
- 缺少必须字段；
- 请求日期范围未完整返回；
- 分页未完成或响应无法解析。

不得使用空 DataFrame、全零行情、过期缓存或 `None` 静默冒充成功。若后续允许使用 stale cache，必须沿用项目现有 `stale` / `fallback` / `partial` 质量标识，并明确时间戳和来源。

当日尚未收盘的日 K 线不得无标识地视为完整收盘数据。复权结果必须记录复权类型；复权因子与价格口径不能混用。

## 9. 第三方 SDK 评估

PyPI 上存在同名 `tdxquant` HTTP SDK，它封装官方本地 HTTP 接口并提供 DataFrame 和字段转换。这不是官方文档要求安装的 `tqcenter`，首期不能直接假定它是官方或成熟依赖。

将其加入项目依赖前至少应确认：

- 存在明确且兼容本项目的开源许可证；
- PyPI 发布物能与公开源码和版本 tag 对应；
- 支持项目当前 Python 与 pandas 版本；
- timeout、异常类型和分页行为稳定；
- 不允许绕过 Bridge 的只读方法白名单；
- 能锁定经过集成测试的明确版本。

在这些条件未满足时，优先为 Bridge/provider 编写最小 HTTP client。官方请求是简单 JSON RPC，依赖治理和安全边界比减少少量封装代码更重要。

第三方项目参考：

- [PyPI tdxquant](https://pypi.org/project/tdxquant/)
- [finanalyzer/tdxquant](https://github.com/finanalyzer/tdxquant)

## 10. 验收样本与标准

至少选择以下样本：

- `600519.SH`：普通上交所股票；
- `000001.SZ`：普通深交所股票；
- `300750.SZ`：创业板；
- `688981.SH`：科创板；
- 一只当前有效的北交所股票；
- 一只 A 股 ETF；
- 一只近期除权股票；
- 一只停牌或曾长期停牌股票。

必须验证：

- 代码和交易所映射正确；
- OHLCV 与成交额单位正确；
- 日期升序且没有重复记录；
- 停牌日、无交易日和空响应能够区分；
- 未收盘日线有明确处理；
- 不复权、前复权和后复权口径可区分；
- 复权因子可追溯；
- 请求范围或分页不完整时不能报告完整成功；
- TdxQuant 不可用时自动进入后续 provider；
- 非 A 股请求不会发送给 TdxQuant；
- 日线能够进入现有技术指标和报告流程；
- 实时结果符合项目统一行情对象契约；
- 日志和 diagnostics 不泄露凭据。

## 11. 测试与文档要求

建议新增：

```text
tests/test_tdx_quant_fetcher.py
tests/test_tdx_quant_manager_routing.py
tests/test_tdx_quant_realtime_routing.py
```

测试应覆盖代码转换、字段标准化、复权参数、分页、超时、权限不足、客户端离线、空响应、非法响应、fallback、市场过滤、统一实时类型和凭据脱敏。

实现阶段至少执行：

```bash
python -m py_compile <changed_python_files>
./scripts/ci_gate.sh
```

在线验证依赖 Windows TdxQuant 环境；若 CI 不具备该环境，确定性测试必须使用契约 fixture 或本地 fake server，交付说明中另列真实终端验证结果和缺口。

用户可见的数据源、配置和诊断变化实现时需同步 `.env.example`、相关 `docs/*.md` 和 `docs/CHANGELOG.md`。如修改 Web 设置界面，还需执行 Web lint/build 并在 PR 描述附页面截图。

## 12. 风险与回滚

主要风险：

- Windows 终端需要长期运行和保持登录；
- 数据权限、终端版本或官方响应格式可能变化；
- loopback HTTP 接口缺少面向公网的认证语义；
- 复权、分页、停牌和未收盘日线处理不当会污染分析；
- Bridge 成为新的部署组件和故障点；
- 未经审计的第三方 SDK可能带来许可证和兼容风险。

回滚方式：

1. 设置 `TDX_QUANT_ENABLED=false` 或移除相关配置；
2. 管理器不再实例化 `TdxQuantFetcher`；
3. 现有数据源按原优先级继续工作；
4. 停止 Windows Bridge，不影响既有 `PytdxFetcher`；
5. 首期不引入破坏性数据库迁移，回滚无需清理业务数据。

## 13. 实施拆分

建议拆成可独立验证的工作项：

1. 定义并实现只读 Windows Bridge 契约；
2. 新增配置、`TdxQuantFetcher` 和日线 fallback；
3. 接入统一实时行情对象和实时路由；
4. 增加股票名称、证券信息和交易日历；
5. 使用真实终端完成样本对账、故障演练和文档收敛；
6. 稳定后另行评估分钟线、Tick、板块和财务数据。

各工作项不得借机引入交易权限或替换现有 provider；只有在真实终端样本对账通过后，才建议将 TdxQuant 配置为 A 股首选数据源。
