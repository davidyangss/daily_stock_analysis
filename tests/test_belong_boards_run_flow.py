# -*- coding: utf-8 -*-
"""Regression tests for belong-board run-flow diagnostics."""

import time
from types import SimpleNamespace
from unittest.mock import patch

from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    current_diagnostic_snapshot,
    reset_run_diagnostic_context,
)
from data_provider.base import DataFetcherManager


class _BoardFetcher:
    def __init__(self, name: str, result):
        self.name = name
        self.priority = 0
        self._result = result
        self.calls = 0

    def get_belong_board(self, _stock_code: str):
        self.calls += 1
        return self._result


class _FailingBoardFetcher(_BoardFetcher):
    def __init__(self, name: str, error: Exception):
        super().__init__(name, [])
        self._error = error

    def get_belong_board(self, _stock_code: str):
        self.calls += 1
        raise self._error


class _SlowBoardFetcher(_BoardFetcher):
    def __init__(self, name: str, delay_seconds: float, result):
        super().__init__(name, result)
        self._delay_seconds = delay_seconds

    def get_belong_board(self, _stock_code: str):
        self.calls += 1
        time.sleep(self._delay_seconds)
        return self._result


def _capture_belong_board_run(manager: DataFetcherManager):
    flow_events = []
    token = activate_run_diagnostic_context(
        trace_id="trace-boards",
        task_id="task-boards",
        query_id="query-boards",
        stock_code="600519",
        trigger_source="api",
        event_sink=flow_events.append,
    )
    try:
        boards = manager.get_belong_boards("600519")
        diagnostics = current_diagnostic_snapshot()
    finally:
        reset_run_diagnostic_context(token)
    return boards, diagnostics, flow_events


def test_get_belong_boards_records_successful_provider_run():
    manager = DataFetcherManager(
        fetchers=[
            _BoardFetcher(
                "BoardFetcher",
                [{"name": "白酒", "type": "行业"}],
            )
        ]
    )

    boards, diagnostics, flow_events = _capture_belong_board_run(manager)

    assert boards
    assert diagnostics is not None
    provider_runs = diagnostics["provider_runs"]
    assert len(provider_runs) == 1
    assert provider_runs[0]["data_type"] == "belong_boards"
    assert provider_runs[0]["provider"] == "BoardFetcher"
    assert provider_runs[0]["operation"] == "get_belong_board"
    assert provider_runs[0]["success"] is True
    assert provider_runs[0]["record_count"] == len(boards)
    assert [event["type"] for event in flow_events] == ["provider_run_started", "provider_run"]
    assert flow_events[0]["node_id"] == flow_events[1]["node_id"]
    assert flow_events[0]["node_id"] == "provider_belong_boards_boardfetcher_1"


def test_get_belong_boards_records_empty_attempt_and_fallback():
    manager = DataFetcherManager(
        fetchers=[
            _BoardFetcher("EmptyBoardFetcher", []),
            _BoardFetcher("FallbackBoardFetcher", [{"name": "电力设备", "type": "行业"}]),
        ]
    )

    boards, diagnostics, flow_events = _capture_belong_board_run(manager)

    assert boards
    assert diagnostics is not None
    provider_runs = diagnostics["provider_runs"]
    assert [run["provider"] for run in provider_runs] == ["EmptyBoardFetcher", "FallbackBoardFetcher"]
    assert [run["success"] for run in provider_runs] == [False, True]
    assert provider_runs[0]["error_type"] == "empty"
    assert provider_runs[0]["fallback_to"] == "FallbackBoardFetcher"
    assert len(flow_events) == 4


def test_get_belong_boards_records_exception_attempt_and_fallback():
    manager = DataFetcherManager(
        fetchers=[
            _FailingBoardFetcher("FailingBoardFetcher", RuntimeError("board source down")),
            _BoardFetcher("FallbackBoardFetcher", [{"name": "电力设备", "type": "行业"}]),
        ]
    )

    boards, diagnostics, flow_events = _capture_belong_board_run(manager)

    assert boards
    assert diagnostics is not None
    provider_runs = diagnostics["provider_runs"]
    assert [run["provider"] for run in provider_runs] == ["FailingBoardFetcher", "FallbackBoardFetcher"]
    assert provider_runs[0]["success"] is False
    assert provider_runs[0]["error_type"] == "RuntimeError"
    assert provider_runs[0]["fallback_to"] == "FallbackBoardFetcher"
    assert provider_runs[1]["success"] is True
    assert len(flow_events) == 4


def test_get_belong_boards_times_out_one_provider_then_falls_back():
    slow = _SlowBoardFetcher("SlowBoardFetcher", 0.1, [{"name": "迟到板块"}])
    fallback = _BoardFetcher(
        "FallbackBoardFetcher",
        [{"name": "电力设备", "type": "行业"}],
    )
    manager = DataFetcherManager(fetchers=[slow, fallback])

    config = SimpleNamespace(
        provider_loop_timeout_seconds=60.0,
        provider_loop_total_timeout_seconds=60.0,
        provider_timeout_overrides={"slowboardfetcher": 1.0},
        data_provider_max_attempts=1,
        data_provider_retry_base_delay_seconds=0.0,
        data_provider_retry_max_delay_seconds=0.0,
    )
    with patch("src.config.get_config", return_value=config):
        boards = manager.get_belong_boards(
            "600519",
            provider_timeout_seconds=0.01,
            total_timeout_seconds=0.1,
        )

    assert boards == [{"name": "电力设备", "type": "行业"}]
    assert slow.calls == 1
    assert fallback.calls == 1


def test_get_belong_boards_stops_when_total_budget_is_exhausted():
    slow = _SlowBoardFetcher("SlowBoardFetcher", 0.1, [{"name": "迟到板块"}])
    fallback = _BoardFetcher("FallbackBoardFetcher", [{"name": "不应调用"}])
    manager = DataFetcherManager(fetchers=[slow, fallback])

    boards = manager.get_belong_boards(
        "600519",
        provider_timeout_seconds=0.05,
        total_timeout_seconds=0.01,
    )

    assert boards == []
    assert slow.calls == 1
    assert fallback.calls == 0
