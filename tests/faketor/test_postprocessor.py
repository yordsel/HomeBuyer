"""Tests for PostProcessor — signal extraction and state promotion.

Phase E-7 (#51) of Epic #23.
"""

from unittest.mock import MagicMock

from homebuyer.services.faketor.classification import (
    FIRST_TIME_BUYER,
    STRETCHER,
    SegmentClassifier,
    SegmentResult,
)
import time

from homebuyer.services.faketor.extraction import ExtractionResult, SignalExtractor
from homebuyer.services.faketor.postprocessor import PostProcessor, PostProcessResult
from homebuyer.services.faketor.state.buyer import BuyerProfile, FieldSource
from homebuyer.services.faketor.state.context import ResearchContext
from homebuyer.services.faketor.state.market import BerkeleyWideMetrics, MarketSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(segment_id: str = STRETCHER) -> ResearchContext:
    ctx = ResearchContext(user_id="test-user")
    ctx.market = MarketSnapshot(
        mortgage_rate_30yr=6.5,
        berkeley_wide=BerkeleyWideMetrics(median_sale_price=1_300_000),
    )
    ctx.buyer.profile = BuyerProfile(intent="occupy", capital=100_000)
    ctx.buyer.segment_id = segment_id
    ctx.buyer.segment_confidence = 0.75
    return ctx


def _make_extractor(
    raw_extractions: dict[str, int | str | float | bool] | None = None,
) -> SignalExtractor:
    """Create mock extractor. raw_extractions maps field names to values;
    they are wrapped in (value, FieldSource) tuples for apply_extraction().
    """
    extractor = MagicMock(spec=SignalExtractor)
    if raw_extractions:
        # Convert raw values to the (value, FieldSource) tuple format
        formatted = {
            k: (v, FieldSource(
                source="extracted",
                confidence=0.8,
                evidence="test",
                extracted_at=time.time(),
            ))
            for k, v in raw_extractions.items()
        }
        mock_result = MagicMock(spec=ExtractionResult)
        mock_result.to_extractions.return_value = formatted
        extractor.extract_from_output.return_value = mock_result
    else:
        extractor.extract_from_output.return_value = None
    extractor.extract.return_value = None
    return extractor


def _make_classifier(
    segment_id: str = STRETCHER,
    confidence: float = 0.75,
) -> SegmentClassifier:
    classifier = MagicMock(spec=SegmentClassifier)
    classifier.classify.return_value = SegmentResult(
        segment_id=segment_id,
        confidence=confidence,
        reasoning="test",
        factor_coverage=0.5,
    )
    return classifier


# ---------------------------------------------------------------------------
# PostProcessResult tests
# ---------------------------------------------------------------------------


class TestPostProcessResult:
    def test_default_values(self):
        result = PostProcessResult()
        assert result.signals_extracted == 0
        assert result.segment_changed is False
        assert result.analyses_recorded == 0


# ---------------------------------------------------------------------------
# PostProcessor tests
# ---------------------------------------------------------------------------


class TestPostProcessor:
    def test_basic_process(self):
        processor = PostProcessor(_make_extractor(), _make_classifier())
        ctx = _make_context()
        result = processor.process(
            reply_text="Here's my analysis.",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        assert isinstance(result, PostProcessResult)

    def test_extracts_signals_from_output(self):
        extractor = _make_extractor(raw_extractions={"income": 200_000})
        processor = PostProcessor(extractor, _make_classifier())
        ctx = _make_context()
        result = processor.process(
            reply_text="Based on your $200k income...",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        extractor.extract_from_output.assert_called_once_with(
            "Based on your $200k income..."
        )
        assert result.signals_extracted == 1

    def test_no_extraction_on_empty_text(self):
        extractor = _make_extractor()
        processor = PostProcessor(extractor, _make_classifier())
        ctx = _make_context()
        processor.process(
            reply_text="",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        extractor.extract_from_output.assert_not_called()

    def test_reclassifies_after_extraction(self):
        classifier = _make_classifier()
        processor = PostProcessor(_make_extractor(), classifier)
        ctx = _make_context()
        processor.process(
            reply_text="Analysis done.",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        classifier.classify.assert_called_once()

    def test_segment_change_detected(self):
        # Start as STRETCHER, reclassify as FIRST_TIME_BUYER
        classifier = _make_classifier(FIRST_TIME_BUYER, 0.8)
        processor = PostProcessor(_make_extractor(), classifier)
        ctx = _make_context(segment_id=STRETCHER)
        result = processor.process(
            reply_text="Analysis done.",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        assert result.segment_changed is True
        assert result.previous_segment == STRETCHER
        assert result.new_segment == FIRST_TIME_BUYER

    def test_no_segment_change(self):
        classifier = _make_classifier(STRETCHER, 0.75)
        processor = PostProcessor(_make_extractor(), classifier)
        ctx = _make_context(segment_id=STRETCHER)
        result = processor.process(
            reply_text="Analysis done.",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        assert result.segment_changed is False

    def test_records_property_analyses(self):
        processor = PostProcessor(_make_extractor(), _make_classifier())
        ctx = _make_context()
        result = processor.process(
            reply_text="Done.",
            tool_calls=[
                {"name": "get_price_prediction", "input": {"address": "123 Main St"}},
                {"name": "get_comparable_sales", "input": {"address": "123 Main St"}},
            ],
            discussed_properties=[42],
            context=ctx,
        )
        assert result.analyses_recorded == 2
        assert result.properties_discussed == [42]
        assert ctx.property is not None
        assert 42 in ctx.property.analyses

    def test_ignores_non_analysis_tools(self):
        processor = PostProcessor(_make_extractor(), _make_classifier())
        ctx = _make_context()
        result = processor.process(
            reply_text="Done.",
            tool_calls=[
                {"name": "search_properties", "input": {}},
                {"name": "get_market_summary", "input": {}},
            ],
            discussed_properties=[42],
            context=ctx,
        )
        assert result.analyses_recorded == 0

    def test_creates_property_state_if_missing(self):
        processor = PostProcessor(_make_extractor(), _make_classifier())
        ctx = _make_context()
        ctx.property = None
        processor.process(
            reply_text="Done.",
            tool_calls=[
                {"name": "get_price_prediction", "input": {"address": "123 Main"}},
            ],
            discussed_properties=[42],
            context=ctx,
        )
        assert ctx.property is not None

    def test_extraction_failure_nonfatal(self):
        extractor = _make_extractor()
        extractor.extract_from_output.side_effect = RuntimeError("boom")
        processor = PostProcessor(extractor, _make_classifier())
        ctx = _make_context()
        result = processor.process(
            reply_text="Analysis.",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        # Should complete without error
        assert result.signals_extracted == 0

    def test_classification_failure_nonfatal(self):
        classifier = _make_classifier()
        classifier.classify.side_effect = RuntimeError("boom")
        processor = PostProcessor(_make_extractor(), classifier)
        ctx = _make_context()
        result = processor.process(
            reply_text="Analysis.",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        # Should complete without error
        assert isinstance(result, PostProcessResult)

    def test_no_tool_calls_no_properties(self):
        processor = PostProcessor(_make_extractor(), _make_classifier())
        ctx = _make_context()
        result = processor.process(
            reply_text="Hello.",
            tool_calls=[],
            discussed_properties=[],
            context=ctx,
        )
        assert result.analyses_recorded == 0
        assert result.properties_discussed == []
