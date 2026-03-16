"""Tests for the Faketor AnalysisAccumulator.

Verifies that tool facts are correctly recorded and formatted into the
VERIFIED DATA SUMMARY injected into each subsequent system prompt.
"""


from homebuyer.services.faketor.accumulator import AnalysisAccumulator


class TestAccumulatorEmpty:
    """Tests for an empty accumulator."""

    def test_empty_summary_is_empty_string(self):
        acc = AnalysisAccumulator()
        assert acc.get_summary() == ""

    def test_empty_tool_sequence(self):
        acc = AnalysisAccumulator()
        assert acc.tool_sequence == []


class TestAccumulatorRecording:
    """Tests for recording facts from tool calls."""

    def test_single_tool_recorded(self):
        acc = AnalysisAccumulator()
        acc.record(
            "search_properties",
            {"neighborhood": "N Berkeley"},
            {
                "total_results": 10,
                "adu_eligible_count": 6,
                "sb9_eligible_count": 3,
                "price_range": [800_000, 1_500_000],
                "median_price": 1_100_000,
            },
        )
        assert acc.tool_sequence == ["search_properties"]
        assert acc.search_facts is not None
        assert acc.search_facts["total_results"] == 10

    def test_dev_potential_recorded(self):
        acc = AnalysisAccumulator()
        acc.record(
            "get_development_potential",
            {"address": "123 Test St", "latitude": 37.87, "longitude": -122.27},
            {"adu_eligible": True, "sb9_eligible": False, "zone_class": "R-1"},
        )
        assert "123 Test St" in acc.dev_potentials
        assert acc.dev_potentials["123 Test St"]["adu_eligible"] is True

    def test_prediction_recorded(self):
        acc = AnalysisAccumulator()
        acc.record(
            "get_price_prediction",
            {"address": "456 Oak Ave"},
            {"predicted_price": 1_200_000, "price_lower": 1_100_000, "price_upper": 1_300_000},
        )
        assert "456 Oak Ave" in acc.predictions

    def test_neighborhood_keyed_by_name(self):
        acc = AnalysisAccumulator()
        acc.record(
            "get_neighborhood_stats",
            {"neighborhood": "N Berkeley"},
            {"neighborhood": "N Berkeley", "median_price": 1_400_000, "total_sales": 120},
        )
        assert "N Berkeley" in acc.neighborhood_stats

    def test_comps_recorded(self):
        acc = AnalysisAccumulator()
        acc.record(
            "get_comparable_sales",
            {"address": "789 Cedar Ln"},
            {"comp_count": 5, "price_range": [900_000, 1_200_000]},
        )
        assert "789 Cedar Ln" in acc.comps


class TestAccumulatorSummary:
    """Tests for the VERIFIED DATA SUMMARY generation."""

    def test_search_in_summary(self):
        acc = AnalysisAccumulator()
        acc.record(
            "search_properties",
            {},
            {
                "total_results": 5,
                "adu_eligible_count": 3,
                "sb9_eligible_count": 1,
            },
        )
        summary = acc.get_summary()
        assert "Property Search:" in summary
        assert "5 properties found" in summary
        assert "ADU eligible: 3" in summary

    def test_dev_potential_in_summary(self):
        acc = AnalysisAccumulator()
        acc.record(
            "get_development_potential",
            {"address": "100 Main St"},
            {"adu_eligible": True, "sb9_eligible": False, "effective_max_units": 4, "zone_class": "R-2"},
        )
        summary = acc.get_summary()
        assert "100 Main St" in summary
        assert "ADU=Yes" in summary
        assert "SB9=No" in summary

    def test_prediction_in_summary(self):
        acc = AnalysisAccumulator()
        acc.record(
            "get_price_prediction",
            {"address": "200 Elm St"},
            {"predicted_price": 1_250_000, "price_lower": 1_150_000, "price_upper": 1_350_000},
        )
        summary = acc.get_summary()
        assert "$1.2M" in summary
        assert "200 Elm St" in summary

    def test_rental_in_summary(self):
        acc = AnalysisAccumulator()
        acc.record(
            "estimate_rental_income",
            {"address": "300 Pine St"},
            {"monthly_rent": 4000, "cap_rate_pct": 3.5, "cash_on_cash_pct": 4.2},
        )
        summary = acc.get_summary()
        assert "300 Pine St" in summary
        assert "Cap rate=3.5%" in summary

    def test_summary_markers(self):
        acc = AnalysisAccumulator()
        acc.record("search_properties", {}, {"total_results": 1, "adu_eligible_count": 0, "sb9_eligible_count": 0})
        summary = acc.get_summary()
        assert summary.startswith("=== VERIFIED DATA SUMMARY")
        assert "=== END VERIFIED DATA ===" in summary

    def test_tool_sequence_deduplicates(self):
        acc = AnalysisAccumulator()
        for _ in range(3):
            acc.record(
                "search_properties",
                {},
                {"total_results": 1, "adu_eligible_count": 0, "sb9_eligible_count": 0},
            )
        summary = acc.get_summary()
        assert "×3" in summary


class TestAccumulatorAddressResolution:
    """Tests for _resolve_address."""

    def test_address_from_address_field(self):
        result = AnalysisAccumulator._resolve_address({"address": "123 Test St"})
        assert result == "123 Test St"

    def test_address_from_property_id(self):
        result = AnalysisAccumulator._resolve_address({"property_id": 42})
        assert result == "property#42"

    def test_address_from_latlon(self):
        result = AnalysisAccumulator._resolve_address(
            {"latitude": 37.8716, "longitude": -122.2727}
        )
        assert "(37.8716, -122.2727)" in result

    def test_address_unknown_fallback(self):
        result = AnalysisAccumulator._resolve_address({})
        assert result == "unknown"

    def test_address_field_takes_priority(self):
        result = AnalysisAccumulator._resolve_address({
            "address": "123 Test St",
            "property_id": 42,
            "latitude": 37.87,
        })
        assert result == "123 Test St"


class TestAccumulatorMaxProperties:
    """Tests for the _MAX_PROPERTY_DETAIL_LINES limit."""

    def test_max_property_lines(self):
        acc = AnalysisAccumulator()
        for i in range(15):
            acc.record(
                "get_development_potential",
                {"address": f"{i} Test St"},
                {"adu_eligible": True, "sb9_eligible": False, "effective_max_units": 2, "zone_class": "R-1"},
            )
        summary = acc.get_summary()
        # Should have "and X more" truncation
        assert "and 5 more" in summary
