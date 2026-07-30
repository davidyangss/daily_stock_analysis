# -*- coding: utf-8 -*-
"""Regression tests for AkShare chip distribution source fallback."""

import sys
from types import SimpleNamespace

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.akshare_fetcher import (
    AkshareFetcher,
    _calculate_chip_distribution_from_history,
)


def _chip_history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-07-27", periods=3),
            "open": [10.0, 10.2, 10.4],
            "close": [10.2, 10.4, 10.6],
            "high": [10.3, 10.5, 10.7],
            "low": [9.9, 10.1, 10.3],
            # AkShare's Sina and Tencent adapters expose a decimal ratio.
            "turnover": [0.01, 0.02, 0.03],
        }
    )


def _eastmoney_chip() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2026-07-29"],
            "获利比例": [0.61],
            "平均成本": [10.2],
            "90成本-低": [9.5],
            "90成本-高": [11.0],
            "90集中度": [0.073],
            "70成本-低": [9.8],
            "70成本-高": [10.7],
            "70集中度": [0.044],
        }
    )


def _install_fake_akshare(monkeypatch, *, eastmoney, sina, tencent):
    calls = []

    def record(name, result):
        def call(**kwargs):
            calls.append((name, kwargs))
            if isinstance(result, Exception):
                raise result
            return result.copy()

        return call

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_cyq_em=record("eastmoney", eastmoney),
            stock_zh_a_daily=record("sina", sina),
            stock_zh_a_hist_tx=record("tencent", tencent),
        ),
    )
    return calls


def _run_calls_inline(monkeypatch):
    def inline(func, *args, timeout=None, call_name="", **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("data_provider.akshare_fetcher._akshare_call_with_timeout", inline)


def test_chip_distribution_prefers_eastmoney(monkeypatch):
    calls = _install_fake_akshare(
        monkeypatch,
        eastmoney=_eastmoney_chip(),
        sina=_chip_history(),
        tencent=_chip_history(),
    )
    _run_calls_inline(monkeypatch)
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)

    chip = fetcher.get_chip_distribution("600519")

    assert [name for name, _ in calls] == ["eastmoney"]
    assert chip is not None
    assert chip.source == "akshare_eastmoney"
    assert chip.avg_cost == 10.2


def test_chip_distribution_uses_sina_unadjusted_history_after_eastmoney_failure(monkeypatch):
    calls = _install_fake_akshare(
        monkeypatch,
        eastmoney=ConnectionError("eastmoney unavailable"),
        sina=_chip_history(),
        tencent=_chip_history(),
    )
    _run_calls_inline(monkeypatch)
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)

    chip = fetcher.get_chip_distribution("600519")

    assert [name for name, _ in calls] == ["eastmoney", "sina"]
    assert calls[1][1]["symbol"] == "sh600519"
    assert calls[1][1]["adjust"] == ""
    assert chip is not None
    assert chip.source == "akshare_sina_calculated"
    assert chip.date == "2026-07-29"
    assert chip.avg_cost > 0


def test_chip_distribution_uses_tencent_after_sina_failure(monkeypatch):
    calls = _install_fake_akshare(
        monkeypatch,
        eastmoney=pd.DataFrame(),
        sina=TimeoutError("sina unavailable"),
        tencent=_chip_history(),
    )
    _run_calls_inline(monkeypatch)
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)

    chip = fetcher.get_chip_distribution("300750")

    assert [name for name, _ in calls] == ["eastmoney", "sina", "tencent"]
    assert calls[2][1]["symbol"] == "sz300750"
    assert calls[2][1]["adjust"] == ""
    assert chip is not None
    assert chip.source == "akshare_tencent_calculated"


def test_chip_distribution_rejects_incomplete_eastmoney_metrics(monkeypatch):
    incomplete = _eastmoney_chip().drop(columns=["90集中度"])
    calls = _install_fake_akshare(
        monkeypatch,
        eastmoney=incomplete,
        sina=_chip_history(),
        tencent=_chip_history(),
    )
    _run_calls_inline(monkeypatch)
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)

    chip = fetcher.get_chip_distribution("600519")

    assert [name for name, _ in calls] == ["eastmoney", "sina"]
    assert chip is not None
    assert chip.source == "akshare_sina_calculated"


def test_local_chip_calculation_keeps_decimal_turnover_contract():
    history = pd.DataFrame(
        {
            "date": pd.date_range("2026-07-28", periods=2),
            "open": [10.0, 20.0],
            "close": [10.0, 20.0],
            "high": [10.0, 20.0],
            "low": [10.0, 20.0],
            "turnover": [1.0, 1.0],
        }
    )

    chip = _calculate_chip_distribution_from_history(
        "600519", history, "akshare_sina_calculated"
    )

    # A 100% turnover on the second day fully replaces the first day's chips.
    # The upstream-compatible 150-bin grid quantizes the one-price chip to
    # the closest bucket below 20 rather than preserving the exact tick.
    assert chip.avg_cost > 19.9
    assert chip.profit_ratio == 1.0
    assert chip.cost_90_low == chip.avg_cost
    assert chip.cost_90_high == chip.avg_cost
