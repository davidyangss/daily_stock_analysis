"""Chinese report modules and Markdown export for trader-analysis runs."""

from __future__ import annotations

import re
from typing import Any, Mapping

from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceLedger
from src.trader_analysis.schemas.result import TraderAnalysisReport, TraderAnalysisRun


REPORT_MODULES = (
    ("market", "📈 市场技术分析"),
    ("sentiment", "💭 市场情绪分析"),
    ("news", "📰 新闻事件分析"),
    ("fundamentals", "💰 基本面分析"),
    ("bull_researcher", "🐂 多头研究员"),
    ("bear_researcher", "🐻 空头研究员"),
    ("research_decision", "🔬 研究经理决策"),
    ("trader_plan", "💼 交易员计划"),
    ("aggressive_analyst", "⚡ 激进分析师"),
    ("conservative_analyst", "🛡️ 保守分析师"),
    ("neutral_analyst", "⚖️ 中性分析师"),
    ("portfolio_manager", "👔 投资组合经理"),
    ("final_decision", "🎯 最终交易决策"),
    ("investment_advice", "📋 投资建议"),
)

_MARKET_PROPOSAL_PREFIX = re.compile(
    r"^FINAL TRANSACTION PROPOSAL:\s*\*{0,2}(BUY|HOLD|SELL)\*{0,2}\s*[:：-]?\s*",
    re.IGNORECASE,
)


def _localize_market_report_prefix(content: str) -> str:
    """Localize the upstream graph's optional English stop-signal prefix."""
    labels = {"BUY": "买入", "HOLD": "持有", "SELL": "卖出"}
    return _MARKET_PROPOSAL_PREFIX.sub(
        lambda match: f"最终交易建议：{labels[match.group(1).upper()]}\n\n",
        content,
        count=1,
    )


def _clean_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _evidence_appendix(envelope: EvidenceEnvelope | None, *, item_key: str) -> str:
    if envelope is None:
        return ""
    items = list((envelope.payload or {}).get(item_key) or [])
    if not items:
        return (
            "### 证据摘要与来源\n\n"
            f"- 本次未取得可交叉核验的条目；数据状态：`{envelope.status.value}`。"
        )
    lines = [
        "### 证据摘要与来源",
        "",
        f"> 证据采集时间：{envelope.fetched_at.isoformat()}；内容时间为来源返回值，“未提供”表示不得自行推断。",
        "",
        "| # | 摘要 | 来源 | 内容时间 | 采集时间 | 原文 |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(items[:10], start=1):
        title = _clean_cell(item.get("title")) or "无标题"
        snippet = _clean_cell(item.get("snippet"))
        summary = title if not snippet else f"{title}：{snippet[:240]}"
        source = _clean_cell(item.get("source")) or _clean_cell(envelope.provider) or "未知来源"
        published = _clean_cell(item.get("published_date")) or "未提供"
        fetched = _clean_cell(item.get("fetched_at")) or envelope.fetched_at.isoformat()
        url = str(item.get("url") or "").strip()
        link = f"[查看]({url})" if url.startswith(("http://", "https://")) else "未提供"
        lines.append(f"| {index} | {summary} | {source} | {published} | {fetched} | {link} |")
    return "\n".join(lines)


def reports_from_state(
    state: Mapping[str, Any], *, ledger: EvidenceLedger | None = None,
) -> list[TraderAnalysisReport]:
    """Extract all public report modules from one final TradingAgents state."""
    research = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    if not isinstance(research, Mapping):
        research = {}
    if not isinstance(risk, Mapping):
        risk = {}

    values = {
        "market": _localize_market_report_prefix(str(state.get("market_report") or "").strip()),
        "sentiment": state.get("sentiment_report"),
        "news": state.get("news_report"),
        "fundamentals": state.get("fundamentals_report"),
        "bull_researcher": research.get("bull_history"),
        "bear_researcher": research.get("bear_history"),
        "research_decision": state.get("investment_plan") or research.get("judge_decision"),
        "trader_plan": state.get("trader_investment_plan"),
        "aggressive_analyst": risk.get("aggressive_history"),
        "conservative_analyst": risk.get("conservative_history"),
        "neutral_analyst": risk.get("neutral_history"),
        "portfolio_manager": risk.get("judge_decision"),
        "final_decision": state.get("final_trade_decision"),
        "investment_advice": state.get("investment_plan"),
    }
    titles = dict(REPORT_MODULES)
    reports = [
        TraderAnalysisReport(kind=kind, title=titles[kind], content=content)
        for kind, _title in REPORT_MODULES
        if (content := str(values.get(kind) or "").strip())
    ]
    if ledger is None:
        return reports
    appendices = {
        "news": _evidence_appendix(ledger.envelopes.get("news"), item_key="items"),
        "sentiment": _evidence_appendix(ledger.envelopes.get("sentiment"), item_key="social_items"),
    }
    for report in reports:
        appendix = appendices.get(report.kind)
        if appendix:
            report.content = f"{report.content.rstrip()}\n\n{appendix}"
    return reports


def render_run_markdown(run: TraderAnalysisRun) -> str:
    """Render the persisted API report contract as one downloadable document."""
    instrument = run.instrument
    name = instrument.name if instrument and instrument.name != run.symbol else "名称未核验"
    raw_status = run.analysis_status.value if run.analysis_status else run.task_status.value
    status = {
        "complete": "完整",
        "degraded": "降级可用",
        "insufficient_evidence": "证据不足",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    }.get(raw_status, raw_status)
    market = {
        "SH": "上海证券交易所",
        "SZ": "深圳证券交易所",
        "BJ": "北京证券交易所",
    }.get(instrument.exchange if instrument else "", "未核验")
    currency = "人民币（CNY）" if instrument and instrument.currency == "CNY" else "未核验"
    lines = [
        f"# {name}（{run.symbol}）交易员分析报告",
        "",
        f"- 分析日期：{run.trade_date.isoformat()}",
        f"- 市场：{market}",
        f"- 币种：{currency}",
        f"- 分析状态：{status}",
        f"- 运行编号：{run.run_id}",
        f"- 生成时间：{(run.completed_at or run.created_at).isoformat()}",
        "",
        "> 风险提示：本报告由 AI 根据运行时可核验证据生成，仅供研究参考，不构成投资建议。",
        "",
    ]
    by_kind = {report.kind: report for report in run.reports}
    for kind, title in REPORT_MODULES:
        report = by_kind.get(kind)
        if report:
            lines.extend((f"## {title}", "", report.content.strip(), ""))
    quality = by_kind.get("data_quality")
    if quality:
        lines.extend(("## 🧾 数据质量与分析限制", "", quality.content.strip(), ""))
    return "\n".join(lines).rstrip() + "\n"
