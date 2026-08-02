"""Chinese report modules and Markdown export for trader-analysis runs."""

from __future__ import annotations

import json
import re
from typing import Any, Collection, Mapping

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
    ("data_evidence", "🔎 完整数据证据清单"),
)

_TRANSACTION_PROPOSAL_LINE = re.compile(
    r"^[ \t]*FINAL TRANSACTION PROPOSAL:[ \t]*\*{0,2}(BUY|HOLD|SELL)\*{0,2}"
    r"[ \t]*[:：-]?[ \t]*(?:\r?\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
_REPORT_FIELD_LINE = re.compile(
    r"^(?P<indent>[ \t]*)\*\*(?P<label>[A-Za-z][A-Za-z /-]*?)(?:[:：])?\*\*"
    r"[ \t]*[:：]?[ \t]*(?P<value>.*)$",
    re.MULTILINE,
)
_REPORT_FIELD_LABELS = {
    "Overall Sentiment": "整体情绪（Overall Sentiment）",
    "Confidence": "置信度（Confidence）",
    "Recommendation": "投资建议（Recommendation）",
    "Rationale": "核心依据（Rationale）",
    "Strategic Actions": "策略行动（Strategic Actions）",
    "Action": "操作方向（Action）",
    "Reasoning": "决策依据（Reasoning）",
    "Entry Price": "参考价格（Entry Price）",
    "Execution Price": "执行价格（Execution Price）",
    "Stop Loss": "止损价格（Stop Loss）",
    "Reassessment Price": "重新评估价格（Reassessment Price）",
    "Position Sizing": "仓位安排（Position Sizing）",
    "Rating": "评级（Rating）",
    "Executive Summary": "执行摘要（Executive Summary）",
    "Investment Thesis": "投资逻辑（Investment Thesis）",
    "Time Horizon": "观察周期（Time Horizon）",
}
_REPORT_ENUM_LABELS = {
    "STRONGLY BULLISH": "强烈看多",
    "MILDLY BULLISH": "温和看多",
    "STRONGLY BEARISH": "强烈看空",
    "MILDLY BEARISH": "温和看空",
    "OVERWEIGHT": "超配",
    "UNDERWEIGHT": "低配",
    "BULLISH": "看多",
    "BEARISH": "看空",
    "NEUTRAL": "中性",
    "MIXED": "多空分歧",
    "BUY": "买入",
    "HOLD": "持有",
    "SELL": "卖出",
    "LOW": "低",
    "MEDIUM": "中",
    "HIGH": "高",
}
_ENGLISH_ENUM_WITH_CHINESE = re.compile(
    r"\b(?P<enum>STRONGLY BULLISH|MILDLY BULLISH|STRONGLY BEARISH|MILDLY BEARISH|"
    r"OVERWEIGHT|UNDERWEIGHT|BULLISH|BEARISH|NEUTRAL|MIXED|BUY|HOLD|SELL)"
    r"[ \t]*[（(](?P<chinese>[\u3400-\u9fff][^）)]*)[）)]",
    re.IGNORECASE,
)
_QUALITY_STATUS_LINE = re.compile(
    r"^(?P<prefix>- 总体状态：)(?P<status>complete|degraded|insufficient_evidence)$",
    re.MULTILINE,
)
_QUALITY_STATUS_LABELS = {
    "complete": "完整",
    "degraded": "降级可用",
    "insufficient_evidence": "证据不足",
}
_FORMAL_REPORT_RAW_STATUS_LABELS = {
    "<unavailable: A-share Reddit source is not configured>": (
        "A 股 Reddit 数据源未配置"
        "（原始状态：<unavailable: A-share Reddit source is not configured>）"
    ),
}
_CHINESE_MARKDOWN_HEADING = re.compile(r"^#{1,6}[ \t]+[^\n]*[\u3400-\u9fff]", re.MULTILINE)
_MARKET_WORKPAD_MARKER = re.compile(
    r"^[ \t]*(?:now\s+i\b|i\s+(?:have|need|will)\b|let\s+me\b|key\s+data\s+points?\b|"
    r"the\s+stock\b|from\s+(?:the\s+)?peak\b|(?:now\s+)?write\s+the\s+report\b|yes\b)",
    re.IGNORECASE | re.MULTILINE,
)

_MARKET_ADJUSTMENT_NOTES = {
    "none": (
        "技术指标基于不复权日线数据计算；受历史分红除权影响，"
        "历史指标值可能与前复权行情软件显示存在差异。"
    ),
    "qfq": "技术指标基于前复权日线数据计算。",
    "auto_adjust": "技术指标基于数据源自动复权日线数据计算。",
    "unknown": "技术指标所用日线的复权口径未确认；历史指标值不宜与其他行情软件直接比较。",
}


def _strip_market_workpad_prefix(content: str) -> str:
    """Drop a recognizable English workpad before the formal Chinese report."""
    heading = _CHINESE_MARKDOWN_HEADING.search(content)
    if heading is None:
        return content
    prefix = content[:heading.start()]
    if not _MARKET_WORKPAD_MARKER.search(prefix):
        return content
    return content[heading.start():].lstrip()


def _localize_enum_prefix(value: str) -> str:
    for enum, label in _REPORT_ENUM_LABELS.items():
        bold_pattern = re.compile(
            rf"^\*\*{re.escape(enum)}\*\*(?=$|[ \t（(])",
            re.IGNORECASE,
        )
        if bold_pattern.match(value):
            return bold_pattern.sub(f"**{label}（{enum.title()}）**", value, count=1)
        plain_pattern = re.compile(rf"^{re.escape(enum)}(?=$|[ \t（(])", re.IGNORECASE)
        if plain_pattern.match(value):
            return plain_pattern.sub(f"{label}（{enum.title()}）", value, count=1)
    return value


def _localize_report_field(match: re.Match[str]) -> str:
    english_label = match.group("label").strip()
    localized_label = _REPORT_FIELD_LABELS.get(english_label)
    if localized_label is None:
        return match.group(0)
    value = _localize_enum_prefix(match.group("value"))
    value = re.sub(
        r"[ \t]*\(Score:[ \t]*([^)]+)\)",
        r"（评分（Score）：\1）",
        value,
        flags=re.IGNORECASE,
    )
    return f"{match.group('indent')}**{localized_label}**：{value}"


def _localize_formal_report(kind: str, content: str) -> str:
    """Localize stable upstream labels while preserving evidence and decisions."""
    if kind == "data_evidence":
        return content
    body, appendix_marker, appendix = content.partition("\n### 证据摘要与来源")
    if kind == "market":
        body = _strip_market_workpad_prefix(body)
    body = _TRANSACTION_PROPOSAL_LINE.sub(
        lambda match: (
            "最终交易建议（Final Transaction Proposal）："
            f"{_REPORT_ENUM_LABELS[match.group(1).upper()]}（{match.group(1).upper()}）\n\n"
        ),
        body,
    )
    body = _REPORT_FIELD_LINE.sub(_localize_report_field, body)
    body = _ENGLISH_ENUM_WITH_CHINESE.sub(
        lambda match: f"{match.group('chinese')}（{match.group('enum')}）",
        body,
    )
    for raw_status, localized_status in _FORMAL_REPORT_RAW_STATUS_LABELS.items():
        body = body.replace(raw_status, localized_status)
    if kind == "data_quality":
        body = _QUALITY_STATUS_LINE.sub(
            lambda match: (
                f"{match.group('prefix')}{_QUALITY_STATUS_LABELS[match.group('status')]}"
                f"（{match.group('status')}）"
            ),
            body,
        )
    return body if not appendix_marker else f"{body}{appendix_marker}{appendix}"


def _clean_cell(value: Any) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ").strip()


def _market_adjustment_disclosure(ledger: EvidenceLedger) -> str:
    envelope = ledger.envelopes.get("market_daily_bars")
    adjustment = str(((envelope.payload or {}).get("adjustment") if envelope else None) or "unknown")
    note = _MARKET_ADJUSTMENT_NOTES.get(adjustment, _MARKET_ADJUSTMENT_NOTES["unknown"])
    return f"> 数据口径（adjustment=`{adjustment}`）：{note}"


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
        "| # | 证据类型 | 摘要 | 来源 | 内容时间 | 采集时间 | 原文 |",
        "| ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(items[:10], start=1):
        title = _clean_cell(item.get("title")) or "无标题"
        excerpt = _clean_cell(item.get("content_excerpt"))
        snippet = excerpt or _clean_cell(item.get("search_snippet") or item.get("snippet"))
        summary = title if not snippet else f"{title}：{snippet[:240]}"
        evidence_type = "浏览器正文摘录" if excerpt else "搜索摘要"
        if item.get("content_fetch_status") == "unavailable":
            evidence_type += "（正文不可用）"
        source = _clean_cell(item.get("source")) or _clean_cell(envelope.provider) or "未知来源"
        published = _clean_cell(item.get("published_date")) or "未提供"
        fetched = _clean_cell(
            item.get("content_fetched_at") if excerpt else item.get("fetched_at")
        ) or envelope.fetched_at.isoformat()
        url = str(item.get("url") or "").strip()
        link = f"[查看]({url})" if url.startswith(("http://", "https://")) else "未提供"
        lines.append(
            f"| {index} | {evidence_type} | {summary} | {source} | {published} | {fetched} | {link} |"
        )
    return "\n".join(lines)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, indent=2).replace("```", "` ` `")


def render_evidence_manifest(
    ledger: EvidenceLedger,
    *,
    consumed_capabilities: Collection[str] | None = None,
) -> str:
    """Render the full canonical preflight input and actual tool consumption."""
    consumed = set(consumed_capabilities or ())
    lines = [
        "### 审计口径",
        "",
        "- “预检已加载”表示数据进入本次运行的 canonical evidence ledger；并不等于模型实际读取。",
        "- “工具实际消费”仅在 TradingAgents 工具调用读取该 evidence envelope 后标记；"
        "完整 LLM 请求/响应和逐次工具参数/结果以同一运行编号的 Trace 为准。",
        "- 下列 payload 是进入工具层的标准化实际数据；`as_of` 是数据业务时点，"
        "`fetched_at` 是本系统采集时点，二者不可混用。",
        "",
        "### 证据总览",
        "",
        "| 能力 | evidence_id | 状态 | 主数据源 | 来源链 | 数据业务时点 | 采集时点 | 工具实际消费 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for capability, envelope in ledger.envelopes.items():
        source_chain = ", ".join(str(item) for item in envelope.source_chain) or "未提供"
        lines.append(
            "| {capability} | {evidence_id} | {status} | {provider} | {source_chain} | "
            "{as_of} | {fetched_at} | {consumed} |".format(
                capability=_clean_cell(capability),
                evidence_id=_clean_cell(envelope.evidence_id),
                status=_clean_cell(envelope.status.value),
                provider=_clean_cell(envelope.provider) or "未提供",
                source_chain=_clean_cell(source_chain),
                as_of=_clean_cell(envelope.as_of.isoformat() if envelope.as_of else None) or "未提供",
                fetched_at=_clean_cell(envelope.fetched_at.isoformat()),
                consumed="是" if capability in consumed else "否",
            )
        )

    for capability, envelope in ledger.envelopes.items():
        lines.extend(("", f"### {capability} 实际输入", ""))
        if envelope.issues:
            lines.extend(("#### 数据问题", ""))
            for issue in envelope.issues:
                detail = {
                    "missing_fields": issue.missing_fields,
                    "expected": issue.expected,
                    "observed": issue.observed,
                    "retriable": issue.retriable,
                }
                lines.append(
                    f"- `{issue.severity.value}` / `{issue.code}`：{issue.message}；"
                    f"详情=`{_clean_cell(_json_text(detail))}`"
                )
            lines.append("")

        payload = dict(envelope.payload or {})
        rows = payload.pop("rows", None) if capability == "market_daily_bars" else None
        if rows is not None:
            lines.extend(("#### 日线元数据", "", "```json", _json_text(payload), "```", ""))
            lines.extend((
                "#### 完整标准化日线",
                "",
                "| 交易日 | 开盘 | 最高 | 最低 | 收盘 | 成交量（股） | 成交额（元） | 涨跌幅（%） |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ))
            for row in rows or []:
                lines.append(
                    "| {trade_date} | {open} | {high} | {low} | {close} | "
                    "{volume} | {amount} | {pct_change} |".format(
                        trade_date=_clean_cell(row.get("trade_date")) or "未提供",
                        open=_clean_cell(row.get("open")) or "未提供",
                        high=_clean_cell(row.get("high")) or "未提供",
                        low=_clean_cell(row.get("low")) or "未提供",
                        close=_clean_cell(row.get("close")) or "未提供",
                        volume=_clean_cell(row.get("volume_shares")) or "未提供",
                        amount=_clean_cell(row.get("amount_cny")) or "未提供",
                        pct_change=_clean_cell(row.get("pct_change")) or "未提供",
                    )
                )
        else:
            lines.extend(("```json", _json_text(payload), "```"))
    return "\n".join(lines)


def reports_from_state(
    state: Mapping[str, Any], *, ledger: EvidenceLedger | None = None,
    consumed_capabilities: Collection[str] | None = None,
) -> list[TraderAnalysisReport]:
    """Extract all public report modules from one final TradingAgents state."""
    research = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    if not isinstance(research, Mapping):
        research = {}
    if not isinstance(risk, Mapping):
        risk = {}

    values = {
        "market": state.get("market_report"),
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
        TraderAnalysisReport(
            kind=kind,
            title=titles[kind],
            content=_localize_formal_report(kind, content).strip(),
        )
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
        if report.kind == "market":
            disclosure = _market_adjustment_disclosure(ledger)
            if disclosure not in report.content:
                report.content = f"{disclosure}\n\n{report.content}"
        appendix = appendices.get(report.kind)
        if appendix:
            report.content = f"{report.content.rstrip()}\n\n{appendix}"
    reports.append(TraderAnalysisReport(
        kind="data_evidence",
        title=dict(REPORT_MODULES)["data_evidence"],
        content=render_evidence_manifest(
            ledger,
            consumed_capabilities=consumed_capabilities,
        ),
    ))
    return reports


def localize_run_for_publication(run: TraderAnalysisRun) -> TraderAnalysisRun:
    """Return a localized copy without rewriting the persisted audit record."""
    public_run = run.model_copy(deep=True)
    for report in public_run.reports:
        report.content = _localize_formal_report(report.kind, report.content).strip()
    return public_run


def render_run_markdown(run: TraderAnalysisRun) -> str:
    """Render the persisted API report contract as one downloadable document."""
    run = localize_run_for_publication(run)
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
