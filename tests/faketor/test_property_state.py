"""Tests for PropertyState, FilterIntent, FocusProperty, AnalysisRecord, PropertyAnalysis.

Covers:
- Recording analyses
- Staleness detection against market snapshots
- Serialization roundtrips
- Market-sensitive tool filtering
"""


from homebuyer.services.faketor.state.market import MarketDelta
from homebuyer.services.faketor.state.property import (
    AnalysisRecord,
    FilterIntent,
    FocusProperty,
    PropertyAnalysis,
    PropertyState,
    _MARKET_SENSITIVE_TOOLS,
)


# ---------------------------------------------------------------------------
# FilterIntent
# ---------------------------------------------------------------------------


class TestFilterIntent:
    def test_defaults(self):
        fi = FilterIntent()
        assert fi.criteria == {}
        assert fi.description == ""

    def test_serialization_roundtrip(self):
        fi = FilterIntent(
            criteria={"min_beds": 3, "neighborhood": "N Berkeley"},
            description="3+ beds in North Berkeley",
            created_at=1000.0,
        )
        restored = FilterIntent.from_dict(fi.to_dict())
        assert restored.criteria["min_beds"] == 3
        assert restored.description == "3+ beds in North Berkeley"


# ---------------------------------------------------------------------------
# FocusProperty
# ---------------------------------------------------------------------------


class TestFocusProperty:
    def test_defaults(self):
        fp = FocusProperty()
        assert fp.property_id == 0
        assert fp.last_known_status == "unknown"

    def test_serialization_roundtrip(self):
        fp = FocusProperty(
            property_id=42,
            address="123 Test St",
            last_known_status="active",
            status_checked_at=2000.0,
            property_context={"beds": 3, "baths": 2},
        )
        restored = FocusProperty.from_dict(fp.to_dict())
        assert restored.property_id == 42
        assert restored.address == "123 Test St"
        assert restored.last_known_status == "active"
        assert restored.property_context["beds"] == 3


# ---------------------------------------------------------------------------
# AnalysisRecord
# ---------------------------------------------------------------------------


class TestAnalysisRecord:
    def test_serialization_roundtrip(self):
        ar = AnalysisRecord(
            tool_name="get_price_prediction",
            result_summary="Predicted: $1.35M",
            conclusion="5% underpriced",
            computed_at=1000.0,
            market_snapshot_at=999.0,
        )
        restored = AnalysisRecord.from_dict(ar.to_dict())
        assert restored.tool_name == "get_price_prediction"
        assert restored.conclusion == "5% underpriced"

    def test_conclusion_can_be_none(self):
        ar = AnalysisRecord(tool_name="test", result_summary="test")
        d = ar.to_dict()
        restored = AnalysisRecord.from_dict(d)
        assert restored.conclusion is None


# ---------------------------------------------------------------------------
# PropertyAnalysis
# ---------------------------------------------------------------------------


class TestPropertyAnalysis:
    def test_serialization_roundtrip(self):
        pa = PropertyAnalysis(
            property_id=42,
            address="123 Test St",
            analyses={
                "get_price_prediction": AnalysisRecord(
                    tool_name="get_price_prediction",
                    result_summary="$1.35M",
                    computed_at=1000.0,
                    market_snapshot_at=999.0,
                ),
            },
        )
        restored = PropertyAnalysis.from_dict(pa.to_dict())
        assert restored.property_id == 42
        assert "get_price_prediction" in restored.analyses


# ---------------------------------------------------------------------------
# PropertyState — record_analysis
# ---------------------------------------------------------------------------


class TestPropertyStateRecordAnalysis:
    def test_creates_property_analysis_on_first_record(self):
        ps = PropertyState()
        ps.record_analysis(
            property_id=1,
            address="100 Main St",
            tool_name="get_price_prediction",
            result_summary="$1.2M",
            conclusion=None,
            market_snapshot_at=1000.0,
        )
        assert 1 in ps.analyses
        assert ps.analyses[1].address == "100 Main St"
        assert "get_price_prediction" in ps.analyses[1].analyses

    def test_appends_to_existing_property(self):
        ps = PropertyState()
        ps.record_analysis(
            property_id=1, address="100 Main St",
            tool_name="get_price_prediction", result_summary="$1.2M",
            conclusion=None, market_snapshot_at=1000.0,
        )
        ps.record_analysis(
            property_id=1, address="100 Main St",
            tool_name="get_comparable_sales", result_summary="5 comps",
            conclusion=None, market_snapshot_at=1000.0,
        )
        assert len(ps.analyses[1].analyses) == 2

    def test_overwrites_same_tool(self):
        ps = PropertyState()
        ps.record_analysis(
            property_id=1, address="100 Main St",
            tool_name="get_price_prediction", result_summary="$1.2M",
            conclusion=None, market_snapshot_at=1000.0,
        )
        ps.record_analysis(
            property_id=1, address="100 Main St",
            tool_name="get_price_prediction", result_summary="$1.3M",
            conclusion="updated", market_snapshot_at=2000.0,
        )
        assert len(ps.analyses[1].analyses) == 1
        assert ps.analyses[1].analyses["get_price_prediction"].result_summary == "$1.3M"


# ---------------------------------------------------------------------------
# PropertyState — get_stale_analyses
# ---------------------------------------------------------------------------


class TestPropertyStateStaleAnalyses:
    def _populated_state(self, snapshot_at: float = 1000.0) -> PropertyState:
        ps = PropertyState()
        # Market-sensitive tool
        ps.record_analysis(
            property_id=1, address="100 Main St",
            tool_name="get_price_prediction", result_summary="$1.2M",
            conclusion=None, market_snapshot_at=snapshot_at,
        )
        # Non-market-sensitive tool
        ps.record_analysis(
            property_id=1, address="100 Main St",
            tool_name="get_development_potential", result_summary="ADU eligible",
            conclusion=None, market_snapshot_at=snapshot_at,
        )
        return ps

    def test_no_stale_when_no_material_delta(self):
        ps = self._populated_state(snapshot_at=1000.0)
        delta = MarketDelta(rate_material=False, price_material=False, inventory_material=False)
        stale = ps.get_stale_analyses(current_snapshot_at=2000.0, material_delta=delta)
        assert stale == []

    def test_no_stale_when_delta_is_none(self):
        ps = self._populated_state(snapshot_at=1000.0)
        stale = ps.get_stale_analyses(current_snapshot_at=2000.0, material_delta=None)
        assert stale == []

    def test_stale_when_material_delta_and_old_snapshot(self):
        ps = self._populated_state(snapshot_at=1000.0)
        delta = MarketDelta(rate_material=True)
        stale = ps.get_stale_analyses(current_snapshot_at=2000.0, material_delta=delta)
        # Only market-sensitive tool should be stale
        assert len(stale) == 1
        prop_id, address, record = stale[0]
        assert prop_id == 1
        assert record.tool_name == "get_price_prediction"

    def test_not_stale_when_same_snapshot(self):
        ps = self._populated_state(snapshot_at=2000.0)
        delta = MarketDelta(rate_material=True)
        # Same snapshot_at — nothing is stale
        stale = ps.get_stale_analyses(current_snapshot_at=2000.0, material_delta=delta)
        assert stale == []

    def test_market_sensitive_tools_constant(self):
        """Verify the set of market-sensitive tools is what we expect."""
        expected = {
            "get_price_prediction",
            "estimate_sell_vs_hold",
            "estimate_rental_income",
            "analyze_investment_scenarios",
            "get_comparable_sales",
            "get_neighborhood_stats",
        }
        assert _MARKET_SENSITIVE_TOOLS == expected


# ---------------------------------------------------------------------------
# PropertyState — serialization
# ---------------------------------------------------------------------------


class TestPropertyStateSerialization:
    def test_empty_roundtrip(self):
        ps = PropertyState()
        restored = PropertyState.from_dict(ps.to_dict())
        assert restored.filter_intent is None
        assert restored.focus_property is None
        assert restored.analyses == {}

    def test_populated_roundtrip(self):
        ps = PropertyState(
            filter_intent=FilterIntent(
                criteria={"min_beds": 3},
                description="3+ beds",
                created_at=1000.0,
            ),
            focus_property=FocusProperty(
                property_id=42,
                address="123 Test St",
            ),
        )
        ps.record_analysis(
            property_id=42, address="123 Test St",
            tool_name="get_price_prediction", result_summary="$1.35M",
            conclusion="fair price", market_snapshot_at=1000.0,
        )

        d = ps.to_dict()
        restored = PropertyState.from_dict(d)
        assert restored.filter_intent.criteria["min_beds"] == 3
        assert restored.focus_property.property_id == 42
        assert 42 in restored.analyses
        assert restored.analyses[42].analyses["get_price_prediction"].conclusion == "fair price"

    def test_from_dict_skips_non_integer_keys(self):
        """Code review fix for #31: corrupt non-integer keys should be
        skipped rather than crashing deserialization."""
        data = {
            "analyses": {
                "42": {"property_id": 42, "address": "A", "analyses": {}},
                "not-an-int": {"property_id": 0, "address": "B", "analyses": {}},
                "": {"property_id": 0, "address": "C", "analyses": {}},
            },
        }
        ps = PropertyState.from_dict(data)
        # Valid key kept, invalid keys skipped
        assert 42 in ps.analyses
        assert len(ps.analyses) == 1
