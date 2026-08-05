# -*- coding: utf-8 -*-
"""
Contract tests for get_stock_info tool output semantics.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent.tools.data_tools import _handle_get_stock_info


class _DummyManager:
    def __init__(self):
        self.fundamental_budget = None
        self.belong_kwargs = {}
        self._context = {
            "market": "cn",
            "status": "partial",
            "source_chain": [
                {"provider": "tushare", "result": "ok"},
                {"provider": "fundamental_pipeline", "result": "partial"},
            ],
            "coverage": {
                "valuation": "ok",
                "growth": "not_supported",
                "earnings": "not_supported",
                "institution": "not_supported",
                "capital_flow": "not_supported",
                "dragon_tiger": "not_supported",
                "boards": "ok",
            },
            "valuation": {
                "status": "ok",
                "data": {
                    "pe_ratio": 12.3,
                    "pb_ratio": 2.1,
                    "total_mv": 1.0e11,
                    "circ_mv": 7.0e10,
                },
            },
            "growth": {"status": "not_supported", "data": {}},
            "earnings": {"status": "not_supported", "data": {}},
            "institution": {"status": "not_supported", "data": {}},
            "capital_flow": {"status": "not_supported", "data": {}},
            "dragon_tiger": {"status": "not_supported", "data": {}},
            "boards": {
                "status": "ok",
                "data": {
                    "top": [{"name": "白酒", "change_pct": 2.3}],
                    "bottom": [{"name": "煤炭", "change_pct": -1.7}],
                },
            },
        }
        self._belong_boards = [{"name": "白酒"}, {"name": "消费"}]

    def get_fundamental_context(self, _stock_code: str, budget_seconds=None):
        self.fundamental_budget = budget_seconds
        return self._context

    def build_failed_fundamental_context(self, _stock_code: str, _reason: str):
        return {}

    def get_belong_boards(self, _stock_code: str, **kwargs):
        self.belong_kwargs = kwargs
        return self._belong_boards

    def get_stock_name(self, _stock_code: str, allow_realtime=True):
        return "贵州茅台"

    @staticmethod
    def _run_with_timeout(task, _timeout_seconds, _task_name):
        return task(), None, 0


class TestGetStockInfoContract(unittest.TestCase):
    def test_get_stock_info_preserves_board_semantics(self) -> None:
        manager = _DummyManager()
        with patch("src.agent.tools.data_tools._get_fetcher_manager", return_value=manager):
            result = _handle_get_stock_info("600519")

        self.assertEqual(result["name"], "贵州茅台")
        self.assertEqual(result["code"], "600519")
        self.assertEqual(result["pe_ratio"], 12.3)
        self.assertEqual(result["pb_ratio"], 2.1)
        self.assertEqual(result["status"], "partial")
        total_budget = result["timeout_budget"]["total_seconds"]
        self.assertGreater(manager.fundamental_budget, 0)
        self.assertLess(manager.fundamental_budget, total_budget)
        self.assertLessEqual(manager.belong_kwargs["provider_timeout_seconds"], 8)
        self.assertLessEqual(
            manager.belong_kwargs["total_timeout_seconds"],
            total_budget - manager.fundamental_budget,
        )

        # Contract: boards is compatibility alias of belong_boards.
        self.assertEqual(result["belong_boards"], manager._belong_boards)
        self.assertEqual(result["boards"], result["belong_boards"])

        # Contract: sector_rankings comes from fundamental_context.boards.data.
        self.assertEqual(result["sector_rankings"], manager._context["boards"]["data"])
        self.assertEqual(
            result["fundamental_context"]["boards"]["data"],
            result["sector_rankings"],
        )
        self.assertEqual(
            result["fundamental_context"]["source_chain"],
            manager._context["source_chain"],
        )

    def test_get_stock_info_exposes_growth_and_reuses_quote_valuation(self) -> None:
        manager = _DummyManager()
        manager._context["valuation"]["data"] = {
            "pe_ratio": None,
            "pb_ratio": None,
            "total_mv": None,
            "circ_mv": None,
        }
        manager._context["growth"] = {
            "status": "ok",
            "data": {
                "revenue_yoy": 21.5,
                "net_profit_yoy": 18.2,
                "roe": 12.6,
                "gross_margin": 46.8,
            },
        }
        manager.get_realtime_quote = lambda _code: type("Quote", (), {
            "pe_ratio": 90.59,
            "pb_ratio": 10.52,
            "total_mv": 260_418_000_000,
            "circ_mv": 248_077_000_000,
        })()

        with patch("src.agent.tools.data_tools._get_fetcher_manager", return_value=manager):
            result = _handle_get_stock_info("603986")

        self.assertEqual(result["pe_ratio"], 90.59)
        self.assertEqual(result["pb_ratio"], 10.52)
        self.assertEqual(result["revenue_yoy"], 21.5)
        self.assertEqual(result["net_profit_yoy"], 18.2)
        self.assertEqual(result["roe"], 12.6)
        self.assertEqual(result["gross_margin"], 46.8)
        self.assertEqual(result["missing_fields"], [])
        self.assertEqual(result["status"], "available")

    def test_get_stock_info_reports_missing_fields_without_inventing_values(self) -> None:
        manager = _DummyManager()
        manager._context["status"] = "failed"
        manager._context["valuation"] = {"status": "failed", "data": {}}
        manager._context["growth"] = {"status": "failed", "data": {}}
        manager._context["boards"] = {"status": "failed", "data": {}}
        manager._belong_boards = []
        manager.get_realtime_quote = lambda _code: None

        with patch("src.agent.tools.data_tools._get_fetcher_manager", return_value=manager):
            result = _handle_get_stock_info("600519")

        self.assertEqual(result["status"], "missing")
        self.assertIsNone(result["pe_ratio"])
        self.assertIsNone(result["revenue_yoy"])
        self.assertIn("pe_ratio", result["missing_fields"])
        self.assertTrue(result["data_limitations"])


if __name__ == "__main__":
    unittest.main()
