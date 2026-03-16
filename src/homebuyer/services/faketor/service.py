"""Faketor — AI real estate advisor chat powered by Claude with tool use.

Faketor uses Claude's tool-use capability to call existing HomeBuyer APIs
(development potential, improvement simulation, comps, market data, neighborhood
stats) and synthesize property-specific recommendations including sell-vs-hold
analysis.
"""

import json
import logging

from homebuyer.config import ANTHROPIC_API_KEY
from homebuyer.services.faketor.accumulator import AnalysisAccumulator
from homebuyer.services.faketor.facts import compute_facts_for_tool
from homebuyer.services.faketor.tools import registry
from homebuyer.utils.serialization import safe_json_dumps

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_CLAUDE_MODEL = "claude-sonnet-4-20250514"
_MAX_ITERATIONS = 12
_FALLBACK_REPLY = "Here's what I found based on my analysis so far."

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
- Property search: find properties by neighborhood, zoning, lot size, price, beds/baths, \
  year built, ADU eligibility, or SB9 eligibility — compare development opportunities across \
  multiple properties at once
- Development potential: zoning, ADU, Middle Housing, SB 9 lot splitting
- Improvement ROI: ML-simulated value impact of renovations
- Comparable sales and neighborhood statistics
- Market-wide trends, mortgage rates, inventory
- Price prediction from the ML model
- Sell-vs-hold analysis with appreciation projections and rental yield estimates
- Rental income estimation with data-driven rent estimates and expense modeling
- Investment scenario comparison (as-is, ADU, SB9, multi-unit) with cash flow projections, \
mortgage analysis, and tax benefits
- Permit history: look up building permits filed for any property — see renovations, \
  construction work, job values, and filing dates
- Database queries: answer ad-hoc analytical questions by querying the database directly — \
  counts, averages, distributions, filtering, grouping across 17,000+ properties
- Regulations knowledge base: look up Berkeley zoning definitions, ADU/JADU rules, \
  SB 9 lot splitting, Middle Housing Ordinance, BESO energy requirements, transfer tax \
  rates, rent control, permitting, and hillside overlay restrictions
- Glossary knowledge base: look up definitions of financial terms (LTV, DTI, cap rate, \
  NOI, 1031 exchange, Prop 13, etc.), real estate terms (contingency, comps, CMA, DOM, \
  escrow, etc.), loan programs (FHA, VA, CalHFA), and construction terms (setback, FAR, \
  lot coverage) — all with Berkeley-specific context

REGULATIONS KNOWLEDGE BASE:
You have a lookup_regulation tool with authoritative Berkeley regulatory knowledge including \
all 32+ zoning code definitions (R-1, R-1H, R-2, R-2A, R-2AH, C-SA, C-W, MUR, ES-R, etc.), \
ADU/JADU rules, SB 9 lot splitting, Middle Housing Ordinance (effective Nov 2025), BESO energy \
requirements, transfer tax rates, rent control, permitting processes, and hillside overlay \
restrictions. Use lookup_regulation BEFORE telling users to check the municipal code. For \
property-specific zoning analysis, use get_development_potential instead.

GLOSSARY KNOWLEDGE BASE:
You have a lookup_glossary_term tool with 70+ financial and real estate term definitions, \
all with Berkeley-specific context. Categories: mortgage (LTV, DTI, PITI, PMI, ARM), \
investment_metrics (cap rate, NOI, GRM, cash-on-cash, IRR, DSCR), tax (Prop 13, 1031, \
Section 121, depreciation, capital gains), loan_programs (FHA, VA, conventional, CalHFA), \
closing_costs (title insurance, escrow, transfer tax), property_types (SFR, condo, TIC, \
duplex), transaction (contingency, earnest money, disclosures, offer review), valuation \
(CMA, comps, price per sqft, appraisal gap), construction (setback, FAR, lot coverage), \
and market (DOM, months of supply, absorption rate). Use lookup_glossary_term when:
- A user asks "what is X" for any financial or real estate concept
- You use jargon in your response that the user might not understand
- Your tool results contain metrics (cap rate, cash-on-cash, GRM) and the user seems unfamiliar
- A user asks about loan programs, closing costs, or tax implications

RULES:
- Always ground your advice in data from the tools — call them before answering
- If the user asks something you can answer with a tool, use it
- When the user mentions a specific address, use lookup_property first to get property details, \
then use those details when calling other tools
- You can call multiple tools in sequence — e.g. lookup_property → get_development_potential
- Do NOT provide specific investment advice or guaranteed returns
- Mention that your projections are estimates based on historical data
- When the user asks to find or search for properties matching criteria (e.g. "find large lots \
  in North Berkeley zoned R-1"), use search_properties — do NOT use lookup_property for that
- When comparing development opportunities across properties, use search_properties first to \
  find candidates, then optionally drill into specific properties with get_development_potential \
  or analyze_investment_scenarios
- IMPORTANT: When following up on search_properties results with get_development_potential, \
  ALWAYS pass the property_id from the search results. This ensures the exact correct property \
  is looked up. Without property_id, lat/lon proximity matching may return data from a \
  neighboring property in a different zone, causing incorrect results.
- When the user asks about permit history, renovations, or construction work on a property, \
  use lookup_permits with the property address
- When the user asks aggregate or analytical questions (counts, averages, distributions, \
  "how many", "what percentage", "which neighborhoods have the most"), use query_database \
  to write and execute a SQL query. This is much better than trying to use search_properties \
  with filters and counting the results manually
- Keep responses concise — 2-4 paragraphs max unless asked for detail
- Use dollar amounts and percentages to make your points concrete
- Tool responses include pre-computed *_note fields (price_note, sale_to_list_note, \
  roi_note, equity_note). Always use these notes verbatim when presenting the \
  corresponding metrics — they contain the correct interpretation
- When discussing rental income, note that estimates use local price-to-rent ratios \
  and neighborhood data, but actual rents depend on condition, exact location, \
  and current market conditions
- For investment scenarios, compare the as-is scenario with the best development option \
  and highlight the trade-offs (capital required, timeline, risk)
- IMPORTANT: NEVER call per-property analysis tools (get_price_prediction, \
  analyze_investment_scenarios, get_development_potential, estimate_rental_income, \
  get_comparable_sales, estimate_sell_vs_hold) in a loop for multiple properties. You have \
  a limited iteration budget and will run out before finishing, leaving the user with an \
  incomplete answer. Instead:
  • For "which have the best investment potential" or ranking questions: use query_database \
    to rank properties using the precomputed_scenarios table (see PRECOMPUTED ANALYSIS DATA \
    below), then optionally drill into the top 2-3 individually
  • For comprehensive multi-property reports: use generate_investment_prospectus with \
    from_working_set=true — it handles batch analysis internally
  • For aggregate statistics across the working set: use query_database with the _working_set \
    temp table
- When the user asks for an "investment prospectus", "property report", or "comprehensive \
  investment summary", use generate_investment_prospectus. This tool aggregates valuation, \
  market data, development potential, rental scenarios, comps, and risk factors into a single \
  professional report with charts, narratives, and a recommended strategy
- generate_investment_prospectus supports three multi-property modes:
  - "curated" (1-10 diverse properties): portfolio overview with allocation charts and per-property analysis
  - "similar" (2-10 alike properties): side-by-side comparison highlighting shared traits and differences
  - "thesis" (10+ properties): investment thesis with statistics and representative example properties
- The mode is auto-detected based on property count and similarity, but you can override it \
  with the mode parameter. If the user's intent is ambiguous (e.g. "make a prospectus for \
  these 5 properties"), ask whether they want a portfolio overview (curated) or a comparison \
  (similar) — offer option buttons
- Use from_working_set=true when the user wants a prospectus for "these properties", "the \
  current results", or "my working set". This pulls properties directly from the session \
  working set populated by previous search_properties or query_database calls
- generate_investment_prospectus is a heavyweight tool — it calls multiple analysis modules \
  internally. Only use it when the user specifically wants a comprehensive report, not for \
  quick questions about a single metric. For thesis mode with 10+ properties, only 3-5 \
  example properties get full analysis; the rest contribute to aggregate statistics

DATA MODEL:
The properties table distinguishes between physical lots and sellable units:
- record_type='lot': Physical lots — SFR, duplexes, triplexes, fourplexes, apartments. \
  lot_size_sqft is the actual lot. Development potential analysis applies to these.
- record_type='unit': Sellable units within a larger lot — condos, co-ops. \
  lot_size_sqft is the SHARED lot size for all units on the lot. Use lot_group_key \
  to find all units sharing the same physical lot.
- property_category provides granular classification: sfr, duplex, triplex, fourplex, \
  apartment, condo, townhouse, pud, coop, land, mixed_use.
- When a user asks about development potential for a condo unit, explain that it's a unit \
  within a larger lot and analyze the lot as a whole (the system does this automatically).
- For development opportunity searches, filter to record_type='lot' to exclude individual \
  condo units that can't be independently developed.

COMPUTED vs STORED FIELDS:
- Development eligibility (adu_eligible, sb9_eligible, effective_max_units, \
  middle_housing_eligible) are COMPUTED at runtime by the development calculator. \
  They are NOT columns in the properties table.
- To filter or count by development eligibility, use search_properties with \
  adu_eligible=true or sb9_eligible=true — NEVER use query_database with these fields.
- When the user asks "which of these are ADU-eligible?" about the working set, use \
  search_properties with adu_eligible=true and any other active filters to get the subset.
- search_properties results include a development.adu_eligible field in each result.

DATA ACCURACY RULES:
- Every tool result includes a "_facts" section with pre-computed, verified statistics. \
  ALWAYS use _facts for counts, ranges, and eligibility flags instead of computing your own.
- When stating how many properties match a criterion (e.g. "6 of 10 are ADU eligible"), \
  use the exact count from _facts. NEVER say "all N properties" unless _facts confirms \
  the count equals N.
- A VERIFIED DATA SUMMARY may appear in your context with cross-tool facts. \
  Reference it for any claim that spans multiple tool calls.
- Never invent appreciation rates, market percentages, or price trends not in tool results. \
  If data isn't available, say "I don't have data on that."
- Reference properties by address, never by list position ("the first property").
- When comparing properties across tool calls, use the VERIFIED DATA SUMMARY rather than \
  trying to recall earlier tool results from memory.

WORKING SET RULES:
When a session working set is active (shown in "PROPERTY WORKING SET" above), it contains the \
current universe of properties the user is discussing. Follow these rules:
- "these", "those", "the current set", "the results" refer to the properties in the working set
- Use update_working_set for ALL operations that change which properties are in scope: \
  new searches (mode=replace), sub-filters (mode=narrow), adding properties (mode=expand). \
  The system automatically sends updated sidebar data to the frontend after each call.
- For ADU/SB9 eligibility filtering, use update_working_set with adu_eligible=true or \
  sb9_eligible=true — this works in all three modes (replace, narrow, expand).
- Use query_database ONLY for pure analytics (counts, averages, distributions, groupings) \
  that do NOT change which properties are in the working set.
- When the user says "go back", "undo that", "remove the last filter", use undo_filter.
- If the user asks about a specific property, use lookup_property or other per-property tools.
- IMPORTANT: Always call update_working_set even if the working set descriptor seems to \
  contain the answer. The descriptor is a summary for your context — the frontend needs \
  tool calls to update the sidebar.

PRECOMPUTED ANALYSIS DATA:
The database has a precomputed_scenarios table with cached investment analysis for ALL properties. \
Use query_database to rank and compare properties across the entire working set in a SINGLE \
query — never loop per-property tools.
IMPORTANT: When the user asks about a property's current value, worth, or "most valuable", \
use json_extract(ps.prediction_json, '$.predicted_price') from precomputed_scenarios — NOT \
last_sale_price from properties. last_sale_price is the HISTORICAL sale price (possibly years \
old) and does NOT reflect current market value. predicted_price is the ML model's estimate \
of what the property would sell for today.
The table columns:
- property_id (INTEGER) — joins to properties.id
- scenario_type (TEXT) — use 'buyer'
- prediction_json (TEXT) — JSON: {predicted_price, confidence_pct}
- rental_json (TEXT) — JSON: {scenarios: [{scenario_name, cap_rate_pct, cash_on_cash_pct, \
  monthly_cash_flow, gross_rent_multiplier, total_monthly_rent, ...}], \
  best_scenario: "name string", not_applicable: 0|1}. \
  scenarios[0] is always "Rent As-Is". best_scenario is the NAME of the highest-return scenario.
- potential_json (TEXT) — JSON: {adu: {eligible: 0|1}, sb9: {eligible: 0|1}, effective_max_units}

Key json_extract paths:
  json_extract(ps.prediction_json, '$.predicted_price')
  json_extract(ps.rental_json, '$.scenarios[0].cap_rate_pct')     -- as-is cap rate
  json_extract(ps.rental_json, '$.scenarios[0].cash_on_cash_pct') -- as-is cash-on-cash
  json_extract(ps.rental_json, '$.scenarios[0].monthly_cash_flow') -- as-is cash flow
  json_extract(ps.rental_json, '$.scenarios[0].total_monthly_rent') -- as-is rent
  json_extract(ps.rental_json, '$.best_scenario')                 -- best scenario name
  json_extract(ps.potential_json, '$.adu.eligible')
  json_extract(ps.potential_json, '$.sb9.eligible')
  json_extract(ps.potential_json, '$.effective_max_units')

Example — Rank working set by investment potential (single query, all properties):
  SELECT p.id, p.address, p.last_sale_price, p.lot_size_sqft, p.zoning_class,
         json_extract(ps.prediction_json, '$.predicted_price') as pred_price,
         json_extract(ps.rental_json, '$.scenarios[0].cap_rate_pct') as cap_rate,
         json_extract(ps.rental_json, '$.scenarios[0].monthly_cash_flow') as monthly_cf,
         json_extract(ps.rental_json, '$.best_scenario') as best_scenario,
         json_extract(ps.potential_json, '$.adu.eligible') as adu_ok,
         json_extract(ps.potential_json, '$.sb9.eligible') as sb9_ok
  FROM _working_set ws
  JOIN properties p ON ws.property_id = p.id
  LEFT JOIN precomputed_scenarios ps ON p.id = ps.property_id AND ps.scenario_type = 'buyer'
  ORDER BY json_extract(ps.rental_json, '$.scenarios[0].cap_rate_pct') DESC
  LIMIT 10

This queries ALL properties in the working set in ONE tool call. After identifying top candidates, \
you can drill into 2-3 specific properties with per-property tools for detailed analysis.

DATA QUALITY AWARENESS:
- About 232 Multi-Family 5+ properties have PER-UNIT assessor features (sqft, beds, baths \
  reflect one unit) but WHOLE-BUILDING sale prices and lot sizes. This creates misleading \
  metrics like extremely low building-to-lot ratios or extremely high price-per-sqft.
- When searching for development opportunities, underdeveloped properties, or density analysis, \
  EXCLUDE per-unit mismatch records using: WHERE building_sqft / NULLIF(sqft, 0) <= 3 \
  OR building_sqft IS NULL
- search_properties results include a data_quality field. When presenting results, note any \
  properties flagged with data quality issues (per_unit_mismatch or mf5_limited_data).
- For building density or building-to-lot ratio calculations, ALWAYS use building_sqft (total \
  building footprint), never sqft (per-unit living area).
- The building_to_lot_ratio field in search results is pre-computed using the correct \
  building_sqft column — use it directly instead of computing your own ratio.

SEARCH RESULT PRESENTATION:
- When search_properties returns results, ALWAYS state how many you're showing vs how many \
  total match. Say "Here are 25 of 88 matching properties" NOT "Here are all 25 properties".
- The _facts.total_matching field tells you the true count. If total_matching > the number \
  of results returned, mention that more exist and the user can refine or you can query_database \
  for the full set.
- Never say "all X properties" unless the returned count equals total_matching.

OWNER CONTEXT RULES:
When a user says they OWN a property, BOUGHT it, or refers to it as "my property/house":
1. Use lookup_property to get the property's last_sale_price and last_sale_date
2. Pass purchase_price from the user's stated price OR from last_sale_price if they didn't specify
3. Pass purchase_date from the user's stated date OR from last_sale_date
4. Pass mortgage_rate if the user mentions their actual rate (e.g., "I got a 3.25% rate")
5. These owner-context values ensure that investment cards show ACTUAL mortgage payments \
   (based on what they paid), not hypothetical numbers based on today's market value
6. Property tax under CA Prop 13 is assessed on purchase price, so this is important for accuracy
7. If the user gives a current value estimate, pass it as current_value_override

PROPERTY TYPE ANALYSIS RULES:
When analyzing a property, always consider its property_category (shown in the CURRENT PROPERTY \
CONTEXT) before recommending or running analyses. The backend enforces guardrails, but you should \
also frame your responses appropriately:

**Single-Family Residential (sfr):**
- Full analysis suite: price prediction, comps, development potential (ADU, SB9, lot split), \
  improvement ROI, rental income, all investment scenarios.

**Duplex / Triplex / Fourplex:**
- All analyses EXCEPT SB9 lot splitting (SB9 only applies to single-family in R-1/R-1H zones).
- ADU may apply depending on lot size and zoning.
- When discussing investment scenarios, note that SB9 is excluded and explain why.

**Condo / Co-op / Townhouse:**
- Price prediction, comparable sales, sell vs hold, improvement simulation, as-is rental income.
- Do NOT suggest or run development potential tools (the owner does not control the lot).
- Do NOT suggest lot-split, ADU, or SB9 scenarios.
- Investment analysis is limited to as-is rental scenario only.
- Frame analysis around: unit value, HOA considerations, comparable unit sales, rental yield.

**Apartment (5+ units):**
- Price prediction, comparable sales, sell vs hold, improvement simulation, as-is rental income.
- Do NOT suggest ADU/SB9/lot-split (irrelevant at this scale).
- Investment analysis is limited to as-is existing unit rental analysis.
- Frame analysis around: per-unit economics, cap rate, gross rent multiplier, building-level value.

**Land / Vacant:**
- Price prediction, comparable land sales, sell vs hold, zoning-based development analysis.
- Do NOT suggest improvement simulation (no structure to improve).
- Do NOT suggest rental income (no units to rent).
- Focus on: zoning capacity, what CAN be built, new construction feasibility, permitted uses.

**Mixed-Use:**
- Price prediction, comparable sales, sell vs hold, improvement simulation.
- Development potential is limited to the residential portion.
- Rental income analysis covers existing residential units only.

**Commercial:**
- Price prediction, comparable sales, sell vs hold.
- Do NOT suggest residential-focused analyses (ADU, SB9, improvement ROI, residential rental).

CONTEXT:
You are the primary interface for the HomeBuyer app. Users may ask about any Berkeley property \
by address, or about the overall market. If property details (address, coordinates, etc.) are \
provided in the conversation context, use them when calling tools. If the user asks about a \
different property, use lookup_property to find it first."""


def _sanitize_history(history: list[dict]) -> list[dict]:
    """Ensure every message in history has a non-empty string content field.

    The Anthropic API rejects messages where ``content`` is ``None`` or empty.
    This can happen when a prior assistant turn produced only tool calls (no
    text) and the response was persisted with ``content: ""`` or ``null``.
    """
    sanitized: list[dict] = []
    for msg in history:
        content = msg.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            # Skip empty messages — they carry no useful context and would
            # cause a BadRequestError from the Anthropic API.
            continue
        sanitized.append(msg)

    # Anthropic requires alternating user/assistant roles.  After dropping
    # empty messages we may have consecutive same-role entries.  Merge them
    # so the API doesn't reject the payload.
    merged: list[dict] = []
    for msg in sanitized:
        if merged and merged[-1]["role"] == msg["role"]:
            prev_c = merged[-1]["content"]
            curr_c = msg["content"]
            # Only merge when both are strings — list content (tool_results)
            # cannot be safely concatenated.
            if isinstance(prev_c, str) and isinstance(curr_c, str):
                merged[-1] = {**merged[-1], "content": prev_c + "\n\n" + curr_c}
            else:
                merged.append(dict(msg))
        else:
            merged.append(dict(msg))
    return merged


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
        working_set_descriptor: str = "",
    ) -> dict:
        """Run a single chat turn with tool use.

        Args:
            message: The user's new message.
            history: Previous messages [{role, content}, ...].
            property_context: Property details (lat, lon, address, neighborhood, etc.).
            tool_executor: Callable(tool_name, tool_input) -> str that executes tools.
            working_set_descriptor: Session working set summary for system prompt.

        Returns:
            {"reply": str, "tool_calls": list, "blocks": list} or {"error": str}
        """
        if not self._enabled or not self._client:
            return {"error": "Faketor is unavailable (no API key configured)"}

        # Build system prompt with property context and working set
        base_system = SYSTEM_PROMPT + f"\n\nCURRENT PROPERTY CONTEXT:\n{json.dumps(property_context, indent=2)}"
        if working_set_descriptor:
            base_system += f"\n\n{working_set_descriptor}"

        # Build messages: sanitize history then append new user message
        messages = _sanitize_history(history) + [{"role": "user", "content": message}]

        tool_calls_log = []
        blocks = []  # Structured response blocks for frontend rendering
        accumulator = AnalysisAccumulator()

        try:
            # Agentic loop: keep going until Claude stops calling tools
            for iteration in range(_MAX_ITERATIONS):
                # Inject accumulated facts summary into system prompt
                system = base_system
                if accumulator.tool_sequence:
                    system = base_system + "\n\n" + accumulator.get_summary()

                # Warn when approaching iteration limit so the model wraps up
                remaining = _MAX_ITERATIONS - iteration
                if remaining <= 3 and iteration > 0:
                    system += (
                        f"\n\n⚠️ ITERATION BUDGET: You have {remaining} tool calls remaining. "
                        "Summarize what you've found so far and provide your answer. "
                        "Do NOT start new per-property analyses."
                    )

                response = self._client.messages.create(
                    model=_CLAUDE_MODEL,
                    max_tokens=4096,
                    system=system,
                    tools=registry.get_tool_schemas(),
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

                # Execute tools, enrich with facts, collect results
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

                    # Parse result for fact enrichment and block creation
                    result_data = None
                    try:
                        result_data = json.loads(result_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    # Enrich tool result with _facts for Claude
                    if isinstance(result_data, (dict, list)):
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            facts = compute_facts_for_tool(tool_block.name, result_data)
                            if facts:
                                accumulator.record(tool_block.name, tool_block.input, facts)
                                if isinstance(result_data, dict):
                                    result_data["_facts"] = facts
                                    result_str = safe_json_dumps(result_data)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result_str,
                    })

                    # Build frontend block (strip _facts — frontend doesn't need it)
                    block_type = registry.get_block_type(tool_block.name)
                    if block_type and result_data is not None:
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            if isinstance(result_data, dict):
                                block_data = {k: v for k, v in result_data.items() if k != "_facts"}
                            else:
                                block_data = result_data
                            blocks.append({
                                "type": block_type,
                                "tool_name": tool_block.name,
                                "data": block_data,
                            })

                messages.append({"role": "user", "content": tool_results})

            # If we hit max iterations, return what we have with a graceful message
            fallback_reply = (
                _FALLBACK_REPLY
                if blocks
                else "I gathered a lot of data but ran out of room to summarize it. Could you ask a more specific question?"
            )
            return {
                "reply": fallback_reply,
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

    # ------------------------------------------------------------------
    # Streaming version
    # ------------------------------------------------------------------

    _TOOL_LABELS: dict[str, str] = {
        "lookup_property": "Looking up property...",
        "get_price_prediction": "Running price prediction...",
        "get_comparable_sales": "Finding comparable sales...",
        "get_development_potential": "Checking development potential...",
        "get_neighborhood_stats": "Getting neighborhood stats...",
        "get_market_summary": "Loading market data...",
        "estimate_rental_income": "Estimating rental income...",
        "analyze_investment_scenarios": "Comparing investment scenarios...",
        "estimate_sell_vs_hold": "Analyzing sell vs hold...",
        "get_improvement_simulation": "Simulating improvements...",
        "search_properties": "Searching properties...",
        "lookup_permits": "Looking up permits...",
        "query_database": "Querying database...",
        "undo_filter": "Undoing last filter...",
        "generate_investment_prospectus": "Generating investment prospectus...",
        "lookup_regulation": "Looking up Berkeley regulations...",
        "update_working_set": "Updating property list...",
        "lookup_glossary_term": "Looking up definition...",
    }

    def chat_stream(
        self,
        message: str,
        history: list[dict],
        property_context: dict,
        tool_executor,
        working_set_descriptor: str = "",
    ):
        """Streaming version of chat(). Yields SSE event dicts.

        Event types:
          {"event": "text_delta", "data": {"text": "..."}}
          {"event": "tool_start", "data": {"name": "...", "label": "..."}}
          {"event": "tool_result", "data": {"name": "...", "block": {...} or None}}
          {"event": "done", "data": {"reply": "...", "tool_calls": [...], "blocks": [...]}}
          {"event": "error", "data": {"message": "..."}}
        """
        if not self._enabled or not self._client:
            yield {"event": "error", "data": {"message": "Faketor is unavailable (no API key configured)"}}
            return

        base_system = SYSTEM_PROMPT + f"\n\nCURRENT PROPERTY CONTEXT:\n{json.dumps(property_context, indent=2)}"
        if working_set_descriptor:
            base_system += f"\n\n{working_set_descriptor}"
        messages = _sanitize_history(history) + [{"role": "user", "content": message}]

        tool_calls_log: list[dict] = []
        blocks: list[dict] = []
        all_text_parts: list[str] = []
        accumulator = AnalysisAccumulator()

        try:
            for iteration in range(_MAX_ITERATIONS):
                # Inject accumulated facts summary into system prompt
                system = base_system
                if accumulator.tool_sequence:
                    system = base_system + "\n\n" + accumulator.get_summary()

                # Warn when approaching iteration limit so the model wraps up
                remaining = _MAX_ITERATIONS - iteration
                if remaining <= 3 and iteration > 0:
                    system += (
                        f"\n\n⚠️ ITERATION BUDGET: You have {remaining} tool calls remaining. "
                        "Summarize what you've found so far and provide your answer. "
                        "Do NOT start new per-property analyses."
                    )

                # Stream this iteration's response
                with self._client.messages.stream(
                    model=_CLAUDE_MODEL,
                    max_tokens=4096,
                    system=system,
                    tools=registry.get_tool_schemas(),
                    messages=messages,
                ) as stream:
                    iteration_text: list[str] = []
                    for text_chunk in stream.text_stream:
                        yield {"event": "text_delta", "data": {"text": text_chunk}}
                        iteration_text.append(text_chunk)

                    response = stream.get_final_message()

                # If Claude is done, break out
                if response.stop_reason == "end_turn":
                    all_text_parts.extend(iteration_text)
                    break

                # Extract tool use blocks
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    all_text_parts.extend(iteration_text)
                    break

                # Add paragraph break between pre-tool text and post-tool text
                # so they don't jam together in the rendered message
                if iteration_text:
                    all_text_parts.extend(iteration_text)
                    all_text_parts.append("\n\n")
                    yield {"event": "text_delta", "data": {"text": "\n\n"}}

                # Append assistant content to messages for next iteration
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool, enrich with facts
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_calls_log.append({
                        "name": tool_block.name,
                        "input": tool_block.input,
                    })

                    yield {
                        "event": "tool_start",
                        "data": {
                            "name": tool_block.name,
                            "label": self._TOOL_LABELS.get(tool_block.name, f"Using {tool_block.name}..."),
                        },
                    }

                    try:
                        result_str = tool_executor(tool_block.name, tool_block.input)
                    except Exception as e:
                        logger.warning("Tool %s failed: %s", tool_block.name, e)
                        result_str = json.dumps({"error": str(e)})

                    # Parse result for fact enrichment and block creation
                    result_data = None
                    try:
                        result_data = json.loads(result_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    # Enrich tool result with _facts for Claude
                    if isinstance(result_data, (dict, list)):
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            facts = compute_facts_for_tool(tool_block.name, result_data)
                            if facts:
                                accumulator.record(tool_block.name, tool_block.input, facts)
                                if isinstance(result_data, dict):
                                    result_data["_facts"] = facts
                                    result_str = safe_json_dumps(result_data)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result_str,
                    })

                    # Build frontend block (strip _facts)
                    block_type = registry.get_block_type(tool_block.name)
                    block = None
                    if block_type and result_data is not None:
                        is_error = isinstance(result_data, dict) and result_data.get("error")
                        if not is_error:
                            if isinstance(result_data, dict):
                                block_data = {k: v for k, v in result_data.items() if k != "_facts"}
                            else:
                                block_data = result_data
                            block = {
                                "type": block_type,
                                "tool_name": tool_block.name,
                                "data": block_data,
                            }
                            blocks.append(block)

                    yield {
                        "event": "tool_result",
                        "data": {
                            "name": tool_block.name,
                            "block": block,
                        },
                    }

                messages.append({"role": "user", "content": tool_results})

            # Yield done event with complete response
            full_reply = "".join(all_text_parts)
            if not full_reply:
                full_reply = (
                    _FALLBACK_REPLY
                    if blocks
                    else "I gathered a lot of data but ran out of room to summarize it. Could you ask a more specific question?"
                )
            yield {
                "event": "done",
                "data": {
                    "reply": full_reply,
                    "tool_calls": tool_calls_log,
                    "blocks": blocks,
                },
            }

        except Exception as e:
            error_str = str(e).lower()
            logger.warning("Faketor streaming chat failed: %s", e, exc_info=True)
            if "rate_limit" in error_str or "429" in str(e):
                yield {"event": "error", "data": {"message": "Faketor is temporarily busy (rate limited). Try again in a moment."}}
            elif "authentication" in error_str or "401" in str(e):
                yield {"event": "error", "data": {"message": "Faketor is unavailable (invalid API key)"}}
            else:
                yield {"event": "error", "data": {"message": f"Faketor encountered an error: {type(e).__name__}"}}
