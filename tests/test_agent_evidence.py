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
    build_prefetched_context_evidence,
    build_strategy_evidence_manifest,
    extract_strategy_evidence_manifest,
    format_strategy_evidence_markdown,
    summarize_tool_result,
    merge_prefetched_evidence,
)
from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.skills.engine import StrategyEngine, StrategyResultStatus
from src.agent.skills.skill_agent import SkillAgent
from src.notification import _append_strategy_data_evidence_block


class TestToolEvidence(unittest.TestCase):
    def test_complete_stock_info_metrics_override_broad_partial_context(self) -> None:
        evidence = summarize_tool_result(
            "get_stock_info",
            {
                "status": "partial",
                "pe_ratio": 17.12,
                "pb_ratio": 2.56,
                "revenue_yoy": 34.46,
                "net_profit_yoy": 0.89,
                "roe": 1.84,
                "gross_margin": 26.24,
                "data_limitations": ["belong_boards unavailable"],
            },
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "available")
        self.assertFalse(evidence["partial"])
        self.assertEqual(evidence["missing_fields"], [])

    def test_incomplete_stock_info_metrics_remain_partial(self) -> None:
        evidence = summarize_tool_result(
            "get_stock_info",
            {
                "status": "partial",
                "pe_ratio": 17.12,
                "pb_ratio": 2.56,
                "revenue_yoy": 34.46,
                "net_profit_yoy": 0.89,
                "roe": 1.84,
                "gross_margin": None,
            },
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "partial")
        self.assertTrue(evidence["partial"])
        self.assertEqual(evidence["missing_fields"], ["gross_margin"])

    def test_large_numeric_metrics_use_thousands_separators(self) -> None:
        evidence = summarize_tool_result(
            "get_daily_history",
            json.dumps({
                "success": True,
                "data": [{
                    "date": "2026-07-30",
                    "open": 356.75,
                    "high": 392.07,
                    "low": 342.0,
                    "close": 371.1,
                    "volume": 97123885.0,
                    "amount": 35483794588.0,
                }],
                "source": "db_cache",
            }),
            execution_success=True,
        )

        metrics = {item["key"]: item for item in evidence["metric_details"]}
        self.assertEqual(metrics["latest_close"]["display_value"], "371.10元")
        self.assertEqual(metrics["latest_volume"]["display_value"], "97,123,885.00股")
        self.assertEqual(metrics["latest_amount"]["display_value"], "35,483,794,588.00元")

    def test_prefetched_chip_is_persistable_detailed_evidence(self) -> None:
        items = build_prefetched_context_evidence({
            "chip_distribution": {
                "source": "akshare_sina_calculated",
                "profit_ratio": 0.0758,
                "avg_cost": 470.14,
                "cost_90_low": 363.73,
                "cost_90_high": 711.6,
                "concentration_90": 0.3235,
                "concentration_70": None,
            }
        })

        self.assertEqual(len(items), 1)
        chip = items[0]
        self.assertEqual(chip["tool"], "get_chip_distribution")
        self.assertTrue(chip["prefetched"])
        self.assertEqual(chip["status"], "available")
        metrics = {item["key"]: item for item in chip["metric_details"]}
        self.assertEqual(metrics["profit_ratio"]["display_value"], "7.58%")
        self.assertEqual(metrics["avg_cost"]["display_value"], "470.14元")
        self.assertEqual(metrics["concentration_70"]["status"], "missing")
        self.assertIn("concentration_70", chip["missing_fields"])

        manifest = merge_prefetched_evidence(None, items)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["items"][0]["stage"], "prefetch")
        json.dumps(manifest, ensure_ascii=False)

    def test_prefetched_trend_result_is_persisted_as_strategy_input(self) -> None:
        items = build_prefetched_context_evidence({
            "trend_result": {
                "current_price": 1880.0,
                "ma5": 1865.2,
                "ma20": 1812.6,
                "macd_dif": 12.3,
                "rsi_6": 67.8,
                "signal_score": 72,
            },
        })

        self.assertEqual(len(items), 1)
        trend = items[0]
        self.assertEqual(trend["tool"], "analyze_trend")
        self.assertTrue(trend["prefetched"])
        self.assertEqual(trend["key_values"]["ma20"], 1812.6)
        metrics = {item["key"]: item for item in trend["metric_details"]}
        self.assertEqual(metrics["rsi_6"]["display_value"], "67.80")
        self.assertEqual(metrics["signal_score"]["display_value"], "72分")

    def test_prefetched_fundamentals_replace_missing_metric_evidence(self) -> None:
        existing = summarize_tool_result(
            "get_stock_info",
            {"status": "partial", "pe_ratio": None, "pb_ratio": None},
            execution_success=True,
        )
        manifest = {
            "schema_version": "strategy-evidence-v1",
            "status": "verified",
            "items": [existing],
            "strategy_requirements": [],
            "limitations": [],
        }
        prefetched = build_prefetched_context_evidence({
            "fundamental_context": {
                "status": "partial",
                "source_chain": [{"provider": "realtime_quote", "result": "fallback"}],
                "valuation": {
                    "status": "ok",
                    "data": {"pe_ratio": 90.59, "pb_ratio": 10.52},
                },
                "growth": {"status": "partial", "data": {}},
            },
        })

        merged = merge_prefetched_evidence(manifest, prefetched)
        stock_info = merged["items"][0]
        metrics = {metric["key"]: metric for metric in stock_info["metric_details"]}
        self.assertEqual(stock_info["key_values"]["pe_ratio"], 90.59)
        self.assertEqual(metrics["pe_ratio"]["status"], "available")
        self.assertEqual(metrics["pb_ratio"]["display_value"], "10.52倍")
        self.assertNotIn("pe_ratio", stock_info["missing_fields"])
        self.assertIn("roe", stock_info["missing_fields"])

    def test_prefetched_fundamentals_upgrade_required_missing_evidence(self) -> None:
        missing = summarize_tool_result(
            "get_stock_info",
            {"status": "missing", "missing_reason": "required_tool_not_called"},
            execution_success=True,
        )
        missing["required"] = True
        missing["required_by"] = ["expectation_repricing"]
        manifest = {
            "schema_version": "strategy-evidence-v1",
            "status": "insufficient",
            "items": [missing],
            "strategy_requirements": [{
                "skill_id": "expectation_repricing",
                "status": "insufficient",
                "missing_tools": ["get_stock_info"],
                "limited_tools": [],
                "evidence": [missing],
            }],
            "strategy_evaluations": [{
                "skill_id": "expectation_repricing",
                "status": "insufficient",
                "evaluation_mode": "joint",
                "evidence_status": "insufficient",
            }],
            "limitations": [
                "expectation_repricing: required data unavailable (get_stock_info)"
            ],
        }
        prefetched = build_prefetched_context_evidence({
            "fundamental_context": {
                "status": "partial",
                "source_chain": [{"provider": "realtime_quote", "result": "fallback"}],
                "valuation": {"status": "ok", "data": {"pe_ratio": 17.12, "pb_ratio": 2.56}},
                "growth": {"status": "partial", "data": {"roe": 1.84}},
            },
        })

        merged = merge_prefetched_evidence(manifest, prefetched)

        stock_info = merged["items"][0]
        self.assertEqual(stock_info["status"], "partial")
        self.assertTrue(stock_info["prefetched"])
        self.assertNotIn("missing_reason", stock_info)
        requirement = merged["strategy_requirements"][0]
        self.assertEqual(requirement["status"], "limited")
        self.assertEqual(requirement["missing_tools"], [])
        self.assertEqual(requirement["limited_tools"], ["get_stock_info"])
        self.assertEqual(requirement["evidence"][0]["status"], "partial")
        self.assertEqual(merged["strategy_evaluations"][0]["status"], "invalid")
        self.assertEqual(merged["strategy_evaluations"][0]["evidence_status"], "limited")
        self.assertEqual(merged["status"], "limited")
        self.assertEqual(
            merged["limitations"],
            ["expectation_repricing: required data degraded (get_stock_info)"],
        )

    def test_merge_does_not_use_another_strategy_same_tool_result(self) -> None:
        missing = summarize_tool_result(
            "get_realtime_quote",
            {"status": "missing", "missing_reason": "required_tool_not_called"},
            execution_success=True,
        )
        available = summarize_tool_result(
            "get_realtime_quote",
            {"price": 12.34, "source": "runtime"},
            execution_success=True,
        )
        manifest = {
            "schema_version": "strategy-evidence-v1",
            "status": "insufficient",
            "items": [dict(missing), dict(available)],
            "strategy_requirements": [
                {
                    "skill_id": "strategy_a",
                    "status": "insufficient",
                    "missing_tools": ["get_realtime_quote"],
                    "limited_tools": [],
                    "evidence": [dict(missing)],
                },
                {
                    "skill_id": "strategy_b",
                    "status": "verified",
                    "missing_tools": [],
                    "limited_tools": [],
                    "evidence": [dict(available)],
                },
            ],
            "strategy_evaluations": [],
            "limitations": [],
        }

        merged = merge_prefetched_evidence(manifest, [])
        requirements = {
            item["skill_id"]: item for item in merged["strategy_requirements"]
        }

        self.assertEqual(requirements["strategy_a"]["status"], "insufficient")
        self.assertEqual(
            requirements["strategy_a"]["evidence"][0]["status"],
            "missing",
        )
        self.assertEqual(requirements["strategy_b"]["status"], "verified")
        self.assertEqual(
            requirements["strategy_b"]["evidence"][0]["status"],
            "available",
        )

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

    def test_intel_and_capital_flow_tools_have_chinese_presentations(self) -> None:
        intel = summarize_tool_result(
            "search_comprehensive_intel",
            {"dimensions": {"latest_news": {"results_count": 1}}},
            execution_success=True,
        )
        capital_flow = summarize_tool_result(
            "get_capital_flow",
            {"status": "ok", "main_net_inflow": 12_000_000},
            execution_success=True,
        )

        self.assertEqual(intel["tool_display_name"], "综合情报搜索")
        self.assertEqual(capital_flow["tool_display_name"], "主力资金流向获取")
        self.assertNotEqual(intel["tool_display_name"], "search_comprehensive_intel")
        self.assertNotEqual(capital_flow["tool_display_name"], "get_capital_flow")

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

    def test_failure_reason_uses_errors_array(self) -> None:
        evidence = summarize_tool_result(
            "get_capital_flow",
            {"status": "failed", "errors": ["capital_flow timeout"]},
            execution_success=True,
        )

        self.assertEqual(evidence["status"], "fetch_failed")
        self.assertEqual(evidence["missing_reason"], "capital_flow timeout")


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

    def test_uncalled_fundamental_tool_lists_each_required_metric(self) -> None:
        agent = self._agent(["get_stock_info"])

        opinion = agent.attach_execution_evidence(
            AgentOpinion(agent_name="skill_test_skill", signal="hold", confidence=0.4),
            [],
        )

        evidence = opinion.raw_data["required_tool_evidence"][0]
        self.assertEqual(evidence["status"], "missing")
        self.assertEqual(evidence["data_description"], "股票基础资料与基本面")
        self.assertEqual(
            [item["label"] for item in evidence["metric_details"]],
            [
                "市盈率（PE）",
                "市净率（PB）",
                "营收同比增长率",
                "净利润同比增长率",
                "净资产收益率（ROE）",
                "毛利率",
            ],
        )
        self.assertTrue(all(
            item["status"] == "missing" for item in evidence["metric_details"]
        ))

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

    def test_prefetched_fundamentals_satisfy_specialist_without_second_call(self) -> None:
        agent = self._agent(["get_stock_info", "search_stock_news"])
        ctx = AgentContext(query="分析 600519", stock_code="600519")
        ctx.set_data("fundamental_context", {
            "status": "partial",
            "source_chain": [{"provider": "iwencai", "result": "ok"}],
            "valuation": {"status": "ok", "data": {"pe_ratio": 18.5}},
            "growth": {"status": "partial", "data": {"revenue_yoy": None}},
        })

        prompt = agent.system_prompt(ctx)
        opinion = agent.attach_execution_evidence(
            AgentOpinion(
                agent_name="skill_test_skill",
                signal="hold",
                confidence=0.5,
            ),
            [],
            ctx=ctx,
        )

        self.assertIn("do not call them again: get_stock_info", prompt)
        self.assertIn("Call each still-unresolved required tool once: search_stock_news", prompt)
        evidence_by_tool = {
            item["tool"]: item for item in opinion.raw_data["required_tool_evidence"]
        }
        self.assertTrue(evidence_by_tool["get_stock_info"]["prefetched"])
        self.assertEqual(evidence_by_tool["get_stock_info"]["status"], "partial")
        self.assertNotIn("get_stock_info", opinion.raw_data["missing_required_tools"])
        self.assertIn("get_stock_info", opinion.raw_data["limited_required_tools"])
        self.assertIn("search_stock_news", opinion.raw_data["missing_required_tools"])


class TestStrategyEvidenceManifest(unittest.TestCase):
    def test_consensus_opinion_is_not_projected_as_selected_strategy(self) -> None:
        selected = [{"skill_id": "box_oscillation", "skill_name": "箱体震荡"}]
        specialist = AgentOpinion(
            agent_name="skill_box_oscillation",
            signal="hold",
            confidence=0.6,
            reasoning="箱体仍待确认。",
            raw_data={"evidence_status": "verified"},
        )
        consensus = AgentOpinion(
            agent_name="skill_consensus",
            signal="hold",
            confidence=0.6,
            reasoning="deterministic aggregate",
            raw_data={"strategy_synthesis": {"final_signal": "hold"}},
        )

        manifest = build_strategy_evidence_manifest(
            tool_evidence=[],
            opinions=[specialist, consensus],
            invalid_records=[],
            selected_strategies=selected,
        )

        self.assertEqual(manifest["selected_strategies"], selected)
        self.assertEqual(
            [item["skill_id"] for item in manifest["strategy_evaluations"]],
            ["box_oscillation"],
        )

    def test_joint_strategy_assessments_expose_each_declared_input(self) -> None:
        tool_evidence = [
            {
                "tool": tool,
                "status": status,
                "sources": ["runtime"],
                "cached": False,
                "partial": status == "partial",
                "key_values": {
                    "get_daily_history": {"latest_close": 10.2},
                    "analyze_trend": {"ma20": 9.8},
                    "get_realtime_quote": {"price": 10.2},
                    "search_stock_news": {"record_count": 3},
                    "get_stock_info": {"pe_ratio": 18.0},
                }[tool],
            }
            for tool, status in (
                ("get_daily_history", "available"),
                ("analyze_trend", "available"),
                ("get_realtime_quote", "available"),
                ("search_stock_news", "available"),
                ("get_stock_info", "partial"),
            )
        ]
        manifest = build_strategy_evidence_manifest(
            tool_evidence=tool_evidence,
            opinions=[],
            invalid_records=[],
            selected_strategies=[
                {"skill_id": "box_oscillation", "skill_name": "箱体震荡"},
                {"skill_id": "emotion_cycle", "skill_name": "情绪周期"},
                {"skill_id": "expectation_repricing", "skill_name": "预期重估"},
            ],
            selected_strategy_requirements={
                "box_oscillation": [
                    "get_daily_history", "analyze_trend", "get_realtime_quote",
                ],
                "emotion_cycle": [
                    "get_daily_history", "get_realtime_quote", "analyze_trend",
                    "search_stock_news",
                ],
                "expectation_repricing": [
                    "search_stock_news", "get_stock_info", "get_realtime_quote",
                    "analyze_trend",
                ],
            },
            joint_strategy_assessments={
                "box_oscillation": {
                    "joint_assessment": "箱体边界触碰次数不足。",
                    "signal": "hold",
                    "confidence": 0.55,
                    "decisive_evidence": [{
                        "tool": "get_realtime_quote",
                        "fields": ["price"],
                        "summary": "现价接近支撑。",
                    }],
                    "conditions_met": ["现价接近支撑。"],
                    "conditions_missed": ["触碰次数不足。"],
                    "limitations": ["缺少完整触碰次数。"],
                },
                "emotion_cycle": {
                    "joint_assessment": "情绪强度一般。",
                    "signal": "hold",
                    "confidence": 0.5,
                    "decisive_evidence": [{
                        "tool": "search_stock_news",
                        "fields": ["record_count"],
                        "summary": "取得三条直接相关新闻。",
                    }],
                    "conditions_met": ["存在可核验新闻"],
                    "conditions_missed": ["换手强度不足"],
                    "limitations": [],
                },
                "expectation_repricing": {
                    "joint_assessment": "盈利预期仍在下修。",
                    "signal": "sell",
                    "confidence": 0.62,
                    "decisive_evidence": [{
                        "tool": "get_stock_info",
                        "fields": ["pe_ratio"],
                        "summary": "估值字段仅部分可用。",
                    }],
                    "conditions_met": [],
                    "conditions_missed": ["缺少完整盈利增速"],
                    "limitations": ["基本面输入部分可用"],
                },
            },
        )

        evaluations = {
            item["skill_id"]: item for item in manifest["strategy_evaluations"]
        }
        self.assertEqual(evaluations["box_oscillation"]["status"], "completed")
        self.assertEqual(evaluations["box_oscillation"]["evaluation_mode"], "joint")
        self.assertEqual(evaluations["box_oscillation"]["reasoning"], "箱体边界触碰次数不足。")
        self.assertEqual(evaluations["box_oscillation"]["conditions_met"], ["现价接近支撑。"])
        self.assertEqual(evaluations["box_oscillation"]["conditions_missed"], ["触碰次数不足。"])
        self.assertEqual(evaluations["emotion_cycle"]["reasoning"], "情绪强度一般。")
        self.assertEqual(evaluations["expectation_repricing"]["evidence_status"], "limited")

        requirements = {
            item["skill_id"]: item for item in manifest["strategy_requirements"]
        }
        self.assertEqual(requirements["box_oscillation"]["status"], "verified")
        self.assertEqual(requirements["emotion_cycle"]["status"], "verified")
        self.assertEqual(requirements["expectation_repricing"]["status"], "limited")
        quote_item = next(
            item for item in manifest["items"] if item["tool"] == "get_realtime_quote"
        )
        self.assertEqual(
            quote_item["required_by"],
            ["box_oscillation", "emotion_cycle", "expectation_repricing"],
        )

    def test_joint_assessment_with_missing_dependency_is_insufficient(self) -> None:
        manifest = build_strategy_evidence_manifest(
            tool_evidence=[],
            opinions=[],
            invalid_records=[],
            selected_strategies=[{"skill_id": "emotion_cycle", "skill_name": "情绪周期"}],
            selected_strategy_requirements={"emotion_cycle": ["search_stock_news"]},
            joint_strategy_assessments={"emotion_cycle": "新闻情绪偏弱。"},
        )

        self.assertEqual(manifest["status"], "insufficient")
        self.assertEqual(manifest["strategy_evaluations"][0]["status"], "insufficient")
        self.assertEqual(manifest["strategy_requirements"][0]["missing_tools"], ["search_stock_news"])
        self.assertEqual(manifest["items"][0]["missing_reason"], "required_tool_not_called")

    def test_manifest_exposes_selected_strategy_inputs_and_decisions(self) -> None:
        opinion = AgentOpinion(
            agent_name="skill_growth_quality",
            signal="buy",
            confidence=0.82,
            reasoning="营收和利润增速匹配成长质量条件。",
            raw_data={
                "evidence_status": "verified",
                "missing_required_tools": [],
                "limited_required_tools": [],
                "required_tool_evidence": [{
                    "tool": "get_stock_info",
                    "status": "available",
                    "sources": ["iwencai"],
                    "cached": False,
                    "partial": False,
                    "key_values": {"revenue_yoy": 25.1, "net_profit_yoy": 31.6},
                }],
                "conditions_met": ["营收同比增长超过 20%", "净利润增速高于营收增速"],
                "conditions_missed": ["ROE 数据缺失"],
                "score_adjustment": 12,
            },
        )

        manifest = build_strategy_evidence_manifest(
            tool_evidence=opinion.raw_data["required_tool_evidence"],
            opinions=[opinion],
            invalid_records=[],
            selected_strategies=[{
                "skill_id": "growth_quality",
                "skill_name": "成长质量策略",
            }],
            overall_decision={
                "signal": "buy",
                "confidence": 0.78,
                "operation_advice": "回调分批关注",
                "reasoning": "策略条件大部分满足。",
            },
        )

        self.assertEqual(manifest["selected_strategies"], [{
            "skill_id": "growth_quality",
            "skill_name": "成长质量策略",
        }])
        evaluation = manifest["strategy_evaluations"][0]
        self.assertEqual(evaluation["status"], "completed")
        self.assertEqual(evaluation["signal"], "buy")
        self.assertEqual(evaluation["confidence"], 0.82)
        self.assertEqual(evaluation["conditions_met"][0], "营收同比增长超过 20%")
        self.assertEqual(manifest["overall_decision"]["signal"], "buy")
        self.assertEqual(manifest["items"][0]["required_by"], ["growth_quality"])

        rendered = format_strategy_evidence_markdown(manifest, "zh")
        self.assertIn("所选策略", rendered)
        self.assertIn("成长质量策略", rendered)
        self.assertIn("策略分析输出", rendered)
        self.assertIn("| 已完成 | 买入 | 82% |", rendered)
        self.assertIn("| 条件状态 | 判定条件 |", rendered)
        self.assertIn("| 满足条件 | 营收同比增长超过 20% |", rendered)
        self.assertIn("营收和利润增速匹配成长质量条件", rendered)
        self.assertIn("策略分析输入数据", rendered)
        self.assertIn("综合判定", rendered)
        self.assertIn("基本信息获取", rendered)
        self.assertNotIn("`get_stock_info`", rendered)

    def test_selected_strategy_without_specialist_opinion_uses_overall_decision_only(self) -> None:
        manifest = build_strategy_evidence_manifest(
            tool_evidence=[{
                "tool": "analyze_trend",
                "status": "available",
                "sources": ["db_cache"],
                "cached": True,
                "partial": False,
                "key_values": {"ma5": 10.2, "ma20": 9.8},
            }],
            opinions=[],
            invalid_records=[],
            selected_strategies=[{
                "skill_id": "bull_trend",
                "skill_name": "多头趋势策略",
            }],
            overall_decision={
                "signal": "hold",
                "confidence_label": "中",
                "reasoning": "单 Agent 综合分析结论。",
            },
        )

        self.assertEqual(manifest["strategy_evaluations"][0]["status"], "not_evaluated")
        self.assertNotIn("signal", manifest["strategy_evaluations"][0])
        self.assertEqual(manifest["overall_decision"]["signal"], "hold")

    def test_selected_strategy_without_input_still_has_visible_insufficient_block(self) -> None:
        manifest = build_strategy_evidence_manifest(
            tool_evidence=[],
            opinions=[],
            invalid_records=[],
            selected_strategies=[{
                "skill_id": "bull_trend",
                "skill_name": "多头趋势策略",
            }],
            overall_decision={"signal": "hold", "reasoning": "未取得可用输入。"},
        )

        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["status"], "insufficient")
        self.assertEqual(manifest["items"], [])
        self.assertEqual(manifest["strategy_evaluations"][0]["status"], "not_evaluated")

        rendered = format_strategy_evidence_markdown(manifest, "zh")
        self.assertIn("多头趋势策略", rendered)
        self.assertIn("未单独评估", rendered)
        self.assertIn("持有/观望", rendered)

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
        self.assertEqual(manifest["strategy_evaluations"][0]["status"], "insufficient")
        self.assertNotIn("signal", manifest["strategy_evaluations"][0])
        self.assertNotIn("confidence", manifest["strategy_evaluations"][0])
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
        self.assertIn("##### 策略分析输入数据", rendered)
        self.assertIn("searxng", rendered)
        self.assertIn(
            "| breakout | 必需输入数据不可用 | 新闻搜索 | 公开新闻与舆情 | "
            "无数据；searxng；no results |",
            rendered,
        )
        self.assertNotIn("required data unavailable", rendered)

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

        self.assertIn("#### 策略分析输入数据", rendered)
        self.assertIn("| K线形态识别 | 抓取失败 | 日线K线（开盘、最高、最低、收盘、成交量） |", rendered)
        self.assertIn("[AkshareFetcher](https://www.akshare.xyz/)", rendered)
        self.assertIn("AkshareFetcher get_daily_data: empty result", rendered)

    def test_markdown_renders_metric_details_as_hierarchical_table(self) -> None:
        rendered = format_strategy_evidence_markdown({
            "schema_version": "strategy-evidence-v1",
            "status": "limited",
            "items": [{
                "tool": "analyze_trend",
                "tool_display_name": "技术指标分析",
                "status": "available",
                "sources": ["db_cache"],
                "metric_details": [
                    {"key": "current_price", "label": "分析价格", "status": "available", "display_value": "371.10元", "description": "技术指标计算使用的价格"},
                    {"key": "revenue_yoy", "label": "营收同比增长率", "status": "missing", "display_value": None, "description": "营业收入相对上年同期的变化"},
                ],
            }],
            "strategy_requirements": [],
            "limitations": ["fundamentals partial"],
        }, "zh")

        self.assertIn("#### 策略分析输入数据", rendered)
        self.assertIn("| 技术指标分析 | 成功 |", rendered)
        self.assertIn("**技术指标分析 · 策略分析输入数据**", rendered)
        self.assertIn("| 指标 | 状态 | 数值 | 含义 |", rendered)
        self.assertIn("| 分析价格 | 可用 | 371.10元 | 技术指标计算使用的价格 |", rendered)
        self.assertIn("| 营收同比增长率 | 缺失 | — | 营业收入相对上年同期的变化 |", rendered)
        self.assertIn("#### ⚠️ 数据限制", rendered)

    def test_markdown_groups_inputs_by_strategy_and_localizes_diagnostics(self) -> None:
        rendered = format_strategy_evidence_markdown({
            "schema_version": "strategy-evidence-v1",
            "status": "limited",
            "selected_strategies": [
                {"skill_id": "expectation_repricing", "skill_name": "expectation_repricing"},
                {"skill_id": "concept_ranking", "skill_name": "concept_ranking"},
            ],
            "strategy_evaluations": [
                {
                    "skill_id": "expectation_repricing",
                    "skill_name": "expectation_repricing",
                    "status": "completed",
                    "signal": "hold",
                    "confidence": 0.5,
                    "reasoning": "估值字段部分可用。",
                    "conditions_met": [],
                    "conditions_missed": [],
                },
                {
                    "skill_id": "concept_ranking",
                    "skill_name": "concept_ranking",
                    "status": "completed",
                    "signal": "hold",
                    "confidence": 0.52,
                    "reasoning": "概念排序待确认。",
                    "conditions_met": [],
                    "conditions_missed": [],
                },
            ],
            "strategy_requirements": [
                {
                    "skill_id": "expectation_repricing",
                    "status": "limited",
                    "missing_tools": [],
                    "limited_tools": ["get_stock_info"],
                    "evidence": [{
                        "tool": "get_stock_info",
                        "status": "partial",
                        "sources": ["iwencai"],
                        "key_values": {"pe_ratio": 18.5},
                    }],
                },
                {
                    "skill_id": "concept_ranking",
                    "status": "verified",
                    "missing_tools": [],
                    "limited_tools": [],
                    "evidence": [{
                        "tool": "get_stock_info",
                        "status": "available",
                        "sources": ["tushare"],
                        "key_values": {"concept_ranking": 3},
                    }],
                },
            ],
            "items": [],
            "limitations": [
                "expectation_repricing: required data degraded (get_stock_info)",
            ],
        }, "zh")

        self.assertEqual(rendered.count("##### 策略分析输出"), 2)
        self.assertEqual(rendered.count("##### 策略分析输入数据"), 2)
        self.assertIn("iwencai", rendered)
        self.assertIn("tushare", rendered)
        self.assertIn("| 策略 | 限制状态 | 关键数据工具 | 仍需补充的数据 | 当前数据 / 失败情况 |", rendered)
        self.assertIn("| 预期重估 | 必需输入数据部分可用 | 基本信息获取 |", rendered)
        self.assertIn(
            "市净率（PB）、营收同比增长率、净利润同比增长率、"
            "净资产收益率（ROE）、毛利率 | 部分数据；iwencai |",
            rendered,
        )
        self.assertIn("概念板块排名", rendered)
        self.assertNotIn("concept_ranking", rendered)
        self.assertNotIn("expectation_repricing", rendered)
        self.assertNotIn("required data degraded", rendered)


if __name__ == "__main__":
    unittest.main()
