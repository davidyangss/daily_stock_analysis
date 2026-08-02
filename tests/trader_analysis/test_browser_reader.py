import socket
from types import SimpleNamespace

from src.trader_analysis.adapters.browser_reader import BrowserReaderConfig, CommunityPageReader


def _public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def test_browser_reader_returns_bounded_public_excerpt(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-browser")
    monkeypatch.setattr("src.trader_analysis.adapters.browser_reader.socket.getaddrinfo", _public_dns)
    monkeypatch.setattr("src.trader_analysis.adapters.browser_reader.shutil.which", lambda command: "/bin/agent-browser")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "read":
            return SimpleNamespace(returncode=0, stdout='{"data":{"content":"' + ('a' * 130) + '"}}', stderr="")
        return SimpleNamespace(returncode=0, stdout='{"success":true}', stderr="")

    monkeypatch.setattr("src.trader_analysis.adapters.browser_reader.subprocess.run", run)
    reader = CommunityPageReader(BrowserReaderConfig(
        enabled=True, max_pages=1, max_chars=5, allowed_domains=("xueqiu.com",),
    ))

    result = reader.enrich_items([{"url": "https://xueqiu.com/S/SH603986"}], run_id="run-1")

    assert result[0]["content_excerpt"] == "aaaaa"
    assert result[0]["content_truncated"] is True
    assert result[0]["content_fetch_status"] == "ok"
    assert "--allowed-domains" in calls[0][0]
    assert calls[0][0][-2:] == ["open", "https://xueqiu.com/S/SH603986"]
    assert calls[1][0][-1] == "read"
    assert calls[2][0][-1] == "close"
    assert "OPENAI_API_KEY" not in calls[0][1]["env"]
    assert calls[0][1]["env"]["AGENT_BROWSER_AUTO_CONNECT"] == "false"


def test_browser_reader_rejects_waf_payload(monkeypatch) -> None:
    monkeypatch.setattr("src.trader_analysis.adapters.browser_reader.socket.getaddrinfo", _public_dns)
    monkeypatch.setattr("src.trader_analysis.adapters.browser_reader.shutil.which", lambda command: "/bin/agent-browser")

    def run(command, **kwargs):
        output = '{"data":{"content":"' + ('x' * 130) + '_waf_token"}}' if command[-1] == "read" else "{}"
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr("src.trader_analysis.adapters.browser_reader.subprocess.run", run)
    reader = CommunityPageReader(BrowserReaderConfig(enabled=True, allowed_domains=("xueqiu.com",)))

    result = reader.read("https://xueqiu.com/S/SH603986", run_id="run-1")

    assert result["content_fetch_status"] == "unavailable"
    assert result["content_fetch_reason"] == "low_quality_content"


def test_browser_reader_rejects_private_dns_without_starting_process(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.trader_analysis.adapters.browser_reader.socket.getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    started = []
    monkeypatch.setattr(
        "src.trader_analysis.adapters.browser_reader.subprocess.run",
        lambda *args, **kwargs: started.append(True),
    )
    reader = CommunityPageReader(BrowserReaderConfig(enabled=True, allowed_domains=("xueqiu.com",)))

    result = reader.read("https://xueqiu.com/S/SH603986", run_id="run-1")

    assert result["content_fetch_status"] == "unavailable"
    assert result["content_fetch_reason"] == "ValueError"
    assert started == []


def test_browser_reader_rejects_non_allowlisted_domain(monkeypatch) -> None:
    reader = CommunityPageReader(BrowserReaderConfig(enabled=True, allowed_domains=("xueqiu.com",)))

    result = reader.read("https://example.com/news", run_id="run-1")

    assert result["content_fetch_status"] == "unavailable"
    assert result["content_fetch_reason"] == "ValueError"
