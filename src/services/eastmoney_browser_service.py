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
import re
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.launched = False
        self.closed = False
        self.login_ok = login_ok
        self._kline_response = kline_response or {
            "rc": 0,
            "data": {"klines": ["2026-07-29,10.00,10.50,9.80,10.20,1000000,0.05"]},
        }
        self._raise_on_fetch = raise_on_fetch

    def launch(self, profile_dir: str, executable_path: str, headless: bool) -> None:
        self.launched = True
        self.profile_dir = profile_dir

    def check_login(self) -> bool:
        return self.login_ok

    def fetch_kline(self, secid: str, lmt: int, timeout_seconds: int) -> Dict[str, Any]:
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        return self._kline_response

    def close(self) -> None:
        self.closed = True


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
        """启动浏览器服务；配置关闭或无 adapter 时保持 disabled"""
        with self._lock:
            if self._state not in (BrowserState.DISABLED, BrowserState.STOPPED):
                return
            if not self._config.eastmoney_browser_enabled:
                logger.debug("[eastmoney_browser] 配置关闭，保持 disabled")
                return
            if not self._config.eastmoney_browser_profile_dir:
                logger.warning("[eastmoney_browser] PROFILE_DIR 未配置，保持 disabled")
                return
            if self._adapter is None:
                try:
                    self._adapter = PlaywrightBrowserAdapter()
                except Exception as exc:
                    logger.warning("[eastmoney_browser] 无法创建适配器: %s", exc)
                    return
            self._set_state(BrowserState.STARTING)

        try:
            self._adapter.launch(
                profile_dir=self._config.eastmoney_browser_profile_dir,
                executable_path="/usr/bin/google-chrome",
                headless=False,
            )
            login_ok = self._adapter.check_login()
            with self._lock:
                if login_ok:
                    self._set_state(BrowserState.READY)
                    logger.info("[eastmoney_browser] 已就绪，登录状态正常")
                else:
                    self._set_state(BrowserState.LOGIN_REQUIRED)
                    logger.warning("[eastmoney_browser] Profile 未登录，需手动登录东财")
        except Exception as exc:
            with self._lock:
                self._last_error_type = type(exc).__name__
                self._set_state(BrowserState.DEGRADED)
            logger.error("[eastmoney_browser] 启动失败: %s", exc)

    def stop(self) -> None:
        """安全关闭浏览器，保留 Profile"""
        with self._lock:
            if self._state == BrowserState.STOPPED:
                return
            self._set_state(BrowserState.STOPPED)
        if self._adapter is not None:
            try:
                self._adapter.close()
            except Exception as exc:
                logger.warning("[eastmoney_browser] 关闭时异常: %s", exc)
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
        with self._lock:
            state = self._state
        if state not in (BrowserState.READY,):
            logger.debug("[eastmoney_browser] 状态 %s，跳过 %s", state, stock_code)
            return None

        secid = _stock_code_to_secid(stock_code)
        if secid is None:
            logger.debug("[eastmoney_browser] %s 无法转换为 secid，跳过", stock_code)
            return None

        with self._lock:
            self._set_state(BrowserState.REQUESTING)

        try:
            resp = self._adapter.fetch_kline(  # type: ignore[union-attr]
                secid=secid,
                lmt=lmt,
                timeout_seconds=self._config.eastmoney_browser_request_timeout,
            )
            rc = resp.get("rc")
            klines = resp.get("data", {}).get("klines")
            if rc != 0 or not isinstance(klines, list) or len(klines) == 0:
                raise ValueError(f"响应异常: rc={rc}, klines={str(klines)[:80]}")
            with self._lock:
                self._consecutive_failures = 0
                self._last_success_at = _utc_now()
                self._set_state(BrowserState.READY)
            logger.info("[eastmoney_browser] %s 成功，共 %d 行", stock_code, len(klines))
            return klines
        except Exception as exc:
            with self._lock:
                self._consecutive_failures += 1
                self._last_error_type = type(exc).__name__
                if self._consecutive_failures >= self._FAILURE_THRESHOLD:
                    self._set_state(BrowserState.DEGRADED)
                    logger.warning("[eastmoney_browser] 连续失败 %d 次，进入 degraded: %s",
                                   self._consecutive_failures, exc)
                else:
                    self._set_state(BrowserState.READY)
                    logger.warning("[eastmoney_browser] 请求失败 (%d/%d): %s",
                                   self._consecutive_failures, self._FAILURE_THRESHOLD, exc)
            return None

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """返回低敏状态摘要（不含 Cookie、Profile 路径、账号信息）"""
        with self._lock:
            return {
                "enabled": self._config.eastmoney_browser_enabled,
                "state": self._state.value,
                "browser_running": self._state not in (
                    BrowserState.DISABLED, BrowserState.STOPPED,
                ),
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

    _CDP_PORT = 9227  # 非标准端口，避免与用户 Chrome 冲突

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._chrome_proc = None

    def launch(self, profile_dir: str, executable_path: str, headless: bool) -> None:
        import os, subprocess, time
        import urllib.request
        from playwright.sync_api import sync_playwright

        exe = executable_path or _CHROME_EXECUTABLE
        cmd = [
            exe,
            f"--remote-debugging-port={self._CDP_PORT}",
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
        cdp_url = f"http://localhost:{self._CDP_PORT}/json"
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
            f"http://localhost:{self._CDP_PORT}"
        )
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else self._browser.new_context()
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        logger.info("[PlaywrightBrowserAdapter] CDP 连接成功，port=%d", self._CDP_PORT)

    def check_login(self) -> bool:
        """
        东财 K 线 API 不要求账号 Cookie，浏览器启动后即视为可用。
        实际可用性由 fetch_kline 的连续失败计数驱动熔断，不在此探测。
        """
        logger.debug("[PlaywrightBrowserAdapter] check_login → True (no auth required)")
        return True
            logger.warning("[PlaywrightBrowserAdapter] check_login 异常: %s", exc)
            return False

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
        text = resp.text()
        return _json.loads(text)

    def close(self) -> None:
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
            except Exception as exc:
                logger.warning("[PlaywrightBrowserAdapter] chrome.terminate: %s", exc)
            self._chrome_proc = None

