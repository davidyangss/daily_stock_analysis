# -*- coding: utf-8 -*-
"""
===================================
Name-to-Code Resolution Engine
===================================

Resolve stock name to code: local mapping + pinyin + AkShare fallback + fuzzy matching.
"""

from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Dict, Optional, Set, Tuple

from src.data.stock_index_loader import StockIndexIdentity, get_stock_index_identities
from src.data.stock_mapping import STOCK_ENGLISH_NAME_MAP, STOCK_NAME_MAP
from src.services.stock_code_utils import is_code_like, normalize_code

logger = logging.getLogger(__name__)

# AkShare result cache: (timestamp, name_to_code_dict)
_akshare_cache: Optional[tuple[float, Dict[str, str]]] = None
_AKSHARE_CACHE_TTL = 1800  # 30 MIN


@dataclass(frozen=True)
class NameResolutionCandidate:
    """One auditable name-to-code candidate returned to API/Bot callers."""

    code: str
    display_code: str
    name: str
    market: str = ""
    asset_type: str = "stock"
    matched_term: str = ""
    match_type: str = "exact_name"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def _contains_cjk(text: str) -> bool:
    """Return True when text contains CJK characters."""
    return any("\u3400" <= ch <= "\u9fff" for ch in text)


def _normalize_name_term(value: str) -> str:
    """Normalize display-name text without collapsing meaningful CJK content."""
    return re.sub(r"[\s\-_.·,，()（）]+", "", str(value or "").strip()).casefold()


def _identity_terms(identity: StockIndexIdentity) -> tuple[str, ...]:
    canonical = normalize_code(identity.canonical_code) or identity.canonical_code
    english_aliases = STOCK_ENGLISH_NAME_MAP.get(canonical, ())
    return tuple(dict.fromkeys((*identity.name_terms(), *english_aliases)))


def _candidate_from_identity(
    identity: StockIndexIdentity,
    *,
    matched_term: str,
    match_type: str,
) -> NameResolutionCandidate:
    return NameResolutionCandidate(
        code=normalize_code(identity.canonical_code) or identity.canonical_code,
        display_code=identity.display_code or identity.canonical_code,
        name=identity.name_zh or identity.name_en or identity.display_code,
        market=identity.market,
        asset_type=identity.asset_type,
        matched_term=matched_term,
        match_type=match_type,
    )


def _dedupe_candidates(
    candidates: list[NameResolutionCandidate],
    *,
    limit: int,
) -> tuple[NameResolutionCandidate, ...]:
    result: list[NameResolutionCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.code.upper()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    return tuple(result)


@lru_cache(maxsize=1)
def _index_lookup_snapshot() -> tuple[
    Dict[str, tuple[tuple[StockIndexIdentity, str], ...]],
    Dict[str, StockIndexIdentity],
    tuple[tuple[str, str, StockIndexIdentity], ...],
]:
    """Build immutable exact-name/code indexes and one partial-search term list."""
    exact_names: Dict[str, list[tuple[StockIndexIdentity, str]]] = {}
    exact_codes: Dict[str, StockIndexIdentity] = {}
    partial_terms: list[tuple[str, str, StockIndexIdentity]] = []
    for identity in get_stock_index_identities():
        identity_code = normalize_code(identity.canonical_code) or identity.canonical_code
        exact_codes.setdefault(identity_code.upper(), identity)
        exact_codes.setdefault(str(identity.display_code or "").strip().upper(), identity)
        for term in _identity_terms(identity):
            normalized_term = _normalize_name_term(term)
            if not normalized_term:
                continue
            exact_names.setdefault(normalized_term, []).append((identity, term))
            partial_terms.append((normalized_term, term, identity))
    return (
        {key: tuple(values) for key, values in exact_names.items()},
        exact_codes,
        tuple(partial_terms),
    )


def _index_name_candidates(
    query: str,
    *,
    limit: int,
    allow_partial: bool,
) -> tuple[NameResolutionCandidate, ...]:
    normalized_query = _normalize_name_term(query)
    if not normalized_query:
        return ()

    exact_names, _exact_codes, partial_terms = _index_lookup_snapshot()
    exact_entries = exact_names.get(normalized_query, ())
    if exact_entries:
        return _dedupe_candidates(
            [
                _candidate_from_identity(
                    identity,
                    matched_term=term,
                    match_type="exact_name",
                )
                for identity, term in exact_entries
            ],
            limit=limit,
        )
    if not allow_partial:
        return ()

    partial: list[tuple[int, float, NameResolutionCandidate]] = []
    for normalized_term, term, identity in partial_terms:
        min_length = 2 if (_contains_cjk(term) or _contains_cjk(query)) else 3
        if len(normalized_query) < min_length or len(normalized_term) < min_length:
            continue
        if normalized_query in normalized_term or normalized_term in normalized_query:
            partial.append((
                min(len(normalized_query), len(normalized_term)),
                identity.popularity,
                _candidate_from_identity(
                    identity,
                    matched_term=term,
                    match_type="partial_name",
                ),
            ))

    partial.sort(key=lambda item: (-item[0], -item[1], item[2].code))
    return _dedupe_candidates([item[2] for item in partial], limit=limit)


def _index_code_candidate(query: str) -> tuple[NameResolutionCandidate, ...]:
    normalized = normalize_code(query)
    if not normalized:
        return ()
    _exact_names, exact_codes, _partial_terms = _index_lookup_snapshot()
    identity = exact_codes.get(normalized.upper()) or exact_codes.get(query.strip().upper())
    if identity is not None:
        return (
            _candidate_from_identity(
                identity,
                matched_term=query,
                match_type="exact_code",
            ),
        )
    return ()


def _is_code_like(s: str) -> bool:
    """Backward-compatible wrapper of shared code-like check."""
    return is_code_like(s)


def _normalize_code(raw: str) -> Optional[str]:
    """Backward-compatible wrapper of shared code normalization."""
    return normalize_code(raw)


def _build_reverse_map_no_duplicates(
    code_to_name: Dict[str, str],
) -> Dict[str, str]:
    """
    Build name -> code map. If a name maps to multiple codes (ambiguous), exclude it.
    """
    name_to_codes: Dict[str, Set[str]] = {}
    for code, name in code_to_name.items():
        if not name or not code:
            continue
        name = name.strip()
        if name not in name_to_codes:
            name_to_codes[name] = set()
        name_to_codes[name].add(code)
    # Only include names with exactly one code
    return {name: next(iter(codes)) for name, codes in name_to_codes.items() if len(codes) == 1}


def _build_local_name_indexes(code_to_name: Dict[str, str]) -> Tuple[Dict[str, str], Set[str]]:
    """
    Build cached local lookup structures:
    - unique name -> code
    - ambiguous names that should fail fast
    """
    name_to_codes: Dict[str, Set[str]] = {}
    for code, name in code_to_name.items():
        if not name or not code:
            continue
        normalized_name = name.strip()
        if not normalized_name:
            continue
        name_to_codes.setdefault(normalized_name, set()).add(code)

    unique_names = {
        name: next(iter(codes))
        for name, codes in name_to_codes.items()
        if len(codes) == 1
    }
    ambiguous_names = {
        name
        for name, codes in name_to_codes.items()
        if len(codes) > 1
    }
    return unique_names, ambiguous_names


_LOCAL_REVERSE_MAP, _ = _build_local_name_indexes(STOCK_NAME_MAP)


def _get_akshare_name_to_code() -> Optional[Dict[str, str]]:
    """Fetch A-share name->code from AkShare, with cache."""
    global _akshare_cache
    now = time.time()
    if _akshare_cache is not None and (now - _akshare_cache[0]) < _AKSHARE_CACHE_TTL:
        return _akshare_cache[1]
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        if df is None or df.empty:
            return None
        code_to_name = {}
        for _, row in df.iterrows():
            code = row.get("code")
            name = row.get("name")
            if code is None or name is None:
                continue
            code_str = str(code).strip()
            # Strip .SH/.SZ suffix
            if "." in code_str:
                base, suffix = code_str.rsplit(".", 1)
                if suffix.upper() in ("SH", "SZ", "SS") and base.isdigit():
                    code_str = base
            code_to_name[code_str] = str(name).strip()
        result = _build_reverse_map_no_duplicates(code_to_name)
        _akshare_cache = (now, result)
        logger.info(f"[NameResolver] AkShare cache loaded: {len(result)} name->code mappings")
        return result
    except Exception as e:
        logger.warning(f"[NameResolver] AkShare fallback failed: {e}")
        return None


def _is_single_char_typo(input_name: str, candidate_name: str) -> bool:
    """Return True when two names only differ by one character position."""
    if not input_name or not candidate_name:
        return False
    if len(input_name) != len(candidate_name):
        return False
    # Keep typo fallback conservative: only for names with enough signal.
    if len(input_name) < 3:
        return False
    diff = sum(1 for a, b in zip(input_name, candidate_name) if a != b)
    return diff == 1


def _market_for_legacy_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    if normalized.isalpha():
        return "US"
    if normalized.isdigit() and len(normalized) == 5:
        return "HK"
    if normalized.isdigit() and len(normalized) == 6:
        return "CN"
    return ""


def _local_exact_candidates(name: str, *, limit: int) -> tuple[NameResolutionCandidate, ...]:
    normalized_name = _normalize_name_term(name)
    local_matches = [
        NameResolutionCandidate(
            code=code,
            display_code=code,
            name=stock_name,
            market=_market_for_legacy_code(code),
            matched_term=stock_name,
            match_type="exact_name",
        )
        for code, stock_name in STOCK_NAME_MAP.items()
        if _normalize_name_term(stock_name) == normalized_name
    ]
    if local_matches:
        return _dedupe_candidates(local_matches, limit=limit)
    return ()


def _static_english_exact_candidates(
    name: str,
    *,
    limit: int,
) -> tuple[NameResolutionCandidate, ...]:
    normalized_name = _normalize_name_term(name)
    matches = [
        NameResolutionCandidate(
            code=code,
            display_code=code,
            name=STOCK_NAME_MAP.get(code, ""),
            market=_market_for_legacy_code(code),
            matched_term=alias,
            match_type="exact_name",
        )
        for code, aliases in STOCK_ENGLISH_NAME_MAP.items()
        for alias in aliases
        if _normalize_name_term(alias) == normalized_name
    ]
    return _dedupe_candidates(matches, limit=limit)


def _static_code_candidate(name: str) -> tuple[NameResolutionCandidate, ...]:
    normalized_code = normalize_code(name)
    if not normalized_code or normalized_code not in STOCK_NAME_MAP:
        return ()
    return (
        NameResolutionCandidate(
            code=normalized_code,
            display_code=normalized_code,
            name=STOCK_NAME_MAP[normalized_code],
            market=_market_for_legacy_code(normalized_code),
            matched_term=name,
            match_type="exact_code",
        ),
    )


def _fallback_name_candidates(name: str, *, limit: int) -> tuple[NameResolutionCandidate, ...]:
    """Resolve names not covered by the generated index using legacy sources."""

    if not _contains_cjk(name):
        return ()

    akshare_map = _get_akshare_name_to_code() or {}
    exact_code = akshare_map.get(name)
    if exact_code:
        return (
            NameResolutionCandidate(
                code=exact_code,
                display_code=exact_code,
                name=name,
                market="CN",
                matched_term=name,
                match_type="exact_name",
            ),
        )

    all_name_to_code = dict(_LOCAL_REVERSE_MAP)
    all_name_to_code.update(akshare_map)
    if len(name) <= 2:
        return ()
    names = list(all_name_to_code)
    matches = difflib.get_close_matches(name, names, n=1, cutoff=0.8)
    if not matches:
        typo_matches = difflib.get_close_matches(name, names, n=1, cutoff=0.7)
        if typo_matches and _is_single_char_typo(name, typo_matches[0]):
            matches = typo_matches
    if not matches:
        return ()
    matched_name = matches[0]
    return (
        NameResolutionCandidate(
            code=all_name_to_code[matched_name],
            display_code=all_name_to_code[matched_name],
            name=matched_name,
            market="CN",
            matched_term=matched_name,
            match_type="fuzzy_name",
        ),
    )


@lru_cache(maxsize=2048)
def _resolve_name_candidates_cached(
    name: str,
    limit: int,
) -> tuple[NameResolutionCandidate, ...]:
    s = name.strip()
    if not s:
        return ()

    # Human identity terms win before the broad 1-5 letter ticker heuristic.
    # This prevents inputs such as Apple/Tesla/Baidu from becoming fake tickers.
    static_name_matches = _dedupe_candidates(
        [
            *_local_exact_candidates(s, limit=limit),
            *_static_english_exact_candidates(s, limit=limit),
        ],
        limit=limit,
    )
    if static_name_matches:
        return static_name_matches

    static_code_matches = _static_code_candidate(s)
    if static_code_matches:
        return static_code_matches

    exact_name_matches = _index_name_candidates(s, limit=limit, allow_partial=False)
    if exact_name_matches:
        return exact_name_matches

    code_matches = _index_code_candidate(s)
    if code_matches:
        return code_matches

    partial_name_matches = _index_name_candidates(s, limit=limit, allow_partial=True)
    if partial_name_matches:
        return partial_name_matches

    fallback_matches = _fallback_name_candidates(s, limit=limit)
    if fallback_matches:
        return fallback_matches

    # Preserve explicit/manual support for symbols not yet present in the index.
    # Mixed-case words are treated as company names, not unknown ticker symbols.
    if _is_code_like(s) and (
        not s.isalpha()
        or s.isupper()
        or "." in s
    ):
        normalized = _normalize_code(s)
        if normalized:
            return (
                NameResolutionCandidate(
                    code=normalized,
                    display_code=s.upper(),
                    name="",
                    matched_term=s,
                    match_type="unverified_code",
                ),
            )
    return ()


def resolve_name_candidates(
    name: str,
    *,
    limit: int = 10,
) -> tuple[NameResolutionCandidate, ...]:
    """Return auditable candidates for a company name, alias, pinyin, or code."""
    if not name or not isinstance(name, str):
        return ()
    safe_limit = max(1, min(int(limit or 10), 20))
    return _resolve_name_candidates_cached(name.strip(), safe_limit)


def resolve_name_candidates_in_text(
    text: str,
    *,
    limit: int = 10,
) -> tuple[NameResolutionCandidate, ...]:
    """Find indexed Chinese stock names or aliases mentioned in free text.

    Agent Chat receives complete natural-language questions rather than a
    dedicated name field.  This helper deliberately searches only the local
    generated stock index: it must not make an AkShare/network lookup merely
    because a user typed a conversational sentence.  The caller decides
    whether the returned candidates are safe to auto-select or need a choice.
    """
    if not isinstance(text, str) or not text.strip():
        return ()

    normalized_text = _normalize_name_term(text)
    if not normalized_text:
        return ()

    candidates: list[tuple[int, float, NameResolutionCandidate]] = []
    for identity in get_stock_index_identities():
        for term in _identity_terms(identity):
            normalized_term = _normalize_name_term(term)
            # This path is specifically for Chinese short names / aliases.
            # Two CJK characters are useful (e.g. 茅台); shorter or non-CJK
            # terms are too broad in a sentence and remain the code path.
            if len(normalized_term) < 2 or not _contains_cjk(normalized_term):
                continue
            if normalized_term not in normalized_text:
                continue
            match_type = "exact_name" if normalized_text == normalized_term else "partial_name"
            candidates.append((
                len(normalized_term),
                identity.popularity,
                _candidate_from_identity(identity, matched_term=term, match_type=match_type),
            ))

    candidates.sort(key=lambda item: (-item[0], -item[1], item[2].code))
    return _dedupe_candidates([item[2] for item in candidates], limit=max(1, min(int(limit or 10), 20)))


def clear_name_resolution_cache() -> None:
    """Clear query results after a stock-index refresh."""
    _resolve_name_candidates_cached.cache_clear()
    _index_lookup_snapshot.cache_clear()


def resolve_name_to_code(name: str) -> Optional[str]:
    """Resolve one unambiguous stock name/code, returning ``None`` on ambiguity."""
    candidates = resolve_name_candidates(name, limit=10)
    if len(candidates) == 1:
        return candidates[0].code
    if candidates:
        logger.debug(
            "[NameResolver] 名称存在多个候选: input=%s candidates=%s",
            name,
            [candidate.code for candidate in candidates],
        )
    else:
        logger.debug("[NameResolver] 解析失败: %s", name)
    return None
