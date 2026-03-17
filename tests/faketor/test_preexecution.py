"""Tests for PreExecutor — proactive analysis execution before LLM turns.

Phase E-4 (#48) of Epic #23.
"""

import json

from homebuyer.services.faketor.jobs import AnalysisSpec, TurnPlan, RequestType
from homebuyer.services.faketor.tools.preexecution import (
    PreExecutionResult,
    PreExecutor,
    _build_tool_input,
    _order_analyses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(responses: dict[str, str | dict] | None = None):
    """Create a mock tool executor that returns canned responses.

    Args:
        responses: Mapping of tool_name → JSON string or dict response.
            If a dict is given, it's auto-serialized to JSON.
    """
    responses = responses or {}

    def executor(tool_name: str, tool_input: dict) -> str:
        resp = responses.get(tool_name, json.dumps({"result": "ok"}))
        if isinstance(resp, dict):
            return json.dumps(resp)
        return resp

    return executor


def _make_failing_executor(fail_tools: set[str] | None = None):
    """Create an executor that raises for specified tools."""
    fail_tools = fail_tools or set()

    def executor(tool_name: str, tool_input: dict) -> str:
        if tool_name in fail_tools:
            raise RuntimeError(f"Tool {tool_name} failed")
        return json.dumps({"result": "ok"})

    return executor


def _make_plan(analyses: list[AnalysisSpec]) -> TurnPlan:
    return TurnPlan(
        request_type=RequestType.PROPERTY_EVALUATION,
        segment_id="stretcher",
        proactive_analyses=analyses,
    )


# ---------------------------------------------------------------------------
# PreExecutionResult tests
# ---------------------------------------------------------------------------


class TestPreExecutionResult:
    def test_has_facts_empty(self):
        result = PreExecutionResult()
        assert result.has_facts is False

    def test_has_facts_with_data(self):
        result = PreExecutionResult(facts={"tool_a": {"key": "val"}})
        assert result.has_facts is True

    def test_render_empty(self):
        result = PreExecutionResult()
        assert result.render_prompt_fragment() == ""

    def test_render_with_facts(self):
        result = PreExecutionResult(
            facts={
                "get_price_prediction": {
                    "predicted_price": "$1,200,000",
                    "confidence": "medium",
                }
            }
        )
        fragment = result.render_prompt_fragment()
        assert "=== PRE-EXECUTED ANALYSIS RESULTS ===" in fragment
        assert "=== END PRE-EXECUTED ANALYSIS RESULTS ===" in fragment
        assert "get_price_prediction" in fragment
        assert "$1,200,000" in fragment

    def test_render_with_nested_dict(self):
        result = PreExecutionResult(
            facts={
                "tool_a": {
                    "metrics": {"median": 1000, "count": 5},
                }
            }
        )
        fragment = result.render_prompt_fragment()
        assert "median: 1000" in fragment

    def test_render_with_list_value(self):
        result = PreExecutionResult(
            facts={
                "tool_a": {
                    "addresses": ["123 Main", "456 Oak"],
                }
            }
        )
        fragment = result.render_prompt_fragment()
        assert "123 Main" in fragment

    def test_render_multiple_tools(self):
        result = PreExecutionResult(
            facts={
                "tool_a": {"key_a": "val_a"},
                "tool_b": {"key_b": "val_b"},
            }
        )
        fragment = result.render_prompt_fragment()
        assert "--- tool_a ---" in fragment
        assert "--- tool_b ---" in fragment


# ---------------------------------------------------------------------------
# _order_analyses tests
# ---------------------------------------------------------------------------


class TestOrderAnalyses:
    def test_no_deps_first(self):
        a1 = AnalysisSpec("market", (), "no deps")
        a2 = AnalysisSpec("prediction", ("property_context",), "has deps")
        ordered = _order_analyses([a2, a1])
        assert ordered[0] is a1
        assert ordered[1] is a2

    def test_preserves_order_within_group(self):
        a1 = AnalysisSpec("tool_a", ("property_context",))
        a2 = AnalysisSpec("tool_b", ("property_context",))
        ordered = _order_analyses([a1, a2])
        assert ordered == [a1, a2]

    def test_empty_list(self):
        assert _order_analyses([]) == []


# ---------------------------------------------------------------------------
# _build_tool_input tests
# ---------------------------------------------------------------------------


class TestBuildToolInput:
    def test_no_property_context(self):
        spec = AnalysisSpec("get_price_prediction", ("property_context",))
        result = _build_tool_input(spec, None)
        assert result == {}

    def test_price_prediction_gets_address(self):
        spec = AnalysisSpec("get_price_prediction", ("property_context",))
        ctx = {"address": "1234 Cedar St", "price": 1_200_000}
        result = _build_tool_input(spec, ctx)
        assert result["address"] == "1234 Cedar St"

    def test_comparable_sales_gets_price(self):
        spec = AnalysisSpec("get_comparable_sales", ("property_context",))
        ctx = {"address": "1234 Cedar St", "price": 1_200_000}
        result = _build_tool_input(spec, ctx)
        assert result["address"] == "1234 Cedar St"
        assert result["target_price"] == 1_200_000

    def test_rental_income_gets_bedrooms(self):
        spec = AnalysisSpec("estimate_rental_income", ("property_context",))
        ctx = {"address": "1234 Cedar St", "bedrooms": 3, "sqft": 1500}
        result = _build_tool_input(spec, ctx)
        assert result["bedrooms"] == 3
        assert result["sqft"] == 1500

    def test_development_potential_gets_address(self):
        spec = AnalysisSpec("get_development_potential", ("property_context",))
        ctx = {"address": "1234 Cedar St"}
        result = _build_tool_input(spec, ctx)
        assert result["address"] == "1234 Cedar St"

    def test_neighborhood_stats_gets_neighborhood(self):
        spec = AnalysisSpec("get_neighborhood_stats", ("property_context",))
        ctx = {"address": "1234 Cedar St", "neighborhood": "North Berkeley"}
        result = _build_tool_input(spec, ctx)
        assert result["neighborhood"] == "North Berkeley"

    def test_unknown_tool_gets_address_fallback(self):
        spec = AnalysisSpec("future_tool", ("property_context",))
        ctx = {"address": "1234 Cedar St"}
        result = _build_tool_input(spec, ctx)
        assert result["address"] == "1234 Cedar St"

    def test_no_requires_returns_empty(self):
        spec = AnalysisSpec("get_market_summary")
        result = _build_tool_input(spec, {"address": "1234 Cedar St"})
        assert result == {}

    # --- Gap tool input building ---

    def test_true_cost_with_buyer_capital(self):
        spec = AnalysisSpec("compute_true_cost", ("property_context",))
        prop = {"price": 1_000_000, "mortgage_rate": 6.5, "year_built": 1960}
        buyer = {"capital": 200_000, "current_rent": 3500}
        result = _build_tool_input(spec, prop, buyer)
        assert result["purchase_price"] == 1_000_000
        assert result["mortgage_rate"] == 6.5
        assert result["down_payment_pct"] == 20
        assert result["current_rent"] == 3500
        assert result["year_built"] == 1960

    def test_true_cost_defaults_without_buyer(self):
        spec = AnalysisSpec("compute_true_cost", ("property_context",))
        prop = {"price": 800_000}
        result = _build_tool_input(spec, prop)
        assert result["purchase_price"] == 800_000
        assert result["down_payment_pct"] == 20.0

    def test_pmi_model_low_down_payment(self):
        spec = AnalysisSpec("compute_pmi_model", ("property_context",))
        prop = {"price": 1_000_000, "mortgage_rate": 7.0}
        buyer = {"capital": 100_000}  # 10% down
        result = _build_tool_input(spec, prop, buyer)
        assert result["down_payment_pct"] == 10
        assert result["monthly_savings"] == 2000  # capital * 0.02

    def test_competition_uses_neighborhood_and_price_band(self):
        spec = AnalysisSpec("compute_competition", ("property_context",))
        prop = {"neighborhood": "North Berkeley", "price": 1_000_000}
        result = _build_tool_input(spec, prop)
        assert result["neighborhood"] == "North Berkeley"
        assert result["price_min"] == 800_000
        assert result["price_max"] == 1_200_000

    def test_appreciation_stress_with_buyer(self):
        spec = AnalysisSpec("compute_appreciation_stress", ("property_context",))
        prop = {"price": 900_000, "mortgage_rate": 6.5}
        buyer = {"capital": 180_000}
        result = _build_tool_input(spec, prop, buyer)
        assert result["purchase_price"] == 900_000
        assert result["down_payment_pct"] == 20

    def test_rent_vs_buy_uses_current_rent(self):
        spec = AnalysisSpec("compute_rent_vs_buy", ("property_context",))
        prop = {"price": 800_000, "mortgage_rate": 6.5}
        buyer = {"capital": 160_000, "current_rent": 4000}
        result = _build_tool_input(spec, prop, buyer)
        assert result["current_rent"] == 4000
        assert result["down_payment_pct"] == 20

    def test_neighborhood_lifestyle_no_property(self):
        spec = AnalysisSpec("compute_neighborhood_lifestyle", ())
        result = _build_tool_input(spec, None)
        assert result == {}

    def test_adjacent_market_uses_buyer_budget(self):
        spec = AnalysisSpec("compute_adjacent_market", ("buyer_profile",))
        buyer = {"capital": 800_000}
        result = _build_tool_input(spec, None, buyer)
        assert result["budget"] == 800_000

    def test_adjacent_market_default_budget(self):
        spec = AnalysisSpec("compute_adjacent_market", ("buyer_profile",))
        result = _build_tool_input(spec, None, None)
        assert result["budget"] == 1_000_000

    def test_rate_penalty_with_buyer_income(self):
        spec = AnalysisSpec("compute_rate_penalty", ("property_context", "buyer_profile"))
        prop = {"price": 1_200_000, "mortgage_rate": 7.0}
        buyer = {"equity": 300_000, "income": 250_000}
        result = _build_tool_input(spec, prop, buyer)
        assert result["new_purchase_price"] == 1_200_000
        assert result["annual_gross_income"] == 250_000

    def test_dual_property_with_buyer_equity(self):
        spec = AnalysisSpec("compute_dual_property", ("property_context", "buyer_profile"))
        prop = {"price": 700_000, "mortgage_rate": 6.5}
        buyer = {"equity": 400_000, "income": 200_000}
        result = _build_tool_input(spec, prop, buyer)
        assert result["investment_price"] == 700_000
        assert result["annual_gross_income"] == 200_000

    def test_down_payment_capped_at_100_pct(self):
        spec = AnalysisSpec("compute_true_cost", ("property_context",))
        prop = {"price": 500_000}
        buyer = {"capital": 1_000_000}  # More cash than property price
        result = _build_tool_input(spec, prop, buyer)
        assert result["down_payment_pct"] == 100


# ---------------------------------------------------------------------------
# PreExecutor tests
# ---------------------------------------------------------------------------


class TestPreExecutor:
    def test_empty_plan(self):
        executor = PreExecutor(_make_executor())
        result = executor.execute(TurnPlan())
        assert not result.has_facts
        assert result.execution_time_ms == 0.0

    def test_executes_analyses(self):
        responses = {
            "get_market_summary": {
                "median_price": 1_300_000,
                "inventory": 120,
            }
        }
        plan = _make_plan([AnalysisSpec("get_market_summary")])
        executor = PreExecutor(_make_executor(responses))
        result = executor.execute(plan)
        assert "get_market_summary" in result.raw_results

    def test_graceful_failure(self):
        """Tool failures are logged but don't block other analyses."""
        plan = _make_plan([
            AnalysisSpec("failing_tool"),
            AnalysisSpec("get_market_summary"),
        ])
        executor = PreExecutor(_make_failing_executor({"failing_tool"}))
        result = executor.execute(plan)
        assert "failing_tool" in result.failures
        assert "get_market_summary" in result.raw_results

    def test_error_response_recorded(self):
        """Tool returning error JSON is treated as failure."""
        responses = {
            "bad_tool": {"error": "Not found"},
        }
        plan = _make_plan([AnalysisSpec("bad_tool")])
        executor = PreExecutor(_make_executor(responses))
        result = executor.execute(plan)
        assert "bad_tool" in result.failures
        assert "bad_tool" not in result.raw_results

    def test_non_json_response_skipped(self):
        """Non-JSON responses are logged and skipped."""
        responses = {"bad_tool": "not json {{{"}
        plan = _make_plan([AnalysisSpec("bad_tool")])
        executor = PreExecutor(_make_executor(responses))
        result = executor.execute(plan)
        assert "bad_tool" not in result.raw_results
        assert "bad_tool" not in result.facts

    def test_execution_time_tracked(self):
        plan = _make_plan([AnalysisSpec("get_market_summary")])
        executor = PreExecutor(_make_executor())
        result = executor.execute(plan)
        assert result.execution_time_ms >= 0

    def test_property_context_passed(self):
        """Property context is used to build tool inputs."""
        calls = []

        def tracking_executor(tool_name: str, tool_input: dict) -> str:
            calls.append((tool_name, tool_input))
            return json.dumps({"result": "ok"})

        plan = _make_plan([
            AnalysisSpec("get_price_prediction", ("property_context",)),
        ])
        prop_ctx = {"address": "1234 Cedar St", "price": 1_200_000}
        executor = PreExecutor(tracking_executor)
        executor.execute(plan, property_context=prop_ctx)

        assert len(calls) == 1
        assert calls[0][0] == "get_price_prediction"
        assert calls[0][1]["address"] == "1234 Cedar St"

    def test_buyer_profile_passed_to_gap_tools(self):
        """Buyer profile is used to build inputs for gap tools."""
        calls = []

        def tracking_executor(tool_name: str, tool_input: dict) -> str:
            calls.append((tool_name, tool_input))
            return json.dumps({"result": "ok"})

        plan = _make_plan([
            AnalysisSpec("compute_true_cost", ("property_context",)),
        ])
        prop_ctx = {"price": 1_000_000, "mortgage_rate": 7.0}
        buyer = {"capital": 200_000, "current_rent": 3500}
        executor = PreExecutor(tracking_executor)
        executor.execute(plan, property_context=prop_ctx, buyer_profile=buyer)

        assert len(calls) == 1
        assert calls[0][0] == "compute_true_cost"
        assert calls[0][1]["purchase_price"] == 1_000_000
        assert calls[0][1]["down_payment_pct"] == 20
        assert calls[0][1]["current_rent"] == 3500

    def test_ordering_respected(self):
        """No-dep analyses run before property-dependent ones."""
        call_order = []

        def tracking_executor(tool_name: str, tool_input: dict) -> str:
            call_order.append(tool_name)
            return json.dumps({"result": "ok"})

        plan = _make_plan([
            AnalysisSpec("get_price_prediction", ("property_context",)),
            AnalysisSpec("get_market_summary"),
        ])
        executor = PreExecutor(tracking_executor)
        executor.execute(plan, property_context={"address": "test"})

        assert call_order[0] == "get_market_summary"
        assert call_order[1] == "get_price_prediction"
