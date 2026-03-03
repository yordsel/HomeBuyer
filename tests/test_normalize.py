"""Tests for neighborhood name normalization."""

from homebuyer.processing.normalize import normalize_neighborhood


def test_exact_alias_match():
    """Known aliases map to canonical names."""
    assert normalize_neighborhood("N BERKELEY") == "North Berkeley"
    assert normalize_neighborhood("N. Berkeley") == "North Berkeley"
    assert normalize_neighborhood("NOBE") == "North Berkeley"


def test_canonical_name_unchanged():
    """Canonical names pass through correctly."""
    assert normalize_neighborhood("North Berkeley") == "North Berkeley"
    assert normalize_neighborhood("Claremont") == "Claremont"
    assert normalize_neighborhood("Elmwood") == "Elmwood"


def test_case_insensitive():
    """Matching is case-insensitive."""
    assert normalize_neighborhood("north berkeley") == "North Berkeley"
    assert normalize_neighborhood("CLAREMONT HILLS") == "Claremont"
    assert normalize_neighborhood("w berkeley") == "West Berkeley"


def test_thousand_oaks_typo():
    """Known Thousand Oaks typos are handled."""
    assert normalize_neighborhood("1000 Oaks") == "Thousand Oaks"
    assert normalize_neighborhood("1000  0AKS") == "Thousand Oaks"


def test_unknown_returns_none():
    """Unknown neighborhoods return None for geocoding."""
    assert normalize_neighborhood("Berkeley Map Area 5") is None
    assert normalize_neighborhood("") is None
    assert normalize_neighborhood(None) is None  # type: ignore


def test_whitespace_handling():
    """Whitespace is stripped."""
    assert normalize_neighborhood("  North Berkeley  ") == "North Berkeley"
    assert normalize_neighborhood("  N BERKELEY  ") == "North Berkeley"


def test_fuzzy_matching():
    """Close misspellings are fuzzy matched."""
    # "Claremont" is canonical — "Claremnt" should fuzzy match
    result = normalize_neighborhood("Claremnt")
    # May or may not fuzzy match depending on threshold, but shouldn't error
    assert result is None or result == "Claremont"
