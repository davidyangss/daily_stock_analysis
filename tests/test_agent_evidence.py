# -*- coding: utf-8 -*-
"""Regression tests for deterministic strategy data evidence."""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.agent.evidence import (
    build_strategy_evidence_manifest,
    extract_strategy_evidence_manifest,
    format_strategy_evidence_markdown,
    summarize_tool_result,
)
from src.agent.protocols import AgentOpinion
from src.agent.skills.engine import StrategyEngine, StrategyResultStatus
from src.agent.skills.skill_agent import SkillAgent
from src.notification import _append_strategy_data_evidence_block


class TestToolEvidence(unittest.TestCase):
    def test_available_quote_keeps_source_and_key_values(self) -> None:
        evidence = summarize_tool_result(
            "get_realtime_quote",
            json.dumps({
                "price": 1880.0,
                "volume_ratio": 1.2,
                "source": "tushare",
                "timestamp": "2026-07-29T10:30:00+08:00",
            }),
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "available")
        self.assertEqual(evidence["sources"], ["tushare"])
        self.assertEqual(evidence["key_values"]["price"], 1880.0)
        self.assertEqual(evidence["as_of"], "2026-07-29T10:30:00+08:00")

    def test_successful_tool_call_with_empty_business_result_is_missing(self) -> None:
        evidence = summarize_tool_result(
            "search_stock_news",
            json.dumps({"success": True, "provider": "searxng", "results_count": 0, "results": []}),
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "missing")
        self.assertEqual(evidence["record_count"], 0)
        self.assertEqual(evidence["sources"], ["searxng"])
        self.assertEqual(evidence["missing_reason"], "missing")

    def test_nested_fundamental_status_and_sources_are_preserved(self) -> None:
        evidence = summarize_tool_result(
            "get_stock_info",
            {
                "pe_ratio": None,
                "fundamental_context": {
                    "status": "partial",
                    "source_chain": [
                        {"provider": "yfinance", "result": "ok"},
                        {"provider": "fundamental_pipeline", "result": "partial"},
                    ],
                },
            },
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "partial")
        self.assertEqual(evidence["sources"], ["yfinance", "fundamental_pipeline"])

    def test_daily_history_summarizes_latest_bar_without_exposing_all_rows(self) -> None:
        evidence = summarize_tool_result(
            "get_daily_history",
            {
                "source": "db_cache",
                "requested_days": 60,
                "actual_records": 2,
                "data": [
                    {"date": "2026-07-28", "close": 1870.0, "volume": 100},
                    {
                        "date": "2026-07-29",
                        "open": 1872.0,
                        "high": 1892.0,
                        "low": 1868.0,
                        "close": 1880.0,
                        "volume": 120,
                    },
                ],
            },
            execution_success=True,
            cached=True,
        )

        self.assertEqual(evidence["as_of"], "2026-07-29")
        self.assertEqual(evidence["record_count"], 2)
        self.assertEqual(evidence["requested_records"], 60)
        self.assertEqual(evidence["key_values"]["latest_close"], 1880.0)
        self.assertNotIn("data", evidence)

    def test_empty_sector_collections_are_missing(self) -> None:
        evidence = summarize_tool_result(
            "get_sector_rankings",
            {"top_sectors": [], "bottom_sectors": []},
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "missing")

    def test_pattern_fetch_failure_keeps_tool_description_and_provider_attempts(self) -> None:
        evidence = summarize_tool_result(
            "analyze_pattern",
            {
                "error": "No historical data for 688825",
                "data_description": "日线K线（开盘、最高、最低、收盘、成交量）",
                "provider_attempts": [{
                    "provider": "AkshareFetcher",
                    "operation": "get_daily_data",
                    "reason": "empty result",
                }],
                "failure_source": "AkshareFetcher",
                "failure_operation": "get_daily_data",
                "failure_reason": "empty result",
            },
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "fetch_failed")
        self.assertEqual(evidence["tool_display_name"], "K线形态识别")
        self.assertIn("十字星", evidence["tool_description"])
        self.assertEqual(evidence["data_description"], "日线K线（开盘、最高、最低、收盘、成交量）")
        self.assertEqual(evidence["sources"], ["AkshareFetcher"])
        self.assertEqual(evidence["failure_attempts"][0]["provider"], "AkshareFetcher")
        self.assertEqual(evidence["failure_attempts"][0]["reason"], "empty result")
        self.assertEqual(evidence["source_links"][0]["url"], "https://www.akshare.xyz/")


class TestSkillEvidenceContract(unittest.TestCase):
    @staticmethod
    def _agent(required_tools):
        skill = SimpleNamespace(
            required_tools=list(required_tools),
            instructions="test",
            description="test",
            display_name="Test",
        )
        with patch.object(SkillAgent, "_load_skill", return_value=skill):
            return SkillAgent(
                skill_id="test_skill",
                tool_registry=MagicMock(),
                llm_adapter=MagicMock(),
            )

    def test_missing_required_tool_marks_opinion_insufficient(self) -> None:
        agent = self._agent(["get_realtime_quote", "search_stock_news"])
        opinion = agent.attach_execution_evidence(
            AgentOpinion(agent_name="skill_test_skill", signal="buy", confidence=0.9),
            [{
                "tool": "get_realtime_quote",
                "arguments": {"stock_code": "600519"},
                "evidence": {
                    "tool": "get_realtime_quote",
                    "status": "available",
                    "sources": ["tushare"],
                    "cached": False,
                    "partial": False,
                    "key_values": {"price": 1880.0},
                },
            }],
        )

        self.assertEqual(opinion.raw_data["evidence_status"], "insufficient")
        self.assertEqual(opinion.raw_data["missing_required_tools"], ["search_stock_news"])

        result = StrategyEngine().process([opinion])
        self.assertEqual(result.status, StrategyResultStatus.NO_CONSENSUS)
        self.assertEqual(result.valid_skill_opinions, [])
        self.assertEqual(result.invalid_records[0]["reason"], "insufficient_required_data")

    def test_model_authored_tool_evidence_cannot_bypass_runtime_check(self) -> None:
        agent = self._agent(["search_stock_news"])
        opinion = agent.attach_execution_evidence(
            AgentOpinion(
                agent_name="skill_test_skill",
                signal="buy",
                confidence=0.9,
                raw_data={
                    "tool_evidence": [{
                        "tool": "search_stock_news",
                        "status": "available",
                        "sources": ["model-claimed"],
                    }],
                },
            ),
            [],
        )

        self.assertEqual(opinion.raw_data["tool_evidence"], [])
        self.assertEqual(opinion.raw_data["evidence_status"], "insufficient")
        self.assertEqual(opinion.raw_data["missing_required_tools"], ["search_stock_news"])

    def test_degraded_required_tool_keeps_vote_but_marks_limited(self) -> None:
        agent = self._agent(["get_daily_history"])
        opinion = agent.attach_execution_evidence(
            AgentOpinion(agent_name="skill_test_skill", signal="buy", confidence=0.7),
            [{
                "tool": "get_daily_history",
                "arguments": {"stock_code": "600519", "days": 60},
                "evidence": {
                    "tool": "get_daily_history",
                    "status": "partial",
                    "sources": ["db_cache"],
                    "cached": True,
                    "partial": True,
                    "key_values": {},
                    "record_count": 20,
                    "requested_records": 60,
                },
            }],
        )

        self.assertEqual(opinion.raw_data["evidence_status"], "limited")
        result = StrategyEngine().process([opinion])
        self.assertEqual(result.status, StrategyResultStatus.CONSENSUS)
        self.assertEqual(len(result.valid_skill_opinions), 1)


class TestStrategyEvidenceManifest(unittest.TestCase):
    def test_manifest_and_notification_keep_missing_reason_visible(self) -> None:
        opinion = AgentOpinion(
            agent_name="skill_breakout",
            signal="buy",
            confidence=0.8,
            raw_data={
                "evidence_status": "insufficient",
                "missing_required_tools": ["search_stock_news"],
                "limited_required_tools": [],
                "required_tool_evidence": [{
                    "tool": "search_stock_news",
                    "status": "missing",
                    "sources": ["searxng"],
                    "cached": False,
                    "partial": False,
                    "key_values": {},
                    "missing_reason": "no results",
                }],
            },
        )
        manifest = build_strategy_evidence_manifest(
            tool_evidence=opinion.raw_data["required_tool_evidence"],
            opinions=[opinion],
            invalid_records=[],
        )

        self.assertEqual(manifest["status"], "insufficient")
        self.assertIn("breakout: required data unavailable (search_stock_news)", manifest["limitations"])
        self.assertTrue(manifest["items"][0]["required"])
        self.assertEqual(manifest["items"][0]["required_by"], ["breakout"])
        self.assertEqual(
            extract_strategy_evidence_manifest({"dashboard": {"strategy_data_evidence": manifest}}),
            manifest,
        )

        lines = []
        _append_strategy_data_evidence_block(lines, manifest, "zh")
        rendered = "\n".join(lines)
        self.assertIn("策略关键数据与来源", rendered)
        self.assertIn("source=searxng", rendered)
        self.assertIn("required data unavailable", rendered)

    def test_other_agent_call_cannot_mask_missing_strategy_dependency(self) -> None:
        manifest = build_strategy_evidence_manifest(
            tool_evidence=[{
                "tool": "get_realtime_quote",
                "status": "available",
                "sources": ["other-agent-source"],
                "cached": False,
                "partial": False,
                "key_values": {"price": 10.0},
                "stage": "technical_analyst",
            }],
            opinions=[],
            invalid_records=[{
                "agent_name": "skill_breakout",
                "reason": "insufficient_required_data",
                "missing_required_tools": ["get_realtime_quote"],
                "limited_required_tools": [],
                "required_tool_evidence": [{
                    "tool": "get_realtime_quote",
                    "status": "missing",
                    "sources": [],
                    "cached": False,
                    "partial": False,
                    "key_values": {},
                    "missing_reason": "required_tool_not_called",
                }],
            }],
        )

        self.assertEqual(manifest["status"], "insufficient")
        self.assertEqual(len(manifest["items"]), 1)
        self.assertEqual(manifest["items"][0]["status"], "missing")
        self.assertEqual(manifest["items"][0]["required_by"], ["breakout"])
        self.assertNotIn("other-agent-source", manifest["items"][0]["sources"])

    def test_markdown_uses_chinese_tool_description_and_failure_attempt(self) -> None:
        rendered = format_strategy_evidence_markdown({
            "schema_version": "strategy-evidence-v1",
            "status": "insufficient",
            "items": [{
                "tool": "analyze_pattern",
                "tool_display_name": "K线形态识别",
                "data_description": "日线K线（开盘、最高、最低、收盘、成交量）",
                "status": "fetch_failed",
                "sources": ["AkshareFetcher"],
                "source_links": [{
                    "name": "AkshareFetcher",
                    "url": "https://www.akshare.xyz/",
                }],
                "key_values": {},
                "failure_attempts": [{
                    "provider": "AkshareFetcher",
                    "operation": "get_daily_data",
                    "reason": "empty result",
                }],
            }],
            "strategy_requirements": [],
            "limitations": [],
        }, "zh")

        self.assertIn("K线形态识别 (`analyze_pattern`): 抓取失败", rendered)
        self.assertIn("[AkshareFetcher](https://www.akshare.xyz/)", rendered)
        self.assertIn("failure=AkshareFetcher get_daily_data: empty result", rendered)


if __name__ == "__main__":
    unittest.main()
