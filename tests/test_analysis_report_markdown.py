from api.v1.schemas.analysis import AnalysisResultResponse
from src.services.analysis_report_markdown import render_analysis_result_markdown


def test_render_analysis_result_markdown_uses_public_report_fields() -> None:
    result = AnalysisResultResponse(
        query_id="task-1",
        stock_code="600519",
        stock_name="贵州茅台",
        created_at="2026-08-03T12:00:00",
        report={
            "meta": {"report_type": "detailed", "current_price": 1500.0},
            "summary": {
                "action_label": "持有",
                "trend_prediction": "震荡偏强",
                "sentiment_score": 72,
                "analysis_summary": "等待放量确认",
            },
            "strategy": {"ideal_buy": "1480", "stop_loss": "1420", "take_profit": "1600"},
            "details": {"news_content": "近期公告摘要"},
        },
    )

    markdown = render_analysis_result_markdown(result)

    assert "# 贵州茅台（600519）策略分析报告" in markdown
    assert "- 操作建议：持有" in markdown
    assert "- 理想买入价：1480" in markdown
    assert "近期公告摘要" in markdown
    assert "不构成投资建议" in markdown


def test_render_analysis_result_markdown_uses_per_strategy_evidence_tables() -> None:
    result = AnalysisResultResponse(
        query_id="task-2",
        stock_code="600519",
        stock_name="贵州茅台",
        created_at="2026-08-05T12:00:00",
        report={
            "meta": {"report_type": "detailed", "report_language": "zh"},
            "summary": {"action_label": "观望"},
            "strategy": {},
            "details": {
                "strategy_data_evidence": {
                    "schema_version": "strategy-evidence-v1",
                    "status": "limited",
                    "selected_strategies": [{
                        "skill_id": "expectation_repricing",
                        "skill_name": "expectation_repricing",
                    }],
                    "strategy_evaluations": [{
                        "skill_id": "expectation_repricing",
                        "skill_name": "expectation_repricing",
                        "status": "completed",
                        "signal": "hold",
                        "confidence": 0.5,
                        "reasoning": "估值字段部分可用。",
                        "conditions_met": ["价格接近辅助支撑且回调未放量"],
                        "conditions_missed": ["尚未确认有效箱体与放量突破"],
                    }],
                    "strategy_requirements": [{
                        "skill_id": "expectation_repricing",
                        "status": "limited",
                        "missing_tools": [],
                        "limited_tools": ["get_stock_info"],
                        "evidence": [{
                            "tool": "get_stock_info",
                            "status": "partial",
                            "sources": ["iwencai"],
                            "key_values": {"pe_ratio": 18.5},
                            "metric_details": [{
                                "key": "revenue_yoy",
                                "label": "营收同比增长率",
                                "status": "missing",
                                "display_value": None,
                                "description": "营业收入同比变化",
                            }],
                        }],
                    }],
                    "items": [],
                    "limitations": [
                        "expectation_repricing: required data degraded (get_stock_info)",
                    ],
                },
            },
        },
    )

    markdown = render_analysis_result_markdown(result)

    assert "##### 策略分析输出" in markdown
    assert "| 条件状态 | 判定条件 |" in markdown
    assert "| 满足条件 | 价格接近辅助支撑且回调未放量 |" in markdown
    assert "| 未满足条件 | 尚未确认有效箱体与放量突破 |" in markdown
    assert "##### 策略分析输入数据" in markdown
    assert "| 营收同比增长率 | 缺失 | — | 营业收入同比变化 |" in markdown
    assert "| 策略 | 限制状态 | 关键数据工具 | 仍需补充的数据 | 当前数据 / 失败情况 |" in markdown
    assert "| 预期重估 | 必需输入数据部分可用 | 基本信息获取 | 营收同比增长率 | 部分数据；iwencai |" in markdown
    assert "```json" not in markdown
