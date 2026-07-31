# -*- coding: utf-8 -*-
"""
离线单元测试：EastmoneyBrowserService（Phase 1 骨架）
不启动真实浏览器，全部使用 FakeBrowserAdapter。
"""
import pytest
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from src.services.eastmoney_browser_service import (
    BrowserState,
    EastmoneyBrowserService,
    FakeBrowserAdapter,
    PlaywrightBrowserAdapter,
    _stock_code_to_secid,
)


def _make_config(**kwargs):
    cfg = MagicMock()
    cfg.eastmoney_browser_enabled = kwargs.get("enabled", False)
    cfg.eastmoney_browser_profile_dir = kwargs.get("profile_dir", "")
    cfg.eastmoney_browser_request_timeout = kwargs.get("request_timeout", 12)
    cfg.eastmoney_browser_idle_timeout = kwargs.get("idle_timeout", 1800)
    cfg.eastmoney_browser_session_refresh_interval = kwargs.get(
        "session_refresh_interval", 600
    )
    cfg.eastmoney_browser_failure_cooldown = kwargs.get("failure_cooldown", 300)
    cfg.eastmoney_browser_executable_path = kwargs.get("executable_path", "")
    cfg.eastmoney_browser_headless = kwargs.get("headless", False)
    cfg.eastmoney_browser_cdp_port = kwargs.get("cdp_port", 9227)
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

    def test_degraded_when_adapter_creation_fails(self, tmp_path):
        # Phase 2：adapter=None 会自动创建 PlaywrightBrowserAdapter；
        # 若创建过程抛异常（如 playwright 未安装），服务进入 degraded
        from unittest.mock import patch
        with patch(
            "src.services.eastmoney_browser_service.PlaywrightBrowserAdapter",
            side_effect=RuntimeError("playwright missing"),
        ):
            svc = EastmoneyBrowserService(
                _make_config(enabled=True, profile_dir=str(tmp_path / "profile")), adapter=None
            )
            svc.start()
            assert svc.get_status()["state"] == BrowserState.DEGRADED.value
            assert svc.get_status()["last_error_type"] == "RuntimeError"


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

    def test_lazy_start_supports_non_fastapi_entrypoints(self, tmp_path):
        adapter = FakeBrowserAdapter()
        svc = EastmoneyBrowserService(
            _make_config(enabled=True, profile_dir=str(tmp_path / "profile")),
            adapter=adapter,
        )
        assert svc.fetch_kline("600519") is not None
        assert svc.get_status()["state"] == BrowserState.READY.value

    def test_concurrent_requests_are_serialized_on_adapter_thread(self):
        svc, adapter = self._ready_svc()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(svc.fetch_kline, ["600519", "000001", "300750", "600000"]))
        svc.stop()
        assert all(result for result in results)
        assert len(set(adapter.thread_ids)) == 1

    def test_login_state_recovers_after_manual_login(self):
        svc, adapter = self._ready_svc(login_ok=False)
        assert svc.get_status()["state"] == BrowserState.LOGIN_REQUIRED.value
        adapter.login_ok = True
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if svc.get_status()["state"] == BrowserState.READY.value:
                break
            time.sleep(0.05)
        assert svc.get_status()["state"] == BrowserState.READY.value

    def test_ready_session_refreshes_homepage_on_worker_thread(self):
        adapter = FakeBrowserAdapter()
        svc = EastmoneyBrowserService(
            _make_config(
                enabled=True,
                profile_dir="/tmp/test-profile",
                session_refresh_interval=1,
            ),
            adapter=adapter,
        )
        svc.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and adapter.session_refresh_count == 0:
            time.sleep(0.05)
        svc.stop()
        assert adapter.session_refresh_count >= 1
        assert len(set(adapter.thread_ids)) == 1

    def test_session_refresh_can_be_disabled(self):
        adapter = FakeBrowserAdapter()
        svc = EastmoneyBrowserService(
            _make_config(
                enabled=True,
                profile_dir="/tmp/test-profile",
                session_refresh_interval=0,
            ),
            adapter=adapter,
        )
        svc.start()
        time.sleep(0.7)
        assert adapter.session_refresh_count == 0

    def test_session_refresh_detects_expired_login(self):
        adapter = FakeBrowserAdapter()
        svc = EastmoneyBrowserService(
            _make_config(
                enabled=True,
                profile_dir="/tmp/test-profile",
                session_refresh_interval=1,
            ),
            adapter=adapter,
        )
        svc.start()
        adapter.login_ok = False
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if svc.get_status()["state"] == BrowserState.LOGIN_REQUIRED.value:
                break
            time.sleep(0.05)
        assert svc.get_status()["state"] == BrowserState.LOGIN_REQUIRED.value

    def test_expired_login_transitions_to_login_required(self):
        svc, adapter = self._ready_svc()
        adapter.login_ok = False
        assert svc.fetch_kline("600519") is None
        assert svc.get_status()["state"] == BrowserState.LOGIN_REQUIRED.value

    def test_degraded_service_restarts_after_cooldown(self):
        svc, adapter = self._ready_svc(raise_on_fetch=RuntimeError("temporary"))
        svc._config.eastmoney_browser_failure_cooldown = 0
        for _ in range(EastmoneyBrowserService._FAILURE_THRESHOLD):
            assert svc.fetch_kline("600519") is None
        adapter._raise_on_fetch = None
        assert svc.fetch_kline("600519") is not None
        assert svc.get_status()["state"] == BrowserState.READY.value

    def test_http_proxy_uses_worker_and_strips_sensitive_headers(self):
        svc, adapter = self._ready_svc()
        response = svc.fetch_http(
            "GET",
            "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer secret",
                "Cookie": "session=secret",
                "X-Api-Key": "drop-me",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        assert response["status_code"] == 200
        assert adapter.http_requests == [{
            "method": "GET",
            "url": "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1",
            "headers": {
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            "body": None,
        }]
        assert len(set(adapter.thread_ids)) == 1

    def test_http_proxy_never_returns_cookie_or_stale_encoding_headers(self):
        svc, _ = self._ready_svc(http_response={
            "status_code": 200,
            "headers": {
                "content-type": "application/json",
                "content-encoding": "gzip",
                "content-length": "999",
                "set-cookie": "session=secret",
            },
            "body": '{"ok":true}',
            "url": "https://push2.eastmoney.com/api/test",
        })
        response = svc.fetch_http("GET", "https://push2.eastmoney.com/api/test")
        assert response["headers"] == {"content-type": "application/json"}

    @pytest.mark.parametrize("url", [
        "http://push2.eastmoney.com/api/test",
        "https://eastmoney.com.evil.example/api/test",
        "https://example.com/?next=eastmoney.com",
    ])
    def test_http_proxy_rejects_non_allowed_urls(self, url):
        svc, adapter = self._ready_svc()
        with pytest.raises(ValueError):
            svc.fetch_http("GET", url)
        assert adapter.http_requests == []

    def test_http_proxy_supports_post_body(self):
        svc, adapter = self._ready_svc()
        response = svc.fetch_http(
            "POST",
            "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
            headers={"Content-Type": "application/json"},
            body='{"pageNo":1}',
        )
        assert response is not None
        assert adapter.http_requests[0]["body"] == '{"pageNo":1}'

    def test_http_proxy_allows_eastmoney_futures_domain(self):
        svc, adapter = self._ready_svc()
        response = svc.fetch_http(
            "GET",
            "https://portal.eastmoneyfutures.com/api/test",
        )
        assert response is not None
        assert adapter.http_requests[0]["url"] == (
            "https://portal.eastmoneyfutures.com/api/test"
        )

    @pytest.mark.parametrize("line", [
        "2026-07-29,10,10,10,9,100",  # 字段不足
        "2026-07-29,10,10,9,11,100,1000,1,1,1,1",  # high/low 非法
        "2026-07-29,10,10,10,9,100,1000,1,1,1,101",  # 换手率非法
    ])
    def test_rejects_malformed_kline_rows(self, line):
        svc, _ = self._ready_svc(kline_response={"rc": 0, "data": {"klines": [line]}})
        assert svc.fetch_kline("600519") is None


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


class TestPlaywrightLoginDetection:
    def test_wait_for_cdp_port_tolerates_delayed_release(self):
        first_probe = MagicMock()
        first_probe.bind.side_effect = OSError("still occupied")
        second_probe = MagicMock()
        with patch("socket.socket", side_effect=[first_probe, second_probe]):
            PlaywrightBrowserAdapter._wait_for_cdp_port_available(
                9227,
                timeout_seconds=1,
            )
        first_probe.close.assert_called_once()
        second_probe.bind.assert_called_once_with(("127.0.0.1", 9227))
        second_probe.close.assert_called_once()

    def test_wait_for_cdp_port_rejects_persistent_owner(self):
        probe = MagicMock()
        probe.bind.side_effect = OSError("occupied")
        with patch("socket.socket", return_value=probe):
            with pytest.raises(RuntimeError, match="9227"):
                PlaywrightBrowserAdapter._wait_for_cdp_port_available(
                    9227,
                    timeout_seconds=0,
                )
        probe.close.assert_called_once()

    @pytest.mark.parametrize("cookie_name", ["ct", "pi", "uidal"])
    def test_known_account_cookie_marks_profile_logged_in(self, cookie_name):
        adapter = PlaywrightBrowserAdapter()
        adapter._context = MagicMock()
        adapter._context.cookies.return_value = [{"name": cookie_name, "value": "secret"}]
        assert adapter.check_login() is True

    def test_anonymous_cookie_does_not_mark_profile_logged_in(self):
        adapter = PlaywrightBrowserAdapter()
        adapter._context = MagicMock()
        adapter._context.cookies.return_value = [{"name": "qgqp_b_id", "value": "anonymous"}]
        assert adapter.check_login() is False
