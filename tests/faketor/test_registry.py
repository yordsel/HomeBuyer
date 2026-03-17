"""Tests for the Faketor ToolRegistry.

Tests use fresh ToolRegistry instances for isolation, except the populated
singleton test which verifies all 18 tools are registered at module load.
"""

import logging


from homebuyer.services.faketor.tools.registry import ToolDefinition, ToolRegistry


# ---------------------------------------------------------------------------
# Fresh-instance tests (isolated from module-level singleton)
# ---------------------------------------------------------------------------


class TestToolRegistryBasics:
    """Core registry operations."""

    def _make_tool(self, name: str = "test_tool", **overrides) -> ToolDefinition:
        """Helper to build a minimal ToolDefinition."""
        defn: ToolDefinition = {
            "name": name,
            "description": f"Description for {name}",
            "input_schema": {
                "type": "object",
                "properties": {"x": {"type": "number"}},
                "required": ["x"],
            },
            "block_type": None,
            "fact_computer": None,
        }
        defn.update(overrides)
        return defn

    def test_register_many_populates_registry(self):
        reg = ToolRegistry()
        reg.register_many([
            self._make_tool("alpha"),
            self._make_tool("beta"),
        ])
        assert len(reg) == 2
        assert "alpha" in reg.names
        assert "beta" in reg.names

    def test_get_tool_schemas_returns_anthropic_format(self):
        reg = ToolRegistry()
        reg.register_many([self._make_tool("alpha")])
        schemas = reg.get_tool_schemas()
        assert len(schemas) == 1
        s = schemas[0]
        # Must have exactly these three keys (Anthropic API format)
        assert set(s.keys()) == {"name", "description", "input_schema"}
        assert s["name"] == "alpha"
        assert s["description"] == "Description for alpha"
        assert s["input_schema"]["type"] == "object"

    def test_get_block_type_returns_correct_mapping(self):
        reg = ToolRegistry()
        reg.register_many([
            self._make_tool("alpha", block_type="alpha_card"),
        ])
        assert reg.get_block_type("alpha") == "alpha_card"

    def test_get_block_type_returns_none_for_unknown(self):
        reg = ToolRegistry()
        assert reg.get_block_type("nonexistent") is None

    def test_get_block_type_returns_none_when_no_block_type(self):
        reg = ToolRegistry()
        reg.register_many([self._make_tool("alpha", block_type=None)])
        assert reg.get_block_type("alpha") is None

    def test_get_fact_computer_returns_callable(self):
        def my_fc(data):
            return {"count": 1}

        reg = ToolRegistry()
        reg.register_many([self._make_tool("alpha", fact_computer=my_fc)])
        fc = reg.get_fact_computer("alpha")
        assert callable(fc)
        assert fc({"x": 1}) == {"count": 1}

    def test_get_fact_computer_returns_none_when_absent(self):
        reg = ToolRegistry()
        reg.register_many([self._make_tool("alpha", fact_computer=None)])
        assert reg.get_fact_computer("alpha") is None

    def test_get_fact_computer_returns_none_for_unknown(self):
        reg = ToolRegistry()
        assert reg.get_fact_computer("nonexistent") is None

    def test_names_returns_frozenset(self):
        reg = ToolRegistry()
        reg.register_many([self._make_tool("alpha"), self._make_tool("beta")])
        names = reg.names
        assert isinstance(names, frozenset)
        assert names == frozenset({"alpha", "beta"})


class TestToolRegistryDecorator:
    """Decorator-based registration (used by Phase F gap tools)."""

    def test_decorator_registration(self):
        reg = ToolRegistry()

        @reg.register(
            name="rent_vs_buy",
            description="Compare renting vs buying",
            input_schema={
                "type": "object",
                "properties": {"price": {"type": "number"}},
                "required": ["price"],
            },
            block_type="rent_vs_buy_card",
        )
        def _compute_rvb_facts(data):
            return {"result": "renting_wins"}

        assert len(reg) == 1
        assert "rent_vs_buy" in reg.names

        # Schema is correct
        schemas = reg.get_tool_schemas()
        assert schemas[0]["name"] == "rent_vs_buy"

        # Block type set
        assert reg.get_block_type("rent_vs_buy") == "rent_vs_buy_card"

        # Fact computer is the decorated function
        fc = reg.get_fact_computer("rent_vs_buy")
        assert fc is _compute_rvb_facts
        assert fc({"x": 1}) == {"result": "renting_wins"}

    def test_decorator_returns_original_function(self):
        """The decorator should not wrap or modify the function."""
        reg = ToolRegistry()

        @reg.register(
            name="test",
            description="test",
            input_schema={"type": "object", "properties": {}},
        )
        def my_func(data):
            return {"a": 1}

        # The returned function IS the original
        assert my_func({"x": 1}) == {"a": 1}
        assert my_func.__name__ == "my_func"


class TestToolRegistryDuplicates:
    """Duplicate registration behavior."""

    def test_duplicate_registration_overwrites_with_warning(self, caplog):
        reg = ToolRegistry()
        reg.register_many([
            {
                "name": "alpha",
                "description": "v1",
                "input_schema": {"type": "object", "properties": {}},
                "block_type": None,
                "fact_computer": None,
            },
        ])
        with caplog.at_level(logging.WARNING):
            reg.register_many([
                {
                    "name": "alpha",
                    "description": "v2",
                    "input_schema": {"type": "object", "properties": {}},
                    "block_type": "alpha_card",
                    "fact_computer": None,
                },
            ])
        assert "duplicate registration" in caplog.text.lower()
        # Second registration wins
        schemas = reg.get_tool_schemas()
        assert schemas[0]["description"] == "v2"
        assert reg.get_block_type("alpha") == "alpha_card"


# ---------------------------------------------------------------------------
# Populated singleton test (verifies all 18 tools registered at import)
# ---------------------------------------------------------------------------


class TestPopulatedRegistry:
    """Test the module-level singleton from faketor.tools."""

    def test_all_tools_registered(self):
        from homebuyer.services.faketor.tools import registry

        # 18 original + Phase F gap tools (compute_true_cost, ...)
        assert len(registry) >= 19

    def test_known_tools_present(self):
        from homebuyer.services.faketor.tools import registry

        expected = {
            "lookup_property",
            "get_development_potential",
            "get_improvement_simulation",
            "get_comparable_sales",
            "get_neighborhood_stats",
            "get_market_summary",
            "get_price_prediction",
            "estimate_sell_vs_hold",
            "estimate_rental_income",
            "analyze_investment_scenarios",
            "generate_investment_prospectus",
            "search_properties",
            "lookup_permits",
            "undo_filter",
            "query_database",
            "update_working_set",
            "lookup_regulation",
            "lookup_glossary_term",
            # Phase F gap tools
            "compute_true_cost",
            "rent_vs_buy",
            "pmi_model",
        }
        assert registry.names == expected

    def test_block_type_mappings(self):
        from homebuyer.services.faketor.tools import registry

        assert registry.get_block_type("lookup_property") == "property_detail"
        assert registry.get_block_type("get_price_prediction") == "prediction_card"
        assert registry.get_block_type("search_properties") == "property_search_results"
        assert registry.get_block_type("lookup_regulation") == "regulation_info"
        assert registry.get_block_type("lookup_glossary_term") == "glossary_info"
        # lookup_permits and undo_filter have no block type
        assert registry.get_block_type("lookup_permits") is None
        assert registry.get_block_type("undo_filter") is None

    def test_fact_computers_for_tools_with_enrichment(self):
        from homebuyer.services.faketor.tools import registry

        # These tools should have fact computers
        tools_with_fc = [
            "search_properties",
            "get_development_potential",
            "get_price_prediction",
            "get_comparable_sales",
            "get_neighborhood_stats",
            "estimate_sell_vs_hold",
            "estimate_rental_income",
            "analyze_investment_scenarios",
            "get_improvement_simulation",
            "query_database",
            "undo_filter",
            "lookup_regulation",
            "lookup_glossary_term",
        ]
        for name in tools_with_fc:
            fc = registry.get_fact_computer(name)
            assert fc is not None, f"{name} should have a fact computer"
            assert callable(fc), f"{name} fact computer should be callable"

    def test_fact_computers_absent_for_tools_without_enrichment(self):
        from homebuyer.services.faketor.tools import registry

        # These tools should NOT have fact computers
        tools_without_fc = [
            "lookup_property",
            "lookup_permits",
            "get_market_summary",
            "generate_investment_prospectus",
            "update_working_set",
        ]
        for name in tools_without_fc:
            assert registry.get_fact_computer(name) is None, (
                f"{name} should NOT have a fact computer"
            )

    def test_tool_schemas_match_anthropic_format(self):
        from homebuyer.services.faketor.tools import registry

        schemas = registry.get_tool_schemas()
        assert len(schemas) >= 19  # 18 original + Phase F gap tools
        for s in schemas:
            assert "name" in s
            assert "description" in s
            assert "input_schema" in s
            assert s["input_schema"]["type"] == "object"
            assert "properties" in s["input_schema"]
