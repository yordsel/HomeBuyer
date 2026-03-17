"""MarketContext prompt component.

Frozen market snapshot — rates, prices, inventory. Changes per
interaction based on the MarketSnapshot loaded at context creation.

Phase D-1 (#38) of Epic #23.
"""

from __future__ import annotations

from homebuyer.services.faketor.state.market import MarketSnapshot


def render(market: MarketSnapshot | None) -> str:
    """Render the market context prompt fragment.

    Provides the LLM with frozen market conditions for this turn.
    Returns empty string if no market data is available.
    """
    if market is None:
        return ""

    bw = market.berkeley_wide

    parts = ["=== MARKET CONDITIONS (frozen for this interaction) ==="]

    if market.mortgage_rate_30yr is not None:
        parts.append(f"Mortgage rate (30yr fixed): {market.mortgage_rate_30yr}%")

    if market.conforming_limit is not None:
        parts.append(f"Conforming loan limit (Alameda County): ${market.conforming_limit:,}")

    if bw.median_sale_price is not None:
        parts.append(f"Berkeley median sale price: ${bw.median_sale_price:,}")

    if bw.median_list_price is not None:
        parts.append(f"Berkeley median list price: ${bw.median_list_price:,}")

    if bw.median_ppsf is not None:
        parts.append(f"Median price/sqft: ${bw.median_ppsf:.0f}")

    if bw.median_dom is not None:
        parts.append(f"Median days on market: {bw.median_dom}")

    if bw.avg_sale_to_list is not None:
        parts.append(f"Sale-to-list ratio: {bw.avg_sale_to_list:.1%}")

    if bw.inventory is not None:
        parts.append(f"Active inventory: {bw.inventory} listings")

    if bw.months_of_supply is not None:
        parts.append(f"Months of supply: {bw.months_of_supply:.1f}")

    parts.append("")
    parts.append(
        "Use these numbers as ground truth for all financial calculations. "
        "Do not call get_market_summary unless the user explicitly asks for "
        "a detailed market breakdown — the key metrics are already here."
    )
    parts.append("=== END MARKET CONDITIONS ===")

    return "\n".join(parts)
