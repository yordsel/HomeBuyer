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
        "name": "lookup_property",
        "description": (
            "Look up a Berkeley property by address. Returns property details "
            "from the citywide database including beds, baths, sqft, year built, "
            "lot size, zoning, neighborhood, and last sale info. Use this when "
            "the user mentions a specific address or asks about a property you "
            "don't already have context for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Street address to search for (e.g. '1234 Cedar St')",
                },
            },
            "required": ["address"],
        },
    },
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
    {
        "name": "estimate_rental_income",
        "description": (
            "Estimate rental income for a Berkeley property. Returns monthly/annual "
            "rent estimates, itemized operating expenses, mortgage analysis, cap rate, "
            "cash-on-cash return, and cash flow projections for a rent-as-is scenario. "
            "Use this when the user asks about rental income, what the property could "
            "rent for, monthly rent estimates, or landlord cash flow."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
                "down_payment_pct": {
                    "type": "number",
                    "description": "Down payment percentage (default 20)",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "analyze_investment_scenarios",
        "description": (
            "Run comprehensive investment scenario analysis comparing multiple "
            "strategies: rent as-is, add ADU, SB9 lot split, and multi-unit "
            "development. For each applicable scenario, provides cash flow "
            "projections over 1-20 years, mortgage analysis, tax benefits "
            "(depreciation, interest deduction), and key metrics (cap rate, "
            "cash-on-cash return, equity buildup). Integrates with development "
            "potential data for ADU feasibility and SB9 eligibility. "
            "Use this when the user asks about investment analysis, best scenario, "
            "ROI of adding an ADU vs renting as-is, development returns, or "
            "long-term investment comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "neighborhood": {"type": "string"},
                "beds": {"type": "number"},
                "baths": {"type": "number"},
                "sqft": {"type": "integer"},
                "year_built": {"type": "integer"},
                "lot_size_sqft": {"type": "integer"},
                "property_type": {"type": "string"},
                "down_payment_pct": {
                    "type": "number",
                    "description": "Down payment percentage (default 20)",
                },
                "self_managed": {
                    "type": "boolean",
                    "description": "Whether owner self-manages (no mgmt fee). Default true.",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool name → block type mapping for structured response blocks
# ---------------------------------------------------------------------------

TOOL_TO_BLOCK_TYPE: dict[str, str] = {
    "lookup_property": "property_detail",
    "get_price_prediction": "prediction_card",
    "get_comparable_sales": "comps_table",
    "get_neighborhood_stats": "neighborhood_stats",
    "get_development_potential": "development_potential",
    "get_improvement_simulation": "improvement_sim",
    "estimate_sell_vs_hold": "sell_vs_hold",
    "estimate_rental_income": "rental_income",
    "analyze_investment_scenarios": "investment_scenarios",
    "get_market_summary": "market_summary",
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Faketor, a witty and knowledgeable Berkeley real estate advisor AI. \
You help home buyers evaluate properties in Berkeley, California by pulling real data from \
the HomeBuyer analysis platform.

PERSONALITY:
- Friendly but direct — give clear opinions backed by data
- Sprinkle in light humor when appropriate (you're a "Faketor" after all)
- Use plain language, not jargon
- When you don't have data, say so honestly

CAPABILITIES (use your tools!):
- Property lookup: search any Berkeley property by address (17,000+ parcels in our database)
- Development potential: zoning, ADU, Middle Housing, SB 9 lot splitting
- Improvement ROI: ML-simulated value impact of renovations
- Comparable sales and neighborhood statistics
- Market-wide trends, mortgage rates, inventory
- Price prediction from the ML model
- Sell-vs-hold analysis with appreciation projections and rental yield estimates
- Rental income estimation with data-driven rent estimates and expense modeling
- Investment scenario comparison (as-is, ADU, SB9, multi-unit) with cash flow projections, \
mortgage analysis, and tax benefits

RULES:
- Always ground your advice in data from the tools — call them before answering
- If the user asks something you can answer with a tool, use it
- When the user mentions a specific address, use lookup_property first to get property details, \
then use those details when calling other tools
- You can call multiple tools in sequence — e.g. lookup_property → get_development_potential
- Do NOT provide specific investment advice or guaranteed returns
- Mention that your projections are estimates based on historical data
- Keep responses concise — 2-4 paragraphs max unless asked for detail
- Use dollar amounts and percentages to make your points concrete
- When discussing rental income, note that estimates use local price-to-rent ratios \
  and neighborhood data, but actual rents depend on condition, exact location, \
  and current market conditions
- For investment scenarios, compare the as-is scenario with the best development option \
  and highlight the trade-offs (capital required, timeline, risk)

CONTEXT:
You are the primary interface for the HomeBuyer app. Users may ask about any Berkeley property \
by address, or about the overall market. If property details (address, coordinates, etc.) are \
provided in the conversation context, use them when calling tools. If the user asks about a \
different property, use lookup_property to find it first."""


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
            {"reply": str, "tool_calls": list, "blocks": list} or {"error": str}
        """
        if not self._enabled or not self._client:
            return {"error": "Faketor is unavailable (no API key configured)"}

        # Build system prompt with property context
        system = SYSTEM_PROMPT + f"\n\nCURRENT PROPERTY CONTEXT:\n{json.dumps(property_context, indent=2)}"

        # Build messages: history + new user message
        messages = list(history) + [{"role": "user", "content": message}]

        tool_calls_log = []
        blocks = []  # Structured response blocks for frontend rendering

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
                        "blocks": blocks,
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
                        "blocks": blocks,
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

                    # Accumulate structured blocks for frontend rendering
                    block_type = TOOL_TO_BLOCK_TYPE.get(tool_block.name)
                    if block_type:
                        try:
                            result_data = json.loads(result_str)
                            if not isinstance(result_data, dict) or not result_data.get("error"):
                                blocks.append({
                                    "type": block_type,
                                    "tool_name": tool_block.name,
                                    "data": result_data,
                                })
                        except (json.JSONDecodeError, TypeError):
                            pass  # Skip blocks for non-JSON results

                messages.append({"role": "user", "content": tool_results})

            # If we hit max iterations, return what we have
            return {
                "reply": "I gathered a lot of data but hit my analysis limit. Could you ask a more specific question?",
                "tool_calls": tool_calls_log,
                "blocks": blocks,
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
