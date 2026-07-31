# -*- coding: utf-8 -*-
"""
东财持久浏览器服务
==================
维护一个持久化的浏览器 Profile，由浏览器上下文直接发东财行情请求。
比 Requests+Cookie 注入更稳定（保留完整 TLS/HTTP2/Fingerprint）。

Phase 1：骨架 + 状态机 + FakeBrowserAdapter（离线测试用）
Phase 2：接入真实 Playwright（PlaywrightBrowserAdapter）
Phase 3：接入筹码分布链路
"""
from __future__ import annotations

import logging
import math
import os
import queue
import re
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)


def _is_allowed_eastmoney_hostname(hostname: str) -> bool:
    normalized = hostname.lower().rstrip(".")
    return any(
        normalized == domain or normalized.endswith(f".{domain}")
        for domain in ("eastmoney.com", "eastmoneyfutures.com")
    )


class BrowserState(str, Enum):
    DISABLED = "disabled"
    STARTING = "starting"
    LOGIN_REQUIRED = "login_required"
    READY = "ready"
    REQUESTING = "requesting"
    DEGRADED = "degraded"
    STOPPED = "stopped"


# ---------------------------------------------------------------------------
# Adapter 抽象接口
# ---------------------------------------------------------------------------

class BrowserAdapter(ABC):
    """浏览器操作抽象接口；真实实现在 Phase 2（PlaywrightBrowserAdapter）"""

    @abstractmethod
    def launch(self, profile_dir: str, executable_path: str, headless: bool) -> None:
        """启动浏览器，挂载指定 Profile"""

    @abstractmethod
    def check_login(self) -> bool:
        """检测当前 Profile 是否处于已登录状态"""

    @abstractmethod
    def fetch_kline(self, secid: str, lmt: int, timeout_seconds: int) -> Dict[str, Any]:
        """
        在浏览器上下文内 fetch 东财 K 线接口。
        返回原始响应 dict（含 rc / data.klines）。
        失败时抛出异常。
        """

    @abstractmethod
    def fetch_http(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[str],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """在浏览器上下文请求受允许的东财 URL。"""

    @abstractmethod
    def refresh_session(self, timeout_seconds: int) -> bool:
        """刷新东财首页以延长登录会话，并返回刷新后的登录状态。"""

    @abstractmethod
    def close(self) -> None:
        """安全关闭浏览器进程，保留 Profile"""


# ---------------------------------------------------------------------------
# Fake adapter（离线测试用）
# ---------------------------------------------------------------------------

class FakeBrowserAdapter(BrowserAdapter):
    """内存 fake，用于离线单元测试，不启动真实浏览器"""

    def __init__(
        self,
        *,
        login_ok: bool = True,
        kline_response: Optional[Dict[str, Any]] = None,
        raise_on_fetch: Optional[Exception] = None,
        http_response: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.launched = False
        self.closed = False
        self.login_ok = login_ok
        self._kline_response = kline_response or {
            "rc": 0,
            "data": {"klines": [
                "2026-07-29,10.00,10.20,10.50,9.80,1000000,10000000,7.00,2.00,0.20,3.09"
            ]},
        }
        self._raise_on_fetch = raise_on_fetch
        self._http_response = http_response or {
            "status_code": 200,
            "headers": {"content-type": "application/json; charset=utf-8"},
            "body": '{"rc":0}',
            "url": "https://push2.eastmoney.com/api/test",
        }
        self.thread_ids: List[int] = []
        self.http_requests: List[Dict[str, Any]] = []
        self.session_refresh_count = 0

    def launch(self, profile_dir: str, executable_path: str, headless: bool) -> None:
        self.thread_ids.append(threading.get_ident())
        self.launched = True
        self.profile_dir = profile_dir

    def check_login(self) -> bool:
        self.thread_ids.append(threading.get_ident())
        return self.login_ok

    def fetch_kline(self, secid: str, lmt: int, timeout_seconds: int) -> Dict[str, Any]:
        self.thread_ids.append(threading.get_ident())
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        return self._kline_response

    def close(self) -> None:
        self.thread_ids.append(threading.get_ident())
        self.closed = True

    def fetch_http(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[str],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        self.thread_ids.append(threading.get_ident())
        self.http_requests.append({
            "method": method,
            "url": url,
            "headers": headers,
            "body": body,
        })
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        response = dict(self._http_response)
        response["url"] = url
        return response

    def refresh_session(self, timeout_seconds: int) -> bool:
        self.thread_ids.append(threading.get_ident())
        self.session_refresh_count += 1
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        return self.login_ok


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

_SECID_MARKET = {"6": "1", "0": "0", "3": "0"}  # 上海=1，深圳/北交所=0


def _stock_code_to_secid(stock_code: str) -> Optional[str]:
    """将 A 股六位代码转换为东财 secid（市场.代码），失败返回 None"""
    code = stock_code.strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if code.endswith(suffix):
            code = code[:-3]
            break
    if not code.isdigit() or len(code) != 6:
        return None
    market = _SECID_MARKET.get(code[0])
    if market is None:
        return None
    return f"{market}.{code}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 浏览器服务（单例）
# ---------------------------------------------------------------------------

class EastmoneyBrowserService:
    """
    东财持久浏览器服务（单例）。

    状态机：
      disabled → starting → login_required / ready → requesting → ready
      连续失败 >= 阈值 → degraded；stop() → stopped

    Phase 1 骨架：适配器接口已就绪；真实 Playwright 实现在 Phase 2 接入。
    """

    _instance: Optional["EastmoneyBrowserService"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _FAILURE_THRESHOLD = 3
    _QUEUE_SIZE = 32
    _STOP = object()

    def __init__(
        self,
        config: "Config",
        adapter: Optional[BrowserAdapter] = None,
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._state = BrowserState.DISABLED
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._last_error_type: Optional[str] = None
        self._last_success_at: Optional[str] = None
        self._degraded_at: Optional[float] = None
        self._worker: Optional[threading.Thread] = None
        self._requests: "queue.Queue[Any]" = queue.Queue(maxsize=self._QUEUE_SIZE)
        self._start_event = threading.Event()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # 单例管理
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(
        cls,
        config: Optional["Config"] = None,
        adapter: Optional[BrowserAdapter] = None,
    ) -> "EastmoneyBrowserService":
        """获取或创建单例；测试中可传入 adapter 注入 fake"""
        with cls._instance_lock:
            if cls._instance is None:
                if config is None:
                    from src.config import get_config
                    config = get_config()
                cls._instance = cls(config, adapter)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """仅用于测试：重置单例"""
        with cls._instance_lock:
            if cls._instance is not None:
                try:
                    cls._instance.stop()
                except Exception:
                    pass
            cls._instance = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动专用浏览器线程；所有 Playwright 操作都在该线程执行。"""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            if not self._config.eastmoney_browser_enabled:
                logger.debug("[eastmoney_browser] 配置关闭，保持 disabled")
                return
            if not self._config.eastmoney_browser_profile_dir:
                logger.warning("[eastmoney_browser] PROFILE_DIR 未配置，保持 disabled")
                return
            from src.patches.eastmoney_patch import eastmoney_patch
            eastmoney_patch()
            try:
                self._validate_profile_dir(self._config.eastmoney_browser_profile_dir)
            except Exception as exc:
                self._last_error_type = type(exc).__name__
                self._degraded_at = time.monotonic()
                self._set_state(BrowserState.DEGRADED)
                logger.error("[eastmoney_browser] Profile 目录不可用: %s", exc)
                return
            self._stop_event.clear()
            self._start_event.clear()
            self._requests = queue.Queue(maxsize=self._QUEUE_SIZE)
            self._set_state(BrowserState.STARTING)
            self._worker = threading.Thread(
                target=self._worker_main,
                name="eastmoney-browser-worker",
                daemon=True,
            )
            self._worker.start()

        # start() 可安全地由后台启动线程调用；业务侧 fetch 会继续等待就绪。
        self._start_event.wait(timeout=self._startup_timeout())

    def stop(self) -> None:
        """安全关闭浏览器，保留 Profile"""
        with self._lock:
            if self._state == BrowserState.STOPPED:
                return
            self._set_state(BrowserState.STOPPED)
            worker = self._worker
            self._stop_event.set()
        if worker is not None and worker.is_alive():
            try:
                self._requests.put_nowait(self._STOP)
            except queue.Full:
                # worker 会在当前请求结束后观察 stop_event。
                pass
            if worker is not threading.current_thread():
                worker.join(timeout=self._startup_timeout())
        with self._lock:
            if worker is None or not worker.is_alive():
                self._worker = None
            else:
                logger.warning("[eastmoney_browser] worker 未在关闭预算内退出")
        logger.info("[eastmoney_browser] 已停止")

    # ------------------------------------------------------------------
    # K 线请求
    # ------------------------------------------------------------------

    def fetch_kline(self, stock_code: str, lmt: int = 730) -> Optional[List[str]]:
        """
        获取东财日 K 线原始数据（klines 字符串列表）。
        失败或服务不可用时返回 None，不抛异常（调用方负责 fallback）。
        仅支持 A 股六位代码；ETF / 港股 / 美股直接返回 None。
        """
        secid = _stock_code_to_secid(stock_code)
        if secid is None:
            logger.debug("[eastmoney_browser] %s 无法转换为 secid，跳过", stock_code)
            return None

        if not self._ensure_available():
            return None

        result: "queue.Queue[Tuple[Optional[List[str]], Optional[Exception]]]" = queue.Queue(maxsize=1)
        try:
            self._requests.put(
                ("kline", (secid, min(max(1, int(lmt)), 5000)), result),
                timeout=self._config.eastmoney_browser_request_timeout,
            )
            value, error = result.get(
                timeout=self._config.eastmoney_browser_request_timeout + 1,
            )
        except queue.Full:
            logger.warning("[eastmoney_browser] 请求队列已满，降级: %s", stock_code)
            return None
        except queue.Empty:
            logger.warning("[eastmoney_browser] 请求等待超时，降级: %s", stock_code)
            return None
        if error is not None:
            return None
        logger.info("[eastmoney_browser] %s 成功，共 %d 行", stock_code, len(value or []))
        return value

    def fetch_http(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """代理 AkShare 的东财请求；失败返回 None，由调用层触发 provider fallback。"""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        normalized_method = method.upper()
        if parsed.scheme != "https" or not _is_allowed_eastmoney_hostname(hostname):
            raise ValueError("仅允许代理 HTTPS 东财域名")
        if normalized_method not in {"GET", "POST"}:
            raise ValueError("东财浏览器代理仅支持 GET/POST")
        if len(url) > 16_384 or (body is not None and len(body.encode("utf-8")) > 1_048_576):
            raise ValueError("东财浏览器代理请求过大")
        if not self._ensure_available():
            return None
        safe_headers = self._sanitize_proxy_headers(headers or {})
        result: "queue.Queue[Tuple[Optional[Dict[str, Any]], Optional[Exception]]]" = queue.Queue(maxsize=1)
        try:
            self._requests.put(
                ("http", (normalized_method, url, safe_headers, body), result),
                timeout=self._config.eastmoney_browser_request_timeout,
            )
            value, error = result.get(
                timeout=self._config.eastmoney_browser_request_timeout + 1,
            )
        except (queue.Empty, queue.Full):
            return None
        return None if error is not None else value

    @staticmethod
    def _sanitize_proxy_headers(headers: Dict[str, str]) -> Dict[str, str]:
        excluded = {
            "accept-encoding",
            "authorization",
            "connection",
            "content-length",
            "cookie",
            "host",
            "proxy-authorization",
            "x-api-key",
            "x-auth-token",
        }
        return {
            str(key): str(value)
            for key, value in headers.items()
            if str(key).lower() not in excluded
        }

    def _ensure_available(self) -> bool:
        with self._lock:
            state = self._state
            degraded_at = self._degraded_at
        if state in (BrowserState.DISABLED, BrowserState.STOPPED):
            self.start()
            with self._lock:
                state = self._state
        if state == BrowserState.STARTING:
            self._start_event.wait(timeout=self._startup_timeout())
            with self._lock:
                state = self._state
        if state == BrowserState.DEGRADED and degraded_at is not None:
            cooldown = getattr(self._config, "eastmoney_browser_failure_cooldown", 300)
            if time.monotonic() - degraded_at >= cooldown:
                self.stop()
                self.start()
                with self._lock:
                    state = self._state
        if state not in (BrowserState.READY, BrowserState.REQUESTING):
            logger.debug("[eastmoney_browser] 状态 %s，跳过请求", state.value)
            return False
        return True

    def _worker_main(self) -> None:
        try:
            if self._adapter is None:
                self._adapter = PlaywrightBrowserAdapter(
                    cdp_port=getattr(self._config, "eastmoney_browser_cdp_port", 9227)
                )
            self._adapter.launch(
                profile_dir=self._config.eastmoney_browser_profile_dir,
                executable_path=getattr(self._config, "eastmoney_browser_executable_path", ""),
                headless=getattr(self._config, "eastmoney_browser_headless", False),
            )
            login_ok = self._adapter.check_login()
            with self._lock:
                if self._stop_event.is_set():
                    self._set_state(BrowserState.STOPPED)
                else:
                    self._set_state(BrowserState.READY if login_ok else BrowserState.LOGIN_REQUIRED)
            if self._stop_event.is_set():
                self._safe_close_adapter()
                return
            if not login_ok:
                logger.warning("[eastmoney_browser] Profile 未登录，需在浏览器中登录东财")
            else:
                logger.info("[eastmoney_browser] 已就绪，登录状态正常")
        except Exception as exc:
            with self._lock:
                self._last_error_type = type(exc).__name__
                self._degraded_at = time.monotonic()
                self._set_state(BrowserState.DEGRADED)
            logger.error("[eastmoney_browser] 启动失败: %s", exc)
            self._safe_close_adapter()
            self._start_event.set()
            return
        finally:
            self._start_event.set()

        last_activity = time.monotonic()
        last_session_refresh = last_activity
        while not self._stop_event.is_set():
            try:
                item = self._requests.get(timeout=0.5)
            except queue.Empty:
                with self._lock:
                    state = self._state
                refresh_interval = getattr(
                    self._config,
                    "eastmoney_browser_session_refresh_interval",
                    600,
                )
                now = time.monotonic()
                if (
                    state == BrowserState.READY
                    and refresh_interval > 0
                    and now - last_session_refresh >= refresh_interval
                ):
                    try:
                        login_ok = self._adapter.refresh_session(
                            timeout_seconds=self._config.eastmoney_browser_request_timeout,
                        )
                        last_session_refresh = time.monotonic()
                        last_activity = last_session_refresh
                        with self._lock:
                            self._consecutive_failures = 0
                            self._last_error_type = None
                            self._set_state(
                                BrowserState.READY
                                if login_ok
                                else BrowserState.LOGIN_REQUIRED
                            )
                        if login_ok:
                            logger.debug("[eastmoney_browser] 登录首页会话刷新成功")
                        else:
                            logger.warning("[eastmoney_browser] 首页刷新后登录会话无效")
                    except Exception as exc:
                        last_session_refresh = time.monotonic()
                        self._record_failure(exc)
                if state == BrowserState.LOGIN_REQUIRED:
                    try:
                        if self._adapter.check_login():
                            with self._lock:
                                self._set_state(BrowserState.READY)
                            logger.info("[eastmoney_browser] 检测到有效登录会话，服务已就绪")
                    except Exception as exc:
                        logger.debug("[eastmoney_browser] 登录状态复检失败: %s", type(exc).__name__)
                idle_timeout = getattr(self._config, "eastmoney_browser_idle_timeout", 1800)
                if idle_timeout > 0 and time.monotonic() - last_activity >= idle_timeout:
                    with self._lock:
                        self._degraded_at = time.monotonic()
                        self._set_state(BrowserState.DEGRADED)
                    logger.info("[eastmoney_browser] 空闲超时，浏览器已关闭")
                    break
                continue
            if item is self._STOP:
                break
            operation, payload, result = item
            last_activity = time.monotonic()
            try:
                with self._lock:
                    self._set_state(BrowserState.REQUESTING)
                if not self._adapter.check_login():
                    with self._lock:
                        self._set_state(BrowserState.LOGIN_REQUIRED)
                    raise PermissionError("东财登录会话已失效")
                if operation == "kline":
                    secid, lmt = payload
                    resp = self._adapter.fetch_kline(
                        secid=secid,
                        lmt=lmt,
                        timeout_seconds=self._config.eastmoney_browser_request_timeout,
                    )
                    value: Any = self._validate_kline_response(resp)
                elif operation == "http":
                    method, url, headers, body = payload
                    value = self._adapter.fetch_http(
                        method=method,
                        url=url,
                        headers=headers,
                        body=body,
                        timeout_seconds=self._config.eastmoney_browser_request_timeout,
                    )
                    value = self._validate_http_response(value)
                else:
                    raise ValueError("未知东财浏览器请求类型")
                with self._lock:
                    self._consecutive_failures = 0
                    self._last_error_type = None
                    self._last_success_at = _utc_now()
                    self._set_state(BrowserState.READY)
                result.put((value, None))
            except Exception as exc:
                self._record_failure(exc)
                result.put((None, exc))
        self._safe_close_adapter()

    def _record_failure(self, exc: Exception) -> None:
        with self._lock:
            if isinstance(exc, PermissionError):
                self._last_error_type = type(exc).__name__
                self._set_state(BrowserState.LOGIN_REQUIRED)
                logger.warning("[eastmoney_browser] 登录会话失效，等待用户重新登录")
                return
            self._consecutive_failures += 1
            self._last_error_type = type(exc).__name__
            if self._consecutive_failures >= self._FAILURE_THRESHOLD:
                self._degraded_at = time.monotonic()
                self._set_state(BrowserState.DEGRADED)
            else:
                self._set_state(BrowserState.READY)
        logger.warning("[eastmoney_browser] 请求失败 (%d/%d): %s",
                       self._consecutive_failures, self._FAILURE_THRESHOLD, exc)

    def _safe_close_adapter(self) -> None:
        if self._adapter is not None:
            try:
                self._adapter.close()
            except Exception as exc:
                logger.warning("[eastmoney_browser] 关闭时异常: %s", exc)

    def _startup_timeout(self) -> int:
        return max(16, self._config.eastmoney_browser_request_timeout + 3)

    @staticmethod
    def _validate_profile_dir(profile_dir: str) -> None:
        path = Path(profile_dir).expanduser().resolve()
        repository = Path(__file__).resolve().parents[2]
        if path == repository or repository in path.parents:
            raise ValueError("EASTMONEY_BROWSER_PROFILE_DIR 必须位于仓库外")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            logger.warning("[eastmoney_browser] 无法将 Profile 目录权限设置为 0700")

    @staticmethod
    def _validate_kline_response(resp: Dict[str, Any]) -> List[str]:
        if not isinstance(resp, dict) or resp.get("rc") != 0:
            raise ValueError("东财 K 线响应状态异常")
        data = resp.get("data")
        klines = data.get("klines") if isinstance(data, dict) else None
        if not isinstance(klines, list) or not klines or len(klines) > 5000:
            raise ValueError("东财 K 线数组为空或行数异常")
        previous_date = ""
        validated: List[str] = []
        for line in klines:
            if not isinstance(line, str) or len(line) > 512:
                raise ValueError("东财 K 线行类型或长度异常")
            parts = line.split(",")
            if len(parts) != 11 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
                raise ValueError("东财 K 线字段数或日期异常")
            values = [float(value) for value in parts[1:]]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("东财 K 线包含非有限数值")
            open_price, close_price, high_price, low_price = values[:4]
            turnover = values[9]
            if min(open_price, close_price, high_price, low_price) <= 0:
                raise ValueError("东财 K 线价格必须为正数")
            if high_price < max(open_price, close_price, low_price) or low_price > min(open_price, close_price):
                raise ValueError("东财 K 线 OHLC 关系异常")
            if turnover < 0 or turnover > 100:
                raise ValueError("东财 K 线换手率异常")
            if previous_date and parts[0] <= previous_date:
                raise ValueError("东财 K 线日期未严格递增")
            previous_date = parts[0]
            validated.append(line)
        return validated

    @staticmethod
    def _validate_http_response(resp: Dict[str, Any]) -> Dict[str, Any]:
        from urllib.parse import urlparse

        if not isinstance(resp, dict):
            raise ValueError("东财浏览器代理响应类型异常")
        status_code = resp.get("status_code")
        body = resp.get("body")
        headers = resp.get("headers")
        url = resp.get("url")
        if not isinstance(status_code, int) or not 100 <= status_code <= 599:
            raise ValueError("东财浏览器代理 HTTP 状态异常")
        if not isinstance(body, str) or len(body.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            raise ValueError("东财浏览器代理响应体异常")
        if not isinstance(headers, dict) or not isinstance(url, str):
            raise ValueError("东财浏览器代理响应元数据异常")
        hostname = (urlparse(url).hostname or "").lower()
        if not _is_allowed_eastmoney_hostname(hostname):
            raise ValueError("东财浏览器代理响应跳转到非允许域名")
        excluded_headers = {"content-encoding", "content-length", "set-cookie", "set-cookie2"}
        safe_response_headers = {
            str(key): str(value)
            for key, value in headers.items()
            if str(key).lower() not in excluded_headers
        }
        return {
            "status_code": status_code,
            "body": body,
            "headers": safe_response_headers,
            "url": url,
        }

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """返回低敏状态摘要（不含 Cookie、Profile 路径、账号信息）"""
        with self._lock:
            return {
                "enabled": self._config.eastmoney_browser_enabled,
                "state": self._state.value,
                "browser_running": self._worker is not None and self._worker.is_alive(),
                "login_required": self._state == BrowserState.LOGIN_REQUIRED,
                "last_success_at": self._last_success_at,
                "last_error_type": self._last_error_type,
            }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _set_state(self, new_state: BrowserState) -> None:
        """更新状态（调用前须持有 _lock）"""
        old = self._state
        self._state = new_state
        if old != new_state:
            logger.debug("[eastmoney_browser] %s → %s", old.value, new_state.value)


# ---------------------------------------------------------------------------
# PlaywrightBrowserAdapter（Phase 2）
# ---------------------------------------------------------------------------

_CHROME_EXECUTABLE = "/usr/bin/google-chrome"
_KLINE_DOMAIN = "push2his.eastmoney.com"
_SECID_RE = re.compile(r"^\d\.\d{6}$")
_LOGIN_COOKIE_NAMES = {"ct", "pi", "uidal"}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class PlaywrightBrowserAdapter(BrowserAdapter):
    """
    Phase 2：先正常启动 Chrome（无 Playwright 自动化 flag），
    再用 connect_over_cdp() 接管——保留 Chrome 原生 TLS 指纹。

    启动流程：
      1. subprocess 启动 Chrome + --remote-debugging-port
      2. 等待 CDP endpoint 就绪
      3. playwright.chromium.connect_over_cdp() 接管
      4. 取第一个 context / page 供请求使用
    """

    def __init__(self, cdp_port: int = 9227) -> None:
        self._cdp_port = cdp_port
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._chrome_proc = None
        self._profile_lock = None

    @staticmethod
    def _wait_for_cdp_port_available(port: int, timeout_seconds: float = 5.0) -> None:
        """等待上一 Chrome 进程释放 CDP 端口，同时仍拒绝外部端口占用。"""
        import socket

        deadline = time.monotonic() + timeout_seconds
        last_error: Optional[OSError] = None
        while True:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", port))
                return
            except OSError as exc:
                last_error = exc
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Chrome CDP 端口已被占用: {port}") from last_error
                time.sleep(0.1)
            finally:
                probe.close()

    def launch(self, profile_dir: str, executable_path: str, headless: bool) -> None:
        import fcntl, os, subprocess, time
        import urllib.request
        from playwright.sync_api import sync_playwright

        exe = executable_path or os.environ.get("CHROME_PATH") or _CHROME_EXECUTABLE
        if not Path(exe).is_file():
            raise FileNotFoundError(f"Chrome 可执行文件不存在: {exe}")
        lock_path = Path(profile_dir) / ".dsa-eastmoney-browser.lock"
        self._profile_lock = lock_path.open("a+")
        try:
            fcntl.flock(self._profile_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._profile_lock.close()
            self._profile_lock = None
            raise RuntimeError("东财浏览器 Profile 已被其他进程占用") from exc
        self._wait_for_cdp_port_available(self._cdp_port)
        cmd = [
            exe,
            f"--remote-debugging-port={self._cdp_port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if headless:
            cmd.append("--headless=new")

        env = os.environ.copy()
        env.setdefault("DISPLAY", ":0")

        self._chrome_proc = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # 等 CDP 就绪（最多 15 秒）
        cdp_url = f"http://127.0.0.1:{self._cdp_port}/json"
        for _ in range(30):
            try:
                urllib.request.urlopen(cdp_url, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError(f"Chrome CDP 未就绪: {cdp_url}")

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self._cdp_port}"
        )
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else self._browser.new_context()
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        logger.info("[PlaywrightBrowserAdapter] CDP 连接成功，port=%d", self._cdp_port)
        # 热身导航：访问东财主页建立正常浏览器状态（TLS session / Cookie）
        try:
            self._page.goto(
                "https://www.eastmoney.com",
                timeout=15_000,
                wait_until="domcontentloaded",
            )
            logger.info("[PlaywrightBrowserAdapter] 热身导航完成")
        except Exception as exc:
            logger.warning("[PlaywrightBrowserAdapter] 热身导航失败（不影响启动）: %s", exc)

    def check_login(self) -> bool:
        """只检查账号会话 Cookie 名是否存在，不读取或记录 Cookie 值。"""
        cookies = self._context.cookies(["https://www.eastmoney.com"])
        names = {item.get("name") for item in cookies}
        return bool(names.intersection(_LOGIN_COOKIE_NAMES))

    def refresh_session(self, timeout_seconds: int) -> bool:
        """访问登录后的东财首页，让 Chrome 更新站点 Cookie 和会话活动时间。"""
        self._page.goto(
            "https://www.eastmoney.com",
            timeout=timeout_seconds * 1_000,
            wait_until="domcontentloaded",
        )
        return self.check_login()

    def fetch_kline(self, secid: str, lmt: int, timeout_seconds: int) -> Dict[str, Any]:
        """
        page.goto() 直接导航至东财 K 线 API——走 Chrome 原生网络栈，
        TLS 指纹与用户手动访问地址栏完全一致。
        """
        import json as _json
        if not _SECID_RE.match(secid):
            raise ValueError(f"secid 格式非法: {secid!r}")
        lmt = min(max(1, int(lmt)), 5000)
        url = (
            f"https://{_KLINE_DOMAIN}/api/qt/stock/kline/get"
            f"?secid={secid}"
            "&ut=fa5fd1943c7b386f172d6893dbfba10b"
            "&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            "&klt=101&fqt=0&end=20991231"
            f"&lmt={lmt}"
        )
        resp = self._page.goto(
            url, timeout=timeout_seconds * 1_000, wait_until="commit"
        )
        if resp is None:
            raise RuntimeError("page.goto 无响应")
        if not resp.ok:
            raise RuntimeError(f"东财 K 线 HTTP 状态异常: {resp.status}")
        text = resp.text()
        if len(text.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            raise ValueError("东财 K 线响应体过大")
        return _json.loads(text)

    def fetch_http(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[str],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """使用当前 Chrome page 发出 AkShare 的受限东财 GET/POST 请求。"""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if method == "GET":
            response = self._page.goto(
                url,
                timeout=timeout_seconds * 1_000,
                wait_until="commit",
            )
            if response is None:
                raise RuntimeError("东财浏览器代理 GET 无响应")
            return {
                "status_code": response.status,
                "headers": response.all_headers(),
                "body": response.text(),
                "url": response.url,
            }

        current = urlparse(self._page.url)
        if (current.scheme, current.netloc) != (parsed.scheme, parsed.netloc):
            self._page.goto(
                url,
                timeout=timeout_seconds * 1_000,
                wait_until="commit",
            )
            current = urlparse(self._page.url)
            if (current.scheme, current.netloc) != (parsed.scheme, parsed.netloc):
                raise RuntimeError("无法建立东财 POST 同源页面")
        return self._page.evaluate(
            """async ({method, url, headers, body, timeoutMs}) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                try {
                    const response = await fetch(url, {
                        method,
                        headers,
                        body,
                        credentials: 'include',
                        redirect: 'error',
                        signal: controller.signal,
                    });
                    const responseBody = await response.text();
                    return {
                        status_code: response.status,
                        headers: Object.fromEntries(response.headers.entries()),
                        body: responseBody,
                        url: response.url,
                    };
                } finally {
                    clearTimeout(timer);
                }
            }""",
            {
                "url": url,
                "method": method,
                "headers": headers,
                "body": None if method == "GET" else body,
                "timeoutMs": timeout_seconds * 1_000,
            },
        )

    def close(self) -> None:
        import subprocess

        for attr, method, label in [
            ("_browser", "close", "browser.close"),
            ("_pw",      "stop",  "playwright.stop"),
        ]:
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception as exc:
                    logger.warning("[PlaywrightBrowserAdapter] %s: %s", label, exc)
                setattr(self, attr, None)
        self._context = None
        self._page = None
        if self._chrome_proc is not None:
            try:
                self._chrome_proc.terminate()
                self._chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_proc.kill()
                self._chrome_proc.wait(timeout=5)
            except Exception as exc:
                logger.warning("[PlaywrightBrowserAdapter] chrome.terminate: %s", exc)
            self._chrome_proc = None
        if self._profile_lock is not None:
            try:
                self._profile_lock.close()
            except Exception as exc:
                logger.warning("[PlaywrightBrowserAdapter] profile lock close: %s", exc)
            self._profile_lock = None
