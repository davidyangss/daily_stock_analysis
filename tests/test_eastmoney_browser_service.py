# -*- coding: utf-8 -*-
"""
离线单元测试：EastmoneyBrowserService（Phase 1 骨架）
不启动真实浏览器，全部使用 FakeBrowserAdapter。
"""
import pytest
from unittest.mock import MagicMock

from src.services.eastmoney_browser_service import (
    BrowserState,
    EastmoneyBrowserService,
    FakeBrowserAdapter,
    _stock_code_to_secid,
)


def _make_config(**kwargs):
    cfg = MagicMock()
    cfg.eastmoney_browser_enabled = kwargs.get("enabled", False)
    cfg.eastmoney_browser_profile_dir = kwargs.get("profile_dir", "")
    cfg.eastmoney_browser_request_timeout = kwargs.get("request_timeout", 12)
    cfg.eastmoney_browser_idle_timeout = kwargs.get("idle_timeout", 1800)
    return cfg


@pytest.fixture(autouse=True)
def reset_singleton():
    EastmoneyBrowserService.reset_instance()
    yield
    EastmoneyBrowserService.reset_instance()


# ---------------------------------------------------------------------------
# 配置默认关闭
# ---------------------------------------------------------------------------

class TestDefaultDisabled:
    def test_disabled_when_config_false(self):
        svc = EastmoneyBrowserService(_make_config(enabled=False))
        svc.start()
        assert svc.get_status()["state"] == BrowserState.DISABLED.value

    def test_disabled_when_profile_dir_empty(self):
        svc = EastmoneyBrowserService(_make_config(enabled=True, profile_dir=""))
        svc.start()
        assert svc.get_status()["state"] == BrowserState.DISABLED.value

    def test_disabled_when_adapter_creation_fails(self):
        # Phase 2：adapter=None 会自动创建 PlaywrightBrowserAdapter；
        # 若创建过程抛异常（如 playwright 未安装），服务保持 disabled
        from unittest.mock import patch
        with patch(
            "src.services.eastmoney_browser_service.PlaywrightBrowserAdapter",
            side_effect=RuntimeError("playwright missing"),
        ):
            svc = EastmoneyBrowserService(
                _make_config(enabled=True, profile_dir="/some/path"), adapter=None
            )
            svc.start()
            assert svc.get_status()["state"] == BrowserState.DISABLED.value


# ---------------------------------------------------------------------------
# 状态机转换
# ---------------------------------------------------------------------------

class TestStateMachine:
    def _enabled_svc(self, **adapter_kwargs):
        adapter = FakeBrowserAdapter(**adapter_kwargs)
        svc = EastmoneyBrowserService(
            _make_config(enabled=True, profile_dir="/tmp/test-profile"),
            adapter=adapter,
        )
        return svc, adapter

    def test_start_ready_when_login_ok(self):
        svc, _ = self._enabled_svc(login_ok=True)
        svc.start()
        assert svc.get_status()["state"] == BrowserState.READY.value

    def test_start_login_required_when_not_logged_in(self):
        svc, _ = self._enabled_svc(login_ok=False)
        svc.start()
        assert svc.get_status()["state"] == BrowserState.LOGIN_REQUIRED.value
        assert svc.get_status()["login_required"] is True

    def test_stop_transitions_to_stopped(self):
        svc, adapter = self._enabled_svc(login_ok=True)
        svc.start()
        svc.stop()
        assert svc.get_status()["state"] == BrowserState.STOPPED.value
        assert adapter.closed is True

    def test_stop_idempotent(self):
        svc, _ = self._enabled_svc(login_ok=True)
        svc.start()
        svc.stop()
        svc.stop()  # 不应抛异常
        assert svc.get_status()["state"] == BrowserState.STOPPED.value

    def test_degraded_after_consecutive_failures(self):
        err = RuntimeError("timeout")
        svc, _ = self._enabled_svc(login_ok=True, raise_on_fetch=err)
        svc.start()
        for _ in range(EastmoneyBrowserService._FAILURE_THRESHOLD):
            svc.fetch_kline("600519")
        assert svc.get_status()["state"] == BrowserState.DEGRADED.value
        assert svc.get_status()["last_error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# fetch_kline 正常路径
# ---------------------------------------------------------------------------

class TestFetchKline:
    def _ready_svc(self, **adapter_kwargs):
        adapter = FakeBrowserAdapter(**adapter_kwargs)
        svc = EastmoneyBrowserService(
            _make_config(enabled=True, profile_dir="/tmp/test-profile"),
            adapter=adapter,
        )
        svc.start()
        return svc, adapter

    def test_returns_klines_on_success(self):
        svc, _ = self._ready_svc()
        result = svc.fetch_kline("600519")
        assert result is not None
        assert len(result) > 0

    def test_returns_none_when_disabled(self):
        svc = EastmoneyBrowserService(_make_config(enabled=False))
        assert svc.fetch_kline("600519") is None

    def test_returns_none_when_login_required(self):
        svc, _ = self._ready_svc(login_ok=False)
        # login_required 状态下不请求
        assert svc.get_status()["state"] == BrowserState.LOGIN_REQUIRED.value
        assert svc.fetch_kline("600519") is None

    def test_returns_none_on_fetch_error(self):
        svc, _ = self._ready_svc(raise_on_fetch=ConnectionError("reset"))
        result = svc.fetch_kline("600519")
        assert result is None

    def test_returns_none_for_us_code(self):
        svc, _ = self._ready_svc()
        assert svc.fetch_kline("AAPL") is None

    def test_returns_none_for_hk_code(self):
        svc, _ = self._ready_svc()
        assert svc.fetch_kline("hk00700") is None


# ---------------------------------------------------------------------------
# secid 转换辅助函数
# ---------------------------------------------------------------------------

class TestStockCodeToSecid:
    def test_sh_code(self):
        assert _stock_code_to_secid("600519") == "1.600519"

    def test_sz_code(self):
        assert _stock_code_to_secid("000001") == "0.000001"

    def test_sh_with_suffix(self):
        assert _stock_code_to_secid("600519.SH") == "1.600519"

    def test_sz_with_suffix(self):
        assert _stock_code_to_secid("300750.SZ") == "0.300750"

    def test_us_code_returns_none(self):
        assert _stock_code_to_secid("AAPL") is None

    def test_hk_code_returns_none(self):
        assert _stock_code_to_secid("00700") is None  # 5 位，非 A 股

    def test_empty_returns_none(self):
        assert _stock_code_to_secid("") is None
