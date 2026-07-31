# -*- coding: utf-8 -*-
"""Small contract tests for MX/browser startup ordering."""

from api.app import _provider_precedes


def test_mx_precedes_browser_in_default_order() -> None:
    assert _provider_precedes("tencent,eastmoney_mx,eastmoney_browser", "eastmoney_mx", "eastmoney_browser")


def test_explicit_browser_first_or_missing_mx_does_not_match() -> None:
    assert not _provider_precedes("eastmoney_browser,eastmoney_mx", "eastmoney_mx", "eastmoney_browser")
    assert not _provider_precedes("tencent,eastmoney_browser", "eastmoney_mx", "eastmoney_browser")
