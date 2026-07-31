import requests
import json

import akshare as ak

from src.patches.eastmoney_patch import _browser_request, _eastmoney_browser_url
from src.services.eastmoney_browser_service import EastmoneyBrowserService


def test_browser_request_returns_requests_compatible_response(monkeypatch):
    class Service:
        def fetch_http(self, **kwargs):
            assert kwargs == {
                "method": "POST",
                "url": "https://emappdata.eastmoney.com/stockrank/getAllCurrentList?page=1",
                "headers": {
                    "Content-Length": "13",
                    "Content-Type": "application/json",
                },
                "body": '{"pageNo": 1}',
            }
            return {
                "status_code": 200,
                "headers": {"content-type": "application/json; charset=utf-8"},
                "body": '{"data": [1]}',
                "url": "https://emappdata.eastmoney.com/stockrank/getAllCurrentList?page=1",
            }

    monkeypatch.setattr(EastmoneyBrowserService, "get_instance", lambda: Service())
    response = _browser_request(
        "POST",
        "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
        {"params": {"page": 1}, "json": {"pageNo": 1}},
    )

    assert isinstance(response, requests.Response)
    assert response.ok
    assert response.json() == {"data": [1]}
    assert response.request.method == "POST"


def test_browser_request_fails_closed_when_browser_unavailable(monkeypatch):
    class Service:
        def fetch_http(self, **kwargs):
            return None

    monkeypatch.setattr(EastmoneyBrowserService, "get_instance", lambda: Service())
    try:
        _browser_request("GET", "https://push2.eastmoney.com/api/test", {})
    except requests.ConnectionError as exc:
        assert "浏览器代理不可用" in str(exc)
    else:
        raise AssertionError("expected requests.ConnectionError")


def test_akshare_eastmoney_parser_consumes_browser_response(monkeypatch):
    class Service:
        def fetch_http(self, **kwargs):
            assert kwargs["method"] == "GET"
            assert kwargs["url"].startswith(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            )
            return {
                "status_code": 200,
                "headers": {"content-type": "application/json"},
                "body": json.dumps({
                    "data": {
                        "klines": [
                            "2026-07-29,10.00,10.20,10.50,9.80,1000000,10000000,7.00,2.00,0.20,3.09"
                        ]
                    }
                }),
                "url": kwargs["url"],
            }

    monkeypatch.setattr(EastmoneyBrowserService, "get_instance", lambda: Service())

    def browser_request(session, method, url, **kwargs):
        return _browser_request(method, url, kwargs)

    monkeypatch.setattr(requests.Session, "request", browser_request)
    frame = ak.stock_zh_a_hist(
        symbol="600519",
        start_date="20260729",
        end_date="20260729",
        adjust="",
    )

    assert frame.loc[0, "股票代码"] == "600519"
    assert frame.loc[0, "收盘"] == 10.2


def test_browser_url_scope_and_http_upgrade():
    assert _eastmoney_browser_url("http://fund.eastmoney.com/api/test") == (
        "https://fund.eastmoney.com/api/test"
    )
    assert _eastmoney_browser_url("https://portal.eastmoneyfutures.com/api/test") == (
        "https://portal.eastmoneyfutures.com/api/test"
    )
    assert _eastmoney_browser_url("https://eastmoney.com.evil.example/api") is None
    assert _eastmoney_browser_url("https://example.com/?next=eastmoney.com") is None
