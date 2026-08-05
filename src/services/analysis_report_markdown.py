"""Render the public strategy-analysis API result as downloadable Markdown."""

from __future__ import annotations

from typing import Any

from src.agent.evidence import format_strategy_evidence_markdown


def _value(value: Any) -> str:
    if value is None or value == "":
        return "未提供"
    return str(value)


def render_analysis_result_markdown(result: Any) -> str:
    """Render an ``AnalysisResultResponse`` without accessing private runtime data."""
    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    strategy = report.get("strategy") if isinstance(report.get("strategy"), dict) else {}
    details = report.get("details") if isinstance(report.get("details"), dict) else {}

    code = meta.get("stock_code") or payload.get("stock_code") or "未知代码"
    name = meta.get("stock_name") or payload.get("stock_name") or ""
    title = f"{name}（{code}）" if name else str(code)
    lines = [
        f"# {title}策略分析报告",
        "",
        f"- 报告时间：{_value(meta.get('created_at') or payload.get('created_at'))}",
        f"- 查询 ID：{_value(meta.get('query_id') or payload.get('query_id'))}",
        f"- 报告类型：{_value(meta.get('report_type'))}",
        f"- 当前价格：{_value(meta.get('current_price'))}",
        f"- 涨跌幅：{_value(meta.get('change_pct'))}",
        "",
        "## 核心结论",
        "",
        f"- 操作建议：{_value(summary.get('action_label') or summary.get('operation_advice'))}",
        f"- 趋势判断：{_value(summary.get('trend_prediction'))}",
        f"- 情绪评分：{_value(summary.get('sentiment_score'))}",
        f"- 分析摘要：{_value(summary.get('analysis_summary'))}",
        "",
        "## 交易区间",
        "",
        f"- 理想买入价：{_value(strategy.get('ideal_buy'))}",
        f"- 第二买入价：{_value(strategy.get('secondary_buy'))}",
        f"- 止损价：{_value(strategy.get('stop_loss'))}",
        f"- 止盈价：{_value(strategy.get('take_profit'))}",
    ]
    news = details.get("news_content")
    if isinstance(news, str) and news.strip():
        lines.extend(["", "## 新闻与信息摘要", "", news.strip()])

    evidence = details.get("strategy_data_evidence")
    if evidence:
        report_language = (
            meta.get("report_language")
            or report.get("report_language")
            or payload.get("report_language")
            or "zh"
        )
        rendered_evidence = format_strategy_evidence_markdown(
            evidence,
            str(report_language),
        )
        if rendered_evidence:
            lines.extend(["", "## 策略数据证据", "", rendered_evidence])
    lines.extend(["", "> 本报告仅用于研究，不构成投资建议或交易指令。", ""])
    return "\n".join(lines)
