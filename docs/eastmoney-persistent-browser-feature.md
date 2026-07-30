# 东财持久浏览器筹码数据源设计

## 1. 文档目的

本文记录“由服务维护一个可登录、可持久化的浏览器上下文，并在同一浏览器上下文内访问东财行情接口”的后续实现方案。

下次继续开发时，应先阅读本文并核对当前代码、运行环境和东财页面现状，不要直接复用聊天记录中的 Cookie、请求时间戳或一次性 curl。

本文是功能设计，不表示该能力已经实现。当前可用基线为：

```text
commit: 21d0efe7 feat: add fallback chip distribution sources
筹码顺序: AkShare 东财 → 新浪日线本地计算 → 腾讯日线本地计算
```

## 2. 背景与已确认事实

### 2.1 东财接口

AkShare `stock_cyq_em` 使用的原始数据来自：

```text
https://push2his.eastmoney.com/api/qt/stock/kline/get
```

该端点返回日 K 和换手率，不直接返回成品筹码。AkShare 在本地计算获利比例、平均成本、90%/70%成本区间和集中度。

常见公共参数：

| 参数 | 语义 |
| --- | --- |
| `secid` | 市场与股票代码 |
| `ut=fa5fd1943c7b386f172d6893dbfba10b` | Web 行情请求中常见的公共参数，不等于登录 Cookie 中的 `ut` |
| `fields1` / `fields2` | 返回字段 |
| `klt=101` | 日 K |
| `fqt=0` | 不复权；筹码计算必须使用不复权价格空间 |
| `end` | 截止日期 |
| `lmt` | 返回行数 |

`cb` 和 `_` 主要服务于 JSONP 与防缓存，不应被当作固定认证参数。

### 2.2 本机探测结果

已观察到以下行为：

- Python Requests 默认请求会收到 `RemoteDisconnected`。
- 公共 `ut`、Referer 和浏览器 User-Agent 不能稳定解决问题。
- 仓库现有匿名 NID patch 不能稳定解决问题。
- 系统 curl 强制 IPv4 曾成功返回有效 JSON，随后重复请求仍可能被断开。
- 只使用 `qgqp_b_id`、`nid18`、`gviem` 等匿名指纹 Cookie 仍可能失败。
- 登录 curl 中包含的 `ct`、长 `ut`、`pi`、`uidal` 等属于账户会话凭据，不得写入仓库、日志、命令行或普通配置。
- 把 Chromium/Firefox Cookie 交给 Python Requests 仍会丢失浏览器 TLS、HTTP/2 和 Client Hints 指纹，因此不是首选架构。

结论：如果确需提高东财路径命中率，应让同一个持久浏览器上下文直接发出请求，而不是抽取整套 Cookie 后交给 Requests。

## 3. 当前本机环境

探测日期：2026-07-30。

- 设备：MacBook 安装 Linux。
- 图形服务器：Xorg `:0` 正在运行。
- 当前 `:0` 属于 LightDM greeter：

  ```text
  User=lightdm
  Display=:0
  Type=x11
  Class=greeter
  ```

- `yangss` 当前只有远程 TTY session，没有图形桌面 session。
- 当前安装 Firefox，未发现 Chrome/Chromium。
- 因此现阶段不能把登录窗口安全地启动到 `yangss` 桌面；需要用户先在本机登录 Linux 图形桌面，或者另行批准受保护的远程浏览器界面。

## 4. 功能目标

### 4.1 目标

1. 服务维护独立、持久的东财浏览器 Profile。
2. 用户只在真实浏览器页面中手动登录。
3. 账号密码、验证码和 Cookie 不经过应用 API 或日志。
4. 筹码取数时由浏览器上下文直接 `fetch` 东财 K 线端点。
5. 返回内容经过严格 Schema、行数、字段和大小校验。
6. 浏览器路径失败时继续使用已提交的新浪、腾讯 fallback。
7. 登录失效、浏览器崩溃和接口风控不得阻断主分析流程。

### 4.2 非目标

- 不自动填写、保存或同步东财账号密码。
- 不自动处理验证码、短信验证或滑块。
- 不绕过付费权限或访问账户无权访问的数据。
- 不将登录 Cookie 导出给普通 Requests、前端或诊断接口。
- 不把浏览器调试端口暴露到公网。
- 不保证东财非正式 Web 接口的 SLA。

## 5. 推荐架构

```text
服务启动
  → EastmoneyBrowserService
      → 独立 persistent profile（仓库外，0700）
      → 单实例浏览器进程
      → 登录状态检测
      → 同一 browser context 内 fetch K 线
  → 校验并转换日 K + 换手率
  → 本地 CYQ 计算
  → 返回 ChipDistribution(source="eastmoney_browser")
  → 失败时 AkShare/Sina/Tencent fallback
```

### 5.1 为什么浏览器直接请求

浏览器直接请求能够同时保持：

- Cookie jar；
- TLS 与 HTTP/2 指纹；
- User-Agent 与 Client Hints；
- Referer、Origin 和 Fetch Metadata；
- 页面上下文、缓存和站点存储；
- 与登录时一致的网络出口。

浏览器服务只返回经过白名单转换的行情字段，不返回 Cookie、Local Storage、页面 HTML 或账户信息。

### 5.2 浏览器选择

实现前应做一次短验证：

- 优先评估 Playwright Chromium persistent context；
- 若不希望新增 Chromium，再评估 Playwright Firefox；
- 不直接自动化用户的日常 Firefox Profile；
- 浏览器二进制和自动化库必须显式进入依赖、Docker及桌面打包评估，不能依赖开发机偶然安装。

## 6. Profile 与秘密管理

建议新增配置，但具体名称需在实现时对照配置注册系统确认：

```text
EASTMONEY_BROWSER_ENABLED=false
EASTMONEY_BROWSER_PROFILE_DIR=<仓库外路径>
EASTMONEY_BROWSER_HEADLESS=false
EASTMONEY_BROWSER_REQUEST_TIMEOUT=12
EASTMONEY_BROWSER_IDLE_TIMEOUT=1800
```

规则：

- 默认关闭，保持现有行为。
- `PROFILE_DIR` 不得位于仓库、静态目录或可下载目录。
- 创建目录时权限为 `0700`。
- 不新增 `EASTMONEY_COOKIE` 这类保存完整 Cookie 字符串的配置。
- Profile 不进入备份、诊断包、Actions artifact、Docker image 或桌面安装包。
- 日志只允许记录 `ready/login_required/unavailable/timeout` 等低敏状态。
- 提供显式“关闭浏览器并清除 Profile”管理操作，执行前需要确认。

新增配置时必须同步 `.env.example`、配置注册表、设置帮助、中英文文档和 `docs/CHANGELOG.md`。

## 7. 生命周期与状态机

建议状态：

```text
disabled
starting
login_required
ready
requesting
degraded
stopped
```

关键行为：

1. 服务启动不应阻塞 FastAPI startup；浏览器按需或后台启动。
2. 同一时刻只允许一个浏览器启动流程。
3. K 线请求通过有界队列或锁串行化，避免页面上下文并发失控。
4. 浏览器进程异常退出后可有限次数重启，不无限重启。
5. 登录失效标记为 `login_required`，不自动提交登录表单。
6. 请求超时立即降级，不让浏览器拖垮分析任务。
7. 服务退出时正常关闭浏览器进程，保留 Profile。

## 8. 登录交互

### 8.1 本机桌面模式

前置条件：`yangss` 已登录 Linux 图形桌面，并存在属于该用户的 X11/Wayland session。

流程：

1. 管理员触发“打开东财登录窗口”。
2. 服务使用独立 Profile 启动可见浏览器。
3. 用户在本机手动完成登录、验证码和授权。
4. 服务只检测预期站点的登录状态，不读取密码字段。
5. 用户关闭窗口后，后台 persistent context 是否保留需根据浏览器实现验证；必要时由服务保持进程而非依赖窗口。

### 8.2 无桌面/远程模式

远程登录界面会显著扩大安全面，不纳入首版。若未来实现：

- 只能通过 Tailscale/SSH 等受信通道访问；
- 远程调试/VNC端口只监听 localhost 或受控 tailnet 地址；
- 必须有独立认证、短时会话和审计；
- 不允许直接公网暴露 Chrome DevTools、VNC 或 noVNC；
- PR 中必须单独说明威胁模型、端口、认证和回滚方式。

## 9. 浏览器内数据请求

请求应在已加载的东财页面或同站点浏览器上下文中执行，并动态构造：

```text
https://push2his.eastmoney.com/api/qt/stock/kline/get
```

约束：

- `secid` 由经过验证的六位 A 股代码生成；
- `fqt=0`；
- 最多请求满足 CYQ 算法需要的有限日线窗口；
- 设置连接和总超时；
- 限制响应体大小；
- 仅接受 `rc == 0` 且 `data.klines` 为合法数组；
- 每行必须符合预期字段数和数值范围；
- 日期排序、重复行、空换手率和异常价格必须显式处理；
- 不把原始响应完整写入日志或持久化上下文。

## 10. 与现有筹码链路集成

建议顺序：

```text
1. eastmoney_browser（启用且 ready）
2. AkShare stock_cyq_em
3. akshare_sina_calculated
4. akshare_tencent_calculated
```

兼容要求：

- `ENABLE_CHIP_DISTRIBUTION=false` 时不启动或调用浏览器筹码能力。
- 浏览器失败必须被 provider diagnostics 记录为低敏失败类型。
- 不支持的市场和 ETF 仍直接返回 `None`，不启动浏览器。
- 全部渠道失败仍 fail-open，报告明确筹码未纳入判断。
- 浏览器来源建议标记为 `eastmoney_browser`，不要伪装成 AkShare。
- CYQ 计算器应复用已提交的本地实现，避免新增第二套算法。

## 11. 缓存、限流与熔断

- 成功缓存键：股票代码、最新交易日、算法版本、数据源。
- 同一股票同一交易日不重复请求和计算。
- 登录失效不按普通网络错误无限重试。
- 浏览器连续失败达到阈值后进入冷却，直接使用新浪/腾讯。
- 单只股票请求失败不应重启整个浏览器。
- 全局并发默认 1；批量分析时优先命中缓存。
- 缓存中只保存 K 线或计算结果，不保存 Cookie。

## 12. 管理与诊断接口

如需新增 API，只允许管理员访问，并保持低敏：

```text
GET  /api/v1/admin/eastmoney-browser/status
POST /api/v1/admin/eastmoney-browser/open-login
POST /api/v1/admin/eastmoney-browser/restart
POST /api/v1/admin/eastmoney-browser/logout
```

状态响应只包含：

```json
{
  "enabled": true,
  "state": "ready",
  "browser_running": true,
  "login_required": false,
  "last_success_at": "...",
  "last_error_type": null
}
```

禁止返回：

- Cookie 名和值；
- Profile 绝对路径；
- 页面内容；
- 用户昵称、账号 ID、手机号；
- 请求头和完整异常文本；
- DevTools WebSocket URL。

## 13. 测试矩阵

### 13.1 单元测试

- 配置默认关闭。
- Profile 路径校验和权限。
- 状态机合法转换。
- 单实例启动与并发请求锁。
- 登录未完成时快速降级。
- 浏览器异常、超时、崩溃后的 fallback。
- K 线 JSON字段、行宽、数值和大小校验。
- Cookie、Profile、WebSocket URL 不进入日志和 API。
- 只允许目标东财域名，拒绝任意 URL注入。
- A 股代码到 `secid` 和 Referer 的映射。
- ETF、港股、美股不启动浏览器。

### 13.2 集成测试

- 使用伪浏览器 adapter 验证 Pipeline/manager/fallback，不在普通 CI登录真实东财。
- 本机手动 smoke：登录、重启服务、复用 Profile、请求 K 线、计算筹码。
- 登录过期 smoke：状态变为 `login_required` 并自动走新浪。
- 浏览器关闭 smoke：进程回收，无僵尸进程。
- 屏幕关闭 smoke：已登录桌面会话保持时，后台请求仍可运行。

### 13.3 验证命令

实现后至少执行：

```bash
python -m py_compile <changed_python_files>
python -m pytest -m "not network"
./scripts/ci_gate.sh
```

若涉及 Web 管理页面，还需执行：

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

## 14. 分阶段实施计划

### Phase 0：环境验证

- 用户登录 `yangss` 图形桌面。
- 确认桌面 session、`DISPLAY`/Wayland、DBus 和浏览器窗口可见。
- 使用独立临时 Profile 手动访问东财，不接入服务。
- 验证浏览器上下文内 fetch 是否稳定优于 Requests。

退出条件：同一 persistent context 可重复获取目标 K 线，且关闭屏幕后仍可用。

### Phase 1：浏览器服务骨架

- 新增默认关闭的配置和生命周期服务。
- 实现独立 Profile、状态机、单实例启动和安全关闭。
- 使用 fake adapter 完成离线测试。

### Phase 2：登录与浏览器内 fetch

- 实现可见登录窗口。
- 实现严格域名允许列表和 K 线请求。
- 返回标准化日线，不暴露浏览器存储。

### Phase 3：筹码集成

- 接入现有 CYQ 计算器。
- 加入 provider 顺序、缓存、诊断和熔断。
- 保持新浪/腾讯 fail-open。

### Phase 4：管理界面（可选）

- 增加管理员状态与登录触发入口。
- 如界面变化，PR 描述附页面截图，不把一次性验收截图加入仓库。

## 15. 验收标准

功能只有同时满足以下条件才算完成：

1. 默认关闭时行为与 `21d0efe7` 一致。
2. 浏览器 Profile 与仓库、日志和 API完全隔离。
3. 用户可在独立浏览器中手动登录，应用不接触密码。
4. 同一浏览器上下文能重复获取有效东财 K 线。
5. 服务重启后可复用有效 Profile；失效时明确显示需重新登录。
6. 浏览器请求失败能在总预算内降级到新浪/腾讯。
7. 批量分析不会为每只股票启动新浏览器。
8. 所有新增离线测试、后端 gate 和受影响客户端构建通过。
9. 文档、`.env.example`、配置帮助和 `docs/CHANGELOG.md` 同步。
10. PR 描述说明安全边界、验证证据、风险和回滚方式。

## 16. 回滚方案

- 设置 `EASTMONEY_BROWSER_ENABLED=false` 立即停用新路径。
- 保留现有 AkShare/Sina/Tencent fallback。
- 停止并移除浏览器服务代码与可选依赖。
- Profile 由用户显式确认后单独删除，不在代码回滚时自动清除。
- 若新增管理 API/Web 页面，同步回滚对应路由、Schema、文档和前端入口。

## 17. 下次继续时的第一组检查

```bash
git status --short --branch
git log -1 --oneline
loginctl list-sessions
ps -ef | rg '[X]org|[X]wayland|[g]nome-shell|[p]lasmashell|[x]fce4-session|[f]irefox|[c]hrom(e|ium)'
command -v firefox
command -v chromium
```

只有确认 `yangss` 拥有真实图形 desktop session 后，才进入 Phase 0 的可见浏览器验证。若仍只有 LightDM greeter，不要尝试绕过 Xauthority，也不要把浏览器启动到 greeter session。
