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
