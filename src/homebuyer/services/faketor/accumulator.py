"""Cross-tool fact accumulator for Faketor multi-step analysis.

Tracks verified facts across all tool calls within a single chat turn.
Before each Claude iteration, the accumulated summary is injected into the
system prompt so Claude has a single source of truth for its narrative.
"""

from __future__ import annotations

import logging
from collections import Counter

from homebuyer.utils.formatting import fmt_price as _fmt_price

logger = logging.getLogger(__name__)

# Maximum number of per-property detail lines in the summary.
# Beyond this, we aggregate into stats to keep the summary compact.
_MAX_PROPERTY_DETAIL_LINES = 10


class AnalysisAccumulator:
    """Tracks verified facts across tool calls within a single Faketor chat turn.

    Usage::

        acc = AnalysisAccumulator()
        acc.record("search_properties", tool_input, facts)
        acc.record("get_development_potential", tool_input, facts)
        summary = acc.get_summary()  # inject into system prompt
    """

    def __init__(self) -> None:
        self.tool_sequence: list[str] = []

        # Most recent search
        self.search_facts: dict | None = None

        # Per-property analyses keyed by address (or property_id fallback)
        self.dev_potentials: dict[str, dict] = {}
        self.predictions: dict[str, dict] = {}
        self.rentals: dict[str, dict] = {}
        self.investments: dict[str, dict] = {}
        self.improvements: dict[str, dict] = {}
        self.sell_vs_hold: dict[str, dict] = {}

        # Neighbourhood-level
        self.neighborhood_stats: dict[str, dict] = {}

        # Comps
        self.comps: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, tool_name: str, tool_input: dict, facts: dict) -> None:
        """Record facts from a single tool call."""
        self.tool_sequence.append(tool_name)
        address = self._resolve_address(tool_input)

        if tool_name == "search_properties":
            self.search_facts = facts
        elif tool_name == "get_development_potential":
            self.dev_potentials[address] = facts
        elif tool_name == "get_price_prediction":
            self.predictions[address] = facts
        elif tool_name == "estimate_rental_income":
            self.rentals[address] = facts
        elif tool_name == "analyze_investment_scenarios":
            self.investments[address] = facts
        elif tool_name == "get_improvement_simulation":
            self.improvements[address] = facts
        elif tool_name == "estimate_sell_vs_hold":
            self.sell_vs_hold[address] = facts
        elif tool_name == "get_neighborhood_stats":
            key = facts.get("neighborhood") or tool_input.get("neighborhood") or address
            self.neighborhood_stats[key] = facts
        elif tool_name == "get_comparable_sales":
            self.comps[address] = facts

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    def get_summary(self) -> str:
        """Generate a VERIFIED DATA SUMMARY for injection into the system prompt.

        Returns an empty string if no tools have been recorded yet.
        """
        if not self.tool_sequence:
            return ""

        lines: list[str] = [
            "=== VERIFIED DATA SUMMARY (use these facts verbatim in your response) ===",
            "",
            f"Tools called: {self._tool_sequence_summary()}",
        ]

        # Search results
        if self.search_facts:
            sf = self.search_facts
            lines.append("")
            lines.append(f"Property Search: {sf['total_results']} properties found")
            lines.append(
                f"  ADU eligible: {sf['adu_eligible_count']} of {sf['total_results']}"
            )
            if sf.get("adu_eligible_addresses"):
                addrs = ", ".join(sf["adu_eligible_addresses"][:_MAX_PROPERTY_DETAIL_LINES])
                if len(sf["adu_eligible_addresses"]) > _MAX_PROPERTY_DETAIL_LINES:
                    addrs += f" (and {len(sf['adu_eligible_addresses']) - _MAX_PROPERTY_DETAIL_LINES} more)"
                lines.append(f"    Addresses: {addrs}")
            lines.append(
                f"  SB9 eligible: {sf['sb9_eligible_count']} of {sf['total_results']}"
            )
            if sf.get("price_range"):
                lines.append(
                    f"  Price range: {_fmt_price(sf['price_range'][0])} \u2013 {_fmt_price(sf['price_range'][1])}"
                )
            if sf.get("median_price"):
                lines.append(f"  Median price: {_fmt_price(sf['median_price'])}")
            if sf.get("lot_size_range"):
                lines.append(
                    f"  Lot size range: {sf['lot_size_range'][0]:,} \u2013 {sf['lot_size_range'][1]:,} sqft"
                )
            if sf.get("zoning_classes"):
                lines.append(f"  Zones: {', '.join(sf['zoning_classes'])}")

        # Development potential per property
        if self.dev_potentials:
            lines.append("")
            lines.append(
                f"Development Potential analyzed for {len(self.dev_potentials)} properties:"
            )
            for addr, dp in list(self.dev_potentials.items())[:_MAX_PROPERTY_DETAIL_LINES]:
                adu = "Yes" if dp.get("adu_eligible") else "No"
                sb9 = "Yes" if dp.get("sb9_eligible") else "No"
                adu_sqft = f" (max {dp['adu_max_sqft']} sqft)" if dp.get("adu_max_sqft") and dp.get("adu_eligible") else ""
                units = dp.get("effective_max_units", "?")
                zone = dp.get("zone_class", "?")
                lines.append(
                    f"  {addr}: ADU={adu}{adu_sqft}, SB9={sb9}, Max units={units}, Zone={zone}"
                )
            if len(self.dev_potentials) > _MAX_PROPERTY_DETAIL_LINES:
                lines.append(
                    f"  ... and {len(self.dev_potentials) - _MAX_PROPERTY_DETAIL_LINES} more"
                )

        # Predictions
        if self.predictions:
            lines.append("")
            lines.append(f"Price Predictions for {len(self.predictions)} properties:")
            for addr, pred in list(self.predictions.items())[:_MAX_PROPERTY_DETAIL_LINES]:
                p = _fmt_price(pred.get("predicted_price"))
                lo = _fmt_price(pred.get("price_lower"))
                hi = _fmt_price(pred.get("price_upper"))
                lines.append(f"  {addr}: {p} (range: {lo} \u2013 {hi})")

        # Rentals
        if self.rentals:
            lines.append("")
            lines.append(f"Rental Estimates for {len(self.rentals)} properties:")
            for addr, r in list(self.rentals.items())[:_MAX_PROPERTY_DETAIL_LINES]:
                rent = _fmt_price(r.get("monthly_rent"))
                cap = r.get("cap_rate_pct", "?")
                coc = r.get("cash_on_cash_pct", "?")
                lines.append(f"  {addr}: {rent}/mo, Cap rate={cap}%, CoC={coc}%")

        # Investment scenarios
        if self.investments:
            lines.append("")
            lines.append(f"Investment Scenarios for {len(self.investments)} properties:")
            for addr, inv in list(self.investments.items())[:_MAX_PROPERTY_DETAIL_LINES]:
                best = inv.get("best_cash_on_cash") or {}
                best_name = best.get("name", "?")
                best_coc = best.get("cash_on_cash_pct", "?")
                n = inv.get("scenario_count", 0)
                lines.append(
                    f"  {addr}: {n} scenarios, best CoC={best_coc}% ({best_name})"
                )

        # Sell vs hold
        if self.sell_vs_hold:
            lines.append("")
            lines.append(f"Sell-vs-Hold for {len(self.sell_vs_hold)} properties:")
            for addr, svh in list(self.sell_vs_hold.items())[:_MAX_PROPERTY_DETAIL_LINES]:
                val = _fmt_price(svh.get("current_value"))
                yoy = svh.get("yoy_appreciation_pct", "?")
                rent = _fmt_price(svh.get("monthly_rent"))
                cap = svh.get("cap_rate_pct", "?")
                lines.append(
                    f"  {addr}: Value={val}, YoY={yoy}%, Rent={rent}/mo, Cap={cap}%"
                )

        # Neighborhood stats
        if self.neighborhood_stats:
            lines.append("")
            lines.append(f"Neighborhood Stats ({len(self.neighborhood_stats)}):")
            for name, ns in self.neighborhood_stats.items():
                med = _fmt_price(ns.get("median_price"))
                yoy = ns.get("yoy_price_change_pct", "?")
                sales = ns.get("total_sales", "?")
                lines.append(f"  {name}: Median={med}, YoY={yoy}%, Sales={sales}")

        # Comps
        if self.comps:
            lines.append("")
            lines.append(f"Comparable Sales ({len(self.comps)}):")
            for addr, c in self.comps.items():
                n = c.get("comp_count", 0)
                rng = c.get("price_range")
                rng_str = (
                    f"{_fmt_price(rng[0])} \u2013 {_fmt_price(rng[1])}"
                    if rng
                    else "N/A"
                )
                ppsf = c.get("median_price_per_sqft")
                ppsf_str = f"${ppsf}/sqft" if ppsf else "N/A"
                lines.append(f"  {addr}: {n} comps, range {rng_str}, median {ppsf_str}")

        # Improvements
        if self.improvements:
            lines.append("")
            lines.append(f"Improvement ROI for {len(self.improvements)} properties:")
            for addr, imp in list(self.improvements.items())[:_MAX_PROPERTY_DETAIL_LINES]:
                roi = imp.get("overall_roi")
                roi_str = f"{roi:.1f}x" if roi else "N/A"
                delta = _fmt_price(imp.get("total_delta"))
                cost = _fmt_price(imp.get("total_cost"))
                lines.append(f"  {addr}: ROI={roi_str}, Delta={delta}, Cost={cost}")

        lines.append("")
        lines.append("USE THESE FACTS in your response. Do not recount or re-derive from raw data.")
        lines.append("=== END VERIFIED DATA ===")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_address(tool_input: dict) -> str:
        """Best-effort address label from tool_input."""
        if tool_input.get("address"):
            return tool_input["address"]
        if tool_input.get("property_id"):
            return f"property#{tool_input['property_id']}"
        lat = tool_input.get("latitude")
        lon = tool_input.get("longitude")
        if lat and lon:
            return f"({lat:.4f}, {lon:.4f})"
        return "unknown"

    def _tool_sequence_summary(self) -> str:
        """Compact tool sequence string, e.g. 'search_properties, get_development_potential (\u00d73)'."""
        counts = Counter(self.tool_sequence)
        parts = []
        for tool, count in counts.items():
            if count == 1:
                parts.append(tool)
            else:
                parts.append(f"{tool} (\u00d7{count})")
        return ", ".join(parts)
