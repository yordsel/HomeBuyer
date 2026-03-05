"""Faketor — AI real estate advisor chat powered by Claude with tool use.

Faketor uses Claude's tool-use capability to call existing HomeBuyer APIs
(development potential, improvement simulation, comps, market data, neighborhood
stats) and synthesize property-specific recommendations including sell-vs-hold
analysis.
"""

import json
import logging
from typing import Optional

from homebuyer.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions for Claude
# ---------------------------------------------------------------------------

FAKETOR_TOOLS = [
    {
        "name": "get_development_potential",
        "description": (
            "Get zoning details, ADU feasibility, Middle Housing eligibility, "
            "SB 9 lot-split eligibility, and BESO energy status for a Berkeley property. "
            "Use this when the user asks about what can be built on the property, "
            "zoning rules, adding units, or development upside."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Property latitude"},
                "longitude": {"type": "number", "description": "Property longitude"},
                "address": {"type": "string", "description": "Street address"},
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_improvement_simulation",
        "description": (
            "Simulate the effect of home improvements (kitchen, bathroom, ADU, solar, etc.) "
            "on predicted property value using the ML model. Returns per-category cost, "
            "predicted value delta, ROI, and market correlation data. "
            "Use this when the user asks about renovations, improvements, ROI on upgrades, "
            "or what improvements are worth doing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "address": {"type": "string"},
                "neighborhood": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_comparable_sales",
        "description": (
            "Find recent comparable property sales in the same neighborhood. "
            "Returns sale prices, dates, and property details for similar homes. "
            "Use this when the user asks about recent sales, what similar homes sold for, "
            "or market comps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "neighborhood": {"type": "string", "description": "Berkeley neighborhood name"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
            },
            "required": ["neighborhood"],
        },
    },
    {
        "name": "get_neighborhood_stats",
        "description": (
            "Get neighborhood-level statistics: median/avg price, price per sqft, "
            "year-over-year price change, sale count, dominant zoning, property types. "
            "Use this when the user asks about a neighborhood's market, price trends, "
            "or how the area compares."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "neighborhood": {"type": "string", "description": "Berkeley neighborhood name"},
                "years": {"type": "integer", "description": "Lookback years (default 2)"},
            },
            "required": ["neighborhood"],
        },
    },
    {
        "name": "get_market_summary",
        "description": (
            "Get Berkeley-wide market summary: current median prices, sale-to-list ratio, "
            "days on market, mortgage rates, inventory, price distribution, "
            "top neighborhoods by price. Use this when the user asks about the "
            "overall Berkeley market, trends, or timing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_price_prediction",
        "description": (
            "Get the ML model's predicted sale price for the property, including "
            "confidence interval and feature contributions. Use this when the user "
            "asks what the property is worth, its estimated value, or wants a price opinion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "zip_code": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
            },
            "required": ["latitude", "longitude", "neighborhood"],
        },
    },
    {
        "name": "estimate_sell_vs_hold",
        "description": (
            "Estimate whether to sell now or hold the property for 1, 3, or 5 years. "
            "Uses the ML price prediction, neighborhood year-over-year appreciation, "
            "and market conditions to project future value. Also estimates rough rental "
            "yield based on Berkeley price-to-rent ratios. "
            "Use this when the user asks about selling vs renting, hold period, "
            "investment timeline, or whether to sell now."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "zip_code": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
            },
            "required": ["latitude", "longitude", "neighborhood"],
        },
    },
]

SYSTEM_PROMPT = """You are Faketor, a witty and knowledgeable Berkeley real estate advisor AI. \
You help home buyers evaluate properties in Berkeley, California by pulling real data from \
the HomeBuyer analysis platform.

PERSONALITY:
- Friendly but direct — give clear opinions backed by data
- Sprinkle in light humor when appropriate (you're a "Faketor" after all)
- Use plain language, not jargon
- When you don't have data, say so honestly

CAPABILITIES (use your tools!):
- Development potential: zoning, ADU, Middle Housing, SB 9 lot splitting
- Improvement ROI: ML-simulated value impact of renovations
- Comparable sales and neighborhood statistics
- Market-wide trends, mortgage rates, inventory
- Price prediction from the ML model
- Sell-vs-hold analysis with appreciation projections and rental yield estimates

RULES:
- Always ground your advice in data from the tools — call them before answering
- If the user asks something you can answer with a tool, use it
- Do NOT provide specific investment advice or guaranteed returns
- Mention that your projections are estimates based on historical data
- Keep responses concise — 2-4 paragraphs max unless asked for detail
- Use dollar amounts and percentages to make your points concrete
- When discussing sell vs rent, always mention that rental estimates are rough \
  (based on typical Berkeley price-to-rent ratios, not actual rental comps)

CONTEXT:
The user is looking at a specific property on the Development Potential page. \
Property details (address, coordinates, etc.) are provided in the conversation context. \
Use these details when calling tools — do NOT ask the user for coordinates or addresses."""


class FaketorService:
    """Chat service that wraps Claude with real estate analysis tools."""

    def __init__(self) -> None:
        self._client = None
        self._enabled = bool(ANTHROPIC_API_KEY)

        if self._enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception as e:
                logger.warning("Failed to initialize Anthropic client for Faketor: %s", e)
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def chat(
        self,
        message: str,
        history: list[dict],
        property_context: dict,
        tool_executor,
    ) -> dict:
        """Run a single chat turn with tool use.

        Args:
            message: The user's new message.
            history: Previous messages [{role, content}, ...].
            property_context: Property details (lat, lon, address, neighborhood, etc.).
            tool_executor: Callable(tool_name, tool_input) -> str that executes tools.

        Returns:
            {"reply": str, "tool_calls": list[dict]} or {"error": str}
        """
        if not self._enabled or not self._client:
            return {"error": "Faketor is unavailable (no API key configured)"}

        # Build system prompt with property context
        system = SYSTEM_PROMPT + f"\n\nCURRENT PROPERTY CONTEXT:\n{json.dumps(property_context, indent=2)}"

        # Build messages: history + new user message
        messages = list(history) + [{"role": "user", "content": message}]

        tool_calls_log = []

        try:
            # Agentic loop: keep going until Claude stops calling tools
            max_iterations = 6
            for _ in range(max_iterations):
                response = self._client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    system=system,
                    tools=FAKETOR_TOOLS,
                    messages=messages,
                )

                # If Claude is done, extract text
                if response.stop_reason == "end_turn":
                    text_parts = [
                        b.text for b in response.content if b.type == "text"
                    ]
                    return {
                        "reply": "\n".join(text_parts),
                        "tool_calls": tool_calls_log,
                    }

                # Extract tool use blocks
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    # No tools and not end_turn — extract whatever text we have
                    text_parts = [
                        b.text for b in response.content if b.type == "text"
                    ]
                    return {
                        "reply": "\n".join(text_parts) if text_parts else "I'm not sure how to help with that.",
                        "tool_calls": tool_calls_log,
                    }

                # Append assistant response (with tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Execute tools and collect results
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_calls_log.append({
                        "name": tool_block.name,
                        "input": tool_block.input,
                    })
                    try:
                        result_str = tool_executor(tool_block.name, tool_block.input)
                    except Exception as e:
                        logger.warning("Tool %s failed: %s", tool_block.name, e)
                        result_str = json.dumps({"error": str(e)})

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result_str,
                    })

                messages.append({"role": "user", "content": tool_results})

            # If we hit max iterations, return what we have
            return {
                "reply": "I gathered a lot of data but hit my analysis limit. Could you ask a more specific question?",
                "tool_calls": tool_calls_log,
            }

        except Exception as e:
            error_str = str(e).lower()
            logger.warning("Faketor chat failed: %s", e, exc_info=True)
            if "rate_limit" in error_str or "429" in str(e):
                return {"error": "Faketor is temporarily busy (rate limited). Try again in a moment."}
            elif "authentication" in error_str or "401" in str(e):
                return {"error": "Faketor is unavailable (invalid API key)"}
            else:
                return {"error": f"Faketor encountered an error: {type(e).__name__}"}
