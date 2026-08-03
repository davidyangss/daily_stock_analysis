from datetime import date, datetime, timedelta

from src.trader_analysis.evidence.ledger import create_ledger
from src.trader_analysis.fact_guard import guard_report_facts
from src.trader_analysis.market_facts import build_market_facts
from src.trader_analysis.schemas.evidence import EvidenceEnvelope, EvidenceStatus


def _envelope(capability: str, payload: dict) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        evidence_id=capability,
        run_id="fact-guard",
        capability=capability,
        symbol="002595",
        trade_date=date(2026, 7, 31),
        fetched_at=datetime.now(),
        status=EvidenceStatus.OK,
        provider="fixture",
        payload=payload,
    )


def _market_payload() -> dict:
    start = date(2026, 5, 1)
    closes = [60 - index * 0.35 for index in range(56)]
    rows = []
    for index, close in enumerate(closes):
        trade_date = start + timedelta(days=index)
        rows.append({
            "trade_date": trade_date.isoformat(),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
        })
    rows.extend([
        {"trade_date": "2026-07-28", "open": 48.4, "high": 49.5, "low": 48.11, "close": 48.22},
        {"trade_date": "2026-07-29", "open": 48.21, "high": 49.82, "low": 46.8, "close": 49.37},
        {"trade_date": "2026-07-30", "open": 49.22, "high": 53.8, "low": 49.1, "close": 52.8},
        {"trade_date": "2026-07-31", "open": 51.91, "high": 53.61, "low": 51.05, "close": 52.18},
    ])
    rows.append({
        "trade_date": "2026-07-10", "open": 45.84, "high": 46.4,
        "low": 44.0, "close": 45.77,
    })
    rows.sort(key=lambda row: row["trade_date"])
    return {
        "adjustment": "qfq",
        "rows": rows,
        "indicator_start_date": rows[0]["trade_date"],
        "corporate_action_breaks": [],
    }


def test_fact_guard_corrects_report_math_dates_and_price_relations() -> None:
    ledger = create_ledger("fact-guard", "002595", date(2026, 7, 31))
    market_payload = _market_payload()
    ledger.add(_envelope("market_daily_bars", market_payload))
    ledger.add(_envelope("verified_market_snapshot", {"last_price": 52.18}))
    facts = build_market_facts(market_payload, {"last_price": 52.18})
    canonical_cross = facts["macd_zero_cross_date"]
    wrong_cross = "07-01" if canonical_cross != "2026-07-01" else "07-02"
    state = {"market_report": (
        "距 7 月低点约 +16%。\n"
        "自 46.8 元低点反弹至 52.18 元（7 天 +8.21%、周涨 5.56%）。\n"
        f"DIF 于 {wrong_cross} 突破零轴。\n"
        "退出价宜设于49元下方（低于7-29低点46.8与现价52.18），即约47.8一线。"
    )}

    guarded, issues = guard_report_facts(state, ledger)
    content = guarded["market_report"]

    assert "距 7 月低点约 +18.59%" in content
    assert "按上述价位计算 +11.50%" in content
    assert canonical_cross[5:] in content
    assert "高于 7-29低点 46.8 元、低于现价 52.18" in content
    assert [issue.code for issue in issues] == ["report_market_fact_corrected"]


def test_fact_guard_removes_only_unverified_fund_flow_values() -> None:
    ledger = create_ledger("fact-guard", "002595", date(2026, 7, 31))
    ledger.add(_envelope("market_daily_bars", _market_payload()))
    ledger.add(_envelope("verified_market_snapshot", {"last_price": 52.18}))
    ledger.add(_envelope("news", {"items": [{
        "snippet": "本周主力资金合计净流入1214.61万元。",
    }]}))
    state = {"risk_debate_state": {"conservative_history": (
        "本周主力资金净流入1214.61万元；"
        "近5日主力资金净流入1214.61万元；"
        "近5日资金净流入4618.66万元；10日资金净流入6360.53万元。"
    )}}

    guarded, issues = guard_report_facts(state, ledger)
    content = guarded["risk_debate_state"]["conservative_history"]

    assert "1214.61万元" in content
    assert "4618.66" not in content
    assert "6360.53" not in content
    assert content.count("1214.61万元") == 1
    assert content.count("数值未经本次证据核验") == 3
    assert [issue.code for issue in issues] == [
        "report_unsupported_fund_flow_removed",
    ]
