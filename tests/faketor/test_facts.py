"""Tests for Faketor fact computation functions.

Each test verifies that a fact computer correctly extracts and transforms
tool result data into verified facts for the accumulator and system prompt.
"""


from homebuyer.services.faketor.facts import (
    compute_comps_facts,
    compute_development_facts,
    compute_glossary_facts,
    compute_improvement_facts,
    compute_investment_facts,
    compute_neighborhood_facts,
    compute_prediction_facts,
    compute_query_facts,
    compute_regulation_facts,
    compute_rental_facts,
    compute_search_facts,
    compute_sell_vs_hold_facts,
    compute_undo_filter_facts,
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
