"""Deterministic evidence quality rendering."""

from __future__ import annotations

from src.trader_analysis.schemas.evidence import EvidenceLedger


def render_quality_summary(ledger: EvidenceLedger) -> str:
    lines = [
        "## 数据质量与分析限制",
        "",
        f"- 总体状态：{ledger.overall_status}",
        f"- 使用数据源：{', '.join(ledger.providers_used) if ledger.providers_used else '无'}",
    ]
    if ledger.blocking_issues:
        lines.append("- 阻断问题：")
        lines.extend(f"  - [{issue.code}] {issue.message}" for issue in ledger.blocking_issues)
    if ledger.warnings:
        lines.append("- 降级/警告：")
        lines.extend(f"  - [{issue.code}] {issue.message}" for issue in ledger.warnings)
    for capability, envelope in ledger.envelopes.items():
        as_of = envelope.as_of.isoformat() if envelope.as_of else "未知"
        lines.append(
            f"- {capability}: {envelope.status.value}, "
            f"provider={envelope.provider or 'unknown'}, as_of={as_of}"
        )
    return "\n".join(lines)
