"""Financial and real estate terms glossary knowledge base.

Loads structured term definitions from JSON files in ``data/glossary/``.
Used by the Faketor AI chat service via the ``lookup_glossary_term`` tool.

The JSON files are seeded from curated data in ``data/glossary/seed/``.
Run ``homebuyer collect glossary`` to copy seed files to the live location.

Sources:
    - CFPB (Consumer Financial Protection Bureau)
    - IRS Publications (Section 121, 1031, depreciation)
    - NAR (National Association of Realtors)
    - California DRE, CalHFA, Alameda County Assessor
    - Berkeley Municipal Code, Rent Stabilization Board
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from homebuyer.config import GLOSSARY_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    """Load a JSON glossary file, filtering out ``$meta`` keys."""
    with open(path) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("$")}


# Load glossary terms at import time.
# If JSON files are missing, fall back to empty dicts with a warning.
FINANCIAL_TERMS: dict[str, dict] = {}
REALESTATE_TERMS: dict[str, dict] = {}

_financial_path = GLOSSARY_DIR / "financial_terms.json"
_realestate_path = GLOSSARY_DIR / "realestate_terms.json"

if _financial_path.exists():
    FINANCIAL_TERMS = _load_json(_financial_path)
    logger.debug(
        "Loaded %d financial terms from %s", len(FINANCIAL_TERMS), _financial_path
    )
else:
    logger.warning(
        "Financial terms not found at %s — run 'homebuyer collect glossary'",
        _financial_path,
    )

if _realestate_path.exists():
    REALESTATE_TERMS = _load_json(_realestate_path)
    logger.debug(
        "Loaded %d real estate terms from %s", len(REALESTATE_TERMS), _realestate_path
    )
else:
    logger.warning(
        "Real estate terms not found at %s — run 'homebuyer collect glossary'",
        _realestate_path,
    )

# Merged view: all terms from both glossaries
ALL_TERMS: dict[str, dict] = {**FINANCIAL_TERMS, **REALESTATE_TERMS}


# ---------------------------------------------------------------------------
# Numeric accessors for use by analysis modules
# ---------------------------------------------------------------------------

# Fallback value if glossary not loaded or key_numbers missing.
# This is the 2026 Alameda County 1-unit conforming limit.
_FALLBACK_CONFORMING_LIMIT = 1_249_125


def get_conforming_loan_limit() -> int:
    """Return the current Alameda County 1-unit conforming loan limit.

    Reads from the ``conforming_vs_jumbo`` term's ``key_numbers``.
    The glossary collector fetches this from the FHFA XLSX annually.
    Falls back to a hardcoded default if the glossary isn't loaded.
    """
    term = FINANCIAL_TERMS.get("conforming_vs_jumbo", {})
    key_numbers = term.get("key_numbers", {})

    # Find the most recent year's high-cost limit
    # Keys follow pattern: "{year}_conforming_limit_high_cost"
    best_year = 0
    best_value = None
    for k, v in key_numbers.items():
        if k.endswith("_conforming_limit_high_cost"):
            try:
                year = int(k.split("_")[0])
            except (ValueError, IndexError):
                continue
            if year > best_year:
                best_year = year
                # Parse "$1,249,125" format
                best_value = int(v.replace("$", "").replace(",", ""))

    if best_value is not None:
        return best_value

    logger.debug(
        "Conforming limit not found in glossary key_numbers, using fallback $%s",
        f"{_FALLBACK_CONFORMING_LIMIT:,}",
    )
    return _FALLBACK_CONFORMING_LIMIT


# ---------------------------------------------------------------------------
# Keyword → term key mapping
# ---------------------------------------------------------------------------

_KEYWORD_MAP: dict[str, str] = {}
for _term_key, _term_data in ALL_TERMS.items():
    for _kw in _term_data.get("keywords", []):
        _KEYWORD_MAP[_kw.lower()] = _term_key

# Category → list of term keys (for browsing)
_CATEGORY_MAP: dict[str, list[str]] = {}
for _term_key, _term_data in ALL_TERMS.items():
    cat = _term_data.get("category", "uncategorized")
    _CATEGORY_MAP.setdefault(cat, []).append(_term_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_glossary_term(
    topic: str,
    category: Optional[str] = None,
) -> dict:
    """Look up a financial or real estate term by topic and optional category.

    Args:
        topic: Term to look up — a term key (e.g., ``"cap_rate"``) or
            natural language (e.g., ``"what is a cap rate"``).
        category: Optional category filter (e.g., ``"mortgage"``,
            ``"investment_metrics"``, ``"tax"``, ``"transaction"``).

    Returns:
        Dict with matched term content including ``term``, ``definition``,
        ``berkeley_context``, ``related``, and optionally ``formula``,
        ``key_numbers``, ``example``.
    """
    topic_lower = topic.strip().lower()

    # 1. Exact term key match
    if topic_lower in ALL_TERMS:
        result = dict(ALL_TERMS[topic_lower])
        result["term_key"] = topic_lower
        return result

    # 2. Category browsing — if topic matches a category name, return all
    #    terms in that category
    if topic_lower in _CATEGORY_MAP:
        term_keys = _CATEGORY_MAP[topic_lower]
        terms_summary = [
            {
                "term_key": k,
                "term": ALL_TERMS[k].get("term", k),
                "definition": ALL_TERMS[k].get("definition", ""),
            }
            for k in sorted(term_keys)
        ]
        return {
            "category": topic_lower,
            "title": f"Glossary: {topic_lower.replace('_', ' ').title()}",
            "terms": terms_summary,
            "total": len(terms_summary),
        }

    # 3. Keyword matching — scan keywords for substring match
    for keyword, term_key in _KEYWORD_MAP.items():
        if keyword in topic_lower:
            # If a category filter is provided, check it matches
            if category:
                term_cat = ALL_TERMS[term_key].get("category", "")
                if term_cat != category.lower():
                    continue
            result = dict(ALL_TERMS[term_key])
            result["term_key"] = term_key
            return result

    # 4. Fuzzy substring search — check if topic appears in term names
    for term_key, term_data in ALL_TERMS.items():
        term_name = term_data.get("term", "").lower()
        if topic_lower in term_name or topic_lower in term_key:
            if category:
                term_cat = term_data.get("category", "")
                if term_cat != category.lower():
                    continue
            result = dict(term_data)
            result["term_key"] = term_key
            return result

    # 5. Not found — return available categories and hint
    return {
        "term_key": None,
        "term": "Term Not Found",
        "definition": f"No glossary term found matching '{topic}'.",
        "available_categories": sorted(_CATEGORY_MAP.keys()),
        "available_terms_sample": sorted(ALL_TERMS.keys())[:20],
        "hint": (
            "Try a term key like 'cap_rate', 'ltv', 'contingency', or "
            "a category like 'mortgage', 'investment_metrics', 'transaction'."
        ),
    }
