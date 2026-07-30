# -*- coding: utf-8 -*-
"""Tests for name_to_code_resolver.

Covers:
- Local mapping (STOCK_NAME_MAP reverse)
- Code format boundary (_is_code_like, _normalize_code)
- Pinyin match (when pypinyin available)
- AkShare fallback (mocked)
- Fuzzy match (difflib)
- Ambiguous names return None
"""

import pytest
from unittest.mock import patch

from src.services.name_to_code_resolver import (
    clear_name_resolution_cache,
    resolve_name_candidates,
    resolve_name_to_code,
    _is_code_like,
    _normalize_code,
    _build_reverse_map_no_duplicates,
    resolve_name_candidates_in_text,
)
from src.data.stock_index_loader import StockIndexIdentity


# ---------------------------------------------------------------------------
# _is_code_like
# ---------------------------------------------------------------------------

class TestIsCodeLike:
    def test_a_share_5_digits(self):
        assert _is_code_like("60051") is True
        assert _is_code_like("600519") is True

    def test_a_share_6_digits(self):
        assert _is_code_like("300750") is True

    def test_bse_with_exchange_hint(self):
        assert _is_code_like("920493.BJ") is True
        assert _is_code_like("BJ920493") is True

    def test_bj_exchange_hint_rejects_non_bse_code(self):
        assert _is_code_like("600519.BJ") is False
        assert _is_code_like("BJ600519") is False

    def test_hk_5_digits(self):
        assert _is_code_like("00700") is True

    def test_us_stock_letters(self):
        assert _is_code_like("AAPL") is True
        assert _is_code_like("TSLA") is True
        assert _is_code_like("BRK.B") is True

    def test_rejects_non_code(self):
        assert _is_code_like("贵州茅台") is False
        assert _is_code_like("1234") is False  # too short
        assert _is_code_like("1234567") is False  # too long
        assert _is_code_like("") is False
        assert _is_code_like("   ") is False


# ---------------------------------------------------------------------------
# _normalize_code
# ---------------------------------------------------------------------------

class TestNormalizeCode:
    def test_preserves_valid_a_share(self):
        assert _normalize_code("600519") == "600519"
        assert _normalize_code("  600519  ") == "600519"

    def test_strips_suffix(self):
        assert _normalize_code("600519.SH") == "600519"
        assert _normalize_code("000001.SZ") == "000001"
        assert _normalize_code("920493.BJ") == "920493"

    def test_strips_bse_prefix(self):
        assert _normalize_code("BJ920493") == "920493"

    def test_bj_exchange_hint_rejects_non_bse_code(self):
        assert _normalize_code("600519.BJ") is None
        assert _normalize_code("BJ600519") is None

    def test_preserves_us_stock(self):
        assert _normalize_code("AAPL") == "AAPL"
        assert _normalize_code("brk.b") == "BRK.B"

    def test_returns_none_for_invalid(self):
        assert _normalize_code("") is None
        assert _normalize_code("1234") is None
        assert _normalize_code("贵州茅台") is None


# ---------------------------------------------------------------------------
# _build_reverse_map_no_duplicates
# ---------------------------------------------------------------------------

class TestBuildReverseMapNoDuplicates:
    def test_excludes_ambiguous_names(self):
        # "阿里巴巴" maps to both BABA and 09988
        code_to_name = {"BABA": "阿里巴巴", "09988": "阿里巴巴", "600519": "贵州茅台"}
        result = _build_reverse_map_no_duplicates(code_to_name)
        assert "阿里巴巴" not in result
        assert result.get("贵州茅台") == "600519"

    def test_includes_unique_names(self):
        code_to_name = {"600519": "贵州茅台", "00700": "腾讯控股"}
        result = _build_reverse_map_no_duplicates(code_to_name)
        assert result["贵州茅台"] == "600519"
        assert result["腾讯控股"] == "00700"


# ---------------------------------------------------------------------------
# resolve_name_to_code
# ---------------------------------------------------------------------------

class TestResolveNameToCode:
    def setup_method(self):
        clear_name_resolution_cache()

    def teardown_method(self):
        clear_name_resolution_cache()

    def test_code_like_input_returned_normalized(self):
        assert resolve_name_to_code("600519") == "600519"
        assert resolve_name_to_code("600519.SH") == "600519"
        assert resolve_name_to_code("920493.BJ") == "920493"
        assert resolve_name_to_code("  AAPL  ") == "AAPL"

    def test_local_map_exact_match(self):
        assert resolve_name_to_code("贵州茅台") == "600519"
        assert resolve_name_to_code("腾讯控股") == "00700"

    def test_returns_none_for_empty_or_invalid_input(self):
        assert resolve_name_to_code("") is None
        assert resolve_name_to_code("   ") is None
        assert resolve_name_to_code(None) is None  # type: ignore

    def test_ambiguous_name_returns_none(self):
        # "阿里巴巴" maps to both BABA and 09988 in STOCK_NAME_MAP
        assert resolve_name_to_code("阿里巴巴") is None

    def test_company_and_english_stock_names_resolve_before_ticker_heuristic(self):
        assert resolve_name_to_code("贵州茅台酒股份有限公司") == "600519"
        assert resolve_name_to_code("Apple") == "AAPL"
        assert resolve_name_to_code("Apple Inc.") == "AAPL"
        assert resolve_name_to_code("Tesla") == "TSLA"

    def test_cross_market_company_name_returns_auditable_candidates(self):
        candidates = resolve_name_candidates("Baidu")
        assert {candidate.code for candidate in candidates} == {"BIDU", "09888"}
        assert {candidate.market for candidate in candidates} == {"US", "HK"}
        assert resolve_name_to_code("Baidu") is None

    def test_lowercase_known_ticker_uses_index_identity(self):
        assert resolve_name_to_code("aapl") == "AAPL"

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_akshare_fallback_when_not_in_local(self, mock_akshare):
        mock_akshare.return_value = {"示例股份公司": "600000"}
        result = resolve_name_to_code("示例股份公司")
        assert result == "600000"
        mock_akshare.assert_called()

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_fuzzy_match_fallback(self, mock_akshare):
        mock_akshare.return_value = {"贵州茅台": "600519"}
        # Typo: 贵州茅苔 -> should fuzzy match 贵州茅台
        result = resolve_name_to_code("贵州茅苔")
        assert result == "600519"

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_returns_none_when_no_match(self, mock_akshare):
        mock_akshare.return_value = {}
        result = resolve_name_to_code("不存在的股票名称xyz")
        assert result is None

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_skips_akshare_for_non_cjk_garbage_input(self, mock_akshare):
        result = resolve_name_to_code("aaaaaaa")
        assert result is None
        mock_akshare.assert_not_called()


def test_resolve_name_candidates_in_text_matches_chinese_short_name(monkeypatch):
    monkeypatch.setattr(
        "src.services.name_to_code_resolver.get_stock_index_identities",
        lambda: (
            StockIndexIdentity(
                canonical_code="600519.SH",
                display_code="600519",
                name_zh="贵州茅台",
                aliases=("茅台",),
                market="CN",
                popularity=100,
            ),
        ),
    )

    candidates = resolve_name_candidates_in_text("请分析茅台的趋势")

    assert [(candidate.code, candidate.name, candidate.matched_term) for candidate in candidates] == [
        ("600519", "贵州茅台", "茅台"),
    ]


def test_resolve_name_candidates_in_text_keeps_cross_market_candidates(monkeypatch):
    monkeypatch.setattr(
        "src.services.name_to_code_resolver.get_stock_index_identities",
        lambda: (
            StockIndexIdentity(
                canonical_code="BIDU",
                display_code="BIDU",
                name_zh="百度",
                market="US",
                popularity=100,
            ),
            StockIndexIdentity(
                canonical_code="09888.HK",
                display_code="09888",
                name_zh="百度集团",
                aliases=("百度",),
                market="HK",
                popularity=90,
            ),
        ),
    )

    candidates = resolve_name_candidates_in_text("分析百度")

    assert {(candidate.code, candidate.market) for candidate in candidates} == {
        ("BIDU", "US"),
        ("09888", "HK"),
    }
