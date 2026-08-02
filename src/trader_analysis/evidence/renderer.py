"""Deterministic evidence quality rendering."""

from __future__ import annotations

from src.trader_analysis.schemas.evidence import EvidenceLedger


_ISSUE_LABELS = {
    "runtime_news_not_point_in_time": "新闻数据不是历史时点快照",
    "runtime_sentiment_not_point_in_time": "社区情绪不是历史时点快照",
    "fundamentals_report_expired": "最近一期财报已超过一年",
    "fundamentals_report_date_missing": "基本面数据缺少报告期",
    "fundamentals_partial": "基本面数据部分可用",
    "fundamentals_unavailable": "基本面数据不可用",
}
_CAPABILITY_LABELS = {
    "fundamentals": "基本面",
    "news": "新闻",
    "sentiment": "社区情绪",
    "market_daily_bars": "日线行情",
    "verified_market_snapshot": "已核验行情快照",
}
_STATUS_LABELS = {
    "ok": "可用",
    "partial": "部分可用",
    "unavailable": "不可用",
    "invalid": "无效",
    "stale": "已过期",
}


def render_quality_summary(ledger: EvidenceLedger) -> str:
    lines = [
        "## 数据质量与分析限制",
        "",
        f"- 总体状态：{ledger.overall_status}",
        f"- 使用数据源：{', '.join(ledger.providers_used) if ledger.providers_used else '无'}",
    ]
    if ledger.blocking_issues:
        lines.append("- 阻断问题：")
        lines.extend(
            f"  - [{_ISSUE_LABELS.get(issue.code, issue.code)}] {issue.message}"
            for issue in ledger.blocking_issues
        )
    if ledger.warnings:
        lines.append("- 降级/警告：")
        lines.extend(
            f"  - [{_ISSUE_LABELS.get(issue.code, issue.code)}] {issue.message}"
            for issue in ledger.warnings
        )
    for capability, envelope in ledger.envelopes.items():
        as_of = envelope.as_of.isoformat() if envelope.as_of else "未知"
        lines.append(
            f"- {_CAPABILITY_LABELS.get(capability, capability)}："
            f"{_STATUS_LABELS.get(envelope.status.value, envelope.status.value)}，"
            f"数据源={envelope.provider or '未知'}，数据时间={as_of}"
        )
    return "\n".join(lines)
