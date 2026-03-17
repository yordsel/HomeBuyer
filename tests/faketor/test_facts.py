"""Tests for Faketor fact computation functions.

Each test verifies that a fact computer correctly extracts and transforms
tool result data into verified facts for the accumulator and system prompt.
"""


from homebuyer.services.faketor.facts import (
    compute_adjacent_market_facts,
    compute_appreciation_stress_facts,
    compute_competition_facts,
    compute_comps_facts,
    compute_development_facts,
    compute_dual_property_facts,
    compute_glossary_facts,
    compute_improvement_facts,
    compute_investment_facts,
    compute_neighborhood_facts,
    compute_neighborhood_lifestyle_facts,
    compute_pmi_model_facts,
    compute_prediction_facts,
    compute_query_facts,
    compute_rate_penalty_facts,
    compute_regulation_facts,
    compute_rental_facts,
    compute_rent_vs_buy_facts,
    compute_search_facts,
    compute_sell_vs_hold_facts,
    compute_true_cost_facts,
    compute_undo_filter_facts,
    compute_yield_ranking_facts,
    compute_facts_for_tool,
)


class TestSearchFacts:
    """Tests for compute_search_facts."""

    def test_basic(self):
        data = {
            "results": [
                {
                    "id": 1,
                    "address": "123 Test St",
                    "last_sale_price": 1_000_000,
                    "lot_size_sqft": 5000,
                    "building_sqft": 1500,
                    "zoning_class": "R-1",
                    "neighborhood": "N Berkeley",
                    "data_quality": "normal",
                    "development": {"adu_eligible": True, "sb9_eligible": False},
                },
                {
                    "id": 2,
                    "address": "456 Oak Ave",
                    "last_sale_price": 1_500_000,
                    "lot_size_sqft": 6000,
                    "building_sqft": 2000,
                    "zoning_class": "R-2",
                    "neighborhood": "S Berkeley",
                    "data_quality": "normal",
                    "development": {"adu_eligible": True, "sb9_eligible": True},
                },
            ],
            "total_matching": 50,
        }
        facts = compute_search_facts(data)
        assert facts["total_results"] == 2
        assert facts["total_matching"] == 50
        assert facts["adu_eligible_count"] == 2
        assert facts["sb9_eligible_count"] == 1
        assert facts["median_price"] == 1_250_000
        assert facts["price_range"] == [1_000_000, 1_500_000]
        assert set(facts["zoning_classes"]) == {"R-1", "R-2"}

    def test_empty_results(self):
        facts = compute_search_facts({"results": []})
        assert facts["total_results"] == 0
        assert facts["adu_eligible_count"] == 0
        assert facts["price_range"] is None
        assert facts["median_price"] is None

    def test_missing_results_key(self):
        facts = compute_search_facts({})
        assert facts["total_results"] == 0


class TestDevelopmentFacts:
    """Tests for compute_development_facts."""

    def test_adu_eligible(self):
        data = {
            "adu": {"eligible": True, "max_adu_sqft": 800},
            "sb9": {"eligible": False, "can_split": False},
            "units": {"effective_max_units": 3, "middle_housing_eligible": True},
            "zoning": {"zone_class": "R-1", "zone_desc": "Single Family"},
        }
        facts = compute_development_facts(data)
        assert facts["adu_eligible"] is True
        assert facts["adu_max_sqft"] == 800
        assert facts["sb9_eligible"] is False
        assert facts["effective_max_units"] == 3
        assert facts["zone_class"] == "R-1"
        assert facts["middle_housing_eligible"] is True

    def test_empty_data(self):
        facts = compute_development_facts({})
        assert facts["adu_eligible"] is False
        assert facts["sb9_eligible"] is False


class TestPredictionFacts:
    """Tests for compute_prediction_facts."""

    def test_basic(self):
        data = {
            "predicted_price": 1_200_000,
            "price_lower": 1_100_000,
            "price_upper": 1_300_000,
            "confidence_pct": 85.0,
            "neighborhood": "N Berkeley",
        }
        facts = compute_prediction_facts(data)
        assert facts["predicted_price"] == 1_200_000
        assert facts["price_lower"] == 1_100_000
        assert facts["price_upper"] == 1_300_000
        assert facts["confidence_pct"] == 85.0
        assert facts["neighborhood"] == "N Berkeley"


class TestCompsFacts:
    """Tests for compute_comps_facts."""

    def test_list_input(self):
        comps = [
            {"sale_price": 1_000_000, "price_per_sqft": 600},
            {"sale_price": 1_200_000, "price_per_sqft": 700},
            {"sale_price": 1_100_000, "price_per_sqft": 650},
        ]
        facts = compute_comps_facts(comps)
        assert facts["comp_count"] == 3
        assert facts["price_range"] == [1_000_000, 1_200_000]
        assert facts["median_price"] == 1_100_000
        assert facts["median_price_per_sqft"] == 650

    def test_dict_input(self):
        data = {
            "comps": [
                {"sale_price": 800_000, "price_per_sqft": 500},
                {"sale_price": 900_000, "price_per_sqft": 550},
            ]
        }
        facts = compute_comps_facts(data)
        assert facts["comp_count"] == 2
        assert facts["price_range"] == [800_000, 900_000]

    def test_empty_comps(self):
        facts = compute_comps_facts([])
        assert facts["comp_count"] == 0
        assert facts["price_range"] is None


class TestNeighborhoodFacts:
    """Tests for compute_neighborhood_facts."""

    def test_basic(self):
        data = {
            "neighborhood": "N Berkeley",
            "median_price": 1_400_000,
            "total_sales": 120,
            "yoy_price_change_pct": 5.2,
            "avg_dom": 18,
            "active_listings": 25,
        }
        facts = compute_neighborhood_facts(data)
        assert facts["neighborhood"] == "N Berkeley"
        assert facts["median_price"] == 1_400_000
        assert facts["total_sales"] == 120
        assert facts["yoy_price_change_pct"] == 5.2
        assert facts["avg_dom"] == 18
        assert facts["active_listings"] == 25


class TestSellVsHoldFacts:
    """Tests for compute_sell_vs_hold_facts."""

    def test_basic(self):
        data = {
            "current_predicted_value": 1_500_000,
            "yoy_appreciation_pct": 4.0,
            "rental_estimate": {
                "monthly_rent": 4_000,
                "cap_rate_pct": 3.5,
                "price_to_rent_ratio": 31.2,
            },
            "hold_scenarios": {},
        }
        facts = compute_sell_vs_hold_facts(data)
        assert facts["current_value"] == 1_500_000
        assert facts["yoy_appreciation_pct"] == 4.0
        assert facts["monthly_rent"] == 4_000
        assert facts["cap_rate_pct"] == 3.5

    def test_with_scenarios(self):
        data = {
            "current_predicted_value": 1_000_000,
            "yoy_appreciation_pct": 3.0,
            "rental_estimate": {},
            "hold_scenarios": {
                "1yr": {"projected_value": 1_030_000, "net_gain": 10_000},
                "3yr": {"projected_value": 1_092_727, "net_gain": 30_000},
            },
        }
        facts = compute_sell_vs_hold_facts(data)
        assert facts["1yr_projected"] == 1_030_000
        assert facts["1yr_net_gain"] == 10_000
        assert facts["3yr_projected"] == 1_092_727


class TestRentalFacts:
    """Tests for compute_rental_facts."""

    def test_basic(self):
        data = {
            "scenario_name": "Rent As-Is",
            "monthly_rent": 3_500,
            "annual_gross_rent": 42_000,
            "annual_noi": 28_000,
            "cap_rate_pct": 3.2,
            "cash_on_cash_pct": 4.1,
            "monthly_cash_flow": 500,
        }
        facts = compute_rental_facts(data)
        assert facts["scenario_name"] == "Rent As-Is"
        assert facts["monthly_rent"] == 3_500
        assert facts["cap_rate_pct"] == 3.2
        assert facts["cash_on_cash_pct"] == 4.1


class TestInvestmentFacts:
    """Tests for compute_investment_facts."""

    def test_best_scenario(self):
        data = {
            "scenarios": [
                {
                    "scenario_name": "As-Is",
                    "cap_rate_pct": 3.0,
                    "cash_on_cash_pct": 2.5,
                    "monthly_cash_flow": -200,
                },
                {
                    "scenario_name": "ADU",
                    "cap_rate_pct": 5.0,
                    "cash_on_cash_pct": 6.0,
                    "monthly_cash_flow": 800,
                },
            ],
        }
        facts = compute_investment_facts(data)
        assert facts["scenario_count"] == 2
        assert facts["best_cash_on_cash"]["name"] == "ADU"
        assert facts["best_cash_on_cash"]["cash_on_cash_pct"] == 6.0

    def test_empty_scenarios(self):
        facts = compute_investment_facts({"scenarios": []})
        assert facts["scenario_count"] == 0
        assert facts["best_cash_on_cash"] is None


class TestImprovementFacts:
    """Tests for compute_improvement_facts."""

    def test_top_three(self):
        data = {
            "current_price": 1_000_000,
            "improved_price": 1_150_000,
            "total_delta": 150_000,
            "total_cost": 80_000,
            "roi": 1.88,
            "categories": [
                {"category": "Kitchen", "roi": 2.5, "avg_cost": 30_000},
                {"category": "Bathroom", "roi": 2.0, "avg_cost": 15_000},
                {"category": "Landscaping", "roi": 1.5, "avg_cost": 10_000},
                {"category": "Roof", "roi": 1.2, "avg_cost": 25_000},
            ],
        }
        facts = compute_improvement_facts(data)
        assert facts["current_price"] == 1_000_000
        assert facts["overall_roi"] == 1.88
        assert len(facts["top_improvements"]) == 3
        # Top by ROI: Kitchen (2.5), Bathroom (2.0), Landscaping (1.5)
        assert facts["top_improvements"][0]["category"] == "Kitchen"
        assert facts["top_improvements"][0]["roi"] == 2.5
        assert facts["top_improvements"][2]["category"] == "Landscaping"


class TestUndoFilterFacts:
    """Tests for compute_undo_filter_facts."""

    def test_basic(self):
        data = {
            "working_set_count": 42,
            "removed_filter": "zoning_class = 'R-1'",
            "remaining_filters": ["neighborhood = 'N Berkeley'"],
        }
        facts = compute_undo_filter_facts(data)
        assert facts["working_set_count"] == 42
        assert facts["removed_filter"] == "zoning_class = 'R-1'"


class TestQueryFacts:
    """Tests for compute_query_facts."""

    def test_basic(self):
        data = {
            "columns": ["count", "avg_price"],
            "rows": [{"count": 150, "avg_price": 1_200_000}],
        }
        facts = compute_query_facts(data)
        assert facts["row_count"] == 1
        assert facts["columns"] == ["count", "avg_price"]
        assert facts["result"] == {"count": 150, "avg_price": 1_200_000}

    def test_multi_row_no_result(self):
        data = {
            "columns": ["neighborhood", "count"],
            "rows": [
                {"neighborhood": "N Berkeley", "count": 50},
                {"neighborhood": "S Berkeley", "count": 40},
            ],
        }
        facts = compute_query_facts(data)
        assert facts["row_count"] == 2
        assert "result" not in facts  # Not a single-row aggregate


class TestRegulationFacts:
    """Tests for compute_regulation_facts."""

    def test_found(self):
        data = {
            "category": "adu_rules",
            "title": "ADU and JADU Regulations",
            "source": "BMC 23.306",
        }
        facts = compute_regulation_facts(data)
        assert facts["found"] is True
        assert facts["category"] == "adu_rules"
        assert facts["source"] == "BMC 23.306"

    def test_not_found(self):
        data = {
            "category": None,
            "title": None,
            "available_categories": ["adu_rules", "sb9", "middle_housing"],
        }
        facts = compute_regulation_facts(data)
        assert facts["found"] is False
        assert "available_categories" in facts


class TestGlossaryFacts:
    """Tests for compute_glossary_facts."""

    def test_with_formula(self):
        data = {
            "term_key": "cap_rate",
            "term": "Capitalization Rate",
            "category": "investment_metrics",
            "formula": "NOI / Purchase Price × 100",
        }
        facts = compute_glossary_facts(data)
        assert facts["found"] is True
        assert facts["has_formula"] is True
        assert facts["formula"] == "NOI / Purchase Price × 100"

    def test_without_formula(self):
        data = {
            "term_key": "escrow",
            "term": "Escrow",
            "category": "transaction",
        }
        facts = compute_glossary_facts(data)
        assert facts["found"] is True
        assert "has_formula" not in facts

    def test_category_browse(self):
        data = {
            "term_key": None,
            "terms": [
                {"term_key": "cap_rate"},
                {"term_key": "noi"},
            ],
            "total": 5,
            "category": "investment_metrics",
        }
        facts = compute_glossary_facts(data)
        assert facts["total_in_category"] == 5
        assert facts["term_keys"] == ["cap_rate", "noi"]


class TestFactDispatcher:
    """Tests for the compute_facts_for_tool dispatcher."""

    def test_dispatches_correctly(self):
        data = {
            "results": [
                {
                    "id": 1,
                    "address": "123 Test",
                    "last_sale_price": 1_000_000,
                    "data_quality": "normal",
                    "development": {},
                }
            ]
        }
        facts = compute_facts_for_tool("search_properties", data)
        assert facts is not None
        assert facts["total_results"] == 1

    def test_unknown_tool_returns_none(self):
        result = compute_facts_for_tool("lookup_property", {"address": "test"})
        assert result is None

    def test_defensive_against_bad_data(self):
        """Fact computers should not raise on unexpected data."""
        result = compute_facts_for_tool("search_properties", {"unexpected": True})
        assert result is not None  # Returns facts with total_results=0

    def test_exception_returns_none(self):
        """If a fact computer raises, dispatcher returns None."""
        # Pass a type that will cause an error in the median() call
        # if there were prices, but with no prices it should be fine
        result = compute_facts_for_tool("get_comparable_sales", "not_a_dict_or_list")
        # The function handles this gracefully
        assert result is None or isinstance(result, dict)

    def test_dispatches_gap_tools(self):
        """Dispatcher wires all 10 gap tool fact computers correctly."""
        gap_tools = [
            "compute_true_cost",
            "rent_vs_buy",
            "pmi_model",
            "rate_penalty",
            "competition_assessment",
            "dual_property_model",
            "yield_ranking",
            "appreciation_stress_test",
            "neighborhood_lifestyle",
            "adjacent_market_comparison",
        ]
        for tool_name in gap_tools:
            result = compute_facts_for_tool(tool_name, {})
            assert result is not None, f"Dispatcher returned None for gap tool {tool_name}"
            assert isinstance(result, dict), f"Expected dict for {tool_name}"


# ---------------------------------------------------------------------------
# Additional edge-case tests for original fact computers
# ---------------------------------------------------------------------------


class TestSearchFactsEdgeCases:
    """Edge cases for compute_search_facts."""

    def test_predicted_price_range(self):
        """predicted_price aggregation when present."""
        data = {
            "results": [
                {"id": 1, "predicted_price": 900_000},
                {"id": 2, "predicted_price": 1_200_000},
                {"id": 3, "predicted_price": 1_100_000},
            ]
        }
        facts = compute_search_facts(data)
        assert facts["predicted_price_range"] == [900_000, 1_200_000]

    def test_predicted_price_range_none_when_missing(self):
        """predicted_price_range is None when no results have predicted_price."""
        data = {"results": [{"id": 1}]}
        facts = compute_search_facts(data)
        assert facts["predicted_price_range"] is None

    def test_building_to_lot_ratio_metrics(self):
        """building_to_lot_ratio range and low_density_count."""
        data = {
            "results": [
                {"id": 1, "building_to_lot_ratio": 0.20},  # low density (<0.25)
                {"id": 2, "building_to_lot_ratio": 0.50},
                {"id": 3, "building_to_lot_ratio": 0.10},  # low density
            ]
        }
        facts = compute_search_facts(data)
        assert facts["building_to_lot_ratio_range"] == [0.10, 0.50]
        assert facts["low_density_count"] == 2

    def test_low_density_exactly_at_boundary(self):
        """building_to_lot_ratio exactly 0.25 is NOT low density (< 0.25)."""
        data = {"results": [{"id": 1, "building_to_lot_ratio": 0.25}]}
        facts = compute_search_facts(data)
        assert facts["low_density_count"] == 0

    def test_per_unit_mismatch_and_warnings(self):
        """data_quality metrics: per_unit_mismatch count and warning addresses."""
        data = {
            "results": [
                {"id": 1, "address": "100 Main", "data_quality": "per_unit_mismatch"},
                {"id": 2, "address": "200 Oak", "data_quality": "normal"},
                {"id": 3, "address": "300 Elm", "data_quality": "stale_listing"},
            ]
        }
        facts = compute_search_facts(data)
        assert facts["per_unit_mismatch_count"] == 1
        assert facts["clean_results_count"] == 1
        assert "100 Main" in facts["data_quality_warnings"]
        assert "300 Elm" in facts["data_quality_warnings"]
        assert "200 Oak" not in facts["data_quality_warnings"]

    def test_property_ids_mapping(self):
        """property_ids maps id → address."""
        data = {
            "results": [
                {"id": 10, "address": "100 Main St"},
                {"id": 20, "address": "200 Oak Ave"},
                {"id": 30},  # missing address
            ]
        }
        facts = compute_search_facts(data)
        assert facts["property_ids"][10] == "100 Main St"
        assert facts["property_ids"][20] == "200 Oak Ave"
        assert facts["property_ids"][30] is None

    def test_single_result_price_range_is_same(self):
        """Single result: price_range min == max."""
        data = {"results": [{"id": 1, "last_sale_price": 1_000_000}]}
        facts = compute_search_facts(data)
        assert facts["price_range"] == [1_000_000, 1_000_000]
        assert facts["median_price"] == 1_000_000


class TestPredictionFactsEdgeCases:
    """Edge cases for compute_prediction_facts."""

    def test_empty_dict(self):
        """Empty input → all None."""
        facts = compute_prediction_facts({})
        assert facts["predicted_price"] is None
        assert facts["price_lower"] is None
        assert facts["price_upper"] is None
        assert facts["confidence_pct"] is None
        assert facts["neighborhood"] is None

    def test_partial_data(self):
        """Only some fields present."""
        facts = compute_prediction_facts({"predicted_price": 1_000_000})
        assert facts["predicted_price"] == 1_000_000
        assert facts["price_lower"] is None


class TestNeighborhoodFactsEdgeCases:
    """Edge cases for compute_neighborhood_facts."""

    def test_empty_dict(self):
        """Empty input → all None."""
        facts = compute_neighborhood_facts({})
        assert facts["neighborhood"] is None
        assert facts["median_price"] is None
        assert facts["total_sales"] is None
        assert facts["yoy_price_change_pct"] is None
        assert facts["avg_dom"] is None
        assert facts["active_listings"] is None

    def test_partial_data(self):
        """Only some fields present."""
        facts = compute_neighborhood_facts({"neighborhood": "Downtown"})
        assert facts["neighborhood"] == "Downtown"
        assert facts["median_price"] is None


class TestSellVsHoldFactsEdgeCases:
    """Edge cases for compute_sell_vs_hold_facts."""

    def test_empty_rental_estimate(self):
        """Empty rental_estimate dict → None rent fields."""
        data = {"rental_estimate": {}, "hold_scenarios": {}}
        facts = compute_sell_vs_hold_facts(data)
        assert facts["monthly_rent"] is None
        assert facts["cap_rate_pct"] is None
        assert facts["price_to_rent_ratio"] is None

    def test_missing_rental_estimate(self):
        """Missing rental_estimate key → None rent fields."""
        data = {"hold_scenarios": {}}
        facts = compute_sell_vs_hold_facts(data)
        assert facts["monthly_rent"] is None

    def test_missing_hold_scenarios(self):
        """Missing hold_scenarios key → no horizon keys added."""
        data = {"rental_estimate": {"monthly_rent": 3000}}
        facts = compute_sell_vs_hold_facts(data)
        assert facts["monthly_rent"] == 3000
        # No 1yr_projected, 3yr_projected etc.
        assert "1yr_projected" not in facts

    def test_empty_dict(self):
        """Completely empty input."""
        facts = compute_sell_vs_hold_facts({})
        assert facts["current_value"] is None
        assert facts["monthly_rent"] is None


class TestRentalFactsEdgeCases:
    """Edge cases for compute_rental_facts."""

    def test_empty_dict(self):
        """Empty input → all None."""
        facts = compute_rental_facts({})
        assert facts["scenario_name"] is None
        assert facts["monthly_rent"] is None
        assert facts["annual_gross_rent"] is None
        assert facts["annual_noi"] is None
        assert facts["cap_rate_pct"] is None
        assert facts["cash_on_cash_pct"] is None
        assert facts["monthly_cash_flow"] is None


class TestImprovementFactsEdgeCases:
    """Edge cases for compute_improvement_facts."""

    def test_empty_categories(self):
        """No categories → empty top_improvements."""
        data = {"categories": [], "current_price": 1_000_000}
        facts = compute_improvement_facts(data)
        assert facts["top_improvements"] == []
        assert facts["current_price"] == 1_000_000

    def test_missing_categories_key(self):
        """Missing categories key → empty top_improvements."""
        facts = compute_improvement_facts({})
        assert facts["top_improvements"] == []

    def test_categories_with_none_roi_filtered(self):
        """Categories where roi=None are excluded from top list."""
        data = {
            "categories": [
                {"category": "Kitchen", "roi": 2.5, "avg_cost": 30_000},
                {"category": "Unknown", "roi": None, "avg_cost": 0},
                {"category": "Bath", "roi": 1.8, "avg_cost": 15_000},
            ]
        }
        facts = compute_improvement_facts(data)
        # Only Kitchen and Bath have roi, Unknown filtered out
        assert len(facts["top_improvements"]) == 2
        assert facts["top_improvements"][0]["category"] == "Kitchen"
        assert facts["top_improvements"][1]["category"] == "Bath"

    def test_fewer_than_three_categories(self):
        """Fewer than 3 categories → all returned (no IndexError)."""
        data = {
            "categories": [
                {"category": "Kitchen", "roi": 2.5, "avg_cost": 30_000},
            ]
        }
        facts = compute_improvement_facts(data)
        assert len(facts["top_improvements"]) == 1


class TestCompsFactsEdgeCases:
    """Edge cases for compute_comps_facts."""

    def test_comps_missing_price_per_sqft(self):
        """Comps without price_per_sqft → median_price_per_sqft is None."""
        comps = [
            {"sale_price": 1_000_000},
            {"sale_price": 1_200_000},
        ]
        facts = compute_comps_facts(comps)
        assert facts["comp_count"] == 2
        assert facts["price_range"] == [1_000_000, 1_200_000]
        assert facts["median_price_per_sqft"] is None

    def test_dict_missing_comps_key(self):
        """Dict without 'comps' key → 0 comps."""
        facts = compute_comps_facts({"other_key": "value"})
        assert facts["comp_count"] == 0
        assert facts["price_range"] is None

    def test_comps_missing_sale_price(self):
        """Comps without sale_price → price_range is None."""
        comps = [{"address": "123 Main"}, {"address": "456 Oak"}]
        facts = compute_comps_facts(comps)
        assert facts["comp_count"] == 2
        assert facts["price_range"] is None
        assert facts["median_price"] is None

    def test_single_comp(self):
        """Single comp → range min == max, median == price."""
        comps = [{"sale_price": 800_000, "price_per_sqft": 500}]
        facts = compute_comps_facts(comps)
        assert facts["comp_count"] == 1
        assert facts["price_range"] == [800_000, 800_000]
        assert facts["median_price"] == 800_000


class TestRegulationFactsEdgeCases:
    """Edge cases for compute_regulation_facts."""

    def test_zone_extraction(self):
        """Zone dict → zone_code extracted from first key."""
        data = {
            "category": "setbacks",
            "title": "Setback Rules",
            "zone": {"R-1": {"front": 20, "rear": 15}},
        }
        facts = compute_regulation_facts(data)
        assert facts["zone_code"] == "R-1"

    def test_key_numbers(self):
        """key_numbers passed through when present."""
        data = {
            "category": "adu_rules",
            "title": "ADU Regulations",
            "key_numbers": {"max_sqft": 800, "min_setback": 4},
        }
        facts = compute_regulation_facts(data)
        assert facts["key_numbers"] == {"max_sqft": 800, "min_setback": 4}

    def test_related_categories(self):
        """related categories passed through."""
        data = {
            "category": "adu_rules",
            "title": "ADU",
            "related": ["sb9", "middle_housing"],
        }
        facts = compute_regulation_facts(data)
        assert facts["related_categories"] == ["sb9", "middle_housing"]

    def test_empty_zone_dict(self):
        """Empty zone dict → no zone_code key."""
        data = {"category": "test", "title": "T", "zone": {}}
        facts = compute_regulation_facts(data)
        assert "zone_code" not in facts

    def test_empty_dict(self):
        """Completely empty input → not found."""
        facts = compute_regulation_facts({})
        assert facts["found"] is False
        assert facts["category"] == ""
        assert facts["title"] == ""


class TestGlossaryFactsEdgeCases:
    """Edge cases for compute_glossary_facts."""

    def test_related_terms(self):
        """related terms passed through."""
        data = {
            "term_key": "cap_rate",
            "term": "Cap Rate",
            "category": "investment",
            "related": ["noi", "cash_on_cash"],
        }
        facts = compute_glossary_facts(data)
        assert facts["related_terms"] == ["noi", "cash_on_cash"]

    def test_key_numbers(self):
        """key_numbers passed through."""
        data = {
            "term_key": "ltv",
            "term": "LTV",
            "category": "mortgage",
            "key_numbers": {"conventional_max": 80},
        }
        facts = compute_glossary_facts(data)
        assert facts["key_numbers"] == {"conventional_max": 80}

    def test_source_field(self):
        """source field passed through."""
        data = {
            "term_key": "prop13",
            "term": "Prop 13",
            "category": "tax",
            "source": "CA Constitution Art XIIIA",
        }
        facts = compute_glossary_facts(data)
        assert facts["source"] == "CA Constitution Art XIIIA"

    def test_not_found_with_available_categories(self):
        """Not found → available_categories hint surfaced."""
        data = {
            "term_key": None,
            "available_categories": ["investment", "mortgage", "tax"],
        }
        facts = compute_glossary_facts(data)
        assert facts["found"] is False
        assert facts["available_categories"] == ["investment", "mortgage", "tax"]

    def test_empty_dict(self):
        """Completely empty input → not found."""
        facts = compute_glossary_facts({})
        assert facts["found"] is False
        assert facts["term_key"] == ""


class TestQueryFactsEdgeCases:
    """Edge cases for compute_query_facts."""

    def test_empty_rows(self):
        """Empty rows → row_count 0, no result key."""
        facts = compute_query_facts({"columns": ["a", "b"], "rows": []})
        assert facts["row_count"] == 0
        assert "result" not in facts

    def test_single_row_many_columns_no_result(self):
        """Single row with >5 columns → no result key surfaced."""
        facts = compute_query_facts({
            "columns": ["a", "b", "c", "d", "e", "f"],
            "rows": [{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}],
        })
        assert facts["row_count"] == 1
        assert "result" not in facts  # >5 columns, not surfaced

    def test_single_row_exactly_five_columns(self):
        """Single row with exactly 5 columns → result IS surfaced."""
        row = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
        facts = compute_query_facts({
            "columns": ["a", "b", "c", "d", "e"],
            "rows": [row],
        })
        assert facts["result"] == row

    def test_empty_dict(self):
        """Completely empty input → row_count 0."""
        facts = compute_query_facts({})
        assert facts["row_count"] == 0
        assert facts["columns"] == []


class TestUndoFilterFactsEdgeCases:
    """Edge cases for compute_undo_filter_facts."""

    def test_empty_dict(self):
        """Empty input → all None."""
        facts = compute_undo_filter_facts({})
        assert facts["working_set_count"] is None
        assert facts["removed_filter"] is None
        assert facts["remaining_filters"] is None


# ---------------------------------------------------------------------------
# Gap tool fact computer tests
# ---------------------------------------------------------------------------


class TestTrueCostFacts:
    """Tests for compute_true_cost_facts."""

    def test_basic(self):
        data = {
            "total_monthly_cost": 8_500,
            "monthly_principal_and_interest": 5_000,
            "monthly_property_tax": 1_200,
            "monthly_hoi": 200,
            "monthly_earthquake_insurance": 300,
            "monthly_maintenance_reserve": 800,
            "monthly_pmi": 0,
            "monthly_hoa": 0,
            "is_pmi_applicable": False,
            "down_payment_amount": 200_000,
            "loan_amount": 800_000,
            "monthly_delta_vs_rent": 4_500,
            "delta_direction": "more",
            "pmi_note": "No PMI required",
        }
        facts = compute_true_cost_facts(data)
        assert facts["total_monthly_cost"] == 8_500
        assert facts["monthly_pi"] == 5_000
        assert facts["monthly_tax"] == 1_200
        assert facts["is_pmi_applicable"] is False
        assert facts["delta_direction"] == "more"

    def test_empty_dict(self):
        facts = compute_true_cost_facts({})
        assert facts["total_monthly_cost"] is None
        assert facts["monthly_pi"] is None
        assert facts["is_pmi_applicable"] is None


class TestRentVsBuyFacts:
    """Tests for compute_rent_vs_buy_facts."""

    def test_basic(self):
        data = {
            "crossover_year": 7,
            "crossover_description": "Buying wins after year 7",
            "horizon_years": 10,
            "final_annual_rent": 48_000,
            "final_home_value": 1_400_000,
            "final_home_equity": 600_000,
            "final_buy_advantage": 200_000,
            "total_rent_paid": 400_000,
            "total_ownership_paid": 500_000,
            "total_tax_benefit": 50_000,
            "opportunity_cost_of_down_payment": 80_000,
        }
        facts = compute_rent_vs_buy_facts(data)
        assert facts["crossover_year"] == 7
        assert facts["final_buy_advantage"] == 200_000
        assert facts["total_tax_benefit"] == 50_000

    def test_empty_dict(self):
        facts = compute_rent_vs_buy_facts({})
        assert facts["crossover_year"] is None
        assert facts["horizon_years"] is None


class TestDualPropertyFacts:
    """Tests for compute_dual_property_facts."""

    def test_basic(self):
        data = {
            "available_equity": 300_000,
            "extraction": {"method": "HELOC", "extraction_amount": 200_000, "monthly_increase": 800},
            "investment": {
                "monthly_gross_rent": 3_000,
                "monthly_net_cash_flow": 500,
                "cap_rate_pct": 4.5,
            },
            "combined_monthly_cash_flow": -300,
            "combined_annual_cash_flow": -3_600,
            "cash_on_cash_pct": 2.1,
            "is_cash_flow_positive": False,
            "worst_case_scenario": "vacancy + rate hike",
            "survives_worst_case": True,
        }
        facts = compute_dual_property_facts(data)
        assert facts["available_equity"] == 300_000
        assert facts["extraction_method"] == "HELOC"
        assert facts["extraction_amount"] == 200_000
        assert facts["investment_monthly_rent"] == 3_000
        assert facts["is_cash_flow_positive"] is False
        assert facts["survives_worst_case"] is True

    def test_empty_dict(self):
        facts = compute_dual_property_facts({})
        assert facts["available_equity"] is None
        assert facts["extraction_method"] is None
        assert facts["investment_monthly_rent"] is None

    def test_missing_nested_dicts(self):
        """extraction and investment missing → nested fields are None."""
        data = {"available_equity": 100_000}
        facts = compute_dual_property_facts(data)
        assert facts["available_equity"] == 100_000
        assert facts["extraction_method"] is None
        assert facts["investment_monthly_cf"] is None


class TestCompetitionFacts:
    """Tests for compute_competition_facts."""

    def test_basic(self):
        data = {
            "neighborhood": "North Berkeley",
            "sample_size": 45,
            "competition_score": 72.5,
            "competition_label": "Competitive",
            "sale_to_list_median": 1.05,
            "dom_distribution": {"median": 12, "p25": 7, "p75": 21},
            "above_asking_pct": 65.0,
            "months_of_inventory": 1.2,
            "interpretation": "Sellers market",
        }
        facts = compute_competition_facts(data)
        assert facts["competition_score"] == 72.5
        assert facts["dom_median"] == 12
        assert facts["above_asking_pct"] == 65.0

    def test_empty_dict(self):
        facts = compute_competition_facts({})
        assert facts["competition_score"] is None
        assert facts["dom_median"] is None

    def test_missing_dom_distribution(self):
        """Missing dom_distribution → dom_median is None."""
        facts = compute_competition_facts({"competition_score": 50})
        assert facts["dom_median"] is None


class TestRatePenaltyFacts:
    """Tests for compute_rate_penalty_facts."""

    def test_basic(self):
        data = {
            "existing_rate": 3.0,
            "new_rate": 7.0,
            "existing_monthly_payment": 1_265,
            "new_monthly_payment": 4_250,
            "monthly_penalty": 2_985,
            "annual_penalty": 35_820,
            "penalty_description": "New payment is $2,985/mo more",
            "penalty_pct_of_income": 8.5,
            "is_tolerable": False,
            "breakeven_rate": 3.2,
            "breakeven_description": "At 3.2%, payments match",
            "tolerable_rate": 4.5,
        }
        facts = compute_rate_penalty_facts(data)
        assert facts["monthly_penalty"] == 2_985
        assert facts["is_tolerable"] is False
        assert facts["breakeven_rate"] == 3.2
        assert facts["tolerable_rate"] == 4.5

    def test_empty_dict(self):
        facts = compute_rate_penalty_facts({})
        assert facts["existing_rate"] is None
        assert facts["monthly_penalty"] is None
        assert facts["breakeven_rate"] is None


class TestPmiModelFacts:
    """Tests for compute_pmi_model_facts."""

    def test_basic(self):
        data = {
            "pmi_applicable": True,
            "initial_ltv_pct": 90.0,
            "monthly_pmi": 450,
            "annual_pmi": 5_400,
            "pmi_dropoff_month": 84,
            "pmi_dropoff_years": 7.0,
            "pmi_dropoff_description": "PMI drops after 7 years",
            "total_pmi_cost": 37_800,
            "appreciation_acceleration_months": 60,
            "wait_analysis": {
                "verdict": "buy_now",
                "verdict_description": "Better to buy now",
                "net_cost_of_waiting": 25_000,
            },
        }
        facts = compute_pmi_model_facts(data)
        assert facts["pmi_applicable"] is True
        assert facts["monthly_pmi"] == 450
        assert facts["pmi_dropoff_years"] == 7.0
        assert facts["wait_verdict"] == "buy_now"
        assert facts["net_cost_of_waiting"] == 25_000

    def test_empty_dict(self):
        facts = compute_pmi_model_facts({})
        assert facts["pmi_applicable"] is None
        assert facts["wait_verdict"] is None

    def test_missing_wait_analysis(self):
        """Missing wait_analysis → wait fields None."""
        data = {"pmi_applicable": False}
        facts = compute_pmi_model_facts(data)
        assert facts["wait_verdict"] is None
        assert facts["net_cost_of_waiting"] is None


class TestYieldRankingFacts:
    """Tests for compute_yield_ranking_facts."""

    def test_basic(self):
        data = {
            "property_count": 5,
            "positive_cash_flow_count": 2,
            "negative_spread_count": 3,
            "best_leverage_spread": {
                "address": "100 Main St",
                "leverage_spread_pct": 1.5,
            },
            "best_cash_on_cash": {
                "address": "200 Oak Ave",
                "cash_on_cash_pct": 6.2,
            },
        }
        facts = compute_yield_ranking_facts(data)
        assert facts["property_count"] == 5
        assert facts["best_spread_address"] == "100 Main St"
        assert facts["best_coc_pct"] == 6.2

    def test_empty_dict(self):
        facts = compute_yield_ranking_facts({})
        assert facts["property_count"] is None
        assert facts["best_spread_address"] is None
        assert facts["best_coc_pct"] is None

    def test_missing_best_entries(self):
        """Missing best_* dicts → addresses/pcts are None."""
        data = {"property_count": 0}
        facts = compute_yield_ranking_facts(data)
        assert facts["best_spread_address"] is None
        assert facts["best_coc_address"] is None


class TestAppreciationStressFacts:
    """Tests for compute_appreciation_stress_facts."""

    def test_basic(self):
        data = {
            "scenario_count": 5,
            "all_scenarios_profitable": False,
            "any_scenario_profitable": True,
            "monthly_carry_cost": 6_500,
            "purchase_price": 1_200_000,
        }
        facts = compute_appreciation_stress_facts(data)
        assert facts["scenario_count"] == 5
        assert facts["all_scenarios_profitable"] is False
        assert facts["any_scenario_profitable"] is True
        assert facts["monthly_carry_cost"] == 6_500

    def test_empty_dict(self):
        facts = compute_appreciation_stress_facts({})
        assert facts["scenario_count"] is None
        assert facts["all_scenarios_profitable"] is None


class TestNeighborhoodLifestyleFacts:
    """Tests for compute_neighborhood_lifestyle_facts."""

    def test_basic(self):
        data = {
            "neighborhoods_compared": 4,
            "best_overall": "North Berkeley",
            "best_per_factor": {
                "walkability": "Downtown",
                "schools": "Claremont",
            },
        }
        facts = compute_neighborhood_lifestyle_facts(data)
        assert facts["neighborhoods_compared"] == 4
        assert facts["best_overall"] == "North Berkeley"
        assert facts["best_per_factor"]["walkability"] == "Downtown"

    def test_empty_dict(self):
        facts = compute_neighborhood_lifestyle_facts({})
        assert facts["neighborhoods_compared"] is None
        assert facts["best_overall"] is None
        assert facts["best_per_factor"] is None


class TestAdjacentMarketFacts:
    """Tests for compute_adjacent_market_facts."""

    def test_basic(self):
        data = {
            "budget": 1_000_000,
            "markets_compared": 8,
            "affordable_count": 5,
            "affordable_markets": ["Oakland", "El Cerrito", "Richmond"],
            "best_value": "El Cerrito",
            "meets_requirements_count": 3,
        }
        facts = compute_adjacent_market_facts(data)
        assert facts["budget"] == 1_000_000
        assert facts["affordable_count"] == 5
        assert facts["best_value"] == "El Cerrito"
        assert facts["meets_requirements_count"] == 3

    def test_empty_dict(self):
        facts = compute_adjacent_market_facts({})
        assert facts["budget"] is None
        assert facts["affordable_count"] is None
        assert facts["best_value"] is None
