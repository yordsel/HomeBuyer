#!/usr/bin/env python3
"""D-7 (#44): Baseline quality comparison — old vs new prompt paths.

Sends 20 representative conversations through both the legacy and
orchestrated prompt paths. Captures responses for side-by-side comparison.

Usage:
    # Start server with legacy path:
    USE_SEGMENT_ORCHESTRATION= python -m homebuyer &
    python scripts/d7_quality_comparison.py --mode legacy --port 10000

    # Start server with orchestrated path:
    USE_SEGMENT_ORCHESTRATION=true python -m homebuyer &
    python scripts/d7_quality_comparison.py --mode orchestrated --port 10001

    # Compare results:
    python scripts/d7_quality_comparison.py --compare
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 20 test conversations covering all segments and scenarios
# ---------------------------------------------------------------------------

TEST_CONVERSATIONS = [
    # --- OCCUPY SEGMENTS ---
    # 1. First-time buyer (basic)
    {
        "id": "01_first_time_basic",
        "segment": "first_time_buyer",
        "description": "First-time buyer asking about Berkeley market",
        "messages": [
            "I'm a first-time homebuyer with about $200k saved and a household "
            "income of $180k. I'm looking to buy a home to live in. What can I "
            "afford in Berkeley?",
        ],
    },
    # 2. First-time buyer (property-specific)
    {
        "id": "02_first_time_property",
        "segment": "first_time_buyer",
        "description": "First-time buyer asking about a specific property",
        "messages": [
            "I'm a first-time buyer with $250k down. Tell me about 1234 Cedar St",
        ],
        "property": {"latitude": 37.8787, "longitude": -122.2686, "address": "1234 Cedar St"},
    },
    # 3. Down-payment constrained
    {
        "id": "03_down_payment_constrained",
        "segment": "down_payment_constrained",
        "description": "Buyer with limited down payment",
        "messages": [
            "I make $200k/year but only have $80k saved for a down payment. "
            "I'm currently paying $3,500/month in rent. Is it realistic to buy "
            "in Berkeley with less than 10% down?",
        ],
    },
    # 4. Stretcher
    {
        "id": "04_stretcher",
        "segment": "stretcher",
        "description": "Buyer stretching beyond comfortable budget",
        "messages": [
            "My wife and I make $140k combined. We have $100k saved. We really "
            "want to stay in Berkeley near our kids' school. What are our options? "
            "We know it'll be tight.",
        ],
    },
    # 5. Not viable
    {
        "id": "05_not_viable",
        "segment": "not_viable",
        "description": "Buyer who likely can't afford Berkeley",
        "messages": [
            "I make about $60k and have $20k in savings. I'd love to buy a "
            "place in Berkeley. What's the market like?",
        ],
    },
    # 6. Equity-trapped upgrader
    {
        "id": "06_equity_trapped",
        "segment": "equity_trapped_upgrader",
        "description": "Current homeowner wanting to upgrade",
        "messages": [
            "I bought my 2BR condo in South Berkeley 5 years ago for $650k. "
            "I have a 2.9% rate. We need more space now with 2 kids. I have "
            "about $200k in equity. How do I upgrade without losing my rate?",
        ],
    },
    # 7. Competitive bidder
    {
        "id": "07_competitive_bidder",
        "segment": "competitive_bidder",
        "description": "Well-qualified buyer in competitive market",
        "messages": [
            "My household income is $450k and I have $600k for a down payment. "
            "I keep losing bidding wars in North Berkeley. What's the competition "
            "like and how can I compete better?",
        ],
    },
    # 8. First-time buyer (multi-turn with tool use)
    {
        "id": "08_first_time_multi_turn",
        "segment": "first_time_buyer",
        "description": "Multi-turn conversation with market analysis",
        "messages": [
            "I'm a first-time buyer with $300k down and $220k income. "
            "What neighborhoods should I be looking at?",
            "What about Elmwood? How does it compare to Thousand Oaks?",
        ],
    },
    # 9. Occupy - general market question
    {
        "id": "09_market_overview",
        "segment": "general",
        "description": "General market question without buyer signals",
        "messages": [
            "What's the Berkeley real estate market like right now? "
            "Are prices going up or down?",
        ],
    },
    # 10. Down-payment constrained with PMI question
    {
        "id": "10_pmi_question",
        "segment": "down_payment_constrained",
        "description": "Buyer asking about PMI on low down payment",
        "messages": [
            "If I put 10% down on a $1.2M house in Berkeley, how much would "
            "PMI cost me? When would it drop off? I make $200k/year.",
        ],
    },

    # --- INVEST SEGMENTS ---
    # 11. Cash buyer
    {
        "id": "11_cash_buyer",
        "segment": "cash_buyer",
        "description": "All-cash investor",
        "messages": [
            "I have $1.5M cash to invest. Looking for investment properties "
            "in Berkeley. What's the best cap rate I can expect?",
        ],
    },
    # 12. Leveraged investor
    {
        "id": "12_leveraged_investor",
        "segment": "leveraged_investor",
        "description": "Investor using leverage",
        "messages": [
            "I want to invest in Berkeley real estate. I have $400k for a "
            "down payment and I'm looking at multi-unit properties. What's "
            "the cash-on-cash return I can expect with current rates?",
        ],
    },
    # 13. Value-add investor
    {
        "id": "13_value_add",
        "segment": "value_add_investor",
        "description": "Investor looking for value-add opportunities",
        "messages": [
            "I'm looking for properties with ADU potential in Berkeley. "
            "I have $800k to invest. What neighborhoods have the best "
            "value-add opportunities?",
        ],
    },
    # 14. Appreciation bettor
    {
        "id": "14_appreciation",
        "segment": "appreciation_bettor",
        "description": "Investor focused on appreciation",
        "messages": [
            "I'm less concerned about cash flow — I want to buy in the "
            "neighborhood with the best 5-year appreciation potential. "
            "I have $500k to invest. Which areas are undervalued?",
        ],
    },
    # 15. Equity-leveraging investor
    {
        "id": "15_equity_investor",
        "segment": "equity_leveraging_investor",
        "description": "Using home equity to invest",
        "messages": [
            "I own my home in Piedmont (worth about $2M, $400k left on "
            "mortgage). I want to use my equity to invest in Berkeley "
            "rental properties. What's the best strategy?",
        ],
    },
    # 16. Investor - rent vs buy analysis
    {
        "id": "16_rent_vs_buy",
        "segment": "leveraged_investor",
        "description": "Investor comparing rent vs buy economics",
        "messages": [
            "I'm currently renting for $4,500/month. With $350k down and "
            "a $250k income, does it make more sense financially to buy or "
            "keep renting and invest the difference? Run the numbers for me.",
        ],
    },
    # 17. Cash buyer - specific property analysis
    {
        "id": "17_cash_property",
        "segment": "cash_buyer",
        "description": "Cash buyer analyzing a specific property",
        "messages": [
            "I want to buy this property all-cash as an investment. "
            "What's the rental income potential and cap rate?",
        ],
        "property": {"latitude": 37.8616, "longitude": -122.2583, "address": "2500 Piedmont Ave"},
    },
    # 18. Multi-turn investment analysis
    {
        "id": "18_invest_multi_turn",
        "segment": "value_add_investor",
        "description": "Multi-turn investment conversation",
        "messages": [
            "I want to find a duplex or triplex in Berkeley I can add "
            "an ADU to. Budget is $1.2M. What's available?",
            "What would the total cost be including the ADU construction? "
            "And what's the projected return?",
        ],
    },
    # 19. Investor stress test
    {
        "id": "19_stress_test",
        "segment": "leveraged_investor",
        "description": "Investor asking about risk scenarios",
        "messages": [
            "If I buy a $1.4M property with 20% down, what happens to "
            "my investment if prices drop 15%? Or if rates go to 9%? "
            "I want to understand the downside risk.",
        ],
    },
    # 20. Mixed intent (occupy vs invest unclear)
    {
        "id": "20_mixed_intent",
        "segment": "ambiguous",
        "description": "Buyer with unclear intent",
        "messages": [
            "I'm thinking about buying a property in Berkeley. Maybe "
            "live in it for a few years then rent it out. I have about "
            "$400k and make $200k. What should I be looking at?",
        ],
    },
]


def send_message(port: int, message: str, history: list, property_ctx: dict | None = None):
    """Send a single message to the Faketor chat API."""
    payload = {
        "message": message,
        "history": history,
        "session_id": f"d7-test-{int(time.time())}",
    }
    if property_ctx:
        payload.update(property_ctx)

    try:
        resp = requests.post(
            f"http://127.0.0.1:{port}/api/faketor/chat",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": str(e), "reply": f"[ERROR: {e}]"}


def run_conversation(port: int, conv: dict) -> dict:
    """Run a full conversation and return results."""
    history = []
    results = []
    prop = conv.get("property")

    for i, msg in enumerate(conv["messages"]):
        print(f"    Turn {i+1}: {msg[:60]}...")
        start = time.time()
        response = send_message(port, msg, history, prop)
        elapsed = time.time() - start

        reply = response.get("reply", response.get("error", ""))
        tool_calls = response.get("tool_calls", [])
        tools_used = [t["name"] for t in tool_calls]

        results.append({
            "message": msg,
            "reply": reply,
            "tools_used": tools_used,
            "elapsed_s": round(elapsed, 1),
            "reply_length": len(reply),
        })

        # Build history for next turn
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": reply})

    return {
        "id": conv["id"],
        "segment": conv["segment"],
        "description": conv["description"],
        "turns": results,
    }


def run_tests(port: int, mode: str):
    """Run all test conversations and save results."""
    output_dir = Path("data/d7_quality")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{mode}.json"

    # Check server is running
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
        resp.raise_for_status()
        print(f"Server running on port {port} ({mode} mode)")
    except Exception as e:
        print(f"ERROR: Cannot reach server on port {port}: {e}")
        sys.exit(1)

    all_results = []
    for i, conv in enumerate(TEST_CONVERSATIONS):
        print(f"\n[{i+1}/{len(TEST_CONVERSATIONS)}] {conv['id']}: {conv['description']}")
        result = run_conversation(port, conv)
        all_results.append(result)

    # Save
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to {output_file}")

    # Print summary
    print("\n" + "=" * 70)
    print(f"SUMMARY ({mode})")
    print("=" * 70)
    total_turns = sum(len(r["turns"]) for r in all_results)
    total_time = sum(t["elapsed_s"] for r in all_results for t in r["turns"])
    total_tools = sum(len(t["tools_used"]) for r in all_results for t in r["turns"])
    avg_reply = sum(t["reply_length"] for r in all_results for t in r["turns"]) / total_turns
    errors = sum(1 for r in all_results for t in r["turns"] if "[ERROR" in t["reply"])

    print(f"  Conversations: {len(all_results)}")
    print(f"  Total turns:   {total_turns}")
    print(f"  Total time:    {total_time:.0f}s (avg {total_time/total_turns:.1f}s/turn)")
    print(f"  Total tools:   {total_tools} (avg {total_tools/total_turns:.1f}/turn)")
    print(f"  Avg reply len: {avg_reply:.0f} chars")
    print(f"  Errors:        {errors}")


def compare_results():
    """Compare legacy vs orchestrated results side by side."""
    output_dir = Path("data/d7_quality")
    legacy_file = output_dir / "legacy.json"
    orch_file = output_dir / "orchestrated.json"

    if not legacy_file.exists():
        print(f"Missing {legacy_file} — run with --mode legacy first")
        sys.exit(1)
    if not orch_file.exists():
        print(f"Missing {orch_file} — run with --mode orchestrated first")
        sys.exit(1)

    with open(legacy_file) as f:
        legacy = json.load(f)
    with open(orch_file) as f:
        orch = json.load(f)

    report_file = output_dir / "comparison_report.md"
    lines = ["# D-7 Quality Comparison Report\n"]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Summary table
    lines.append("## Summary\n")
    lines.append("| Metric | Legacy | Orchestrated | Delta |")
    lines.append("|--------|--------|-------------|-------|")

    def _stats(data):
        turns = sum(len(r["turns"]) for r in data)
        total_time = sum(t["elapsed_s"] for r in data for t in r["turns"])
        total_tools = sum(len(t["tools_used"]) for r in data for t in r["turns"])
        avg_reply = sum(t["reply_length"] for r in data for t in r["turns"]) / max(turns, 1)
        errors = sum(1 for r in data for t in r["turns"] if "[ERROR" in t["reply"])
        return turns, total_time, total_tools, avg_reply, errors

    lt, ltime, ltools, lreply, lerr = _stats(legacy)
    ot, otime, otools, oreply, oerr = _stats(orch)

    lines.append(f"| Turns | {lt} | {ot} | - |")
    lines.append(f"| Avg time/turn | {ltime/lt:.1f}s | {otime/ot:.1f}s | {(otime/ot - ltime/lt):+.1f}s |")
    lines.append(f"| Total tools | {ltools} | {otools} | {otools - ltools:+d} |")
    lines.append(f"| Avg reply len | {lreply:.0f} | {oreply:.0f} | {oreply - lreply:+.0f} |")
    lines.append(f"| Errors | {lerr} | {oerr} | {oerr - lerr:+d} |")
    lines.append("")

    # Per-conversation comparison
    lines.append("## Per-Conversation Comparison\n")

    for l, o in zip(legacy, orch):
        lines.append(f"### {l['id']}: {l['description']}")
        lines.append(f"**Target segment:** {l['segment']}\n")

        for ti, (lt_turn, ot_turn) in enumerate(zip(l["turns"], o["turns"])):
            lines.append(f"#### Turn {ti+1}")
            lines.append(f"**User:** {lt_turn['message'][:120]}...\n" if len(lt_turn['message']) > 120 else f"**User:** {lt_turn['message']}\n")

            lines.append(f"**Legacy** ({lt_turn['elapsed_s']}s, tools: {', '.join(lt_turn['tools_used']) or 'none'}):")
            lines.append(f"> {lt_turn['reply'][:500]}{'...' if len(lt_turn['reply']) > 500 else ''}\n")

            lines.append(f"**Orchestrated** ({ot_turn['elapsed_s']}s, tools: {', '.join(ot_turn['tools_used']) or 'none'}):")
            lines.append(f"> {ot_turn['reply'][:500]}{'...' if len(ot_turn['reply']) > 500 else ''}\n")

            # Quality indicators
            l_len = lt_turn["reply_length"]
            o_len = ot_turn["reply_length"]
            l_tools = len(lt_turn["tools_used"])
            o_tools = len(ot_turn["tools_used"])
            lines.append(f"*Reply length: legacy={l_len}, orchestrated={o_len} | "
                         f"Tools: legacy={l_tools}, orchestrated={o_tools}*\n")

        lines.append("---\n")

    with open(report_file, "w") as f:
        f.write("\n".join(lines))
    print(f"Comparison report saved to {report_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="D-7 quality comparison")
    parser.add_argument("--mode", choices=["legacy", "orchestrated"], help="Which path to test")
    parser.add_argument("--port", type=int, default=10000, help="Server port")
    parser.add_argument("--compare", action="store_true", help="Compare results")
    args = parser.parse_args()

    if args.compare:
        compare_results()
    elif args.mode:
        run_tests(args.port, args.mode)
    else:
        parser.print_help()
