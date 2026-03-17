"""Tests for SignalExtractor.

Uses a mock Anthropic client to test extraction logic without real API calls.
Tests cover prompt construction, response parsing, error handling, and
conversion to BuyerProfile extraction format.

Phase C-4 (#35) of Epic #23.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from homebuyer.services.faketor.extraction import (
    ExtractionResult,
    SignalExtractor,
    _safe_bool,
    _safe_int,
)
from homebuyer.services.faketor.state.buyer import BuyerProfile, Signal


# ---------------------------------------------------------------------------
# Mock Anthropic client
# ---------------------------------------------------------------------------


@dataclass
class MockTextBlock:
    text: str
    type: str = "text"


@dataclass
class MockResponse:
    content: list[MockTextBlock]


def _mock_client(response_json: dict[str, Any]) -> MagicMock:
    """Create a mock Anthropic client that returns the given JSON."""
    client = MagicMock()
    client.messages.create.return_value = MockResponse(
        content=[MockTextBlock(text=json.dumps(response_json))]
    )
    return client


def _mock_client_text(text: str) -> MagicMock:
    """Create a mock client that returns raw text."""
    client = MagicMock()
    client.messages.create.return_value = MockResponse(
        content=[MockTextBlock(text=text)]
    )
    return client


def _mock_client_error() -> MagicMock:
    """Create a mock client that raises an exception."""
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API error")
    return client


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------


class TestExtractionResult:
    def test_empty_result(self):
        r = ExtractionResult()
        assert r.is_empty() is True

    def test_non_empty_with_intent(self):
        r = ExtractionResult(intent="occupy")
        assert r.is_empty() is False

    def test_non_empty_with_signals_only(self):
        r = ExtractionResult(
            signals=[Signal(evidence="test", implication="test", confidence=0.5)]
        )
        assert r.is_empty() is False

    def test_to_extractions_empty(self):
        r = ExtractionResult()
        assert r.to_extractions() == {}

    def test_to_extractions_with_fields(self):
        r = ExtractionResult(
            intent="invest",
            capital=500_000,
            signals=[
                Signal(
                    evidence="I have $500k saved",
                    implication="capital",
                    confidence=0.9,
                ),
                Signal(
                    evidence="I want to rent it out",
                    implication="invest intent",
                    confidence=0.85,
                ),
            ],
        )
        extractions = r.to_extractions()
        assert "intent" in extractions
        assert "capital" in extractions
        assert extractions["intent"][0] == "invest"
        assert extractions["capital"][0] == 500_000

    def test_to_extractions_default_confidence(self):
        """Fields without matching signals get default 0.7 confidence."""
        r = ExtractionResult(income=150_000, signals=[])
        extractions = r.to_extractions()
        assert "income" in extractions
        _, source = extractions["income"]
        assert source.confidence == 0.7


# ---------------------------------------------------------------------------
# SignalExtractor — extract from user message
# ---------------------------------------------------------------------------


class TestExtractUserMessage:
    def test_basic_extraction(self):
        client = _mock_client({
            "intent": "occupy",
            "capital": 300_000,
            "income": 200_000,
            "signals": [
                {
                    "evidence": "I want to buy my first home",
                    "implication": "occupy intent, first time buyer",
                    "confidence": 0.95,
                },
                {
                    "evidence": "I have about $300k saved",
                    "implication": "capital of $300k",
                    "confidence": 0.9,
                },
            ],
        })

        extractor = SignalExtractor(client)
        result = extractor.extract("I want to buy my first home. I have about $300k saved.")

        assert result.intent == "occupy"
        assert result.capital == 300_000
        assert result.income == 200_000
        assert len(result.signals) == 2
        assert result.extraction_time_ms > 0

    def test_empty_message_returns_empty(self):
        client = _mock_client({})
        extractor = SignalExtractor(client)
        result = extractor.extract("")
        assert result.is_empty()
        # Client should not have been called
        client.messages.create.assert_not_called()

    def test_whitespace_message_returns_empty(self):
        client = _mock_client({})
        extractor = SignalExtractor(client)
        result = extractor.extract("   ")
        assert result.is_empty()
        client.messages.create.assert_not_called()

    def test_null_fields_ignored(self):
        client = _mock_client({
            "intent": "occupy",
            "capital": None,
            "equity": None,
            "income": None,
            "signals": [],
        })
        extractor = SignalExtractor(client)
        result = extractor.extract("I want to buy a home")
        assert result.intent == "occupy"
        assert result.capital is None

    def test_profile_context_included_in_prompt(self):
        client = _mock_client({"signals": []})
        extractor = SignalExtractor(client)

        profile = BuyerProfile(intent="occupy", capital=200_000)
        extractor.extract("Tell me about the market", current_profile=profile)

        # Verify the prompt includes profile context
        call_args = client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "CURRENT BUYER PROFILE" in user_content
        assert "200000" in user_content

    def test_prior_signals_included_in_prompt(self):
        client = _mock_client({"signals": []})
        extractor = SignalExtractor(client)

        prior = [Signal(evidence="I rent", implication="no_ownership", confidence=0.8)]
        extractor.extract("How much can I afford?", prior_signals=prior)

        call_args = client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "PRIOR SIGNALS" in user_content
        assert "I rent" in user_content


# ---------------------------------------------------------------------------
# SignalExtractor — extract from LLM output
# ---------------------------------------------------------------------------


class TestExtractFromOutput:
    def test_basic_output_extraction(self):
        client = _mock_client({
            "is_first_time_buyer": True,
            "signals": [
                {
                    "evidence": "So you're looking for your first home",
                    "implication": "first_time_buyer confirmed",
                    "confidence": 0.8,
                },
            ],
        })
        extractor = SignalExtractor(client)
        result = extractor.extract_from_output(
            "So you're looking for your first home — great!"
        )
        assert result.is_first_time_buyer is True

    def test_empty_output_returns_empty(self):
        client = _mock_client({})
        extractor = SignalExtractor(client)
        result = extractor.extract_from_output("")
        assert result.is_empty()
        client.messages.create.assert_not_called()

    def test_prompt_labels_output_differently(self):
        """LLM response extraction uses different label than user message."""
        client = _mock_client({"signals": []})
        extractor = SignalExtractor(client)
        extractor.extract_from_output("Based on your budget of $500k...")

        call_args = client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "LLM RESPONSE" in user_content


# ---------------------------------------------------------------------------
# Response parsing edge cases
# ---------------------------------------------------------------------------


class TestResponseParsing:
    def test_markdown_code_block_stripped(self):
        """Handles ```json ... ``` wrapper."""
        raw = '```json\n{"intent": "invest", "signals": []}\n```'
        client = _mock_client_text(raw)
        extractor = SignalExtractor(client)
        result = extractor.extract("I want a rental property")
        assert result.intent == "invest"

    def test_invalid_json_returns_empty(self):
        client = _mock_client_text("This is not JSON at all")
        extractor = SignalExtractor(client)
        result = extractor.extract("Tell me about homes")
        assert result.is_empty()

    def test_api_error_returns_empty(self):
        client = _mock_client_error()
        extractor = SignalExtractor(client)
        result = extractor.extract("I want to buy a home")
        assert result.is_empty()
        assert result.extraction_time_ms > 0

    def test_boolean_string_conversion(self):
        """Handles string booleans from LLM."""
        client = _mock_client({
            "owns_current_home": True,
            "is_first_time_buyer": False,
            "signals": [],
        })
        extractor = SignalExtractor(client)
        result = extractor.extract("I own a condo and am buying my second home")
        assert result.owns_current_home is True
        assert result.is_first_time_buyer is False

    def test_string_numbers_converted(self):
        """Handles string numbers from LLM."""
        client = _mock_client({
            "capital": "500000",
            "income": "200000.5",
            "signals": [],
        })
        extractor = SignalExtractor(client)
        result = extractor.extract("I have $500k saved and make $200k")
        assert result.capital == 500_000
        assert result.income == 200_000

    def test_bad_signal_items_skipped(self):
        """Non-dict signal items are skipped."""
        client = _mock_client({
            "signals": [
                {"evidence": "good", "implication": "test", "confidence": 0.8},
                "not a dict",
                42,
                None,
            ],
        })
        extractor = SignalExtractor(client)
        result = extractor.extract("test message")
        assert len(result.signals) == 1


# ---------------------------------------------------------------------------
# Safe conversion helpers
# ---------------------------------------------------------------------------


class TestSafeConversions:
    def test_safe_int_none(self):
        assert _safe_int(None) is None

    def test_safe_int_valid(self):
        assert _safe_int(42) == 42
        assert _safe_int("42") == 42
        assert _safe_int(42.9) == 42

    def test_safe_int_invalid(self):
        assert _safe_int("not a number") is None
        assert _safe_int([]) is None

    def test_safe_bool_none(self):
        assert _safe_bool(None) is None

    def test_safe_bool_bool(self):
        assert _safe_bool(True) is True
        assert _safe_bool(False) is False

    def test_safe_bool_string(self):
        assert _safe_bool("true") is True
        assert _safe_bool("yes") is True
        assert _safe_bool("false") is False
        assert _safe_bool("no") is False

    def test_safe_bool_other(self):
        assert _safe_bool(42) is None
        assert _safe_bool([]) is None
