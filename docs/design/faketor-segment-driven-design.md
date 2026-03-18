# Faketor Segment-Driven Design

## Overview

This document redesigns Faketor's orchestration from the ground up, replacing the current
reactive tool-response model with a segment-aware system that detects who the buyer is,
identifies their Job to Be Done, and tailors tool selection, sequencing, tone, and proactive
behavior accordingly.

The core insight: Faketor currently has 18 well-built tools and responds to whatever the user
asks. But different buyers need fundamentally different things from the same tools. The same
comp analysis serves a Competitive Bidder ("should I bid $1.4M?") and a First-Time Buyer
("is this fairly priced?") but should be framed differently for each. The redesign puts a
segment-detection and job-resolution layer between the user and the tools.

---

## 1. The Buyer Model

### 1.1 Buyer Factors (Demand Side)

Four independent attributes describe any buyer's situation:

| Factor | Type | What It Determines |
|--------|------|--------------------|
| **Intent** | Binary: Occupy / Invest | Fundamentally different jobs. Occupiers optimize for lifestyle + affordability. Investors optimize for returns. |
| **Capital** | Continuous: liquid cash/savings | Determines entry — can they fund a down payment? At what level (3.5% FHA, 10% with PMI, 20% conventional)? Capital is immediately deployable with no friction or cost to access. |
| **Equity** | Continuous: value locked in existing property | Distinct from capital. Must sell, HELOC, or cash-out refi to access. Cost to access is rate-dependent (HELOC rates are variable — typically prime rate + margin; cash-out refi replaces locked rate with current market rate). Subject to Prop 13 reassessment risk if sold. Cannot be accessed if underwater. |
| **Income** | Continuous: household gross income | Determines sustainability — can they service the ongoing monthly costs (PITI + maintenance + earthquake insurance + PMI if applicable)? Also determines borrowing capacity via debt-to-income ratios. |

**Why these four and not others:**

- **Credit score / debt history** — matters for loan approval but is a binary gate (qualify or don't), not a segmentation factor. Someone with a 620 FICO and someone with a 780 FICO who both qualify for the same loan are in the same segment.
- **Demographics** (age, family size, occupation) — Christensen's JTBD framework explicitly rejects demographic segmentation. A 28-year-old tech worker and a 55-year-old professor with the same intent/capital/equity/income are in the same segment.
- **Location preference** — this is a supply-side filter, not a buyer attribute. It constrains what's available, not who the buyer is.

### 1.2 Market Factors (Supply Side)

Two categories of external conditions constrain all buyers:

#### 1.2.1 Rate Environment

A single value (currently 6.12% for 30-year fixed) that acts uniformly across the market but
creates differential impact based on buyer attributes:

| Buyer Attribute | Rate Impact |
|----------------|-------------|
| Has equity at a locked low rate | Punished — moving means rate penalty. Rate penalty = `new_monthly_PI(balance, market_rate) - current_monthly_PI(balance, locked_rate)`. The magnitude depends entirely on the delta between the buyer's locked rate and the current market rate, and on their remaining balance. |
| Has capital, no equity | Neutral — current rate is simply the price of entry. No reference point to compare against. |
| High income, low capital | Amplified — borrowing more means each basis point costs more in absolute dollars. |
| Cash buyer | Immune — rate is irrelevant to their purchase cost (though it affects the opportunity cost of deploying capital vs. investing it elsewhere). |
| Investor using leverage | Deterministic — `leverage_spread = property_cap_rate - mortgage_rate`. When negative, every borrowed dollar reduces returns. The cap rate is property-specific (varies by type, neighborhood, condition, rent estimate) and must be computed per property, not assumed as a market constant. |

Rate also has a **supply-side effect**: it suppresses inventory by creating rate lock-in.
Homeowners whose locked mortgage rate is significantly below the current market rate face a
penalty for selling — their next mortgage will cost substantially more per month on the same
balance. This reduces available listings independent of any demand-side effect. The magnitude
of this suppression depends on the distribution of locked rates across existing homeowners
vs. the current market rate.

**Segment activation thresholds are computed, not fixed:**

Each segment has a rate sensitivity that depends on the buyer's own numbers:

- **Upgrader activation**: computed from `rate_penalty_pct = (new_PI - current_PI) / monthly_gross_income`. When this exceeds the buyer's tolerance (varies by individual — some tolerate 5%, others 15%), the upgrader becomes latent.
- **Investor activation**: computed from `leverage_spread = property_cap_rate - mortgage_rate`. When negative, leveraged investment is cashflow-negative from day one. The threshold is property-specific, not a fixed rate number.
- **Stretcher activation**: computed from `true_monthly_cost(entry_price, current_rate) vs. max_monthly_payment`. When true cost at the lowest available entry price exceeds their max payment, the segment becomes not viable.
- **Down Payment Constrained activation**: computed from `(PI + PMI + tax + insurance + earthquake + maintenance) vs. max_monthly_payment`. PMI compounds the rate sensitivity because it adds cost on top of an already-high payment.
- **Cash Buyer**: rate-immune — always active regardless of rate environment.

There are no universal rate thresholds. A 5% rate freezes an upgrader locked at 2.8% but is
irrelevant to a first-time buyer with no reference rate. A 7% rate freezes most leveraged
investors in a 4% cap rate market but wouldn't freeze investors in a market with 8% cap rates.

#### 1.2.2 Supply

Supply is multi-dimensional. A buyer doesn't compete for "Berkeley housing" — they compete
for a specific slice defined by:

| Dimension | What It Constrains | Data Source |
|-----------|-------------------|-------------|
| **Neighborhood** | Geographic preference — schools, commute, character | `neighborhoods` table, GeoJSON boundaries |
| **Property type** | SFR vs. condo vs. multi-family vs. lot | `property_sales.property_type` |
| **Size** | Beds, baths, sqft — family needs | `property_sales.beds`, `baths`, `sqft` |
| **Price band** | What the buyer can access given capacity | Computed from buyer factors + rate |
| **Zoning** | What can be done with the property | `properties.zoning_class`, regulation data |
| **Condition/age** | Move-in ready vs. fixer | `property_sales.year_built`, permit history |

Each dimension filters total inventory into progressively smaller pools. Different segments
prioritize different dimensions:

- **Competitive Bidder**: neighborhood + size + price band (specific home in specific place)
- **Value-Add Investor**: zoning + lot size + price band (buildable potential, not livability)
- **Stretcher**: price band dominates (will flex on everything else to get in)

**Supply metrics the system tracks (per neighborhood):**

| Metric | Source | What It Signals |
|--------|--------|-----------------|
| Active inventory | `market_metrics.inventory` | How many options exist |
| Months of supply | `market_metrics.months_of_supply` | Balance of supply vs. demand. Should be interpreted relative to Berkeley's own historical range, not national rules of thumb — Berkeley is chronically low-supply, so the baseline is different than a typical market. |
| New listings rate | `market_metrics.new_listings` | Pace of new supply entering |
| Days on market (DOM) | `market_metrics.median_dom` | How fast properties move |
| Sale-to-list ratio | `market_metrics.sale_to_list_ratio` | Demand intensity (>1.0 = bidding wars) |
| % sold above list | `market_metrics.pct_sold_above_list` | Breadth of competition |
| Price drops % | `market_metrics.price_drops_pct` | Seller desperation / weak demand signal |

### 1.3 How Factors Combine: The Decision Tree

Buyer factors and market factors combine to produce a segment. The segment is not directly
set by any single factor — it **emerges** from the interaction.

#### 1.3.1 Capacity Computation (from buyer factors + rate)

```
# Step 1: Compute accessible equity (if owns property)
accessible_equity = existing_property_value - mortgage_balance - transaction_costs(~6%)
equity_access_cost_monthly =
    IF selling: rate_penalty = new_PI(balance, market_rate) - current_PI(balance, locked_rate)
    IF HELOC: heloc_payment(amount, current_HELOC_rate)  # HELOC rates are variable, typically prime + margin
    IF cash-out refi: new_PI(full_balance, market_rate) - current_PI(full_balance, locked_rate)

# Step 2: Compute deployable capital
total_deployable = liquid_capital + accessible_equity (if willing to sell or HELOC)

# Step 3: Compute max monthly payment
max_monthly = (household_income / 12) * dti_ratio - existing_monthly_debt
# dti_ratio is configurable — conventional lenders typically use 0.28 (front-end, housing only)
# or 0.36 (back-end, total debt). FHA allows up to 0.50 in some cases. The appropriate
# ratio depends on the loan program the buyer qualifies for and their risk tolerance.
# Should be set from buyer intake or defaulted based on loan type.

# Step 4: Compute max purchase price (iterative — tax and insurance scale with price)
FOR price IN range(100_000, 5_000_001, 10_000):
    loan = price - down_payment
    PI = amortize(loan, market_rate, 360)
    tax = price * property_tax_rate / 12                   # 1.17% base + parcel-specific assessments
    insurance = price * insurance_rate(property) / 12       # varies by property; default 0.35%
    earthquake = price * earthquake_rate(property) / 12     # varies by construction, age, fault proximity
    maintenance = price * maintenance_rate(property) / 12   # varies by age, type; estimate from year_built
    PMI = loan * pmi_rate(ltv, credit_score) / 12 IF down_payment_pct < 0.20
    total = PI + tax + insurance + earthquake + maintenance + PMI
    IF total <= max_monthly: max_purchase_price = price

# Step 5: Compute rate sensitivity (if owns property)
rate_penalty_monthly = new_PI(mortgage_balance, market_rate) - current_PI(mortgage_balance, locked_rate)
rate_penalty_pct = rate_penalty_monthly / (household_income / 12)
```

**Parameters used in capacity computation:**

*Fixed by jurisdiction (same for all properties in Berkeley):*
- Property tax rate: 1.17% (Prop 13 base rate; actual may include special assessments per parcel)
- Conforming loan limit (Alameda County 2026): $1,249,125 (1-unit), ~$1.6M (2-unit), ~$1.93M (3-unit), ~$2.4M (4-unit)

*Variable by property (must be computed or estimated per property):*
- Homeowner's insurance: varies by coverage level, construction type, claims history. System currently uses 0.35% of value as a default; should be refined when property details are known.
- Earthquake insurance: varies significantly by construction type (wood frame vs. masonry), year built (pre-1940 unreinforced vs. modern bolted foundation), and proximity to the Hayward Fault. A 1920s unreinforced masonry building may pay 3-5x more than a 2010 wood-frame. Not in current system — gap.
- Maintenance reserve: varies by property age and type. Newer construction and condos (where HOA covers exterior) require less. Older Berkeley housing stock (many homes 1900-1940) may require 1%+ of value annually. System should estimate based on `year_built` and `property_type`.
- PMI: varies by LTV ratio, credit score, and loan amount. Ranges from ~0.3% to ~1.5% of loan annually. System currently uses 0.5% as default.

*Variable by buyer (set from intake):*
- Down payment percentage: determines LTV, PMI requirement, and loan amount
- Existing monthly debt: reduces max monthly payment capacity
- Locked mortgage rate (if owns property): determines rate penalty calculation

#### 1.3.2 Segment Classification

```
IF intent = Occupy:

    supply_pool = count_properties(price <= max_purchase_price, type ∈ target_types)
    IF supply_pool < minimum_viable_pool_size:  # e.g., fewer than 5 properties in 2-year lookback
        → NOT VIABLE

    ELIF liquid_capital < max_purchase_price * 0.035:
        → NOT VIABLE (can't even meet FHA minimum)

    down_payment_pct = liquid_capital / max_purchase_price

    ELIF down_payment_pct < 0.20 AND no equity AND requires_PMI(down_payment_pct):
        IF true_monthly_cost(max_purchase_price, market_rate, down_payment_pct) > max_monthly:
            → NOT VIABLE (PMI + rate makes carry unsustainable)
        ELIF down_payment_pct < FHA_minimum(0.035):
            → NOT VIABLE (can't meet minimum down payment)
        ELSE:
            # Stretcher vs. Down Payment Constrained is a spectrum based on how much
            # PMI and reduced equity buffer stress the buyer's monthly budget.
            # The tighter the ratio of true_monthly_cost to max_monthly, the more
            # the buyer is "stretching." There is no fixed cutoff.
            monthly_stress_ratio = true_monthly_cost / max_monthly
            → STRETCHER if monthly_stress_ratio > 0.90
            → DOWN PAYMENT CONSTRAINED if monthly_stress_ratio <= 0.90

    ELIF has_existing_property:
        rate_penalty_pct = rate_penalty_monthly / monthly_gross_income
        # Whether the upgrader is "trapped" depends on their personal tolerance
        # for the rate penalty relative to their income and the perceived benefit
        # of moving. There is no universal threshold.
        IF rate_penalty_pct > buyer_tolerance_threshold:
            → EQUITY-TRAPPED UPGRADER

    ELIF has_equity AND has_capital AND income supports carry:
        → COMPETITIVE BIDDER (full optionality)

    ELIF has_capital AND no equity AND income supports carry:
        → FIRST-TIME BUYER

IF intent = Invest:

    cap_rate = estimated_annual_rent(target) / target_price
    leverage_spread = cap_rate - market_rate

    IF liquid_capital >= target_price:
        → CASH BUYER

    ELIF has_existing_property AND not selling:
        → EQUITY-LEVERAGING INVESTOR

    ELIF leverage_spread > 0:
        → LEVERAGED INVESTOR (only when property cap rate exceeds borrowing cost)

    ELIF has_development_intent:
        → VALUE-ADD INVESTOR

    ELSE:
        → APPRECIATION BETTOR
```

#### 1.3.3 Rate as Segment Activator/Deactivator

The segments are structural — they exist regardless of rate environment. But rates determine
which segments are **active** (participating in the market) vs. **latent** (want to participate
but the math doesn't work):

| Segment | Active when (computed condition) | Latent when (computed condition) |
|---------|-----------------------------------|----------------------------------|
| Not Viable | Never — by definition | `supply_pool < minimum` OR `capital < FHA_minimum` |
| Stretcher | `true_monthly_cost(entry_price, rate, down_pct) <= max_monthly` | `true_monthly_cost(entry_price, rate, down_pct) > max_monthly` |
| First-Time Buyer | `true_monthly_cost(target_price, rate, down_pct) <= max_monthly` AND `capital >= target_price * 0.20` | When true cost exceeds max monthly — but first-timers have no rate penalty, so they're more rate-resilient than upgraders |
| Down Payment Constrained | `true_monthly_cost(target_price, rate, down_pct) <= max_monthly` including PMI | When PMI + rate compound to push true cost beyond max monthly |
| Equity-Trapped Upgrader | `rate_penalty_pct <= buyer_tolerance` | `rate_penalty_pct > buyer_tolerance` — tolerance varies by buyer; depends on income headroom and perceived benefit of moving |
| Competitive Bidder | `true_monthly_cost <= max_monthly` AND has capital + equity for strong offers | When even well-capitalized buyers perceive the market as overvalued relative to their capacity |
| Cash Buyer | Always — rate-immune by definition | Never (though may choose not to deploy capital if opportunity cost exceeds expected return) |
| Equity-Leveraging Investor | `HELOC_cost + property_expenses < rental_income + appreciation_estimate` | When cost of accessing equity exceeds projected total return |
| Value-Add Investor | `development_ROI(project_cost, carrying_cost_at_rate, value_created) > required_return` | When carrying costs during development erode ROI below acceptable threshold |
| Appreciation Bettor | `projected_appreciation_rate > negative_carry_cost / property_value` | When negative carry exceeds credible appreciation projections |

### 1.4 True Cost of Ownership in Berkeley

A critical input to the model. The system currently computes PITI (Principal, Interest, Tax,
Insurance) but the true monthly cost is higher:

| Component | Calculation | On $1.3M property, 20% down, 6.12% |
|-----------|-------------|--------------------------------------|
| Principal & Interest | Amortization at current rate | $6,314/mo |
| Property Tax | 1.17% of value / 12 | $1,268/mo |
| Homeowner's Insurance | 0.35% of value / 12 | $379/mo |
| **PITI Subtotal** | | **$7,961/mo** |
| Earthquake Insurance | Varies by construction type, year built, foundation, proximity to fault (see note below) | Computed per property |
| Maintenance Reserve | Varies by age and property type (see note below) | Computed per property |
| **True Cost (20% down)** | | **Computed per property** |
| PMI (if < 20% down) | Varies by LTV ratio and loan amount | Added when `down_payment_pct < 0.20` |
| Higher P&I (lower down) | Larger loan at same rate | Computed from `amortize(larger_loan, rate, 360)` |
| **True Cost (< 20% down)** | | **Computed per property + buyer** |

**Compare to renting:** The ownership premium over renting is computed using the system's
rental income estimates for comparable properties. The rent-vs-buy breakeven depends on
holding period, appreciation rate, tax benefits, and opportunity cost of the down payment.
This must be calculated per property and per buyer situation — not assumed from market averages.

**What the system currently includes:** PITI in the mortgage analysis; PITI + maintenance +
vacancy + management in the rental/investment analysis. The affordability calculator uses
PITI + HOA but omits earthquake insurance and maintenance.

**Gaps:**
- Earthquake insurance is absent from all calculations. Given that Berkeley sits directly on the Hayward Fault, this is a material omission. The cost varies significantly by property characteristics (construction type, year built, foundation, proximity to fault) and should be estimated per property rather than applied as a flat rate.
- Maintenance reserve uses a flat rate in the investment analysis but is absent from the affordability calculator. Should be estimated per property based on `year_built` and `property_type`.
- Insurance and PMI rates are treated as fixed defaults. Where possible, these should be refined based on property and buyer specifics.
- The true cost understatement vs. PITI varies by property — it is not a fixed percentage. Properties with high earthquake risk, old construction, and low down payments will have a larger gap than newer properties with 20% down.

---

## 2. Segment Definitions

Section 1 established the decision tree that produces segments. This section defines each
segment in detail: who they are, how to detect them (both explicitly through intake and
implicitly through behavior), and what their computed capacity profile looks like.

### 2.1 Occupy Segments

#### 2.1.1 Not Viable

**Definition:** A buyer whose computed capacity cannot access any meaningful supply in Berkeley.

**Computed conditions (any of):**
- `supply_pool(price <= max_purchase_price, type ∈ target_types) < minimum_viable_pool_size`
- `liquid_capital < max_purchase_price * FHA_minimum_down (3.5%)`
- `true_monthly_cost(entry_price, market_rate, down_pct) > max_monthly` at every achievable
  price point in the market

**Detection — explicit (intake):**
- Income and capital inputs produce a max purchase price below the floor of Berkeley's
  available inventory for their target property type

**Detection — implicit (behavioral):**
- Asks "what can I afford in Berkeley?" and the answer is effectively nothing that matches
  their stated needs
- Repeatedly narrows search criteria and still finds zero viable options
- Asks about markets outside Berkeley (signal they may be self-selecting out)

**Capacity profile:**
- Max purchase price is below the market's effective floor for their target type
- OR capital is insufficient for minimum down payment at any viable price
- OR monthly carry at the lowest entry point exceeds their max monthly payment

**What Faketor should do:**
- Be honest. Don't present non-viable options as viable.
- Show what would need to change: "At a rate of X% your monthly carry drops to Y" or
  "With an additional $Z in capital you could access these properties" or "In [adjacent
  market] your budget accesses these options"
- This segment deserves a clear answer, not false hope.

**Important note:** Not Viable is relative to Berkeley and to this moment. A change in any
input — income increase, capital increase, rate decrease, market correction — can shift
the buyer into a viable segment. The classification should be presented as situational,
not permanent.

---

#### 2.1.2 Stretcher

**Definition:** A buyer who can technically enter the Berkeley market but whose monthly
costs consume a high proportion of their capacity. They are stretching to make it work.

**Computed conditions:**
- `down_payment_pct < 0.20` (requires PMI)
- `true_monthly_cost / max_monthly > 0.90` (monthly stress ratio is high)
- No existing property equity to draw on
- Supply pool exists but is limited to lower price tiers

**Detection — explicit (intake):**
- Low-to-moderate capital relative to target price
- Income that technically qualifies but with thin margin
- No existing property ownership

**Detection — implicit (behavioral):**
- Asks about affordability before asking about specific properties
- Questions focus on minimum down payment, PMI, FHA programs
- Asks "can I afford to buy?" rather than "where should I buy?"
- Compares buying costs to their current rent
- Shows sensitivity to monthly payment amounts in conversation

**Capacity profile:**
- Max purchase price reaches into Berkeley's lower tiers (condos, smaller units, less
  expensive neighborhoods)
- PMI adds meaningful cost on top of already-tight payments
- Monthly stress ratio is high — small changes in rate, insurance, or maintenance
  estimates can flip them from viable to not viable
- Thin equity cushion — vulnerable to any price decline in early years

**Risk factors Faketor should surface:**
- PMI duration: how long until equity reaches 80% LTV and PMI drops off
- Rate sensitivity: a 50bps rate increase at their loan size = $X/month change
- The rent-vs-buy math at their price point — it may honestly favor renting
- Maintenance and repair costs they may not be anticipating as current renters
- Limited ability to absorb unexpected expenses (roof, foundation, appliances)

---

#### 2.1.3 First-Time Buyer

**Definition:** A buyer with sufficient capital for 20%+ down payment, adequate income to
service the carry, but no existing property. This is their first purchase.

**Computed conditions:**
- `liquid_capital >= max_purchase_price * 0.20`
- `true_monthly_cost(target_price, market_rate, 0.20) <= max_monthly`
- No existing property (no equity, no locked rate)
- Supply pool has meaningful options at their price point

**Detection — explicit (intake):**
- Capital and income are adequate
- No existing property ownership
- Intent is occupy

**Detection — implicit (behavioral):**
- Asks about neighborhoods, schools, commute — lifestyle-oriented questions
- Asks "where should I buy?" rather than "can I afford to buy?"
- May ask about the buying process itself (inspections, contingencies, timelines)
- Doesn't reference a current mortgage or selling a home
- Questions suggest unfamiliarity with homeownership mechanics (property tax, insurance,
  maintenance responsibilities)

**Capacity profile:**
- Adequate for a meaningful segment of Berkeley's market
- No PMI burden (20%+ down)
- No rate penalty to compare against — the current rate is simply their cost
- No coordination complexity (nothing to sell, no bridge timing)
- Full capital liquidity — can move quickly on offers

**Distinguishing factor from Competitive Bidder:**
The First-Time Buyer has the financial capacity but lacks market experience and the equity
backstop of a prior property. Their job is partly informational ("help me navigate this")
in a way the Competitive Bidder's is not. The Competitive Bidder knows the process and
just needs tactical support.

---

#### 2.1.4 Down Payment Constrained

**Definition:** A buyer with strong income who qualifies for the monthly carry (including
PMI) but lacks the capital for a 20% down payment. The lending system isn't their barrier —
capital accumulation is.

**Computed conditions:**
- `liquid_capital < max_purchase_price * 0.20` but `>= max_purchase_price * FHA_minimum`
- `true_monthly_cost(target_price, market_rate, down_pct) <= max_monthly` including PMI
- `monthly_stress_ratio <= 0.90` (can carry it, just paying more than necessary due to PMI)
- No existing property equity

**Detection — explicit (intake):**
- High income relative to their capital
- Capital is between FHA minimum and 20% of target
- No property ownership

**Detection — implicit (behavioral):**
- Asks about PMI — what it costs, when it goes away
- Asks about low-down-payment programs (FHA, CalHFA, conventional at 5-10%)
- Compares scenarios: "what if I wait a year and save more vs. buy now?"
- May ask about buying a less expensive property (condo) to avoid PMI
- Income-confident but capital-anxious

**Capacity profile:**
- Income is strong — the monthly carry including PMI is sustainable
- Capital shortfall means PMI adds cost that they could avoid with more savings
- The strategic question is timing: buy now with PMI (start building equity, lock in
  price) vs. wait and save for 20% (avoid PMI but prices may rise and savings may not
  keep pace with appreciation)

**Distinguishing factor from Stretcher:**
The Stretcher is stressed by the monthly payment itself. The Down Payment Constrained
buyer can handle the payment — they're just paying a premium (PMI) because their capital
hasn't caught up to their income. The Stretcher's problem is sustainability. The Down
Payment Constrained buyer's problem is optimization.

---

#### 2.1.5 Equity-Trapped Upgrader

**Definition:** A buyer who owns a home in the current market, has accumulated equity, but
faces a rate penalty that makes moving economically painful. Their wealth is locked in an
illiquid, rate-advantaged asset.

**Computed conditions:**
- Owns existing property with `accessible_equity > 0`
- `rate_penalty_pct > buyer_tolerance_threshold` (the monthly cost increase from
  surrendering their locked rate exceeds what they're willing to absorb)
- Income supports current carry but the new carry at market rates is a significant step up

**Detection — explicit (intake):**
- Owns property, reports locked rate significantly below current market rate
- Expresses interest in moving but hasn't committed
- May mention wanting more space, different neighborhood, or life change

**Detection — implicit (behavioral):**
- Asks "should I sell and buy something bigger?" or "is it worth moving right now?"
- Compares current payment to projected new payment
- Asks about renovation or ADU as alternative to moving
- Asks about rate forecasts — "when will rates come down?"
- May ask about renting out current home instead of selling (hybrid occupy/invest)
- Frequently returns to the cost comparison without reaching a decision

**Capacity profile:**
- Significant equity but illiquid
- Rate penalty is the binding constraint, not income or total wealth
- The rate penalty is computed as: `new_PI(balance, market_rate) - current_PI(balance, locked_rate)`
  expressed as a percentage of monthly gross income
- Total wealth (equity + capital) often exceeds what's needed — the problem is the
  ongoing cost structure, not the one-time capital requirement
- May have multiple paths to access equity (sell, HELOC, cash-out refi) each with
  different cost profiles that should be modeled explicitly

**Distinguishing factor from Competitive Bidder:**
Both may have similar total capacity. The difference is the rate penalty. If the buyer
owns a property but `rate_penalty_pct <= buyer_tolerance`, they're a Competitive Bidder
with full optionality — the rate doesn't meaningfully constrain their decision. The
Equity-Trapped Upgrader is specifically defined by the rate penalty exceeding their
tolerance.

---

#### 2.1.6 Competitive Bidder

**Definition:** A buyer with full optionality — adequate capital, adequate income, either
no existing property or an existing property where the rate penalty is tolerable. Their
constraint is not financial capacity but market competition: limited supply and intense
demand in their target segment.

**Computed conditions:**
- `true_monthly_cost(target_price, market_rate, down_pct) <= max_monthly`
- Has capital for 20%+ down payment (potentially combining liquid capital + accessible equity)
- If owns existing property: `rate_penalty_pct <= buyer_tolerance`
- Supply pool exists but competition metrics are elevated (high sale-to-list ratio,
  low DOM, high % sold above list in target neighborhoods)

**Detection — explicit (intake):**
- Strong financial profile across all factors
- Intent is occupy
- If owns property, rate penalty is manageable

**Detection — implicit (behavioral):**
- Asks about specific properties, not about whether they can afford to buy
- Asks "is this worth $X?" or "how much should I offer?"
- References having lost previous bidding wars
- Asks about comp sales, sale-to-list ratios, offer strategy
- Questions are tactical ("should I waive inspection?") rather than foundational
- May express frustration with the process — they can afford it but keep losing

**Capacity profile:**
- Full financial capacity — capital, income, and (if applicable) manageable rate exposure
- The constraint is competition, not resources
- Can structure strong offers: large down payment, fewer contingencies, flexible closing
- May benefit from identifying less competitive micro-markets with similar housing stock

**Competition metrics that matter to this segment:**
- Neighborhood-level sale-to-list ratio (how much over asking is typical here?)
- Neighborhood-level DOM (how fast do they need to decide?)
- Number of recent sales above list vs. below (how broad is the competition?)
- ML model prediction vs. list price (is the listing priced to generate a war, or priced at value?)

---

### 2.2 Invest Segments

#### 2.2.1 Cash Buyer

**Definition:** An investor with sufficient liquid capital to purchase outright without
financing. Rate-immune by definition.

**Computed conditions:**
- `liquid_capital >= target_price`
- Intent is invest

**Detection — explicit (intake):**
- Reports capital sufficient for all-cash purchase
- Intent is invest / income / return-oriented

**Detection — implicit (behavioral):**
- Doesn't ask about mortgage rates or financing
- Asks about yield, cap rate, cash-on-cash return
- Compares real estate returns to alternative investments (stocks, bonds, treasuries)
- May ask about 1031 exchanges (deferring capital gains from a prior sale)
- Focused on net operating income, not monthly mortgage payment

**Capacity profile:**
- Capital exceeds property price — no financing needed
- Opportunity cost of capital is the primary concern, not borrowing cost
- Can close faster than financed buyers (competitive advantage in bidding)
- No PMI, no rate sensitivity, no debt service coverage requirements

**Key consideration:** For a cash buyer, the relevant comparison isn't mortgage rate —
it's the return they'd earn deploying the same capital elsewhere. If treasuries yield 4.5%
risk-free, a Berkeley rental yielding 3.5% with management headaches and illiquidity needs
an appreciation thesis to justify the deployment.

---

#### 2.2.2 Equity-Leveraging Investor

**Definition:** An existing property owner who wants to acquire an investment property
using equity from their current home, without selling it.

**Computed conditions:**
- Owns existing property with `accessible_equity > 0`
- Does not intend to sell existing property
- Plans to access equity via HELOC or cash-out refi for the down payment on a second property
- Intent is invest

**Detection — explicit (intake):**
- Owns home, wants to keep it
- Interested in acquiring a rental or investment property
- Asks about using equity as source of funds

**Detection — implicit (behavioral):**
- Asks about HELOC rates, terms, or qualification
- Asks "can I use my home equity to buy a rental?"
- Discusses carrying two mortgages
- Asks about rental income covering the second mortgage
- May ask about LLC structuring or liability separation

**Capacity profile:**
- Equity is the primary capital source — but accessing it has a cost
  (HELOC at variable rate, or cash-out refi replacing locked rate)
- Must qualify for debt service on both properties
- The investment must clear a higher bar than for a cash buyer because the cost of
  capital includes the HELOC/refi cost, not just opportunity cost
- Rental income from the new property must cover: second mortgage P&I + property taxes
  + insurance + maintenance + vacancy + the cost of accessing equity (HELOC payment)

**Key risk:** Double leverage. If the rental underperforms (vacancy, rent control limits,
major repair), the buyer is servicing two properties from their employment income. The
HELOC is typically variable-rate, adding rate risk on top of property risk.

---

#### 2.2.3 Leveraged Investor

**Definition:** An investor using conventional financing where the property's yield exceeds
their borrowing cost — positive leverage. Cashflow-positive from day one.

**Computed conditions:**
- `leverage_spread = property_cap_rate - mortgage_rate > 0`
- Has capital for down payment but not for all-cash purchase
- Intent is invest

**Detection — explicit (intake):**
- Capital for down payment, seeking financing for the balance
- Looking for cashflow-positive investment

**Detection — implicit (behavioral):**
- Asks about cap rates and whether they exceed the mortgage rate
- Focused on positive monthly cash flow, not appreciation
- Asks about debt service coverage ratio (DSCR) loans
- May compare properties primarily by yield spread

**Capacity profile:**
- Positive leverage — each borrowed dollar increases returns
- The property generates enough income to cover all carrying costs including debt service
- The spread between cap rate and mortgage rate determines the excess cash flow

**Current market note:** This segment is only active when borrowing costs are below
achievable cap rates. Whether this condition exists must be computed per property using
the system's rental income estimates and current mortgage rates — not assumed from
market-wide averages. In markets where cap rates are compressed relative to borrowing
costs, this segment may have zero active participants.

---

#### 2.2.4 Value-Add Investor

**Definition:** An investor whose return thesis depends on creating value through
development — ADU construction, SB 9 lot split, conversion, renovation — rather than
passive income from the property as-is.

**Computed conditions:**
- `development_ROI(project_cost, carrying_cost_at_rate, value_created) > required_return`
- Leverage spread on the property as-is may be negative — the investment thesis depends
  on transforming the property, not holding it
- Has capital for acquisition plus development costs (or phased financing plan)
- Intent is invest with development component

**Detection — explicit (intake):**
- Expresses interest in adding units, building an ADU, lot splitting
- Asks about zoning capacity, entitlements, development feasibility

**Detection — implicit (behavioral):**
- Asks about ADU regulations, SB 9 eligibility, zoning before asking about comps or price
- Asks about building-to-lot ratio, unused FAR, setback requirements
- Asks about permit history or construction costs
- Evaluates properties by development potential rather than current condition
- May ask about contractor availability, timeline, or phasing
- Asks about post-development value or post-development rental income

**Capacity profile:**
- Must fund acquisition + development costs (potentially $150K-$500K+ beyond purchase)
- Carrying costs during development (permits, construction, no rental income) must be
  sustainable from income or reserves
- The ROI calculation is: `(post_development_value - acquisition_cost - development_cost
  - carrying_costs_during_development) / total_invested`
- Timeline matters — longer development = more carrying cost = lower ROI
- Zoning and regulatory feasibility is a prerequisite, not just a nice-to-have

**Key distinction from other investor segments:** The Value-Add Investor isn't buying
income — they're buying a transformation opportunity. The property's current yield is
often irrelevant. What matters is what the property *could become* under its zoning
and what the delta in value would be.

---

#### 2.2.5 Appreciation Bettor

**Definition:** An investor who accepts negative cash flow (carrying costs exceed rental
income) based on a thesis that price appreciation will more than compensate.

**Computed conditions:**
- `leverage_spread < 0` (borrowing costs exceed property yield)
- No development intent — holding the property as-is
- `projected_appreciation_rate > negative_carry_cost / property_value` (the appreciation
  thesis must justify the ongoing loss)
- Has income or reserves to sustain the negative carry indefinitely

**Detection — explicit (intake):**
- Acknowledges the property won't cashflow
- Expresses conviction about Berkeley's price trajectory
- May reference plans to refinance when rates drop

**Detection — implicit (behavioral):**
- Asks about price appreciation history, neighborhood trajectory
- Asks "when will rates come down?" or "should I buy now and refinance later?"
- Accepts negative cash flow numbers without concern
- Focuses on total return (appreciation + equity buildup) rather than monthly income
- Asks about comparable appreciation in prior rate cycles
- May ask about tax benefits of carrying costs (mortgage interest deduction, depreciation)

**Capacity profile:**
- Must have income or reserves to cover the negative carry for an extended period
- The negative carry = `true_monthly_cost - rental_income`
- The bet has a breakeven timeline: how many years of appreciation does it take to
  recover the cumulative negative carry?
- Rate sensitivity is high — if they're betting on refinancing, the bet fails if rates
  don't decline within their expected timeframe
- More speculative than other investor segments — outcome depends on macro conditions
  (rates, market trajectory) more than property-specific factors

**Key risk Faketor should surface:** The appreciation thesis has a specific, calculable
breakeven. If Berkeley appreciates at X% annually, the cumulative negative carry is
recovered in Y years. If appreciation is lower than expected, or if the holding period
is shorter than planned, the investment may lose money. This should be modeled explicitly,
not left as a vague conviction.

---

### 2.3 Segment Transitions

Segments are not permanent. A buyer can move between segments as their circumstances or
the market changes:

| Trigger | Transition |
|---------|-----------|
| Rate drops by 100bps+ | Equity-Trapped Upgrader → Competitive Bidder (rate penalty shrinks below tolerance) |
| Rate drops below cap rate | Appreciation Bettor → Leveraged Investor (spread turns positive) |
| Buyer saves more capital | Stretcher → Down Payment Constrained → First-Time Buyer (capital accumulation) |
| Buyer receives inheritance / windfall | Multiple segments shift — capital constraint removed |
| Buyer sells existing property | Equity-Trapped Upgrader → First-Time Buyer or Competitive Bidder (equity becomes capital) |
| Market correction (prices drop) | Not Viable → Stretcher (supply pool opens at lower prices) |
| Buyer's income changes | Ripples through max_monthly → max_purchase_price → supply_pool → segment |
| Buyer shifts intent (occupy → invest) | Moves to entirely different segment branch |
| Buyer discovers development potential | Cash-Flow Investor → Value-Add Investor (new thesis) |

**Implication for Faketor:** Segment detection is not a one-time classification. As the
conversation evolves and the buyer explores different scenarios ("what if I put less down?",
"what if I looked at duplexes?", "what about renting my current place instead of selling?"),
the inputs to the decision tree change, and the segment may shift. Faketor should recompute
the segment when material inputs change and adjust its behavior accordingly — including
explicitly noting the shift: "Based on what you're describing, this looks more like an
investment decision than a primary residence purchase. That changes the analysis."

---

## 3. Jobs to Be Done

Each segment hires Faketor for a specific job. Following Christensen's JTBD framework,
each job has three dimensions: functional (the practical task), emotional (how the buyer
wants to feel), and social (how the buyer wants to be perceived). The functional dimension
determines tool selection. The emotional dimension determines tone and framing. The social
dimension explains decisions that the functional analysis alone wouldn't predict.

### 3.1 Job Structure

Each segment's job is defined as:

- **Primary job**: The core progress the buyer is trying to make
- **Secondary job**: What Faketor should proactively raise even if the buyer doesn't ask
- **Functional dimension**: The practical work — analysis, computation, comparison
- **Emotional dimension**: The feeling the buyer needs from the interaction
- **Social dimension**: The identity or status concern influencing the decision
- **"Done" looks like**: How the buyer knows the job is complete — the state they're
  trying to reach

### 3.2 Occupy Segment Jobs

#### 3.2.1 Not Viable

**Primary job:** "Help me understand what would need to change for me to buy in Berkeley."

**Secondary job:** "Are there adjacent markets where my situation is viable right now?"

**Functional dimension:**
- Sensitivity analysis: which input change (income, capital, rate, market prices) would
  move them into a viable segment, and by how much?
- Adjacent market comparison: what does their budget access in Oakland, Richmond, El Cerrito,
  Albany?
- Timeline projection: if they save at rate X, when do they cross the viability threshold
  (accounting for potential price appreciation working against them)?

**Emotional dimension:**
- The buyer needs to feel **informed, not dismissed**. Being told "you can't afford Berkeley"
  without a path forward feels like a judgment. The emotional job is: "Tell me I have options,
  even if they're not the ones I hoped for."
- Faketor should present the analysis as empowering ("here's exactly what it would take")
  rather than gatekeeping ("you can't do this").

**Social dimension:**
- Homeownership as a milestone — the buyer may feel pressure from peers, family, or
  cultural expectations to own. Being told they can't afford it touches identity, not just
  finances.
- Faketor should not address this directly (it would feel patronizing) but should be aware
  that the buyer may make decisions that prioritize getting in (stretching, adjacent markets)
  over strictly optimal financial outcomes.

**"Done" looks like:**
- The buyer has a clear, specific understanding of the gap between their current situation
  and Berkeley viability
- They have a concrete plan: save $X more, wait for rates to hit Y%, or explore [specific
  adjacent market]
- OR they have made an informed decision that Berkeley isn't right for them right now

---

#### 3.2.2 Stretcher

**Primary job:** "Help me understand whether buying at my price point makes financial sense,
or if I'm better off renting and investing the difference."

**Secondary job:** "If I do buy, what are the risks I'm not seeing as a current renter?"

**Functional dimension:**
- Rent-vs-buy breakeven analysis at their specific price point, factoring in true costs
  (not just PITI), appreciation assumptions, tax benefits, and opportunity cost of down payment
- PMI duration modeling: when does equity reach 80% LTV given their down payment and
  expected appreciation?
- Stress testing: what happens to their monthly budget if rates rise (for ARM), if a major
  repair hits, if they lose income temporarily?
- Neighborhood options at their price point: where does their budget actually have supply?

**Emotional dimension:**
- The buyer needs **reassurance that they're not making a catastrophic mistake** — or honest
  guidance that they should wait. The emotional job is: "Either give me confidence to proceed
  or save me from a bad decision."
- This segment is the most anxiety-prone. They know they're stretching. They need Faketor
  to be the honest advisor who says "the math works, here's why" or "the math doesn't work,
  here's why" — not a cheerleader and not a pessimist.
- Framing matters: "At your price point, buying breaks even with renting after 8 years.
  If you're confident you'll stay at least that long, it's a reasonable decision" is more
  useful than either "go for it!" or "you can't afford it."

**Social dimension:**
- Peer pressure to own may be driving the decision. The buyer's friends or family may be
  homeowners. Continued renting may feel like falling behind.
- Faketor should present the honest financial comparison without judgment about the
  renting decision. Renting is not failing — it may be the financially optimal choice at
  this price point in this rate environment.

**"Done" looks like:**
- The buyer has a clear rent-vs-buy comparison for their specific situation
- They understand the breakeven timeline and the risks
- They've either decided to proceed (with eyes open) or decided to wait (with a plan for
  when conditions change)

---

#### 3.2.3 First-Time Buyer

**Primary job:** "Help me figure out where I should buy and how much I should put down —
I have the resources but I've never done this before."

**Secondary job:** "What am I not thinking about? What do first-time buyers get wrong?"

**Functional dimension:**
- Neighborhood analysis: which neighborhoods match their lifestyle needs (commute, schools,
  character) within their budget?
- Down payment optimization: is 20% the right amount, or should they put down more (lower
  payment) or less (preserve liquidity)?
- Price validation: for specific properties, are they fairly priced relative to comps
  and the ML model prediction?
- Process guidance: what to expect in inspections, contingencies, closing timeline

**Emotional dimension:**
- The buyer needs to feel **navigated through an unfamiliar process**. Buying a home for
  the first time is overwhelming — not because the math is hard but because the process
  is opaque and the stakes feel enormous.
- The emotional job is: "Make this terrifying process feel manageable. Tell me what I
  should pay attention to and what I can safely ignore."
- Faketor should proactively explain things the buyer might not know to ask about:
  property tax reassessment, title insurance, escrow, inspection red flags, the
  difference between list price and likely close price in Berkeley.

**Social dimension:**
- Homeownership as achievement — first-time buyers often experience the purchase as a
  life milestone. The announcement matters.
- This can lead to overpaying for "the story" (the charming Craftsman, the tree-lined
  street) vs. the financially optimal choice. Faketor shouldn't suppress this but should
  ensure the buyer sees both the emotional appeal and the financial reality.

**"Done" looks like:**
- The buyer has identified 2-3 target neighborhoods that fit their needs and budget
- They understand how Berkeley's competitive dynamics work (bidding wars, over-asking offers)
- They have a down payment strategy
- They feel prepared to make offers, not paralyzed by uncertainty

---

#### 3.2.4 Down Payment Constrained

**Primary job:** "Help me decide: buy now with PMI and start building equity, or wait
until I've saved enough to avoid PMI?"

**Secondary job:** "Is there a stepping-stone strategy — buy something smaller now and
upgrade later?"

**Functional dimension:**
- PMI cost modeling: exact PMI amount at their down payment percentage, and how long
  until it drops off given expected appreciation and principal paydown
- Buy-now-vs-wait comparison: cost of PMI over the expected duration vs. potential price
  appreciation they'd miss by waiting (a race between their savings rate and the market)
- Stepping-stone analysis: if they buy a condo at $700K with 20% down (no PMI) and plan
  to upgrade in 5 years, does the equity buildup + appreciation get them to 20% down on
  their target SFR?
- Down payment assistance programs: FHA, CalHFA, conventional at 5%, employer programs

**Emotional dimension:**
- The buyer needs to feel like they have a **smart strategy, not a desperation move**.
  Buying with PMI can feel like "settling" or "doing it wrong." The emotional job is:
  "Show me that this is a calculated decision, not a compromise."
- If the analysis shows that buying now with PMI is better than waiting (because price
  appreciation outpaces savings), that's empowering. If it shows waiting is better,
  that's also empowering — they need the framework to decide, not a blanket recommendation.

**Social dimension:**
- Similar to the Stretcher — peer pressure to own. But the Down Payment Constrained buyer
  has high income, which creates a specific tension: "I earn enough that I should be able
  to buy, so why can't I?" The gap between income and capital can feel like a personal
  failure rather than a structural issue (it takes years to save $250K+ even at high income).
- Faketor should normalize this: the down payment barrier in Berkeley is a market structure
  issue, not a personal shortcoming.

**"Done" looks like:**
- The buyer has a clear comparison of buy-now-with-PMI vs. wait-and-save scenarios
- They've evaluated stepping-stone strategies (if applicable)
- They've made a timing decision based on quantified trade-offs, not anxiety

---

#### 3.2.5 Equity-Trapped Upgrader

**Primary job:** "Help me decide whether to move or renovate, given the rate penalty I'd
pay to move."

**Secondary job:** "If I do move, when does it make sense? Is there a rate environment
or life circumstance that changes the math?"

**Functional dimension:**
- Rate penalty quantification: exact monthly cost increase, expressed as dollar amount
  and as percentage of income
- Renovate vs. move comparison: cost of renovating current home (ADU, addition, remodel)
  vs. selling + buying, including transaction costs, rate penalty, and the value created
  by renovation
- Rate scenario modeling: "If rates drop to X%, your penalty shrinks to $Y/month. Here's
  the breakeven."
- Sell-first vs. buy-first timing: if they decide to move, the logistics of coordinating
  two transactions. Bridge loan costs. Rent-back arrangements.
- HELOC vs. sell analysis: if they want to keep the property and rent it out, does the
  rental income cover the existing mortgage? What's the net after expenses?

**Emotional dimension:**
- The buyer needs either **validation that staying is smart** or **permission to take the
  leap**. They're stuck between "I have a great rate and leaving feels stupid" and "this
  house doesn't work for my life anymore."
- The emotional job is: "Help me stop agonizing. Give me a clear enough picture that I
  can commit to one direction."
- Faketor should present both paths without advocacy. The goal is decision clarity, not
  a recommendation. The right choice depends on non-financial factors (space needs, family
  changes, neighborhood preferences) that only the buyer can weigh.

**Social dimension:**
- Staying in a "starter home" long-term can feel like stagnation. The buyer may see peers
  upgrading and feel pressure to do the same, even when the math says staying is better.
- Conversely, leaving a great rate may feel irresponsible — "everyone says never give up
  a low rate."
- Both narratives exist simultaneously. Faketor should present the financial reality and
  let the buyer weigh the non-financial factors themselves.

**"Done" looks like:**
- The buyer has a clear, quantified comparison of move vs. renovate
- They understand the rate penalty in concrete terms (not just "rates are high")
- They have rate scenario awareness — what rate environment would change the answer
- They've made a decision or identified the specific trigger that would change their mind

---

#### 3.2.6 Competitive Bidder

**Primary job:** "Help me win a property without overpaying. How much above asking is
rational for this specific property?"

**Secondary job:** "Am I targeting the right neighborhoods, or is there less competitive
supply with similar housing stock?"

**Functional dimension:**
- Comp-based price conviction: what did similar properties actually close at vs. list?
  What's the sale-to-list ratio in this specific neighborhood?
- ML model prediction vs. list price: is the asking price already at fair value, or is it
  priced low to generate a bidding war? What's the confidence interval?
- Competition assessment: DOM, sale-to-list, % sold above list in the target micro-market.
  How many competing buyers should they expect?
- Alternative supply identification: are there neighborhoods with similar housing stock
  but lower competition metrics? Is the buyer's target neighborhood objectively better, or
  is it just more popular?
- Offer strategy context: what do strong offers look like in this micro-market? Is it
  about price, contingency waiver, closing speed, or all three?

**Emotional dimension:**
- The buyer needs **calm in the face of bidding pressure**. The emotional experience of
  repeatedly losing is demoralizing and can lead to panic overbidding — "just bid whatever
  it takes."
- The emotional job is: "Help me stay disciplined. Tell me when I'm bidding rationally
  and when I'm overpaying out of desperation."
- Faketor should normalize losing bids: "You lost because the winning bidder paid 12%
  above the model's fair value estimate. Your discipline saved you from overpaying. The
  right property will come." This is the emotional equivalent of a comp analysis — it's
  calibrating the buyer's emotional state, not just their offer price.

**Social dimension:**
- Bidding wars create urgency and FOMO. Friends who bought last year "before it got worse"
  reinforce the pressure. The buyer may feel they're running out of time.
- Faketor should counter narrative pressure with data: "Berkeley's inventory has been
  tight for [X years]. This isn't a new phenomenon. Taking an extra month to find the
  right property at the right price is almost always better than overpaying."

**"Done" looks like:**
- The buyer has a clear, data-backed price range for their target property
- They understand how much over asking is typical and rational in their target neighborhood
- They've either won a bid at a price they're comfortable with, or they've broadened their
  search to less competitive areas
- They feel in control of the process, not reactive to it

---

### 3.3 Invest Segment Jobs

#### 3.3.1 Cash Buyer

**Primary job:** "Where is the best risk-adjusted deployment of my capital — and is
Berkeley real estate better than my alternatives?"

**Secondary job:** "What are the management realities and regulatory risks I should price in?"

**Functional dimension:**
- Yield comparison: net operating income / purchase price vs. alternative investments
  (treasuries, REITs, equities, other markets)
- Net operating income modeling: rental income - property tax - insurance - maintenance -
  vacancy - management fees. Per property, not market averages.
- Regulatory risk assessment: Berkeley rent control implications, tenant protections,
  eviction restrictions — these directly affect income certainty and exit flexibility
- Portfolio impact: if they own other properties, how does this one correlate?
  Diversification value vs. concentration risk in Berkeley.
- 1031 exchange implications: if deploying proceeds from a prior sale, timeline and
  qualification constraints

**Emotional dimension:**
- The buyer needs **confirmation of analytical superiority** — or honest challenge to their
  thesis. Cash buyers are typically experienced and data-driven. They want Faketor to be
  a rigorous analytical partner, not a hand-holder.
- The emotional job is: "Validate my analysis or show me what I'm missing. Don't
  waste my time with basics."
- Faketor should match the buyer's sophistication level. Skip explanations of how
  mortgages work. Go straight to NOI, cap rate compression trends, and regulatory risk.

**Social dimension:**
- Investment competence as identity. The cash buyer views themselves as a sophisticated
  investor. Presenting analysis that's too basic undermines the relationship. Analysis
  that surfaces something they hadn't considered earns trust.

**"Done" looks like:**
- The buyer has a clear comparison of this property's risk-adjusted yield vs. alternatives
- They understand Berkeley-specific regulatory risks and have priced them in
- They've decided to deploy capital here or identified a better deployment

---

#### 3.3.2 Equity-Leveraging Investor

**Primary job:** "Can I use my home equity to acquire an investment property without
selling, and does the math work?"

**Secondary job:** "What's the risk if the rental underperforms — can I carry both
properties from income alone?"

**Functional dimension:**
- HELOC vs. cash-out refi analysis: cost of each equity access method, impact on existing
  mortgage, variable vs. fixed rate exposure
- Dual-property cash flow model: combined carrying costs of both properties vs. combined
  income (employment + rental). Stress test: what if vacancy hits 2 months? What if HELOC
  rate rises?
- Debt-service qualification: can they qualify for the second mortgage given existing
  obligations? What do lenders require?
- Rental income requirements: how much does the investment property need to generate
  to make the dual-carry sustainable?
- Entity structuring considerations: LLC for liability separation? Insurance implications?

**Emotional dimension:**
- The buyer needs to feel **entrepreneurial but not reckless**. Using home equity to invest
  feels bold — which can be exciting or terrifying depending on how well they understand
  the risk.
- The emotional job is: "Show me the upside clearly, but don't hide the downside. I want
  to feel smart about this, not naive."

**Social dimension:**
- "Building a real estate portfolio" carries status. The buyer may be influenced by
  investment communities (BiggerPockets, real estate Twitter) that normalize leveraged
  acquisition. Faketor should present the math without endorsing or discouraging the
  narrative — let the numbers speak.

**"Done" looks like:**
- The buyer has a clear dual-property cash flow model showing best case, expected case,
  and stress case
- They understand the cost of accessing their equity under each method
- They've decided whether the risk-adjusted return justifies the double leverage
- They have a plan for the downside scenario (vacancy, repair, rate increase on HELOC)

---

#### 3.3.3 Leveraged Investor

**Primary job:** "Find me properties where the yield exceeds my borrowing cost — positive
leverage from day one."

**Secondary job:** "How durable is the positive spread? What would erode it?"

**Functional dimension:**
- Property-level cap rate computation: using the system's rental income estimates and
  true operating expenses, not advertised NOI
- Spread analysis: cap rate minus mortgage rate, per property. Filter for positive spread.
- Spread durability: what happens to the spread if rents decline (rent control, market
  softening), if expenses increase (insurance, maintenance), or if rates rise (for ARM
  or on refinance)?
- DSCR qualification: does the property qualify for a DSCR loan based on its income alone?
- Comparison across properties: rank available inventory by leverage spread

**Emotional dimension:**
- The buyer needs **deal-finding confidence**. They know what they're looking for — they
  need Faketor to efficiently filter and rank, not educate.
- The emotional job is: "Be my analyst. Surface the opportunities I might miss and
  validate the ones I find."

**Social dimension:**
- Minimal — this is the most purely analytical segment. Social factors play less role
  than in any other segment.

**"Done" looks like:**
- The buyer has a ranked list of properties with positive leverage spread
- They understand the sensitivity of the spread to rent changes, expense changes, and
  rate changes
- They've identified 1-3 targets worth pursuing

---

#### 3.3.4 Value-Add Investor

**Primary job:** "Find me properties with development upside — where zoning allows what I
want to build and the numbers work after accounting for carrying costs."

**Secondary job:** "What does the realistic timeline look like, and how does that affect
the ROI?"

**Functional dimension:**
- Zoning and regulatory screening: ADU feasibility, SB 9 lot-split eligibility, maximum
  buildable units, setback requirements, height limits, parking requirements
- Development ROI modeling: acquisition cost + development cost + carrying costs during
  construction vs. post-development value. With carrying costs computed at the current rate
  environment, not abstract.
- Timeline estimation: permit processing time, construction duration, lease-up period.
  Each phase has carrying costs.
- Improvement simulation: the system's tool that models the value impact of specific
  improvements (ADU, kitchen, solar, seismic retrofit)
- Post-development income modeling: what does the property yield after development is
  complete? Does the new income justify the total investment?
- Permit history: what has been built or attempted on this property before? Are there
  existing permits that signal feasibility or complications?

**Emotional dimension:**
- The buyer needs to feel like they **see something others don't**. Value-add investing
  is about finding the hidden upside. The emotional job is: "Confirm my vision for this
  property, or tell me I'm wrong before I spend $300K finding out."
- Faketor should be rigorous about feasibility. A regulatory constraint that kills the
  project should be surfaced immediately, not discovered after acquisition. The emotional
  value is in early, clear disqualification as much as in confirmation.

**Social dimension:**
- Builder/developer identity. The value-add investor sees themselves as someone who creates
  value, not just captures it. Faketor should engage at that level — discuss the
  transformation, not just the spreadsheet.

**"Done" looks like:**
- The buyer has identified properties with confirmed development feasibility (zoning allows
  what they want to build)
- They have a realistic ROI model that includes carrying costs, timeline, and
  post-development income
- They understand the regulatory pathway (what permits are needed, estimated timeline)
- They've decided to pursue a specific project or ruled it out based on the numbers

---

#### 3.3.5 Appreciation Bettor

**Primary job:** "Does the appreciation thesis justify the negative carry? Model the
breakeven for me."

**Secondary job:** "What happens if my thesis is wrong — if rates don't drop, or
appreciation slows?"

**Functional dimension:**
- Breakeven modeling: at X% annual appreciation, how many years until cumulative
  appreciation exceeds cumulative negative carry? Present multiple scenarios (3%, 5%, 7%
  appreciation).
- Refinance scenario: if rates drop to Y%, what's the new monthly carry? At what rate
  does the property become cashflow-positive?
- Historical context: what has Berkeley appreciation looked like over 5, 10, 20 year
  periods? What were the worst 5-year stretches?
- Downside modeling: if prices decline 10%, what's the combined loss (negative carry +
  equity loss)? How long to recover?
- Tax benefit offset: mortgage interest deduction, depreciation (if rental) — how much
  does the after-tax cost differ from the pre-tax negative carry?
- Exit analysis: if the buyer needs to sell in 3 years instead of 10, what's the likely
  outcome given transaction costs?

**Emotional dimension:**
- The buyer needs **thesis validation or honest challenge**. They've already decided they
  believe in Berkeley's appreciation. The emotional job is: "Stress-test my conviction.
  If it holds up, I'll feel confident. If it doesn't, I'd rather know now."
- Faketor should not be a cheerleader ("Berkeley always goes up!") or a pessimist
  ("you're speculating"). It should present the scenarios with equal rigor and let the
  buyer evaluate their own risk tolerance.

**Social dimension:**
- "Buying in Berkeley" carries status independent of the financial outcome. The buyer
  may be partly motivated by owning in a prestigious market. This is a legitimate
  factor but should not be confused with the financial thesis.

**"Done" looks like:**
- The buyer has a clear breakeven timeline under multiple appreciation scenarios
- They understand the downside: what happens if appreciation is flat for 5 years
- They've stress-tested their refinance assumption against multiple rate scenarios
- They've made a decision based on quantified risk, not vague conviction

---

### 3.4 Cross-Cutting Observations

**The emotional dimension is most important for Occupy segments.** Buying a home to live
in is inherently emotional — it's where you'll raise your kids, have your daily life,
feel safe. Invest segments are more analytical by nature. Faketor's tone calibration
should reflect this: warmer and more reassuring for Occupy, more clinical and direct
for Invest.

**The secondary job is often more valuable than the primary.** The buyer usually knows
their primary job — they came to Faketor with a question. The secondary job is what they
didn't think to ask. A Stretcher who gets a rent-vs-buy analysis they didn't request may
get more value from that than from the affordability calculation they did request. Proactive
delivery of secondary jobs is where Faketor differentiates from passive tools like Zillow.

**"Done" is a state, not a transaction.** The buyer's job isn't "buy a house" — it's
"reach confidence about a decision." They might decide to buy, decide to wait, decide
to rent, or decide to invest elsewhere. All of these are successful completions of the
job. Faketor should optimize for decision quality, not for closing a transaction.

---

## 4. Competing Solutions

For each segment, Faketor competes against different alternatives. Understanding what the
buyer would "hire" instead tells us what Faketor must be better at and what it should not
try to replicate. Christensen's framework is explicit: the competition isn't always another
product in the same category. Often it's non-consumption ("do nothing") or a solution from
a completely different category.

### 4.1 The Competitive Landscape by Segment

#### 4.1.1 Not Viable

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Zillow / Redfin calculators** | Quick affordability estimate; free; always available | P&I-only framing overstates what the buyer can afford; doesn't account for true costs; doesn't tell the buyer they can't afford it — just shows listings | Faketor's advantage is honesty. It should tell the buyer the truth and show what would need to change. Zillow wants engagement; Faketor should want decision quality. |
| **Friends / family advice** | Emotional support; shared experience; trust | Often wrong about market specifics; advice based on their own different situation (different income, different era, different market); may push homeownership as a universal good | Faketor provides specific, quantified analysis vs. anecdotal reassurance. |
| **Non-consumption (do nothing)** | No effort, no risk, no cost | The buyer remains in uncertainty — they don't know if they can't afford it or just haven't looked hard enough | Faketor converts uncertainty into clarity. Even "you can't buy in Berkeley right now" is progress vs. not knowing. |

**Faketor's win condition:** Be the only solution that gives a specific, honest, quantified
answer: "Here's exactly what would need to change, and here are your alternatives."

---

#### 4.1.2 Stretcher

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Zillow / Redfin** | Broad listings; mortgage estimate; "you can afford" messaging encourages engagement | Systematically understates true cost (P&I only or PITI without earthquake/maintenance); designed to convert browsers into buyers, not to protect buyers from bad decisions | Faketor's advantage is true-cost analysis. Showing the real monthly cost including maintenance, earthquake insurance, and PMI — and comparing honestly to renting. |
| **Mortgage broker / lender** | Pre-approval gives buying power clarity; explains loan programs | Incentivized to get the buyer into a loan — they earn fees on origination, not on good advice; will approve the buyer for more than they should borrow | Faketor has no origination incentive. It can say "you qualify for $800K but should probably buy at $650K" without losing a commission. |
| **Rent-vs-buy calculators (NYT, Nerdwallet)** | Quick directional answer | Simplistic — typically assume national averages for maintenance, insurance, appreciation; don't account for Berkeley-specific costs (earthquake, high property tax, older housing stock) | Faketor can run the rent-vs-buy analysis with Berkeley-specific inputs and the buyer's actual numbers, not national defaults. |
| **Non-consumption (keep renting)** | Zero risk, zero effort, preserves flexibility | No equity buildup; rent may rise; no stability of ownership | This is a legitimate outcome. Faketor should not treat "keep renting" as a failure — it may be the right answer. The competition is Faketor's own honesty. |

**Faketor's win condition:** Be the advisor who prevents the Stretcher from making a mistake
that Zillow and a mortgage broker would have encouraged.

---

#### 4.1.3 First-Time Buyer

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Human buyer's agent** | Tours homes; negotiates offers; provides relationship-based market knowledge; handles transaction logistics; has relationships with listing agents that can win deals | Incentivized by commission (2.5-3% of purchase price) — higher price = higher commission; may steer toward properties with cooperative brokers; quality varies enormously; time-limited attention | Faketor provides quantitative analysis without commission incentive. Can't tour homes or negotiate, but can provide data-driven price validation and neighborhood intelligence that many agents don't offer. |
| **Parents / family** | Trusted relationship; may provide financial assistance; emotional support | Advice based on different era (parents bought at different prices, rates, and market conditions); may prioritize emotional factors over financial ones; geographic knowledge may be outdated or absent for Berkeley | Faketor provides current, Berkeley-specific, quantitative context that family advice lacks. |
| **Online forums (Reddit, BiggerPockets)** | Crowd-sourced experience; diverse perspectives; free | Anecdotal; contradictory advice; no personalization; Berkeley-specific advice may be sparse or wrong | Faketor provides personalized, data-backed analysis for their specific situation. |
| **Zillow / Redfin** | Listings, estimates, neighborhood data | Zestimate accuracy is poor for Berkeley's heterogeneous housing stock; doesn't help with bidding strategy; no process guidance | Faketor has Berkeley-specific ML model trained on local data, plus comp-based analysis that accounts for neighborhood micro-markets. |

**Faketor's win condition:** Be the analytical complement to a human agent — not a
replacement. The First-Time Buyer likely still needs an agent for tours, negotiation, and
transaction management. Faketor's role is providing the quantitative backbone and process
education the agent may not deliver.

**Important limitation:** Faketor cannot tour properties, negotiate offers, write contracts,
or manage the transaction. It should be explicit about this and encourage the buyer to work
with a competent agent for execution while using Faketor for analysis and education.

---

#### 4.1.4 Down Payment Constrained

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Mortgage broker** | Knows all the loan programs (FHA, CalHFA, conventional at 5%, employer programs); can find the best rate for the buyer's profile | Incentivized toward origination, not optimization; may not present "wait and save" as an option because it generates no fees; won't model the buy-now-vs-wait tradeoff | Faketor can model the PMI cost over time, the appreciation race, and the wait-vs-buy tradeoff without origination incentive. |
| **Financial advisor** | Holistic financial planning; considers the down payment in context of retirement savings, emergency fund, other goals | Typically doesn't have real estate market expertise; may not know Berkeley-specific dynamics; hourly or AUM fees may be a barrier | Faketor combines financial modeling with Berkeley-specific market data — something neither a generic financial advisor nor a mortgage broker offers. |
| **Online calculators (PMI calculators, rent-vs-buy)** | Quick directional answers; free | Don't model the dynamic race between savings rate and appreciation; don't consider stepping-stone strategies; national defaults, not Berkeley-specific | Faketor models the specific tradeoff: "If you save $3K/month, you'll reach 20% down in 18 months. But if Berkeley appreciates 5% in that time, your target price moves up and you're still short." |

**Faketor's win condition:** Be the only tool that models the buy-now-vs-wait decision
as a dynamic race between the buyer's savings rate and the market's appreciation rate,
with Berkeley-specific inputs.

---

#### 4.1.5 Equity-Trapped Upgrader

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Human agent** | Can assess renovation feasibility physically; knows the resale market for the current home; can coordinate buy-sell timing | May be incentivized toward selling (commission on two transactions); unlikely to model the rate penalty quantitatively; renovation assessment is qualitative, not ROI-modeled | Faketor provides the quantitative framework: rate penalty calculation, renovate-vs-move ROI, rate scenario modeling. Agent provides the execution. |
| **Contractor** | Can estimate renovation costs accurately; knows what's buildable | Incentivized to do the work; won't model whether the renovation is a better financial decision than moving; doesn't know the buyer's broader financial picture | Faketor models the renovation decision in context — does the ADU ROI exceed the cost of moving? The contractor provides the cost input; Faketor provides the analysis. |
| **Financial advisor** | Can model the rate penalty in context of total financial picture | Doesn't know Berkeley's market dynamics; can't assess renovation value or neighborhood appreciation differentials | Faketor combines rate penalty math with Berkeley-specific appreciation data, renovation ROI modeling, and neighborhood intelligence. |
| **Non-consumption (stay and do nothing)** | Zero cost, zero risk, preserves the great rate | The buyer remains in a home that doesn't fit their life; emotional cost of "stuck" grows over time | This is the default competitor. The buyer is already "hiring" non-consumption. Faketor's job is to either validate this choice or present an alternative that justifies the rate penalty. |

**Faketor's win condition:** Be the only tool that models renovate-vs-move as a quantified
comparison, with rate penalty as the central variable, and rate scenarios showing when the
answer changes.

---

#### 4.1.6 Competitive Bidder

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Human agent with local relationships** | Off-market access; relationships with listing agents that can tip bidding dynamics; can read seller motivation; knows which listing agents price low to generate wars | Comp analysis is often gut-feel rather than data-driven; may encourage higher bids to close the deal (commission incentive); not every agent has local relationships | Faketor provides quantitative comp analysis and ML-based price prediction that most agents can't match. Can't replace the agent's relationship network or physical presence. |
| **Redfin / Zillow comp tools** | Quick comp lookup; free; accessible | Comp selection is algorithmic but not sophisticated (proximity and recency, not similarity scoring); Zestimate doesn't account for Berkeley micro-market variation; no bidding strategy guidance | Faketor's comp scoring (similarity-weighted by beds/baths/sqft/year) is more sophisticated. The ML model is trained specifically on Berkeley data. |
| **Appraiser** | Professional property valuation | Expensive ($400-600); point-in-time; doesn't provide bidding strategy or competition assessment; appraisals are backward-looking | Faketor provides similar valuation analysis plus forward-looking competition metrics (sale-to-list trends, DOM, inventory) that inform bid strategy. |

**Faketor's win condition:** Be the analytical backbone behind the buyer's bidding decisions.
The agent handles relationships and negotiation. Faketor provides the data conviction: "This
property is worth $1.35M based on comps and the model. The neighborhood's sale-to-list ratio
suggests you'll need to offer $1.42M to compete. Here's the risk if you go higher."

**Important limitation:** Faketor has no off-market access and no relationship with listing
agents. In Berkeley's competitive market, these relationships sometimes matter as much as
price. Faketor should acknowledge this gap rather than pretend it doesn't exist.

---

#### 4.1.7 Cash Buyer (Investor)

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Commercial real estate broker** | Deep market knowledge; off-market deal flow; can source multi-family opportunities; handles transaction | Focused on closing deals (commission); may not provide rigorous yield comparison across asset classes; may not know Berkeley's regulatory landscape in detail | Faketor provides rigorous NOI modeling and regulatory risk assessment. Can't source deals or handle transactions. |
| **Financial advisor / wealth manager** | Portfolio-level asset allocation advice; considers real estate in context of total wealth; risk management | Typically not a real estate specialist; doesn't know Berkeley cap rates, rent control rules, or property-specific dynamics | Faketor provides Berkeley-specific property-level analysis that a generalist wealth manager can't. |
| **BiggerPockets / investor forums** | Experienced investor community; deal analysis frameworks; market intelligence | Generic frameworks not calibrated to Berkeley; advice is anecdotal; may normalize aggressive leverage inappropriate for Berkeley's risk profile | Faketor provides Berkeley-specific data analysis, not generic frameworks. |
| **Spreadsheet (DIY analysis)** | Full control; customizable; no cost | Time-intensive; requires the buyer to source their own data; prone to optimistic assumptions | Faketor provides the data the spreadsheet needs, pre-computed and stress-tested. It's the analyst behind the spreadsheet. |

**Faketor's win condition:** Be the Berkeley-specific analytical engine that feeds
the cash buyer's investment decision. They likely have a broker for deal sourcing and
an advisor for portfolio context. Faketor fills the gap: property-level, Berkeley-specific
analysis with regulatory awareness.

---

#### 4.1.8 Equity-Leveraging Investor

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Mortgage broker** | Knows HELOC products, rates, terms, and qualification requirements | Won't model the dual-property cash flow or stress-test the downside; incentivized to originate | Faketor models the full dual-property picture: HELOC cost + investment property cost vs. combined income. |
| **BiggerPockets / BRRRR community** | Frameworks for leveraged acquisition (Buy, Rehab, Rent, Refinance, Repeat); peer experience | Often normalized for markets cheaper than Berkeley; risk framing may be too aggressive for Berkeley's price points and regulatory environment | Faketor applies the concept to Berkeley's actual numbers, where the stakes are 5-10x higher than the typical BRRRR deal. |
| **Non-consumption (don't expand)** | Preserves financial stability; no additional risk | Opportunity cost of idle equity; no portfolio growth | Faketor's job is to quantify whether the opportunity justifies the risk — and to honestly present the case for staying put when it doesn't. |

**Faketor's win condition:** Be the stress-test for leveraged expansion. The buyer may
have talked themselves into it based on optimistic assumptions. Faketor shows the realistic
downside: "If your tenant vacates for 2 months and the HELOC rate rises 100bps, your
combined monthly shortfall is $X. Can you sustain that from savings?"

---

#### 4.1.9 Leveraged Investor

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Commercial broker** | Deal sourcing; knows which properties cash flow | Commission incentive; may overstate projected rents or understate expenses | Faketor provides independent yield analysis using the system's own rental estimates, not the broker's projections. |
| **DSCR lender** | Underwrites based on property income, not personal income | Only evaluates whether the property qualifies for the loan, not whether it's a good investment for this buyer | Faketor evaluates the investment merit, not just the lendability. |
| **Spreadsheet** | Full customization | Same data sourcing burden as for the cash buyer | Faketor is the data engine behind the spreadsheet. |

**Faketor's win condition:** Independent yield verification. Brokers and lenders have
incentives to close; Faketor has incentive to be accurate.

---

#### 4.1.10 Value-Add Investor

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Architect / design-build firm** | Can assess physical feasibility; provides cost estimates; manages permits and construction | Incentivized to build (they earn fees on construction, not on "don't build"); won't model whether the development is the best use of the buyer's capital; feasibility assessment comes after engagement, not before | Faketor screens for feasibility first — before the buyer engages an architect. Zoning, setbacks, ADU rules, SB 9 eligibility can all be checked before spending money on architectural plans. |
| **Development consultant** | Deep regulatory knowledge; knows the permit process; can navigate Berkeley's planning department | Expensive ($150-300/hr); overkill for initial screening; the buyer may not need a consultant until they've identified a viable project | Faketor provides the initial screening at zero cost. The consultant is for execution after Faketor confirms feasibility. |
| **BiggerPockets / value-add investor community** | Frameworks for evaluating rehab and development projects; peer deal analysis | Not Berkeley-specific; may not know Berkeley's particularly complex zoning, permit, and rent control landscape | Faketor has Berkeley's actual zoning data, regulation rules, and permit history. |

**Faketor's win condition:** Be the free, instant feasibility screener that saves the
buyer from wasting time and money on projects that zoning or regulations won't allow.
Surface the deal-killers early.

---

#### 4.1.11 Appreciation Bettor

| Competing solution | What it does well | What it does poorly | Faketor's position |
|---|---|---|---|
| **Real estate agent (narrative)** | "Berkeley always goes up" — agents have strong narratives about local appreciation that feel convincing | Anecdotal and survivorship-biased; doesn't quantify the risk; incentivized toward purchase | Faketor models the appreciation thesis explicitly: breakeven timeline, downside scenarios, historical worst cases. |
| **Financial advisor** | Can model total return including tax benefits; evaluates in portfolio context | Typically doesn't have Berkeley-specific appreciation data at the neighborhood level | Faketor has 24 months of neighborhood-level trend data and historical price data to ground the thesis. |
| **Market reports (Redfin, Compass)** | Broad market trends; professional presentation | Typically present trailing data as forward projections; don't stress-test the thesis; marketing documents, not analysis | Faketor uses the same underlying data but models scenarios rather than extrapolating. |

**Faketor's win condition:** Be the stress-test for the appreciation thesis. The buyer
can get confirmation bias anywhere. What they can't easily get is a rigorous, quantified
model of "what if you're wrong?"

---

### 4.2 Cross-Cutting Competitive Insights

**Faketor's universal advantage: no transaction incentive.** Every human professional in
the real estate ecosystem (agent, broker, lender, contractor, architect) earns money when
a transaction happens or work is commissioned. None of them earn money when the buyer decides
to wait, rent, or do nothing. Faketor has no such incentive, which makes it uniquely
positioned to give honest advice — including "don't buy right now."

**Faketor's universal limitation: no physical presence.** It can't tour homes, read a
seller's body language, negotiate with a listing agent, inspect a foundation, or manage
a closing. For Occupy segments, a human agent remains essential for execution. Faketor
should position itself as the analytical backbone that complements an agent, not as a
replacement.

**The real competitor is often non-consumption.** For the Not Viable buyer, the Stretcher,
the Equity-Trapped Upgrader, and the Appreciation Bettor, the strongest competing solution
is "do nothing." Faketor's job for these segments is to convert passive uncertainty into
active, informed decision-making — even when the right decision is to continue doing nothing,
but now with clarity about why and what would change the answer.

**Sophistication calibration matters.** A Stretcher needs education and reassurance. A Cash
Buyer needs rigorous analysis without the education. Presenting the same level of explanation
to both degrades the experience for both. This maps directly to the emotional dimension from
Section 3 — tone and framing are competitive differentiators, not just nice-to-haves.

---

## 5. Tool Audit

Faketor currently has 18 tools. This section maps each tool against the 11 buyer segments,
assessing: (a) which segments use the tool, (b) how the tool's output should be framed
differently per segment, (c) what's missing from the tool's capabilities relative to
segment jobs, and (d) which tools should be proactively invoked vs. only called on request.

### 5.1 Tool Inventory

For reference, the 18 tools organized by functional category:

| Category | Tool | What It Does |
|----------|------|-------------|
| **Lookup** | `lookup_property` | Single-address property detail (beds, baths, sqft, zoning, last sale) |
| **Search** | `search_properties` | Multi-criteria property search (returns up to 25, reports total matching) |
| **Search** | `update_working_set` | Manage session property universe (replace, narrow, expand modes) |
| **Search** | `undo_filter` | Revert most recent working-set filter |
| **Valuation** | `get_price_prediction` | ML model predicted price with confidence interval and SHAP feature contributions |
| **Valuation** | `get_comparable_sales` | Neighborhood comps with price ranges, median $/sqft |
| **Market** | `get_neighborhood_stats` | Neighborhood-level median price, YoY change, sale count, zoning mix |
| **Market** | `get_market_summary` | Berkeley-wide summary: median prices, sale-to-list, DOM, rates, inventory |
| **Development** | `get_development_potential` | Zoning details, ADU/JADU feasibility, SB 9, Middle Housing eligibility, BESO |
| **Development** | `get_improvement_simulation` | ML-modeled value impact of improvements (kitchen, bath, ADU, solar, etc.) |
| **Investment** | `estimate_rental_income` | Rental income estimate, itemized expenses, mortgage analysis, cap rate, cash-on-cash |
| **Investment** | `estimate_sell_vs_hold` | Multi-year hold analysis with appreciation, rental yield, and sell-vs-hold recommendation |
| **Investment** | `analyze_investment_scenarios` | Multi-strategy comparison (rent as-is, add ADU, SB9 split, multi-unit) with cash flow projections |
| **Investment** | `generate_investment_prospectus` | Comprehensive multi-property prospectus (curated, similar, or thesis mode) |
| **Permits** | `lookup_permits` | Building permit history for a specific address |
| **Knowledge** | `lookup_regulation` | Berkeley zoning definitions, ADU rules, SB 9, rent control, transfer tax, etc. |
| **Knowledge** | `lookup_glossary_term` | 70+ financial and real estate terms with Berkeley-specific context |
| **Analytics** | `query_database` | Read-only SQL against full database (analytical/aggregate queries only) |

### 5.2 Segment × Tool Matrix

The matrix below shows tool relevance per segment. Relevance levels:

- **P** = Primary — this tool serves the segment's primary JTBD directly
- **S** = Secondary — this tool serves the segment's secondary JTBD or supports the primary
- **C** = Contextual — useful when the buyer asks, but not proactively surfaced
- **—** = Not relevant to this segment
- **F** = Framing change required — the tool exists but its output must be interpreted or
  presented differently for this segment (noted in the framing column)

#### 5.2.1 Occupy Segments

| Tool | Not Viable | Stretcher | First-Time | Down Pmt Constrained | Equity-Trapped | Competitive Bidder |
|------|-----------|-----------|------------|---------------------|---------------|-------------------|
| `lookup_property` | S | S | P | S | P | P |
| `search_properties` | C | S | P | P | S | P |
| `update_working_set` | — | S | P | P | C | P |
| `undo_filter` | — | C | C | C | C | C |
| `get_price_prediction` | — | S | P | S | P | **P/F** |
| `get_comparable_sales` | — | S | P | S | P | **P/F** |
| `get_neighborhood_stats` | S | P | P | P | S | P |
| `get_market_summary` | P | P | S | S | S | P |
| `get_development_potential` | — | — | C | C | **P** | C |
| `get_improvement_simulation` | — | — | C | — | **P** | C |
| `estimate_rental_income` | — | — | C | C | **S** | C |
| `estimate_sell_vs_hold` | — | — | — | — | **P** | — |
| `analyze_investment_scenarios` | — | — | — | — | S | — |
| `generate_investment_prospectus` | — | — | — | — | — | — |
| `lookup_permits` | — | C | C | C | P | C |
| `lookup_regulation` | — | C | S | C | **P** | C |
| `lookup_glossary_term` | S | **P** | **P** | S | C | C |
| `query_database` | C | C | C | C | C | C |

#### 5.2.2 Invest Segments

| Tool | Cash Buyer | Equity-Leveraging | Leveraged | Value-Add | Appreciation Bettor |
|------|-----------|-------------------|-----------|-----------|-------------------|
| `lookup_property` | P | P | S | P | S |
| `search_properties` | P | P | **P** | **P** | S |
| `update_working_set` | P | P | **P** | **P** | S |
| `undo_filter` | C | C | C | C | C |
| `get_price_prediction` | **P/F** | S | S | **P/F** | **P/F** |
| `get_comparable_sales` | **P/F** | S | **P/F** | **P/F** | S |
| `get_neighborhood_stats` | P | S | P | P | **P** |
| `get_market_summary` | S | S | S | S | **P** |
| `get_development_potential` | S | S | C | **P** | — |
| `get_improvement_simulation` | S | C | C | **P** | — |
| `estimate_rental_income` | **P** | **P** | **P** | **P** | S |
| `estimate_sell_vs_hold` | S | C | C | C | **P** |
| `analyze_investment_scenarios` | **P** | **P** | S | **P** | S |
| `generate_investment_prospectus` | **P** | S | S | **P** | S |
| `lookup_permits` | S | C | C | **P** | C |
| `lookup_regulation` | **P** | S | S | **P** | C |
| `lookup_glossary_term` | C | S | C | C | C |
| `query_database` | P | C | **P** | P | C |

### 5.3 Framing Analysis

The same tool output means different things to different segments. Below, each **P/F**
(primary with framing change) is detailed.

#### 5.3.1 `get_price_prediction`

| Segment | What the buyer is actually asking | How to frame the output |
|---------|-----------------------------------|------------------------|
| **First-Time Buyer** | "Is this property fairly priced?" | Frame as a fairness check: "The model estimates fair value at $X. The asking price is Y% above/below this. Based on comps and the confidence interval, this looks [fairly priced / priced to generate a bidding war / overpriced]." Include the confidence interval prominently — this buyer needs to understand uncertainty. |
| **Competitive Bidder** | "What's the rational ceiling for my bid?" | Frame as bid calibration: "The model's upper confidence bound is $X. The sale-to-list ratio in this neighborhood suggests closing at Y% above list. A bid above $Z puts you into overpayment territory based on the model." The confidence interval becomes the bidding range. |
| **Equity-Trapped Upgrader** | "What's my current home worth? What would the upgrade cost?" | Use for two properties: current home (to compute equity) and target home (to compute cost). Frame as a gap analysis: "Your current home is estimated at $X. Your target is estimated at $Y. The gap is $Z, plus transaction costs of ~$W." |
| **Cash Buyer (Investor)** | "What's the acquisition cost basis for yield computation?" | Frame as input to yield analysis, not as a stand-alone number. Skip the "is this fairly priced?" framing — the cash buyer cares about yield at this price, not whether the price is "fair" in an abstract sense. "At a purchase price of $X (model estimate), the cap rate is Y%." |
| **Value-Add Investor** | "What's the as-is value, and what's the spread to after-improvement value?" | Frame as a value-creation opportunity: "As-is, the model estimates $X. After [specific improvements], the improvement simulation projects $Y. The value-creation spread is $Z minus improvement costs of $W." |
| **Appreciation Bettor** | "What's the starting point for my appreciation thesis?" | Frame as a baseline for projection: "The model estimates current value at $X. At Y% annual appreciation, this reaches $Z in [3/5/10] years. The confidence interval suggests a range of $A to $B as the starting point, which materially affects the appreciation timeline." |

#### 5.3.2 `get_comparable_sales`

| Segment | What the buyer is actually asking | How to frame the output |
|---------|-----------------------------------|------------------------|
| **First-Time Buyer** | "What have similar homes sold for recently?" | Present as education: "Here are recent sales of similar homes. Notice the range — prices vary by $X depending on [condition, lot size, specific block]. The median for this type is $Y/sqft." Help them understand what drives price variation. |
| **Competitive Bidder** | "What's the closing price pattern — how much over asking?" | Present as competitive intelligence: "Of these N comps, X sold above asking at an average of Y% over list. The highest premium was Z% for [property with specific desirable attributes]. This tells you what a winning bid looks like in this micro-market." Emphasize sale-to-list ratios, not just sale prices. |
| **Cash Buyer (Investor)** | "Is the asking price justified by the market?" | Present as market-calibrated acquisition cost: "Recent comps suggest a price range of $X to $Y for this profile. At the asking price, you're [below/at/above] the comp median. Price per sqft: asking is $X/sqft vs. comp median of $Y/sqft." Skip the education — go straight to the number. |
| **Leveraged Investor** | "Can I acquire below the comp median to improve my yield?" | Present as acquisition strategy: "Comp median is $X. If you can acquire at $Y (Z% below median), your day-one cap rate improves from A% to B%. Properties that traded below median in this set: [list with reasons — condition, DOM, distressed]." |
| **Value-Add Investor** | "What will this be worth after I improve it?" | Present as value benchmark: "Improved properties in this neighborhood sell for $X/sqft (your subject is at $Y/sqft today). The spread represents the value-creation opportunity. Note: comp prices are for finished product — adjust for your holding and improvement costs." |

#### 5.3.3 `estimate_rental_income`

This tool is framed identically for most invest segments but serves different roles
for occupy segments when invoked:

| Segment | Role of Rental Income Data |
|---------|---------------------------|
| **Equity-Trapped Upgrader** | "If I keep my current home and rent it out, does the rental income cover my existing mortgage?" This is a stay-vs-sell decision input, not an investment analysis. Frame accordingly: "Your current mortgage is $X/mo. Estimated rent is $Y/mo. After expenses (tax, insurance, maintenance, management), net rental income is $Z/mo. Shortfall: $W/mo that you'd carry from income." |
| **Cash Buyer (Investor)** | Pure yield analysis. Cap rate, NOI, cash-on-cash return. No mortgage analysis needed (they're buying cash). Frame: "NOI: $X/yr. At purchase price $Y, cap rate: Z%. Compare to [relevant benchmarks]." |
| **Equity-Leveraging Investor** | Dual-property focus. Frame: "Investment property rental income: $X/mo. After expenses and new mortgage: net cash flow $Y/mo. Combined with your existing primary residence costs, total monthly housing expenditure: $Z. This requires $W/mo from employment income." |
| **Leveraged Investor** | Yield-spread focus. Frame: "At purchase price $X with 25% down at current rates, monthly mortgage is $Y. Net rental income after expenses: $Z/mo. Monthly cash flow: positive/negative $W. DSCR: [ratio]." The spread between yield and borrowing cost is the key metric. |
| **Value-Add Investor** | Pre-improvement and post-improvement rental comparison. Frame: "Current-state rental income: $X/mo (cap rate Y%). Post-[ADU/improvement] projected rental income: $Z/mo (cap rate W%). The additional rental income justifies the improvement cost in [N] years." |

### 5.4 Tool Gap Analysis

Mapping the functional JTBDs from Section 3 against existing tool capabilities reveals
gaps — jobs that segments need done but that no current tool addresses.

#### 5.4.1 Missing Tools

| Gap ID | Segment(s) Affected | Job Not Served | What's Needed |
|--------|---------------------|---------------|--------------|
| **G-1** | Stretcher, Not Viable | Rent-vs-buy breakeven analysis | A tool that computes the crossover point where buying becomes cheaper than renting, given: current rent, expected rent increases, purchase price, true monthly ownership cost (PITI + earthquake + maintenance + PMI), down payment opportunity cost, tax benefits, and expected appreciation. None of the existing tools produce this comparison directly. The affordability calculator in `market_analysis.py` computes max affordable price but doesn't compare to renting. |
| **G-2** | Down Payment Constrained | PMI duration and buy-now-vs-wait modeling | A tool that models: (a) PMI cost at the buyer's down payment percentage, (b) how many months until PMI drops off (equity reaches 80% LTV via appreciation + principal paydown), (c) the race between the buyer's savings rate and market appreciation — if they wait to reach 20% down, does the market move the target? No existing tool models this dynamic. |
| **G-3** | Equity-Trapped Upgrader | Rate penalty quantification and scenario modeling | A tool that takes the buyer's existing mortgage (balance, rate, remaining term) and computes: (a) current monthly payment, (b) payment on equivalent balance at market rate, (c) the delta as both dollar amount and % of income, (d) rate scenarios — at what market rate does the penalty shrink to a tolerable threshold? The `estimate_sell_vs_hold` tool partially addresses this but approaches from the investment side (should you sell?), not the upgrader's perspective (what does moving cost me in rate terms?). |
| **G-4** | Stretcher, First-Time, Down Pmt Constrained | True monthly cost computation | A tool that computes the all-in monthly cost of ownership: mortgage P&I + property tax + homeowner's insurance + earthquake insurance (varies by construction type, age, foundation) + maintenance reserve (varies by age and property type) + PMI (if applicable) + HOA (if applicable). The current `analyze_mortgage()` in `rental_analysis.py` computes PITI but omits earthquake insurance and maintenance. The buyer-facing output understates true cost by the computed variance. |
| **G-5** | Competitive Bidder | Competition assessment / bid strategy | A tool that aggregates competitive dynamics for a specific neighborhood or micro-market: recent sale-to-list ratios, DOM distribution, % of sales above/below asking, inventory trend, absorption rate, price band competition intensity. Currently, pieces of this exist across `get_neighborhood_stats` and `get_market_summary`, but neither produces a competition-focused synthesis. The bidder needs: "In this neighborhood, at your price point, here's how competitive the market is and what winning bids look like." |
| **G-6** | Equity-Leveraging Investor | Dual-property cash flow model | A tool that takes two properties (primary residence + investment target) and models the combined financial picture: existing mortgage + equity access cost (HELOC or cash-out refi, with variable rate modeling) + investment property mortgage + investment property rental income - combined expenses. Stress tests: vacancy, rate increase on HELOC, maintenance spike. No current tool models the interaction between two properties. |
| **G-7** | Leveraged Investor | Portfolio yield ranking with leverage spread | A tool that takes the current working set and ranks all properties by leverage spread (cap rate minus borrowing cost), DSCR, and cash-on-cash return at a specified down payment percentage and rate. The `query_database` tool can partially do this via SQL against `precomputed_scenarios`, but extracting JSON fields and computing spreads in SQL is fragile and requires the agent to construct complex queries. A dedicated tool would be more reliable and would apply consistent computation methodology. |
| **G-8** | Appreciation Bettor | Appreciation thesis stress-tester | A tool that models the breakeven between negative carry and price appreciation under multiple scenarios: (a) at X% appreciation, breakeven in Y years; (b) if prices are flat for Z years then appreciate, total cost of the thesis; (c) if forced to sell at year N, net outcome after transaction costs; (d) refinance scenario — if rates drop to R%, new monthly cost and revised breakeven. `estimate_sell_vs_hold` addresses part of this but is framed around a sell-or-hold decision for a current owner, not an appreciation-thesis evaluation for a prospective buyer. |
| **G-9** | All Occupy segments | Neighborhood lifestyle matching | A capability (not necessarily a single tool) that helps Occupy segments match neighborhoods to lifestyle needs: commute time, school quality, walkability, dining/shopping, parks, character/vibe. Currently, `get_neighborhood_stats` provides price and sales data but nothing about lifestyle attributes. This data is harder to source, but even a qualitative description per neighborhood (from the agent's knowledge or a lookup table) would serve the First-Time Buyer's neighborhood discovery job. |
| **G-10** | Not Viable, Stretcher | Adjacent market comparison | A capability that shows what the buyer's budget can purchase in nearby markets (Oakland, El Cerrito, Albany, Richmond) compared to Berkeley. This is a "what are my alternatives?" analysis. Faketor's data is Berkeley-only, so this would require either expanding the data footprint or providing qualitative guidance. |

#### 5.4.2 Tool Enhancement Requirements

These are existing tools that need modification, not new tools:

| Enhancement ID | Tool | What Needs to Change | Segments Affected |
|----------------|------|---------------------|-------------------|
| **E-1** | `estimate_rental_income` | Add earthquake insurance to operating expense line items. Currently uses `_INSURANCE_RATE = 0.0035` which covers hazard insurance only. Earthquake insurance varies by construction type, year built, and foundation type — typical range is 0.15% to 0.40% of dwelling value. The tool should compute this based on property attributes rather than using a fixed rate. | All Invest segments, Equity-Trapped Upgrader |
| **E-2** | `estimate_rental_income` | Add a maintenance reserve line item. Currently not included in operating expenses. Should be computed based on property age and type — newer properties require less; older Berkeley housing stock (pre-1940) requires more. | All Invest segments, Equity-Trapped Upgrader |
| **E-3** | `analyze_investment_scenarios` | Include carrying costs during the development/improvement period in the ADU and SB9 scenarios. Currently models post-development cash flows but doesn't account for the 6-18 months of carrying costs during permitting and construction when the investment produces no income. This materially affects the true ROI for Value-Add Investors. | Value-Add Investor |
| **E-4** | `get_price_prediction` | Expose the SHAP feature contributions more prominently in the output. Currently returns them but the agent doesn't consistently surface them. For segment-aware framing, the feature contributions tell different stories: for a First-Time Buyer, "the model values this property's extra bathroom at $45K" is educational; for a Value-Add Investor, "adding a bathroom would shift the model's prediction by ~$45K" is actionable. | First-Time Buyer, Competitive Bidder, Value-Add Investor |
| **E-5** | `get_market_summary` | Add rate sensitivity context. Currently reports the current mortgage rate but doesn't compute what it means for different buyer profiles. Should include: monthly P&I at median price for common down payment levels (20%, 10%, 5%, 3.5%), and the income required to carry each at standard DTI thresholds. This turns a market summary into a segment-relevant affordability snapshot. | Not Viable, Stretcher, First-Time Buyer, Down Payment Constrained |
| **E-6** | `estimate_sell_vs_hold` | Add a rate-penalty dimension for homeowners considering selling. Currently projects future value and rental yield, but doesn't model: "If you sell this property and buy another, your monthly payment increases by $X due to the rate difference." This is the central question for the Equity-Trapped Upgrader and should be a first-class output, not something the agent must compute manually. | Equity-Trapped Upgrader |
| **E-7** | `search_properties` and `update_working_set` | Add affordability filtering — allow filtering by estimated monthly cost (not just sale price) so that Stretcher and Down Payment Constrained buyers can search by what they can actually pay, not by sticker price. This requires integrating the true-cost computation (G-4) into the search pipeline. | Stretcher, Down Payment Constrained |

### 5.5 Proactive vs. Reactive Tool Invocation

Currently, Faketor invokes tools only in response to user queries. Segment-aware
orchestration should proactively invoke certain tools when the segment and context
indicate the buyer would benefit from unsolicited analysis.

#### 5.5.1 Proactive Invocation Rules

| Segment | Trigger | Proactive Tool(s) | Rationale |
|---------|---------|-------------------|-----------|
| **Not Viable** | Buyer asks about properties clearly outside their budget | `get_market_summary` + G-4 (true cost) | Show the buyer the gap between their capacity and the market, quantified — don't let them browse listings they can't afford without context |
| **Stretcher** | Buyer asks about a specific property | G-1 (rent-vs-buy) + G-4 (true cost) | Automatically compare the true monthly cost of buying to their current rent. The Stretcher may not think to ask for this comparison. |
| **First-Time Buyer** | Buyer looks up a property or asks about a neighborhood | `lookup_glossary_term` (contextual) | Proactively define terms the buyer encounters for the first time: sale-to-list ratio, DOM, contingency, etc. Don't wait for them to ask. |
| **First-Time Buyer** | Buyer is evaluating a specific property | `get_price_prediction` + `get_comparable_sales` | Always validate price. A first-time buyer may not know to ask "is this fairly priced?" |
| **Down Pmt Constrained** | Buyer looks at properties at their budget ceiling | G-2 (PMI modeling) | Automatically show: "At this price with your down payment, PMI costs $X/month for approximately Y months. Total PMI cost: $Z." |
| **Equity-Trapped Upgrader** | Buyer compares current home to a target | G-3 (rate penalty) + `get_improvement_simulation` | Automatically show the rate penalty alongside the renovation alternative: "Moving costs you $X/month in rate penalty. For reference, an ADU addition would cost $Y and add $Z to your home's value." |
| **Competitive Bidder** | Buyer asks about a specific property | `get_comparable_sales` + G-5 (competition) + `get_price_prediction` | Full bidding package: comps, model prediction, and competition metrics — all at once, framed as a bid range. |
| **Cash Buyer** | Buyer evaluates a property | `estimate_rental_income` + `lookup_regulation` (rent control) | Automatically show yield and regulatory risk — don't wait for the investor to ask about rent control. |
| **Equity-Leveraging Investor** | Buyer identifies an investment target | G-6 (dual-property model) | Immediately model the combined financial picture. This is the central question for this segment. |
| **Leveraged Investor** | Working set is updated | G-7 (portfolio yield ranking) | Automatically rank the working set by leverage spread. This is the primary job — the investor wants a ranked list, not a property-by-property analysis. |
| **Value-Add Investor** | Buyer looks up a property | `get_development_potential` + `lookup_permits` + `get_improvement_simulation` | Full feasibility package: what can be built, what's been built before, and what it would be worth. |
| **Appreciation Bettor** | Buyer evaluates a property | `get_neighborhood_stats` (appreciation trend) + G-8 (stress test) | Automatically show the appreciation history and stress-test the thesis. This buyer came with a thesis — test it, don't wait to be asked. |

#### 5.5.2 Tool Sequencing per Segment

For key segment interactions, tools should fire in a specific sequence where each
tool's output informs the next. This is orchestration logic, not user-driven.

**First-Time Buyer evaluating a property:**
1. `lookup_property` — get property details
2. `get_price_prediction` — is the price fair?
3. `get_comparable_sales` — what context supports the prediction?
4. `get_neighborhood_stats` — how does this neighborhood perform?
5. [If applicable] `lookup_glossary_term` — define unfamiliar terms surfaced in steps 2-4

**Competitive Bidder evaluating a property:**
1. `lookup_property` — get property details
2. `get_price_prediction` — model estimate (this becomes the "fair value" anchor)
3. `get_comparable_sales` — recent closes, emphasizing sale-to-list
4. G-5 (competition assessment) — how competitive is this micro-market right now?
5. Synthesize into a bid range: "Fair value: $X. Expected closing price: $Y. Maximum rational bid: $Z."

**Value-Add Investor evaluating a property:**
1. `lookup_property` — get property details (especially lot size, zoning)
2. `get_development_potential` — what's buildable?
3. `lookup_permits` — what's been built or attempted before?
4. `get_improvement_simulation` — value impact of the planned improvement
5. `analyze_investment_scenarios` — full scenario comparison (rent as-is vs. add ADU vs. SB9)
6. `lookup_regulation` — any regulatory constraints on the planned development?

**Equity-Trapped Upgrader comparing options:**
1. `lookup_property` (current home) — get current home details
2. `get_price_prediction` (current home) — what's it worth?
3. G-3 (rate penalty) — what does moving cost in monthly terms?
4. `get_improvement_simulation` (current home) — what would renovating achieve?
5. `estimate_sell_vs_hold` (current home) — should they sell or hold?
6. [If considering rental] `estimate_rental_income` (current home) — can they rent it out?

### 5.6 Iteration Budget Implications

Faketor has a 12-iteration limit per turn. The proactive tool sequences above
consume 4-6 iterations for a single property evaluation. This creates constraints:

| Scenario | Iterations Used | Budget Remaining |
|----------|----------------|-----------------|
| FTB evaluating a property (5 tools) | 5-6 | 6-7 (comfortable) |
| Competitive Bidder package (4 tools + synthesis) | 5-6 | 6-7 (comfortable) |
| Value-Add full evaluation (6 tools) | 6-7 | 5-6 (tight for follow-ups) |
| Upgrader comparison (6 tools, 2 properties) | 7-8 | 4-5 (tight) |
| Multi-property ranking (working set) | 1-2 (use `query_database` on precomputed_scenarios) | 10-11 (efficient) |

**Design implications:**

1. **Prefer batch tools over loops.** The `generate_investment_prospectus` and
   `query_database` tools can handle multi-property analysis in a single call.
   Per-property tools should only be used for the 1-2 properties the buyer
   is focused on, not iterated across a working set.

2. **Proactive sequences should be budget-aware.** The segment detector should
   estimate iteration cost before committing to a proactive sequence. If the
   buyer's initial question already consumed 3-4 iterations, don't auto-trigger
   a 5-tool sequence — prioritize the most valuable tools for this segment and
   defer the rest.

3. **Precomputed scenarios reduce iteration cost.** The `precomputed_scenarios`
   table caches prediction, rental, and development potential data per property.
   For ranking and comparison jobs, use `query_database` against this table
   instead of calling per-property tools. This is especially important for the
   Leveraged Investor (G-7: portfolio yield ranking).

4. **New gap tools should be designed for single-call efficiency.** G-1 (rent-vs-buy),
   G-3 (rate penalty), G-4 (true cost), G-6 (dual-property model), and G-8
   (appreciation stress test) should each produce their complete analysis in a
   single tool call, not require multiple calls to assemble.

### 5.7 Tool Priority by Segment

For each segment, which tools deliver the most value? This determines where Faketor
should invest its iteration budget when resources are constrained.

| Segment | Tier 1 (always invoke) | Tier 2 (invoke if budget allows) | Tier 3 (only on request) |
|---------|----------------------|--------------------------------|------------------------|
| **Not Viable** | `get_market_summary`, G-4 (true cost) | `get_neighborhood_stats` | `lookup_glossary_term` |
| **Stretcher** | G-1 (rent-vs-buy), G-4 (true cost), `get_neighborhood_stats` | `get_price_prediction`, `get_comparable_sales` | `lookup_glossary_term`, `lookup_regulation` |
| **First-Time Buyer** | `get_price_prediction`, `get_comparable_sales`, `get_neighborhood_stats` | `lookup_glossary_term`, `search_properties` | `get_development_potential`, `estimate_rental_income` |
| **Down Pmt Constrained** | G-2 (PMI model), G-4 (true cost), `search_properties` | `get_price_prediction`, `get_neighborhood_stats` | `lookup_glossary_term` |
| **Equity-Trapped** | G-3 (rate penalty), `estimate_sell_vs_hold`, `get_improvement_simulation` | `estimate_rental_income`, `get_development_potential` | `lookup_permits`, `lookup_regulation` |
| **Competitive Bidder** | `get_price_prediction`, `get_comparable_sales`, G-5 (competition) | `get_neighborhood_stats`, `get_market_summary` | `lookup_permits`, `get_development_potential` |
| **Cash Buyer** | `estimate_rental_income`, `analyze_investment_scenarios`, `lookup_regulation` | `get_price_prediction`, `get_comparable_sales` | `get_development_potential`, `lookup_permits` |
| **Equity-Leveraging** | G-6 (dual-property), `estimate_rental_income`, `analyze_investment_scenarios` | `get_price_prediction`, `lookup_regulation` | `get_development_potential` |
| **Leveraged** | G-7 (yield ranking), `estimate_rental_income`, `query_database` | `get_comparable_sales`, `get_neighborhood_stats` | `lookup_regulation` |
| **Value-Add** | `get_development_potential`, `get_improvement_simulation`, `analyze_investment_scenarios` | `lookup_permits`, `lookup_regulation`, `get_price_prediction` | `get_comparable_sales` |
| **Appreciation Bettor** | `get_neighborhood_stats`, `estimate_sell_vs_hold`, G-8 (stress test) | `get_market_summary`, `get_price_prediction` | `get_comparable_sales` |

### 5.8 Summary of Required Changes

| Category | Count | Items |
|----------|-------|-------|
| **New tools needed** | 10 | G-1 through G-10 |
| **Existing tools needing enhancement** | 7 | E-1 through E-7 |
| **Framing changes (no code change)** | 5 | Price prediction, comparable sales, rental income, sell-vs-hold, market summary |
| **Proactive invocation rules** | 11 | One per segment |
| **Tool sequences to orchestrate** | 4+ | Per-segment evaluation sequences |

The framing changes require no tool code changes — they are implemented in the
orchestration layer (Section 7) via segment-aware system prompt injection. The new tools
and enhancements require code changes in `faketor.py`, `rental_analysis.py`,
`market_analysis.py`, and potentially new service modules.

---

## 6. Workflow Design

This section specifies the end-to-end flow for a segment-aware Faketor conversation:
how the buyer's segment is detected, how jobs are resolved, how tools are selected and
sequenced, how responses are framed, and how state evolves across turns.

The design in this section is prescriptive — it describes how the system should work,
not how the current system works. Where the right design conflicts with the current
architecture, the current architecture changes.

### 6.1 Design Principles

Before specifying components, the principles that govern the design:

1. **The buyer is the primary entity, not the property.** The current system is
   property-centric — the request model requires lat/lon and property attributes;
   the buyer is invisible. The redesigned system inverts this: the buyer (their
   segment, financial situation, and job) is the primary context; the property they're
   looking at is secondary context within an interaction.

2. **The LLM should do what LLMs are good at.** Signal extraction from natural language,
   intent classification, tone calibration, and response framing are all things an LLM
   does better than rule-based code. The orchestration layer should use the LLM for
   these tasks — not replicate them poorly with keyword matching. Deterministic logic
   (segment classification from known factors, capacity computation, tool execution)
   stays in code.

3. **The system prompt is composable, not monolithic.** The current ~1000-line
   `SYSTEM_PROMPT` string is a maintenance liability and makes segment-aware behavior
   hard to inject. The redesign uses a prompt assembly pipeline where independent
   concerns (personality, data model rules, segment context, tool instructions,
   framing guidance) are composed from separate, testable units.

4. **Proactive tool execution happens before the LLM loop, not inside it.** The current
   system gives Claude 12 iterations and hopes it picks the right tools. The redesigned
   system pre-executes segment-relevant tools, injects their results as verified context,
   and gives Claude a richer starting point with fewer iterations needed. This is more
   efficient and more predictable.

5. **Research context is a first-class entity with proper separation of concerns.** The
   current `SessionWorkingSet` tracks property filter state only. The redesigned state
   has four concerns: buyer state (who they are), property state (what they're looking at
   and what they've learned about it), market state (a frozen snapshot of supply-side
   conditions), and conversation state (the ephemeral processing pipeline). Each has its
   own lifecycle, persistence model, and staleness semantics.

### 6.2 System Architecture

```
Frontend                      API                         Orchestration
───────                      ───                         ─────────────
ChatRequest ─────────────►  /api/faketor/chat/stream
  • message                    │
  • session_id                 │
  • property_context {}        │    (property is optional context,
                               │     not a required field)
                               │
                               └─► ContextStore.load_or_create(user_id)
                                     │
                                     │    ┌──────────────────────────────────────┐
                                     │    │      ResearchContext (persistent)    │
                                     │    │                                      │
                                     │    │  ┌──────────────────────────────┐   │
                                     │    │  │   BuyerState                 │   │
                                     │    │  │   • profile (factors)        │   │
                                     │    │  │   • segment + confidence     │   │
                                     │    │  │   • signal log               │   │
                                     │    │  │   • segment history          │   │
                                     │    │  └──────────────────────────────┘   │
                                     │    │  ┌──────────────────────────────┐   │
                                     │    │  │   MarketSnapshot             │   │
                                     │    │  │   • snapshot_at timestamp    │   │
                                     │    │  │   • 30yr rate               │   │
                                     │    │  │   • conforming limit        │   │
                                     │    │  │   • berkeley-wide metrics   │   │
                                     │    │  │   • per-neighborhood metrics│   │
                                     │    │  └──────────────────────────────┘   │
                                     │    │  ┌──────────────────────────────┐   │
                                     │    │  │   PropertyState              │   │
                                     │    │  │   • filter intent (criteria) │   │
                                     │    │  │   • result set (computed)    │   │
                                     │    │  │   • filter stack             │   │
                                     │    │  │   • focus property           │   │
                                     │    │  │   • per-property analyses    │   │
                                     │    │  │   • conclusions              │   │
                                     │    │  └──────────────────────────────┘   │
                                     │    └──────────────────────────────────────┘
                                     │
                                     │    TurnState (ephemeral, per-turn):
                                     │    • turn count, job history, fact accumulator
                                     │
                                     ▼
                               Orchestrator.handle_turn()
                                     │
                                     ├─ 1. EXTRACT   → LLM-based signal + factor extraction
                                     │                  from message (structured output)
                                     │
                                     ├─ 2. CLASSIFY  → Deterministic segment classification
                                     │                  from known factors + market snapshot
                                     │
                                     ├─ 3. RESOLVE   → Job + tool plan for this turn
                                     │
                                     ├─ 4. PRE-EXECUTE → Run proactive tools before LLM loop
                                     │                    (results become verified context)
                                     │
                                     ├─ 5. COMPOSE   → Assemble system prompt from components
                                     │
                                     ├─ 6. CONVERSE  → LLM loop (Claude + reactive tools)
                                     │
                                     ├─ 7. POST-PROCESS → Extract signals from LLM response
                                     │                     + promote TurnState to ResearchContext
                                     │
                                     └─ 8. PERSIST   → Save ResearchContext (authenticated only)
```

### 6.3 The Buyer Model

#### 6.3.1 Data Model

```
BuyerProfile {
    // Core factors (from Section 1)
    intent: "occupy" | "invest" | null
    capital: number | null                        // liquid cash ($)
    equity: number | null                         // property equity ($)
    equity_rate: number | null                    // locked mortgage rate (%)
    equity_balance: number | null                 // remaining mortgage balance ($)
    income: number | null                         // annual household gross ($)
    monthly_obligations: number | null            // existing monthly debt ($)
    current_rent: number | null                   // monthly rent if renting ($)
    is_first_time_buyer: boolean | null
    owns_current_home: boolean | null

    // Derived by extraction, not by keyword matching
    sophistication: "novice" | "informed" | "expert" | null
    risk_tolerance: "conservative" | "moderate" | "aggressive" | null
    timeline: "exploring" | "active" | "urgent" | null

    // Provenance — every field has a source
    field_sources: Map<field_name, FieldSource>
}

FieldSource {
    origin: "intake_form" | "user_profile_db" | "conversation_extraction" | "prior_session"
    turn: number | null                           // which turn it was extracted from
    raw_evidence: string | null                   // the user's actual words
    confidence: float                             // how confident the extraction is
    stale: boolean                                // marked stale when returning user's context is loaded
}
```

**Key design decision: every field has provenance.** When the system uses a buyer's
income in a calculation, it knows whether that came from a structured intake form
(high confidence, current) or was extracted from a casual remark two sessions ago
(lower confidence, possibly stale). This prevents the system from over-trusting
inferred data and allows it to ask for confirmation when confidence is low or data
is stale.

#### 6.3.2 Profile Sources

| Source | When | Confidence | Stale on Resume? |
|--------|------|-----------|-----------------|
| **Intake form** | User completes structured onboarding | 1.0 | No — user explicitly provided |
| **User profile (DB)** | Authenticated user with saved profile | 0.9 | Yes — circumstances change between sessions |
| **Conversation extraction** | LLM extracts from user's messages | 0.6 – 0.9 (varies) | N/A — same interaction |
| **Returning user carry-forward** | Returning user, persisted profile | 0.7 × prior confidence | Yes |

### 6.4 Signal Extraction (Step 1: EXTRACT)

Signal extraction is the process of identifying buyer factors, intent, and
sophistication from the user's message. This is where the current design would be
most wrong if done with keyword matching.

#### 6.4.1 Why LLM Extraction, Not Keywords

Consider the message: "My wife and I are thinking about getting out of our place
in Oakland — we bought there 6 years ago at 2.9% and it's worth maybe $800K now.
We're looking at Berkeley because of the schools."

A keyword matcher might catch "schools" → occupy intent. It would miss:

- They own a home (equity holder)
- They bought 6 years ago at 2.9% (equity_rate, rate-lock context)
- Current value ~$800K (equity estimate — minus remaining balance)
- They're a couple (household context)
- Oakland → Berkeley is an upgrade move (upgrader signal)
- "Thinking about" → timeline is "exploring," not "urgent"
- Schools motivation → occupy intent with family-oriented lifestyle needs

An LLM reading this naturally extracts all of the above. The extraction should be
structured — not free-text reasoning that needs parsing, but a defined output schema.

#### 6.4.2 Extraction Method

Signal extraction uses a **lightweight, structured LLM call** — separate from the
main conversation LLM loop. This call:

1. Receives: the user's message + the current `BuyerProfile` state (what's already known)
2. Returns: a structured JSON update to the profile
3. Uses a small, fast model (not the full conversation model) — this is a classification
   task, not a generation task
4. Runs before the main LLM loop, so the segment classification has fresh data

**Extraction prompt (schematic):**

```
You are a buyer signal extractor. Given a message from a user of a Berkeley
real estate advisor, extract any buyer profile information.

Current profile state:
{buyer_profile_json}

User message:
"{message}"

Return a JSON object with ONLY the fields you can extract from this message.
Do not guess — only extract what the user explicitly or clearly implies.

Schema:
{
    "intent": "occupy" | "invest" | null,
    "capital": number | null,
    "equity": number | null,
    "equity_rate": number | null,
    "equity_balance": number | null,
    "income": number | null,
    "current_rent": number | null,
    "owns_current_home": boolean | null,
    "is_first_time_buyer": boolean | null,
    "sophistication": "novice" | "informed" | "expert" | null,
    "risk_tolerance": "conservative" | "moderate" | "aggressive" | null,
    "timeline": "exploring" | "active" | "urgent" | null,
    "signals": [
        {"evidence": "...", "implication": "...", "confidence": 0.0-1.0}
    ]
}

Return only fields present in the message. Empty object {} if nothing extractable.
```

**Cost and latency:** This extraction call processes a short message with a simple
schema. Using a fast model (e.g., Haiku-class), it adds ~200-400ms and minimal token
cost per turn. This is negligible compared to the main conversation model's response
time.

#### 6.4.3 Extraction Runs on Both Input and Output

Signal extraction runs twice per turn:

1. **Pre-turn extraction** (on the user's message) — feeds into segment classification
   before the main LLM loop starts. This is the primary extraction.

2. **Post-turn extraction** (on the LLM's response + user's next message) — captures
   signals from the conversational exchange. If the LLM asked "Are you looking at this
   as a home or an investment?" and the user answered, the answer is extracted at the
   start of the next turn. But also: if the LLM's response surfaced information that
   the user reacted to (e.g., the user saw a price and said "that's out of my range"),
   that reaction is a signal.

This two-phase extraction means the system gets smarter with each turn, even when the
user isn't explicitly volunteering financial information.

### 6.5 Segment Classification (Step 2: CLASSIFY)

Once extraction provides buyer factors, classification is deterministic. This is the
decision tree from Section 1.4, implemented as code — not an LLM call.

#### 6.5.1 Why Classification Is Deterministic

The segment definitions (Section 2) are derived from market structure: intent ×
capital × equity × income, evaluated against current market factors. Given the same
inputs, the same segment always results. This is exactly what code does better than
an LLM.

The LLM does the hard part (extraction from natural language). Code does the
predictable part (classification from structured data).

#### 6.5.2 Classification Logic

```python
def classify(profile: BuyerProfile, market: MarketSnapshot) -> SegmentResult:
    """Deterministic segment classification from buyer factors + market snapshot.

    Uses the frozen MarketSnapshot (captured at context load/refresh),
    not a live query. This ensures classification is consistent within an interaction
    even if market data updates mid-conversation.

    Returns segment_id and confidence. Confidence reflects how many factors
    are known — not how uncertain the classification is. With all four factors
    known, confidence is 1.0. With only intent known, confidence is 0.3.
    """
    # Compute how much we know
    known_factors = sum([
        profile.intent is not None,
        profile.capital is not None or profile.equity is not None,
        profile.income is not None,
    ])

    if known_factors == 0:
        return SegmentResult(segment_id=None, confidence=0.0)

    # Base confidence from factor coverage
    confidence = known_factors / 3.0  # 3 factor groups: intent, capital/equity, income

    # --- Intent branch ---
    if profile.intent == "occupy":
        return _classify_occupy(profile, market, confidence)
    elif profile.intent == "invest":
        return _classify_invest(profile, market, confidence)
    else:
        # Intent unknown — use sophistication and behavior signals to estimate
        if profile.sophistication == "expert":
            # Expert vocabulary strongly suggests invest
            return _classify_invest(profile, market, confidence * 0.7)
        elif profile.owns_current_home is False and profile.is_first_time_buyer:
            # First-time renter strongly suggests occupy
            return _classify_occupy(profile, market, confidence * 0.7)
        else:
            return SegmentResult(segment_id=None, confidence=confidence * 0.3)


def _classify_occupy(profile, market, base_confidence):
    """Classify within the occupy branch."""
    # Compute capacity against market
    capacity = compute_buyer_capacity(profile, market)

    if capacity.max_affordable_price < market.entry_price_threshold:
        return SegmentResult("not_viable", base_confidence)

    if capacity.monthly_stress_ratio > capacity.stress_threshold:
        return SegmentResult("stretcher", base_confidence)

    if profile.owns_current_home and profile.equity_rate is not None:
        rate_penalty = compute_rate_penalty(profile, market)
        if rate_penalty.monthly_delta > profile.income / 12 * 0.05:  # >5% of monthly gross
            return SegmentResult("equity_trapped_upgrader", base_confidence)

    if profile.capital is not None:
        down_pct = profile.capital / capacity.target_price if capacity.target_price else 0
        if down_pct < 0.20:
            return SegmentResult("down_payment_constrained", base_confidence)

    if profile.is_first_time_buyer:
        return SegmentResult("first_time_buyer", base_confidence)

    # Has capital, has income, no constraints identified
    return SegmentResult("competitive_bidder", base_confidence)


def _classify_invest(profile, market, base_confidence):
    """Classify within the invest branch."""
    has_liquid_capital = profile.capital and profile.capital >= market.median_price * 0.25
    has_equity = profile.equity and profile.equity > 0
    needs_financing = not (profile.capital and profile.capital >= market.median_price)

    if not needs_financing:
        return SegmentResult("cash_buyer", base_confidence)

    if has_equity and not has_liquid_capital:
        return SegmentResult("equity_leveraging_investor", base_confidence)

    # Check for value-add signals (from extraction)
    if any(s.implication == "development_intent" for s in profile.signals):
        return SegmentResult("value_add_investor", base_confidence)

    # Check for appreciation thesis signals
    if any(s.implication == "appreciation_thesis" for s in profile.signals):
        return SegmentResult("appreciation_bettor", base_confidence)

    # Default invest: leveraged investor (looking for yield > cost of capital)
    return SegmentResult("leveraged_investor", base_confidence)
```

#### 6.5.3 Confidence Model

Confidence is not a probability of correctness — it's a measure of information
completeness. The system's behavior scales with confidence:

| Confidence | Known Factors | System Behavior |
|-----------|--------------|-----------------|
| **0.0** | None | Generic mode — no segment behavior. Prompt guides LLM to elicit signals naturally. |
| **0.1 – 0.3** | Intent only, or sophistication only | Light adaptation — tone adjusts, but no proactive tools or strong framing. |
| **0.3 – 0.6** | Intent + partial financial picture | Moderate adaptation — segment-aware framing, selective proactive tools (Tier 1 only). |
| **0.6 – 0.8** | Intent + capital/equity + income (some inferred) | Full adaptation — all segment behaviors active, proactive tool sequences enabled. |
| **0.8 – 1.0** | All factors explicit (intake form or confirmed extraction) | Full adaptation + secondary job surfacing + cross-interaction consistency. |

**Confidence decay on return:** When a returning user's profile is loaded from
the database, each field's confidence is multiplied by 0.8. This reflects the reality
that circumstances change — income may have changed, capital may have been deployed
elsewhere, intent may have shifted. The system uses the prior profile as a starting
point but treats it as provisional until confirmed in the current conversation.

#### 6.5.4 Segment Transitions

When new information changes the classification:

1. **Higher confidence replaces lower.** If the current segment is "first_time_buyer"
   at confidence 0.5 and new data classifies as "down_payment_constrained" at 0.7,
   the transition happens.

2. **Equal confidence requires explicit evidence.** If both classifications have similar
   confidence, the system holds the current segment unless the new evidence is an
   explicit statement (e.g., "Actually, I'm looking at this as an investment").

3. **Transitions are logged.** Every transition is recorded with the evidence that
   triggered it, enabling debugging and pattern analysis.

4. **Transitions are not announced.** The buyer doesn't see "Reclassified from X to Y."
   The framing simply shifts naturally. Conversations shift tone all the time — this
   is not jarring.

### 6.6 Job Resolution (Step 3: RESOLVE)

Once a segment is classified, the job resolver determines what to do in this turn:
what the user asked for (explicit), what the segment needs (proactive), and how to
prioritize.

#### 6.6.1 Three Layers of Intent

Every turn has three layers of intent that may overlap or diverge:

| Layer | Source | Example |
|-------|--------|---------|
| **Explicit** | What the user typed | "Tell me about 1234 Cedar St" |
| **Segment** | What this segment's primary JTBD calls for | Stretcher → rent-vs-buy analysis |
| **Secondary** | What the segment's secondary JTBD should surface | Stretcher → true cost warnings |

The job resolver's output is a **turn plan** that combines all three:

```
TurnPlan {
    explicit_request: RequestType               // classified from user's message
    segment_job: Job                            // from Section 3
    proactive_analyses: Analysis[]              // pre-executed before LLM loop
    framing: FramingDirective                   // how to present results
    secondary_nudge: string | null              // secondary job to weave in
}
```

#### 6.6.2 Request Classification

The request classifier determines what the user explicitly asked for. Unlike signal
extraction (which needs an LLM for nuance), request classification is well-served by
pattern matching because requests map to discrete tool categories:

| Request Type | Trigger Patterns | Proactive Analyses |
|-------------|-----------------|-------------------|
| `property_evaluation` | Specific address mentioned; property context provided | Segment-dependent (see 6.6.3) |
| `search` | "find", "search", "show me", "which properties" | Working set update |
| `market_question` | "how's the market", "prices", "inventory", "trends" | Market summary |
| `affordability` | "can I afford", "budget", "monthly payment" | True cost computation |
| `investment_analysis` | "cap rate", "cash flow", "ROI", "rental income" | Rental income, scenarios |
| `comparison` | "compare", "vs", "which is better", "rank" | Batch query |
| `development_question` | "build", "ADU", "zoning", "lot split" | Development potential |
| `process_question` | "how does", "what is", "explain" | Glossary/regulation lookup |
| `sell_hold` | "should I sell", "hold", "keep" | Sell-vs-hold analysis |
| `general` | Doesn't match above | No pre-execution — fully reactive |

#### 6.6.3 Proactive Analysis Selection

When the segment is known (confidence ≥ 0.3), the job resolver selects analyses to
pre-execute. These run before the LLM loop, and their results are injected as verified
context — the LLM can reference them without spending iterations on tool calls.

| Segment | On `property_evaluation` | On `search` | On `affordability` |
|---------|------------------------|------------|-------------------|
| **Not Viable** | True cost (G-4), market summary | — | True cost (G-4), market summary |
| **Stretcher** | True cost (G-4), rent-vs-buy (G-1) | Neighborhood stats | True cost (G-4), rent-vs-buy (G-1) |
| **First-Time Buyer** | Price prediction, comps | Neighborhood stats | True cost (G-4) |
| **Down Pmt Constrained** | True cost (G-4), PMI model (G-2) | — | PMI model (G-2) |
| **Equity-Trapped** | Rate penalty (G-3), improvement sim, sell-vs-hold | — | Rate penalty (G-3) |
| **Competitive Bidder** | Price prediction, comps, competition (G-5) | Neighborhood stats | — |
| **Cash Buyer** | Rental income, regulation (rent control) | Yield ranking (G-7) | — |
| **Equity-Leveraging** | Dual-property model (G-6) | — | — |
| **Leveraged** | Rental income, cap rate | Yield ranking (G-7) | — |
| **Value-Add** | Dev potential, permits, improvement sim | Dev potential filter | — |
| **Appreciation Bettor** | Neighborhood stats, stress test (G-8) | Neighborhood stats | — |

**Pre-execution vs. reactive:** Pre-executed analyses consume no LLM iterations. They
run as ordinary function calls in the orchestration layer. The LLM receives their
results as context ("Here is the pre-computed rent-vs-buy analysis for this property...")
and can reference, explain, or extend them. The LLM still has its full iteration budget
for follow-up questions and reactive tool calls.

This fundamentally changes the iteration budget problem from Section 5.6. Instead of
a 12-iteration budget shared between proactive and reactive tools, proactive analyses
are free — only reactive (user-driven) tool calls consume iterations.

### 6.7 Prompt Assembly (Step 5: COMPOSE)

The system prompt is assembled from independent, composable units — not concatenated
onto a monolithic string.

#### 6.7.1 Prompt Components

```
SystemPrompt = assemble([
    BasePersonality,              // Faketor's character, tone baseline, honesty mandate
    DataModelRules,               // Record types, property categories, query rules
    ToolInstructions,             // When to use which tool, anti-patterns (no loops)
    MarketContext,                // Frozen market snapshot — rates, prices, inventory
    SegmentContext,               // Detected segment, buyer profile, confidence
    JobDirective,                 // Primary/secondary job, "done" criteria
    FramingGuide,                 // Tone, term definitions vs. assumed knowledge
    ProactiveBehavior,            // What to surface without being asked
    PropertyContext,              // Focus property + working set summary + prior analyses
    PreExecutedResults,           // Results from step 4 (verified context)
    AccumulatedFacts,             // Per-iteration fact summary (existing pattern)
    IterationBudget,              // Remaining iterations warning (existing pattern)
])
```

Each component is a function that returns a prompt fragment string, with clear
delimiters. Components can be independently tested: given segment X and profile Y,
does `SegmentContext(X, Y)` produce the right prompt block?

#### 6.7.2 Component Independence

Components are designed to avoid cross-dependencies and have different change
frequencies:

- `BasePersonality` never changes — it defines Faketor's character.
- `DataModelRules` changes only when the data model changes — it's not segment-aware.
- `ToolInstructions` changes only when tools are added/removed.
- `MarketContext` changes per interaction — frozen at context load/refresh from the
  `MarketSnapshot`. Provides rates, median prices, inventory, and conforming limits
  as the ground truth for all financial computations within the interaction.
- `SegmentContext`, `JobDirective`, `FramingGuide`, and `ProactiveBehavior` are the
  segment-aware components — they change based on the detected segment,
  and may change mid-interaction on segment transition.
- `PropertyContext` provides the focus property, working set summary, and any
  per-property analyses already completed (from PropertyState). This includes prior
  conclusions: "We previously analyzed 1234 Cedar and concluded it was 8% overpriced."
- `PreExecutedResults` and `AccumulatedFacts` change per turn.

This separation means segment-aware behavior can be developed and tested independently
of the tool infrastructure.

#### 6.7.3 Segment Prompt Templates

Each segment gets a prompt injection block composed from `SegmentContext` +
`JobDirective` + `FramingGuide` + `ProactiveBehavior`. Below are three representative
examples spanning the spectrum:

**Stretcher:**
```
=== BUYER SEGMENT ===
Segment: STRETCHER (confidence: 0.72)
Profile: Renter, $2,800/mo rent. $100K liquid capital. Intent: occupy.
Income: not yet known.

TONE: Warm, reassuring, honest. This buyer is anxious about whether they can
afford to buy. Do not be a cheerleader ("Go for it!") or a pessimist ("You
can't afford this"). Be the honest advisor who says "Here's the math."

PRIMARY JOB: Help this buyer understand whether buying at their price point
makes financial sense compared to continuing to rent.

SECONDARY JOB: If they proceed, surface the risks they're not seeing as a
current renter — true costs beyond the mortgage payment, maintenance surprises,
the illiquidity of homeownership.

FRAMING:
- When showing price predictions: frame as "is this fairly priced?" not "bid range"
- When showing monthly costs: ALWAYS show true cost (PITI + earthquake + maintenance
  + PMI if applicable), never just P&I. Compare explicitly to their current rent.
- When showing neighborhood stats: lead with "what does your budget buy here?"
- Define terms proactively: the buyer may not know PMI, escrow, or contingency

PROACTIVE:
- If the analysis suggests renting is financially better, say so. This is where
  Faketor differentiates from agents and brokers who can't say "don't buy."
- If the buyer's budget requires PMI, surface the PMI cost and duration.
=== END BUYER SEGMENT ===
```

**Competitive Bidder:**
```
=== BUYER SEGMENT ===
Segment: COMPETITIVE BIDDER (confidence: 0.85)
Profile: Strong capital ($350K) + high income ($280K). Intent: occupy.
Has likely lost bids before.

TONE: Confident, data-driven, strategic. This buyer doesn't need reassurance —
they need tactical intelligence. Be concise. Lead with numbers.

PRIMARY JOB: Help this buyer calibrate their bids — what's the rational price
for this specific property given comps, the model, and competitive dynamics?

SECONDARY JOB: Identify less competitive supply with similar housing stock.
The buyer may be fixated on a neighborhood without realizing adjacent areas
have comparable homes with less competition.

FRAMING:
- Price predictions → bid calibration: "Model fair value: $X. Upper bound: $Y.
  Sale-to-list suggests closing at Z% above list."
- Comps → closing patterns: "6 of 8 comps sold above asking, average 7% premium."
- Skip basic term definitions unless asked.
- Neighborhood stats → competition metrics, not education.

PROACTIVE:
- After showing comps, synthesize into a bid range: "Rational bid range: $X to $Y.
  Above $Y, the data doesn't support the premium."
- If sale-to-list exceeds 105%, suggest checking adjacent neighborhoods.
=== END BUYER SEGMENT ===
```

**Value-Add Investor:**
```
=== BUYER SEGMENT ===
Segment: VALUE-ADD INVESTOR (confidence: 0.91)
Profile: Investor seeking development upside. Evaluates based on
post-improvement yield and value creation, not current-state income.

TONE: Direct, technical, project-oriented. This buyer thinks in terms of
"what can I build here and does the math work?"

PRIMARY JOB: Find properties with development upside where zoning allows the
planned development and the numbers work after carrying costs.

SECONDARY JOB: Provide realistic timeline and regulatory pathway. Berkeley's
permitting timeline materially affects carrying costs and ROI — the buyer may
underestimate this.

FRAMING:
- Price predictions → spread analysis: "As-is: $X. Post-improvement: $Y.
  Value creation: $Z minus improvement costs of $W."
- Development potential → feasibility first: "Zoning allows [options].
  Constraints: [setbacks, height, FAR]."
- Investment scenarios → compare pre/post-development cash flows with carrying
  costs during development.
- Permits → feasibility evidence: "Prior ADU permit filed 2023 suggests city
  has approved similar projects on this block."

PROACTIVE:
- Always check development potential first — this is the threshold question.
- Always check permit history — prior permits signal feasibility.
- Warn about regulatory constraints early — a deal-killer discovered after
  acquisition is expensive.
=== END BUYER SEGMENT ===
```

#### 6.7.4 Low-Confidence Fallback

When segment confidence is below 0.3:

```
=== BUYER CONTEXT ===
Segment: Not yet determined.

When responding, naturally incorporate questions that help clarify this buyer's
situation. Do NOT interrogate — weave questions into your response:
- "Are you looking at this as a potential home, or evaluating it as an investment?"
- "Is this your first time buying in Berkeley?"
- "Do you have a sense of your budget or price range?"

One question per response, maximum. Let the conversation flow naturally.
=== END BUYER CONTEXT ===
```

### 6.8 State Model

The system's state has two tiers: a **research context** that persists across all
interactions for an authenticated user, and **per-turn ephemeral state** that exists
only for the duration of an LLM call. There is no intermediate "session" or
"conversation" entity — those are technical implementation details of the LLM context
window, not user-facing concepts.

From the buyer's perspective, they're on a continuous research journey. They don't
think "I'm starting conversation 3." They think "I'm back, show me those houses
again." The system should behave accordingly.

#### 6.8.1 Data Model

```
ResearchContext {
    user_id: string                               // authenticated user (owner)
    created_at: timestamp
    last_active: timestamp

    buyer: BuyerState {
        profile: BuyerProfile                     // Section 6.3.1
        segment_id: string | null
        segment_confidence: float
        segment_history: SegmentTransition[]
    }

    market: MarketSnapshot {
        snapshot_at: timestamp                    // when this snapshot was taken
        mortgage_rate_30yr: float                 // e.g. 6.12
        conforming_limit: int                     // e.g. 1249125 (Alameda County)
        berkeley_wide: {
            median_sale_price: int
            median_list_price: int
            median_ppsf: float
            median_dom: int
            avg_sale_to_list: float
            inventory: int
            months_of_supply: float
            homes_sold: int                       // trailing period
        }
        neighborhoods: Map<string, {              // keyed by neighborhood name
            median_price: int
            yoy_price_change_pct: float
            sale_count: int
            median_ppsf: float
            avg_sale_to_list: float
            median_dom: int
        }>
        prior_snapshot: MarketSnapshot | null      // previous snapshot (for delta)
    }

    property: PropertyState {
        filter_intent: FilterIntent | null        // the search criteria (persisted)
        result_set: PropertyRecord[]              // computed from filter_intent + current data
        filter_stack: FilterLayer[]               // history of narrowing operations
        focus_property: FocusProperty | null       // currently discussed property
        analyses: Map<int, PropertyAnalysis>       // keyed by property_id
    }
}
```

**Anonymous users** don't have a `ResearchContext`. Their state is held in memory
for the duration of a single interaction window (tied to a server-generated session
ID) and discarded when it expires. This is equivalent to the current behavior.

**Authenticated users** have exactly one `ResearchContext`. Every interaction —
regardless of when it happens, whether the user opened a new chat, or how much time
has passed — reads from and writes to this same context. The buyer profile accumulates
over time. Property analyses persist. The market snapshot refreshes when stale.

**Per-turn ephemeral state** exists only during a single orchestrator turn:

```
TurnState {
    turn_count: int                               // within this interaction window
    fact_accumulator: FactStore                   // accumulated verified facts for this window
    message_history: Message[]                    // LLM message array for this window
}
```

This is not a "conversation" entity — it's an implementation detail of the LLM call.
When the LLM context window fills up, older messages are summarized and their
conclusions are promoted into the `ResearchContext`. The user never sees this boundary.

**Why no "conversation" entity:**

Segment analysis confirms that buyers across all 11 segments are pursuing a single
research journey, not maintaining parallel threads. The Stretcher is answering one
question ("should I buy?"). The Competitive Bidder is tracking a handful of properties
in one search. The Value-Add Investor is screening for one development opportunity.
Even the Equity-Leveraging Investor, who by definition has two properties in play,
is making one connected decision — the two properties are analytically linked.

Separating conversations would create artificial walls between parts of the same
research. A buyer who mentions "that Cedar Street place" in a new chat should get
continuity, not a blank stare. One research context per user provides this naturally.
```

**Supporting types:**

```
FilterIntent {
    criteria: {                                   // the search parameters
        neighborhoods: string[] | null
        zoning_classes: string[] | null
        property_type: string | null
        min_price: int | null
        max_price: int | null
        min_beds: int | null
        max_beds: int | null
        min_lot_sqft: int | null
        adu_eligible: boolean | null
        sb9_eligible: boolean | null
        // ... (mirrors search_properties parameters)
    }
    description: string                           // human-readable: "SFR in North Berkeley, R-1, lots > 7000 sqft"
    created_at: timestamp
}

FocusProperty {
    property_id: int
    address: string
    last_known_status: "active" | "pending" | "sold" | "unknown"
    status_checked_at: timestamp
    property_context: PropertyContext             // full property details
}

PropertyAnalysis {
    property_id: int
    address: string
    analyses_run: Map<string, {                   // keyed by analysis type
        tool_name: string                         // e.g. "get_price_prediction"
        result_summary: string                    // "Predicted: $1.35M (confidence 85%)"
        conclusion: string | null                 // "8% overpriced based on comps"
        computed_at: timestamp
        market_snapshot_at: timestamp             // which market snapshot was used
    }>
}
```

#### 6.8.2 MarketSnapshot Semantics

MarketSnapshot is not research state in the way BuyerState and PropertyState are. It's
a **system-level read** that the research context captures once and holds constant for
the duration of an interaction window.

**Why frozen per interaction window:**

1. **Consistency.** If the system quotes a $4,730/mo payment in turn 2, the rate used
   to compute that number must be the same rate available in turn 7. Mid-interaction
   rate changes would produce inconsistent analysis that the buyer can't reconcile.

2. **The market doesn't move that fast.** Interaction windows are minutes to hours. Rates
   don't change intra-day. New sales don't close mid-conversation. A snapshot taken at
   interaction start is accurate for the window's duration.

3. **Reproducibility.** If the buyer screenshots an analysis and refers back to it
   three turns later, the numbers must match.

**Snapshot lifecycle:**

| Event | What Happens |
|-------|-------------|
| **First interaction (new user)** | Query the data layer for current market conditions. Freeze as `MarketSnapshot`. Set `prior_snapshot = null`. |
| **Returning user interaction** | Check if snapshot is stale (time-based, e.g. > 4 hours since last snapshot). If stale: query fresh market data, freeze as new `MarketSnapshot`, set `prior_snapshot` to the old one, compute delta (Section 6.8.6). If fresh: reuse existing snapshot. |
| **During interaction** | Read-only. All tools and computations reference the frozen snapshot. |
| **After interaction** | Save the current snapshot in the research context for delta comparison next time. |

**What the snapshot contains** (and where it comes from):

| Field | Source |
|-------|--------|
| `mortgage_rate_30yr` | `market_metrics` table (most recent period) or external rate feed |
| `conforming_limit` | Glossary service (`get_conforming_loan_limit()`) or config |
| `berkeley_wide.*` | Aggregated from `market_metrics` table (most recent period) |
| `neighborhoods.*` | Aggregated from `market_metrics` + `property_sales` grouped by neighborhood |

#### 6.8.3 PropertyState Semantics

PropertyState holds both *what the buyer is looking at* (selection) and *what they've
learned about it* (analysis). These were previously separate concepts (PropertyState
vs. ResearchState) but they're really one thing — the buyer's research portfolio.

**Filter intent vs. result set:**

The filter intent is the *query definition* — the criteria the buyer specified. The
result set is the *query result* — the properties that match. This distinction matters
because:

- Filter intent persists cleanly. "SFR in North Berkeley, R-1, lots > 7000 sqft" is
  meaningful weeks later.
- Result sets go stale. Properties sell. New listings appear. Prices change.

On return, the system **re-executes the filter intent** against current data.
The result set is always fresh because it's computed on access, not stored. The system
can then surface the delta: "Last time, 12 properties matched. Now there are 14 — 2
new listings appeared, and 1 from your previous set has sold."

**Per-property analyses:**

When the buyer evaluates a property (runs comps, gets a price prediction, checks
development potential), the conclusion is stored in `PropertyState.analyses` keyed by
property ID. This serves two purposes:

1. **Don't re-run.** If the buyer asks about 1234 Cedar again in a later turn, the
   system already has the analysis. It can reference prior conclusions without burning
   iterations or re-computing.

2. **Cross-turn coherence.** If the system said "1234 Cedar is 8% overpriced" in turn 3,
   and the buyer asks "what about that overpriced one on Cedar?" in turn 7, the system
   can connect the reference because the conclusion is stored.

**Analytical staleness:**

Per-property analyses are tagged with the `market_snapshot_at` timestamp — which market
snapshot was used when they were computed. On return, if the market snapshot has
changed materially, the system can flag stale analyses: "The price prediction for
1234 Cedar was computed when rates were 6.12%. Rates are now 5.85% — the analysis may
need updating."

Whether to automatically re-run or flag for manual re-run depends on the magnitude of
the market delta (Section 6.8.6).

**Focus property status tracking:**

The focus property — the one the buyer was deep-diving on — gets special treatment:

| Status on Resume | System Behavior |
|-----------------|-----------------|
| **Still active** | Resume seamlessly. Surface any changes (price reduction, new permits). |
| **Went pending** | Alert immediately: "1234 Cedar went pending since your last visit. It may still be available — pending deals fall through ~15% of the time in Berkeley." |
| **Sold** | Alert immediately: "1234 Cedar sold for $1.35M. Would you like to see similar properties, or look at the others from your previous search?" |
| **Status unknown** | Flag: "I can't confirm the current status of 1234 Cedar. Let me check..." and re-query. |

#### 6.8.4 Promotion from Ephemeral to Persistent State

Per-turn ephemeral state (the LLM message history, fact accumulator) exists only for
the duration of an interaction window. But during each turn, the orchestrator
**promotes** valuable outputs into the persistent research context:

| What's Produced During a Turn | Promoted To | Example |
|------------------------------|-------------|---------|
| Buyer factor extracted from message | `BuyerState.profile` | "I make $180K" → income = 180000 |
| Segment classification change | `BuyerState.segment_id` | Stretcher → Down Payment Constrained |
| Property-specific analysis conclusion | `PropertyState.analyses` | "1234 Cedar: 8% overpriced, poor ADU feasibility" |
| Working set filter applied | `PropertyState.filter_intent` + `filter_stack` | "Narrow to lots > 7000 sqft" |
| Focus property identified | `PropertyState.focus_property` | Buyer deep-dives on 1234 Cedar |
| General market question answered | Not promoted | "What's the Berkeley median?" — ephemeral |
| Glossary lookup | Not promoted | "What is PMI?" — ephemeral |
| Exploratory search without follow-up | Not promoted | "Show me condos in South Berkeley" with no further engagement |

Promotion happens after every turn, not at the end of a "session." The research
context accumulates continuously — there is no batch promotion step.

The promotion criteria: **if the buyer engaged meaningfully with a property or
analysis, promote. If the interaction was informational or exploratory, don't.**

"Engaged meaningfully" means: asked follow-up questions, asked for deeper analysis,
compared against other properties, or referenced it later. A single-turn lookup
with no follow-up is exploratory — it doesn't rise to a research conclusion.

#### 6.8.5 Lifecycle Summary

| Event | BuyerState | MarketSnapshot | PropertyState | Ephemeral Turn State |
|-------|-----------|---------------|--------------|---------------------|
| **First interaction (anonymous)** | Initialize empty | Snapshot from DB | Initialize empty | Initialize empty |
| **First interaction (new authenticated user)** | Initialize empty | Snapshot from DB | Initialize empty | Initialize empty |
| **Interaction (returning authenticated user)** | Load from DB (with decay if stale) | Refresh if stale. Set prior_snapshot. Compute delta. | Load filter intent + analyses from DB. Re-execute filters. Check focus property status. | Initialize empty |
| **Each turn** | Update from extraction. Persist immediately. | Read-only | Update focus, analyses, filter stack. Persist immediately. | Update turn count, facts |
| **Analysis conclusion reached** | — | — | Promote to analyses map | — |
| **Interaction ends (anonymous)** | Discard | Discard | Discard | Discard |
| **Interaction ends (authenticated)** | Already persisted | Already persisted | Already persisted | Discard |

The key difference from a session-based model: authenticated users' state is persisted
**continuously** (after each turn that changes it), not at "session end." There is no
session end — the buyer's research context is always current.

#### 6.8.6 Returning User Flow

When an authenticated user sends a message, the system loads their research context
and reconciles it with current reality. This isn't a separate "resume" action — it's
what happens on every first turn when the research context's market snapshot is stale.

**Context loading sequence:**

```
1. LOAD RESEARCH CONTEXT
   - Load BuyerProfile, PropertyState, MarketSnapshot from DB
   - If last_active was recent (< 4 hours): use as-is, no decay or delta
   - If last_active was stale (> 4 hours): apply confidence decay (×0.8),
     mark fields as stale (pending confirmation)

2. REFRESH MARKET (if stale)
   - Query current market data → new MarketSnapshot
   - Set prior_snapshot to the old snapshot
   - Compute market delta (see below)

3. REFRESH PROPERTY STATE (if stale)
   - Re-execute filter intent against current data → new result set
   - Compute property delta:
     • Properties that left the set (sold, status change)
     • Properties that entered the set (new listings)
     • Count changes
   - Check focus property current status via DB query
   - Flag analyses where market_snapshot_at ≠ current snapshot
     (these may need re-computation)

4. COMPOSE DELTA BRIEFING (if anything changed)
   - Generate a "since you've been away" summary for the LLM to deliver:
     • Market changes: "Rates dropped 25bps since your last visit (6.12% → 5.87%).
       This changes your monthly payment by ~$X."
     • Property changes: "1 of your 12 properties sold. 2 new listings match
       your criteria."
     • Focus property status: "1234 Cedar is still active. Price reduced by $25K."
     • Stale analyses: "Your rent-vs-buy analysis was computed at 6.12%. At the
       new rate, the breakeven timeline may be shorter."
   - Inject this briefing into the first turn's system prompt
     as a CONTEXT UPDATE block

5. INITIALIZE EPHEMERAL STATE
   - turn_count = 0
   - fact_accumulator = empty
   - message_history = empty
```

Note that steps 2-4 only execute when the research context is stale. A buyer who
sends two messages five minutes apart doesn't get a delta briefing on the second
message — the context is already fresh. A buyer who returns after three days gets
the full briefing because the market and property data may have changed.

**Market delta computation:**

```
MarketDelta {
    rate_change: float              // e.g. -0.25 (dropped 25bps)
    rate_change_pct: float          // e.g. -4.1%
    median_price_change: int        // e.g. +15000
    median_price_change_pct: float  // e.g. +1.1%
    inventory_change: int           // e.g. +12
    dom_change: int                 // e.g. -2
    sale_to_list_change: float      // e.g. +0.005

    // Materiality flags — does this delta change the analysis?
    rate_material: boolean          // |rate_change| > 0.125 (12.5 bps)
    price_material: boolean         // |price_change_pct| > 2%
    inventory_material: boolean     // |inventory_change| > 10%
}
```

When `rate_material` is true, all analyses that depend on mortgage rate are flagged
for re-computation. When `price_material` is true, price predictions and comp
analyses are flagged. These flags drive the "stale analyses" section of the resume
briefing.

**Property delta computation:**

```
PropertyDelta {
    left_set: PropertyRecord[]      // properties no longer matching (sold, status change)
    entered_set: PropertyRecord[]   // new properties matching the filter intent
    previous_count: int
    current_count: int

    focus_property_change: {
        status_changed: boolean     // e.g. active → pending
        price_changed: boolean      // price reduction or increase
        new_status: string
        price_delta: int | null
    } | null
}
```

#### 6.8.7 Persistence Strategy

| State Component | Anonymous Users | Authenticated Users |
|----------------|----------------|-------------------|
| **BuyerState** | In-memory only | Persisted to `buyer_profiles` table |
| **MarketSnapshot** | In-memory only | Persisted for delta comparison on return |
| **PropertyState** | In-memory only | Filter intent, per-property analyses, and focus property persisted. Result set is computed, not stored. |
| **TurnState** (ephemeral) | In-memory only | Not persisted — promotes to ResearchContext containers, then discarded |

For anonymous users, nothing persists. Each interaction starts fresh. This is
acceptable because anonymous users haven't invested in creating an account — the
system treats them as ephemeral.

For authenticated users, the ResearchContext persists continuously — after every
turn that changes state, the updated BuyerState, MarketSnapshot, and PropertyState
are written to the database. The system remembers who they are, what the market
looked like last time (for delta), and what they were researching. Every
interaction builds on the prior research context rather than starting from scratch.

### 6.9 End-to-End Worked Example

A 3-turn conversation with a buyer who turns out to be a Stretcher.

**Turn 1:**

User message: "What does a 2-bedroom condo in South Berkeley go for?"

```
EXTRACT (LLM call):
  Input: message + empty profile
  Output: {
    "signals": [
      {"evidence": "asking about 2BR condo pricing",
       "implication": "entry-level price point interest",
       "confidence": 0.5}
    ]
  }
  No buyer factors extracted — this is a market question, not a personal statement.

CLASSIFY:
  Known factors: 0
  Segment: null
  Confidence: 0.0

RESOLVE:
  Explicit request: market_question
  Segment: null → no proactive analyses
  Turn plan: {tools: [get_neighborhood_stats], framing: generic}

PRE-EXECUTE:
  None (no segment-specific pre-execution)

COMPOSE:
  System prompt: BasePersonality + DataModelRules + ToolInstructions
                + LowConfidenceFallback + PropertyContext(none)

CONVERSE:
  Claude calls get_neighborhood_stats("South Berkeley")
  Claude responds with pricing data and naturally asks:
  "South Berkeley 2BR condos have traded in the $600K–$750K range recently.
  Are you looking at this area for yourself, or as an investment?"

POST-PROCESS:
  No new signals from Claude's response (waiting for user's answer)

PERSIST:
  conversation.turn_count = 1
  buyer.profile.signals = [entry-level interest signal]
```

**Turn 2:**

User message: "For myself — I'm renting now, paying $2,800/month.
I have about $100K saved up."

```
EXTRACT (LLM call):
  Input: message + profile with 1 prior signal
  Output: {
    "intent": "occupy",
    "current_rent": 2800,
    "capital": 100000,
    "owns_current_home": false,
    "is_first_time_buyer": true,        // inferred: renting, no ownership mention
    "sophistication": "novice",          // inferred: simple language, no jargon
    "signals": [
      {"evidence": "said 'for myself'", "implication": "occupy intent", "confidence": 0.95},
      {"evidence": "renting at $2,800/mo", "implication": "current housing cost", "confidence": 0.95},
      {"evidence": "$100K saved", "implication": "liquid capital", "confidence": 0.90},
      {"evidence": "no mention of prior ownership", "implication": "likely first-time buyer", "confidence": 0.65}
    ]
  }

CLASSIFY:
  Known factors: intent (occupy) + capital ($100K) + income (not yet known)
  Factor coverage: 2/3 = 0.67
  Capital $100K on $650K target → 15.4% down → PMI required
  Monthly stress ratio: cannot fully compute (no income yet)
  But: capital < 20% down → "down_payment_constrained" candidate
  And: price point is entry-level → "stretcher" candidate
  Decision: "stretcher" (entry-level focus + capital constraint + novice signals)
  Confidence: 0.55 (2 of 3 factor groups known, some inference)

RESOLVE:
  Explicit request: none (buyer shared info, didn't ask a question)
  Segment: stretcher at 0.55 → moderate adaptation
  Primary job: rent-vs-buy comparison
  Proactive analyses (Tier 1 only — moderate confidence):
    1. G-4 (true_cost) at $650K with $100K down
  Turn plan: {
    proactive: [true_cost],
    framing: stretcher,
    secondary_nudge: "compare to current rent"
  }

PRE-EXECUTE:
  Run true_cost($650K, down=$100K, rate=market.mortgage_rate_30yr):
  (Using frozen MarketSnapshot: rate=6.12%, conforming_limit=$1,249,125)
  → P&I: $3,400 / Tax: $634 / Insurance: $190 / PMI: $180
    Earthquake: $95 / Maintenance: $230 / Total: $4,730/mo

COMPOSE:
  System prompt: BasePersonality + DataModelRules + ToolInstructions
                + MarketContext(market_snapshot)
                + StretcherSegment(confidence=0.55, profile)
                + PropertyContext(none)
                + PreExecutedResults(true_cost_analysis)

CONVERSE:
  Claude receives true cost analysis as verified context.
  Claude responds: "Let me put your numbers together. At a $650K condo with
  $100K down (15.4%), the real monthly cost of ownership is about $4,730..."
  [full breakdown as pre-computed]
  "...That's $1,930/month more than your current $2,800 rent. Whether that
  math works depends on your income and how long you'd stay — I'd need your
  household income to give you a complete picture. What do you and your
  partner earn?"

POST-PROCESS:
  No new buyer factors in this exchange (LLM asked for income — response pending)

PERSIST:
  buyer.profile updated with extracted fields
  buyer.segment_id = "stretcher"
  buyer.segment_confidence = 0.55
  conversation.turn_count = 2
```

**Turn 3:**

User message: "We make about $180K combined. Is it worth buying?"

```
EXTRACT (LLM call):
  Output: {
    "income": 180000,
    "signals": [
      {"evidence": "$180K combined income", "implication": "household gross income",
       "confidence": 0.90},
      {"evidence": "asking 'is it worth buying?'", "implication": "seeking buy/rent decision",
       "confidence": 0.85}
    ]
  }

CLASSIFY:
  Known factors: intent (occupy) + capital ($100K) + income ($180K) = 3/3
  Monthly gross: $15,000
  True cost $4,730 → 31.5% of gross income → tight but qualifying
  Segment: "stretcher" (confirmed — income supports purchase but with strain)
  Confidence: 0.85 (all three factor groups known, most from explicit statements)

RESOLVE:
  Explicit request: affordability ("is it worth buying?")
  Segment: stretcher at 0.85 → full adaptation
  Primary job: definitive rent-vs-buy analysis
  Proactive analyses (full — high confidence):
    1. G-1 (rent_vs_buy) with all parameters: rent=$2800, price=$650K,
       down=$100K, income=$180K, rate=current_market
    2. G-4 (true_cost) with DTI context
  Turn plan: {
    proactive: [rent_vs_buy, true_cost_with_dti],
    framing: stretcher_definitive,
    secondary_nudge: "Surface hidden costs of ownership that renters don't face"
  }

PRE-EXECUTE:
  (All computations use frozen MarketSnapshot: rate=6.12%, median=$1.4M)

  Run rent_vs_buy(full_parameters):
  → Breakeven: ~9 years at 4% appreciation
  → Tax benefit: ~$8K/yr mortgage interest deduction
  → After-tax monthly cost: ~$4,300/mo (vs. $2,800 rent)
  → Opportunity cost of $100K down payment at 5% return: $417/mo
  → Net comparison: buying costs ~$1,900/mo more than renting (after tax benefits)
  → 10-year total cost: buying wins by ~$40K IF appreciation is ≥ 4%/yr
  → 5-year total cost: renting wins by ~$85K

  Run true_cost_with_dti:
  → Front-end DTI: 31.5% (within FHA 31% → marginal, conventional 28% → over)
  → Back-end DTI with no other debt: 31.5% (within all programs)
  → Stress test: if maintenance spike of $10K, can cover from 6 months savings?
    $100K - $100K down = $0 remaining → no emergency fund after closing

COMPOSE:
  System prompt includes:
  - Stretcher segment context with full profile
  - Pre-executed rent-vs-buy analysis with all scenarios
  - Pre-executed DTI and stress test results
  - Framing: "Give a definitive, honest assessment. This buyer has provided
    a complete financial picture. The analysis shows buying works long-term
    but leaves them with no emergency fund. Surface this risk."

CONVERSE:
  Claude has all the analysis pre-computed. Uses iterations only for synthesis
  and any follow-up questions the buyer asks.
  Response includes:
  - Clear rent-vs-buy comparison with timeline
  - Honest warning: "The numbers work if you plan to stay 8+ years. But there's
    a risk: after closing costs and your $100K down payment, you'd have no
    emergency fund. A $15K roof repair or a month of lost income would be a
    crisis. I'd suggest either: (a) put less down (say $75K, accepting slightly
    higher PMI) to keep a reserve, or (b) save another $25-30K before buying."
  - Secondary job: earthquake insurance, special assessments, illiquidity

PERSIST:
  buyer.profile.income = 180000
  buyer.segment_confidence = 0.85
  conversation.turn_count = 3
  conversation.job_history includes rent-vs-buy resolution

PROMOTE (conversation → PropertyState):
  The rent-vs-buy analysis is a significant conclusion. If the buyer was evaluating
  a specific property, promote:
  - property.analyses[property_id] = {
      tool: "rent_vs_buy",
      result_summary: "Breakeven at 9 years, 4% appreciation. DTI 31.5%.",
      conclusion: "Buying works long-term but leaves zero emergency fund after closing.",
      market_snapshot_at: market.snapshot_at
    }
  In this case, the analysis was generic (not property-specific), so it attaches
  to the buyer's general research context rather than a specific property.
```

**What's different from the old Section 6:**

1. Signal extraction used an LLM, not keyword matching — it inferred "first-time buyer"
   from context, extracted sophistication level, understood the household structure.
2. Pre-execution ran the rent-vs-buy and true-cost analyses before the LLM loop — Claude
   received them as context, not as results of tool calls it had to decide to make.
3. The stress test (no emergency fund after closing) was surfaced proactively because
   the pre-execution had the data to compute it. In the old design, this would require
   Claude to decide to run a stress test, which it might not have done.
4. The framing directive ("Give a definitive, honest assessment") was generated because
   the system knew the buyer had provided complete information. At lower confidence, the
   directive would have been softer.

### 6.10 Segment Transition Example

**Turn 1-2:** Buyer asks about neighborhoods and prices. Classified as First-Time Buyer
(confidence 0.5) based on educational questions and occupy intent signals.

**Turn 3:** Buyer says: "I want to put 10% down. Is PMI a big deal?"

```
EXTRACT:
  Output: {
    "capital_constraint": "stated 10% down payment — capital below 20% of target",
    "signals": [
      {"evidence": "10% down", "implication": "capital below 20%", "confidence": 0.90},
      {"evidence": "asking about PMI", "implication": "PMI is a concern", "confidence": 0.85}
    ]
  }

CLASSIFY:
  Previous: first_time_buyer at 0.50
  New data: capital is ~10% of target price
  New classification: down_payment_constrained at 0.70
  0.70 > 0.50 → transition accepted
  Logged: {from: "first_time_buyer", to: "down_payment_constrained",
           turn: 3, reason: "10% down payment, PMI concern"}

RESOLVE:
  New primary job: PMI cost-vs-wait modeling
  Proactive analyses shift to: G-2 (PMI model), G-4 (true cost with PMI)
```

The transition is seamless — the buyer experiences better, more relevant analysis,
not a disorienting shift.

### 6.11 Edge Cases

#### 6.11.1 Mixed Intent (House Hacking)

Buyer says: "I want to live in one unit and rent out the other."

- EXTRACT identifies: intent = "occupy" (primary) + secondary invest signal
- CLASSIFY: classifies as occupy-side segment based on primary intent
- RESOLVE: includes rental income tools as secondary analyses
- COMPOSE: segment prompt acknowledges hybrid intent, includes both lifestyle and
  yield framing

The system doesn't force a binary. The prompt can say: "This buyer is primarily
an occupier who also wants rental income from a second unit. Frame the property
evaluation around livability first, investment return second."

#### 6.11.2 Misclassification Recovery

If the LLM frames a response inappropriately (e.g., heavy investment language for
an occupier), the buyer's correction is extracted as a high-confidence signal:

- "No, I'm not an investor — I just want to live here" → `intent: "occupy"`,
  confidence 0.95
- Reclassification is immediate on the next turn
- The worst case is one turn of suboptimal framing — not a system failure

#### 6.11.3 Professional Users

An agent or advisor using Faketor on behalf of a client exhibits expert vocabulary
but asks questions of all types. The system should:

- Detect `sophistication: expert` from vocabulary
- But classify segment based on the questions being asked, not the vocabulary level
- The framing adjusts for sophistication (concise, data-forward, no term definitions)
  independent of segment

#### 6.11.4 Multiple Scenarios in One Conversation

A buyer may say: "OK, now what if I treated this as an investment instead?"

- EXTRACT: explicit intent change to "invest"
- CLASSIFY: reclassifies to appropriate invest segment
- The system doesn't lose the prior occupy-side analysis — it's in conversation history
- Framing shifts to investment vocabulary and metrics

#### 6.11.5 Returning User — Full Resume Walkthrough

A user returns 3 weeks later. Previously: Stretcher with $100K capital, $180K income,
evaluating South Berkeley condos around $650K. Had focused on 1234 Ashby Ave.

**Resume sequence:**

```
1. LOAD BUYER STATE
   Profile loaded from DB:
   - intent: occupy, capital: $100K, income: $180K, rent: $2,800
   - segment: stretcher, confidence: 0.85 × 0.8 = 0.68
   - All fields marked stale

2. SNAPSHOT MARKET
   New snapshot: rate = 5.87% (was 6.12%)
   Market delta:
   - rate_change: -0.25 (dropped 25bps)
   - rate_material: true (|0.25| > 0.125 threshold)
   - median_price_change: +$12K (+0.9%) → price_material: false
   - inventory_change: +8 → inventory_material: false

3. REFRESH PROPERTY STATE
   Re-execute filter intent ("2BR condos in South Berkeley, $600-750K"):
   - Previous result: 12 properties
   - Current result: 13 properties
   - 1 property sold (789 Ward St, closed at $680K)
   - 2 new listings entered the set
   Focus property check (1234 Ashby Ave):
   - Status: still active, price reduced by $15K (was $685K, now $670K)
   Prior analyses flagged:
   - rent_vs_buy analysis: computed at 6.12%, rate has moved → stale
   - true_cost analysis: same → stale

4. COMPOSE RESUME BRIEFING
   "Welcome back! A few things have changed since your last visit:
   - Mortgage rates dropped to 5.87% (from 6.12%). This lowers your
     estimated monthly payment by about $110/mo on a $650K purchase.
   - 1234 Ashby Ave is still on the market — and the price dropped $15K
     to $670K. That improves your numbers.
   - 1 of your 12 properties sold. 2 new listings match your criteria.
   - Your rent-vs-buy analysis was based on the old rate — want me to
     re-run it at the new rate?"
```

When the buyer responds "Yes, and I've saved up more — I have $150K now":

```
EXTRACT:
  - capital: 150000 (updated from 100000, confidence 0.90)

CLASSIFY:
  - With $150K capital on $670K (reduced price): 22.4% down → no PMI!
  - Reclassification: stretcher → first_time_buyer
    (capital now covers 20% down; no longer stretching)
  - Confidence: 0.78 (decayed prior + fresh capital update)
  - Transition logged

PRE-EXECUTE:
  Re-run rent_vs_buy with updated inputs:
  - rate: 5.87% (new snapshot), price: $670K (reduced), down: $150K (22.4%)
  - No PMI (> 20% down)
  - Monthly cost drops from $4,730 to ~$4,050 ($3,200 P&I + $654 tax +
    $196 insurance, no PMI)
  - Delta from rent: $1,250/mo (was $1,930)
  - Breakeven: ~6 years (was ~9)

COMPOSE:
  System prompt now uses first_time_buyer segment (not stretcher)
  Includes: "The buyer's situation has improved materially since last visit.
  Rate dropped, price dropped, capital increased. PMI no longer required.
  The rent-vs-buy comparison shifted significantly in favor of buying."
```

This walkthrough shows how the ResearchContext (BuyerState + MarketSnapshot +
PropertyState), the market delta, and the property delta combine to give the
returning buyer a seamless, context-rich experience — not "who are you and what
are you looking for?" but "here's what changed and here's what it means for you."

---

## 7. Orchestration Architecture

Section 6 designed what the system should do — detect the buyer, classify their
segment, resolve their jobs, compose the right prompt, manage state. This section
specifies the concrete components, interfaces, module layout, and interaction patterns
that implement that design.

The goal is to make this section sufficient for implementation: a developer reading
Section 7 should know what files to create, what classes and functions each file
contains, how they call each other, and what the data contracts between them look like.

### 7.1 Module Layout

The new architecture introduces a `faketor/` package to replace the current monolithic
`services/faketor.py`. The existing file is ~1500 lines mixing system prompt, tool
definitions, tool execution, Claude API interaction, and response formatting. The new
structure separates these concerns into focused modules.

```
src/homebuyer/services/faketor/
├── __init__.py              # Package exports: FaketorService (backward-compat)
├── orchestrator.py          # Turn orchestrator: the central pipeline
├── extraction.py            # Signal extraction (LLM-based)
├── classification.py        # Deterministic segment classification
├── jobs.py                  # Job resolution and turn planning
├── prompts/
│   ├── __init__.py          # assemble() function
│   ├── personality.py       # BasePersonality prompt fragment
│   ├── data_model.py        # DataModelRules prompt fragment
│   ├── tools.py             # ToolInstructions prompt fragment
│   ├── market.py            # MarketContext prompt fragment
│   ├── segment.py           # SegmentContext + FramingGuide + ProactiveBehavior
│   ├── property.py          # PropertyContext prompt fragment
│   ├── preexecuted.py       # PreExecutedResults prompt fragment
│   └── templates/           # Per-segment prompt template strings
│       ├── stretcher.py
│       ├── first_time_buyer.py
│       ├── competitive_bidder.py
│       ├── cash_buyer.py
│       ├── value_add_investor.py
│       └── ...              # One per segment
├── state/
│   ├── __init__.py
│   ├── context.py           # ResearchContext (persistent) + TurnState (ephemeral)
│   ├── buyer.py             # BuyerState + BuyerProfile
│   ├── market.py            # MarketSnapshot + MarketDelta
│   └── property.py          # PropertyState + FilterIntent + PropertyAnalysis
├── tools/
│   ├── __init__.py          # Tool registry and FAKETOR_TOOLS definition
│   ├── definitions.py       # Tool schema definitions (Claude API format)
│   ├── executor.py          # Tool execution engine (replaces _make_session_tool_executor)
│   ├── preexecution.py      # Proactive tool pre-execution (runs before LLM loop)
│   └── new/                 # Gap tools from Section 5
│       ├── rent_vs_buy.py   # G-1
│       ├── pmi_model.py     # G-2
│       ├── rate_penalty.py  # G-3
│       ├── true_cost.py     # G-4
│       ├── competition.py   # G-5
│       ├── dual_property.py # G-6
│       ├── yield_ranking.py # G-7
│       ├── stress_test.py   # G-8
│       ├── lifestyle.py     # G-9
│       └── adjacent.py      # G-10
├── accumulator.py           # Moved from services/accumulator.py (unchanged)
└── facts.py                 # Moved from services/facts.py (unchanged)
```

**What moves, what stays, what's new:**

| Current File | Disposition |
|-------------|-------------|
| `services/faketor.py` | Decomposed into `faketor/` package. The file becomes a thin re-export for backward compatibility during migration. |
| `services/session_cache.py` | `SessionWorkingSet` evolves into `faketor/state/property.py` (PropertyState). `SessionManager` evolves into `faketor/state/context.py` (ResearchContextStore). |
| `services/accumulator.py` | Moves to `faketor/accumulator.py`. No changes — it works well. |
| `services/facts.py` | Moves to `faketor/facts.py`. Extended with fact computers for new gap tools. |
| `api.py` (Faketor endpoints) | Refactored to use new Orchestrator. `FaketorChatRequest` model updated. Research context loading delegated to `faketor/state/context.py`. |

### 7.2 Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                        API Layer                              │
│  FaketorChatRequest → /api/faketor/chat/stream               │
│  (buyer_context, message, session_id, property_context)       │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    Orchestrator                               │
│                                                               │
│  1. ContextStore.load_or_create(user_id)                     │
│  2. Extractor.extract(message, context.buyer)                │
│  3. Classifier.classify(context.buyer, context.market)       │
│  4. JobResolver.resolve(request, segment, context)           │
│  5. PreExecutor.run(turn_plan, context)                      │
│  6. PromptAssembler.assemble(context, turn_plan, pre_results)│
│  7. LLM Loop (Claude API with tool use)                      │
│  8. PostProcessor.process(response, context)                 │
│  9. ContextStore.persist(user_id)                            │
│                                                               │
└───┬──────────┬──────────┬──────────┬─────────┬──────────┬────┘
    │          │          │          │         │          │
    ▼          ▼          ▼          ▼         ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│Extract │ │Classify│ │Resolve │ │Pre-Exec│ │Compose │ │ Tools  │
│  or    │ │  or    │ │ Jobs   │ │ Tools  │ │ Prompt │ │Executor│
└────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
    │          │          │          │         │          │
    ▼          ▼          ▼          ▼         ▼          ▼
┌──────────────────────────────────────────────────────────────┐
│              Research Context (persistent)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                      │
│  │  Buyer   │ │  Market  │ │ Property │                      │
│  │  State   │ │ Snapshot │ │  State   │                      │
│  └──────────┘ └──────────┘ └──────────┘                      │
│                                                               │
│              Turn State (ephemeral, per-turn)                 │
│  ┌──────────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Fact Accumulator  │ │ Job History  │ │ Message History  │  │
│  └──────────────────┘ └──────────────┘ └──────────────────┘  │
└──────────────────────────────────────────────────────────────┘
    │                                                   │
    ▼                                                   ▼
┌──────────────────────┐              ┌────────────────────────┐
│  Persistence Layer   │              │    Data Layer           │
│  (buyer_profiles,    │              │    (database.py,        │
│   research_contexts, │              │     prediction model,   │
│   property_analyses) │              │     zoning, geocoder)   │
└──────────────────────┘              └────────────────────────┘
```

### 7.3 Component Specifications

#### 7.3.1 Orchestrator (`orchestrator.py`)

The Orchestrator is the central coordinator. It implements the 9-step pipeline from the
component diagram, executing each step in sequence. It is the only component that knows
about all other components — everything else is a pure function or a focused service with
no knowledge of the overall pipeline.

```python
class TurnOrchestrator:
    """Orchestrates a single chat turn through the segment-aware pipeline.

    Each method in the pipeline is a pure transformation except for the LLM
    call (step 7) and persistence (step 9). This makes the pipeline testable:
    given a research context and a message, steps 1-6 produce deterministic outputs.
    """

    def __init__(
        self,
        context_store: ResearchContextStore,
        extractor: SignalExtractor,
        classifier: SegmentClassifier,
        job_resolver: JobResolver,
        pre_executor: PreExecutor,
        prompt_assembler: PromptAssembler,
        tool_executor: ToolExecutor,
        llm_client: AnthropicClient,
        data_layer: DataLayer,
    ):
        ...

    def run_turn(
        self,
        session_id: str,
        user_id: str | None,
        message: str,
        history: list[dict],
        property_context: dict | None,
    ) -> Generator[SSEEvent, None, None]:
        """Execute a full turn. Yields SSE events for streaming.

        Steps:
        1. Load or create research context (by user_id for authenticated,
           by session_id for anonymous)
        2. Extract buyer signals from message
        3. Classify segment
        4. Resolve jobs and build turn plan
        5. Pre-execute proactive tools
        6. Assemble system prompt (includes return briefing if context
           has stale market data)
        7. Run LLM loop with reactive tool use (streaming)
        8. Post-process: extract signals from LLM output, promote state
        9. Persist research context (authenticated users only)
        """
        ...
```

**Key design decision:** The Orchestrator does not subclass or extend `FaketorService`.
It replaces it. `FaketorService` is a flat class that mixes concerns. The Orchestrator
is a pipeline coordinator that delegates to focused components. During migration, the
old `FaketorService.chat_stream()` method is preserved as a fallback path.

**No separate resume flow:** There is no `run_resume()` method. Every turn loads the
user's research context. If the market snapshot is stale (>4 hours), step 1 refreshes
it and computes a delta. The return briefing is composed as a prompt component in step 6
and delivered naturally as part of the LLM's first response. From the API's perspective,
a returning user's first turn is identical to any other turn — the context loading
handles the difference.

**Dependency injection:** All components are injected via constructor. This makes
testing straightforward — each component can be replaced with a mock. The API layer
constructs the Orchestrator with real implementations at startup.

#### 7.3.2 Signal Extractor (`extraction.py`)

The Signal Extractor uses an LLM call to parse buyer signals from a message. This is
the most important architectural departure from keyword matching: the LLM understands
context, implication, and nuance that no regex can capture.

```python
class ExtractionResult:
    """Structured output from the extraction LLM call."""
    intent: Literal["occupy", "invest"] | None
    capital: int | None
    equity: int | None
    income: int | None
    current_rent: int | None
    owns_current_home: bool | None
    is_first_time_buyer: bool | None
    sophistication: Literal["novice", "informed", "professional"] | None
    signals: list[Signal]

class Signal:
    evidence: str          # What the buyer said
    implication: str       # What it means for segmentation
    confidence: float      # 0.0–1.0

class SignalExtractor:
    """Extracts buyer signals from a message using a focused LLM call.

    This is NOT the main conversation LLM. It's a separate, cheap, fast
    call using a smaller model (haiku) with a structured output schema.
    The extraction prompt is short and focused — it sees only the message
    and the current buyer profile, not the full conversation history.
    """

    def __init__(self, client: AnthropicClient):
        ...

    def extract(
        self,
        message: str,
        current_profile: BuyerProfile,
        prior_signals: list[Signal],
    ) -> ExtractionResult:
        """Extract buyer signals from a single message.

        Uses claude-haiku with a structured JSON output schema.
        Returns empty ExtractionResult if no signals are detected
        (e.g., the message is a pure property question with no personal info).
        """
        ...

    def extract_from_output(
        self,
        llm_response: str,
        current_profile: BuyerProfile,
    ) -> ExtractionResult:
        """Extract signals from the LLM's response (post-processing).

        The LLM sometimes elicits and confirms information in its response
        that wasn't in the user's message. E.g., "So you're looking for your
        first home — " confirms first_time_buyer without the user saying it.
        """
        ...
```

**Why a separate LLM call, not inline extraction:**

1. **Speed.** Haiku is 10-20x cheaper and 5x faster than Sonnet. The extraction call
   adds ~200ms, not 2 seconds.

2. **Testability.** Extraction can be tested independently: given message X and profile Y,
   does extraction produce the right signals? This is a unit test, not an integration test.

3. **Separation of concerns.** The main LLM conversation should focus on being Faketor —
   analyzing properties, explaining data, giving advice. It should not also be parsing
   buyer signals from its own input. That's a distraction that dilutes prompt space.

4. **Deterministic downstream.** The output of extraction is a structured `ExtractionResult`
   that the deterministic classifier consumes. There's no ambiguity in the handoff.

**Extraction prompt structure:**

```
You are analyzing a home buyer's message to extract financial and situational
signals. You are NOT having a conversation — just parsing.

CURRENT BUYER PROFILE:
{current_profile as JSON}

PRIOR SIGNALS:
{prior_signals as JSON}

USER MESSAGE:
{message}

Extract any of the following if present. Return ONLY what you can confidently
extract. Do not infer aggressively — if the buyer says "I'm renting" that
implies they don't own, but it doesn't tell you their income.

Return JSON matching this schema:
{ExtractionResult schema}
```

#### 7.3.3 Segment Classifier (`classification.py`)

The Segment Classifier is entirely deterministic — no LLM, no heuristics, no
machine learning. It's a pure function that takes structured inputs and returns
a segment classification. This makes it fully testable and predictable.

```python
class SegmentResult:
    segment_id: str        # e.g. "stretcher", "cash_buyer"
    confidence: float      # 0.0–1.0
    reasoning: str         # Human-readable explanation of the classification
    factor_coverage: float # What fraction of factors are known

class SegmentClassifier:
    """Deterministic segment classifier.

    Implements the classification tree from Section 6.5.2. Takes a
    BuyerProfile and MarketSnapshot and returns a SegmentResult.

    This is a pure function — no state, no side effects, no LLM calls.
    """

    def classify(
        self,
        profile: BuyerProfile,
        market: MarketSnapshot,
    ) -> SegmentResult:
        """Classify the buyer into a segment.

        Returns SegmentResult with segment_id=None and confidence=0.0
        if insufficient information is available.
        """
        ...

    def should_transition(
        self,
        current: SegmentResult,
        proposed: SegmentResult,
        trigger_signal: Signal | None,
    ) -> bool:
        """Determine whether a segment transition should occur.

        Implements the transition rules from Section 6.5.4:
        - Higher confidence replaces lower
        - Equal confidence requires explicit evidence
        """
        ...
```

**Classification inputs and outputs are fully specified in Section 6.5.2.** The
implementation is a direct translation of that decision tree into code. No design
decisions remain — it's pure coding.

#### 7.3.4 Job Resolver (`jobs.py`)

The Job Resolver translates a classified segment into a concrete turn plan:
what analyses to pre-execute, how to frame the response, and what secondary
jobs to weave in.

```python
class TurnPlan:
    explicit_request: RequestType       # What the user asked for
    segment_job: Job | None             # Primary JTBD from Section 3
    proactive_analyses: list[Analysis]  # To pre-execute before LLM loop
    framing: FramingDirective           # How to present results
    secondary_nudge: str | None         # Secondary job to surface
    tool_priority: list[str]            # Preferred tool order for reactive use

class RequestType(str, Enum):
    PROPERTY_EVALUATION = "property_evaluation"
    SEARCH = "search"
    MARKET_QUESTION = "market_question"
    AFFORDABILITY = "affordability"
    INVESTMENT_ANALYSIS = "investment_analysis"
    COMPARISON = "comparison"
    DEVELOPMENT_QUESTION = "development_question"
    PROCESS_QUESTION = "process_question"
    SELL_HOLD = "sell_hold"
    GENERAL = "general"

class Analysis:
    """A proactive analysis to run before the LLM loop."""
    tool_name: str                     # Tool to call
    tool_input: dict                   # Arguments
    description: str                   # For logging and debugging
    depends_on: list[str] | None       # Other analyses that must complete first

class JobResolver:
    """Resolves segment + request into a concrete turn plan.

    The resolver knows:
    - What each segment's primary/secondary JTBD is (from Section 3)
    - What proactive analyses each segment×request combination triggers
      (from Section 6.6.3)
    - How to frame results for each segment (from Section 6.7.3)
    """

    def resolve(
        self,
        request_text: str,
        segment: SegmentResult | None,
        context: ResearchContext,
    ) -> TurnPlan:
        """Build a turn plan from the request and current state."""
        ...

    def classify_request(self, message: str) -> RequestType:
        """Classify the user's request into a RequestType.

        Uses pattern matching (not LLM) because request types map to
        discrete tool categories. This is well-served by keyword patterns
        because the boundary between "market question" and "property
        evaluation" is defined by the tools, not by natural language nuance.
        """
        ...
```

**The proactive analysis mapping is data, not code.** The mapping from
(segment, request_type) → analyses is a lookup table, not a chain of if/else
statements. Adding a new segment or changing the analysis for an existing
segment is a table update, not a code change.

```python
# Proactive analysis registry: (segment, request_type) → analyses
PROACTIVE_ANALYSES: dict[tuple[str, RequestType], list[AnalysisSpec]] = {
    ("stretcher", RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("true_cost", requires=["property_context", "market_snapshot"]),
        AnalysisSpec("rent_vs_buy", requires=["property_context", "market_snapshot", "buyer_profile"]),
    ],
    ("stretcher", RequestType.AFFORDABILITY): [
        AnalysisSpec("true_cost", requires=["market_snapshot", "buyer_profile"]),
        AnalysisSpec("rent_vs_buy", requires=["market_snapshot", "buyer_profile"]),
    ],
    ("competitive_bidder", RequestType.PROPERTY_EVALUATION): [
        AnalysisSpec("get_price_prediction", requires=["property_context"]),
        AnalysisSpec("get_comparable_sales", requires=["property_context"]),
        AnalysisSpec("competition_assessment", requires=["property_context", "market_snapshot"]),
    ],
    # ... one entry per (segment, request_type) pair from Section 6.6.3
}
```

#### 7.3.5 Pre-Executor (`tools/preexecution.py`)

The Pre-Executor runs proactive tools before the LLM loop. Its results become
verified context in the system prompt — the LLM can reference them without
spending iterations.

```python
class PreExecutionResult:
    """Results from pre-executing proactive tools."""
    results: dict[str, dict]           # tool_name → result_data
    facts: dict[str, dict]             # tool_name → computed facts
    prompt_fragment: str               # Ready-to-inject prompt section
    elapsed_ms: int                    # Total pre-execution time

class PreExecutor:
    """Runs proactive analyses before the LLM loop.

    Pre-execution is the key mechanism that changes the iteration budget
    problem. Instead of sharing a 12-iteration budget between proactive
    and reactive tools, proactive analyses are free — they run as ordinary
    function calls in the orchestration layer. Only reactive (user-driven)
    tool calls consume LLM iterations.
    """

    def __init__(self, tool_executor: ToolExecutor, fact_computers: FactRegistry):
        ...

    def execute(
        self,
        analyses: list[Analysis],
        context: ResearchContext,
    ) -> PreExecutionResult:
        """Run all proactive analyses and compute facts.

        Handles dependency ordering: if analysis B depends on analysis A's
        output, A runs first. Independent analyses could run concurrently
        (future optimization).

        Failures are handled gracefully: if a proactive analysis fails,
        the result is omitted from the prompt fragment and logged, but
        the turn proceeds. Pre-execution failures are not user-visible errors.
        """
        ...
```

**Pre-execution vs. reactive tool calls are invisible to the LLM.** Both
produce the same fact format. The difference is when they run (before the loop
vs. during the loop) and who initiated them (the orchestrator vs. Claude).
The LLM receives both through the same mechanism — verified data in the
system prompt.

#### 7.3.6 Prompt Assembler (`prompts/__init__.py`)

The Prompt Assembler composes the system prompt from independent components.
Each component is a pure function that takes specific inputs and returns a
prompt fragment string.

```python
class PromptAssembler:
    """Assembles the system prompt from independent components.

    Each component is a function: (inputs) → str. Components have clear
    delimiters and are independently testable.
    """

    def assemble(
        self,
        context: ResearchContext,
        turn_plan: TurnPlan,
        pre_execution_results: PreExecutionResult | None,
        accumulated_facts: str,
        iteration_remaining: int | None,
    ) -> str:
        """Compose the full system prompt for this turn's LLM call.

        Components are assembled in a fixed order. Each component decides
        whether to emit content based on its inputs — e.g., SegmentContext
        emits nothing if segment_confidence < 0.1.
        """
        components = [
            personality.render(),
            data_model.render(),
            tool_instructions.render(),
            market_context.render(context.market),
            segment_context.render(
                context.buyer.segment_id,
                context.buyer.segment_confidence,
                context.buyer.profile,
            ),
            job_directive.render(turn_plan),
            property_context.render(context.property),
            preexecuted_results.render(pre_execution_results),
            accumulated_facts,
            iteration_budget.render(iteration_remaining),
        ]
        return "\n\n".join(c for c in components if c)
```

**Each prompt component module** follows the same pattern:

```python
# prompts/market.py

def render(market: MarketSnapshot) -> str:
    """Render the MarketContext prompt fragment.

    Provides the LLM with the frozen market conditions for this turn:
    rates, prices, inventory, and conforming limits. This is the ground
    truth for all financial computations within the interaction.
    """
    if market is None:
        return ""

    return f"""=== MARKET CONDITIONS (frozen for this interaction) ===
Mortgage rate (30yr fixed): {market.mortgage_rate_30yr}%
Conforming loan limit (Alameda County): ${market.conforming_limit:,}
Berkeley median sale price: ${market.berkeley_wide.median_sale_price:,}
Berkeley median list price: ${market.berkeley_wide.median_list_price:,}
Median price/sqft: ${market.berkeley_wide.median_ppsf:.0f}
Median days on market: {market.berkeley_wide.median_dom}
Sale-to-list ratio: {market.berkeley_wide.avg_sale_to_list:.1%}
Active inventory: {market.berkeley_wide.inventory} listings
Months of supply: {market.berkeley_wide.months_of_supply:.1f}

Use these numbers as ground truth for all financial calculations. Do not
call get_market_summary unless the user explicitly asks for a detailed
market breakdown — the key metrics are already here.
=== END MARKET CONDITIONS ==="""
```

**Why per-segment template files** (`prompts/templates/stretcher.py`, etc.):
The segment prompt blocks from Section 6.7.3 are substantial (20-40 lines each)
and differ qualitatively across segments — they're not parameterized variations
of a single template. Each segment has its own tone, framing rules, proactive
behaviors, and term-definition policy. Making them separate files keeps each
one focused and editable without affecting others.

```python
# prompts/templates/stretcher.py

def render(profile: BuyerProfile, confidence: float) -> str:
    """Render the Stretcher segment prompt block."""
    # Build profile summary from known fields
    profile_parts = []
    if profile.current_rent:
        profile_parts.append(f"Renter, ${profile.current_rent:,}/mo rent")
    if profile.capital:
        profile_parts.append(f"${profile.capital:,} liquid capital")
    profile_parts.append("Intent: occupy")
    if profile.income:
        profile_parts.append(f"Income: ${profile.income:,}/yr")
    else:
        profile_parts.append("Income: not yet known")

    profile_summary = ". ".join(profile_parts) + "."

    return f"""=== BUYER SEGMENT ===
Segment: STRETCHER (confidence: {confidence:.2f})
Profile: {profile_summary}
...
=== END BUYER SEGMENT ==="""
```

#### 7.3.7 Tool Executor (`tools/executor.py`)

The Tool Executor replaces the current `_make_session_tool_executor` closure
in `api.py` and the `_faketor_tool_executor` function. It wraps tool execution
with research context awareness, working set management, fact enrichment,
and discussed property tracking.

```python
class ToolExecutor:
    """Executes Faketor tools with research context integration.

    Responsibilities:
    - Route tool calls to their implementations
    - Inject working set temp table for SQL-based tools
    - Intercept meta-tools (undo_filter, update_working_set)
    - Compute facts from tool results
    - Track discussed properties
    - Build frontend response blocks
    """

    def __init__(
        self,
        data_layer: DataLayer,
        fact_registry: FactRegistry,
    ):
        ...

    def execute(
        self,
        tool_name: str,
        tool_input: dict,
        context: ResearchContext,
    ) -> ToolResult:
        """Execute a tool call and return enriched results.

        Returns a ToolResult containing:
        - result_str: JSON string for the Claude tool_result message
        - facts: Computed facts (if applicable)
        - block: Frontend response block (if applicable)
        - working_set_update: Whether the working set changed
        """
        ...

class ToolResult:
    result_str: str                    # JSON for Claude's tool_result message
    result_data: dict | list | None    # Parsed result (for fact computation)
    facts: dict | None                 # Computed facts
    block: dict | None                 # Frontend block (type + data)
    working_set_changed: bool          # Did this tool modify the working set?
    discussed_property_id: int | None  # Property discussed (for tracking)
```

**The DataLayer** is a facade over the existing infrastructure. It aggregates
the database, ML model, development calculator, rental analyzer, and geocoder
into a single interface that tools can call without knowing the underlying
implementation.

```python
class DataLayer:
    """Facade over HomeBuyer data infrastructure.

    Provides typed access to the database, ML model, development calculator,
    rental analyzer, regulation/glossary services, and geocoder. Tools call
    DataLayer methods instead of reaching into AppState directly.

    This is the boundary between the Faketor package and the rest of
    HomeBuyer. Nothing inside faketor/ imports from api.py or accesses
    AppState directly.
    """

    def __init__(
        self,
        db: Database,
        model: PriceModel,
        dev_calc: DevelopmentCalculator,
        rental_analyzer: RentalAnalyzer,
        geocoder: Geocoder,
        regulation_service: BerkeleyRegulations,
        glossary_service: GlossaryService,
    ):
        ...

    # Property operations
    def lookup_property(self, address: str) -> dict | None: ...
    def search_properties(self, criteria: dict) -> dict: ...

    # Analysis operations
    def predict_price(self, property_dict: dict) -> dict: ...
    def get_development_potential(self, lat: float, lon: float, **kwargs) -> dict: ...
    def get_comparable_sales(self, neighborhood: str, **kwargs) -> list[dict]: ...
    def estimate_rental_income(self, property_dict: dict, **kwargs) -> dict: ...
    def analyze_investment_scenarios(self, property_dict: dict, **kwargs) -> dict: ...

    # Market operations
    def get_market_summary(self) -> dict: ...
    def get_neighborhood_stats(self, neighborhood: str, years: int = 2) -> dict: ...
    def snapshot_market(self) -> MarketSnapshot: ...

    # Knowledge operations
    def lookup_regulation(self, category: str, **kwargs) -> dict: ...
    def lookup_glossary_term(self, term: str) -> dict: ...
    def lookup_permits(self, address: str) -> list[dict]: ...

    # Database operations
    def execute_query(self, sql: str, working_set_ids: list[int] | None) -> dict: ...
```

#### 7.3.8 Research Context Store (`state/context.py`)

The Research Context Store manages the lifecycle of ResearchContext objects —
create, load, persist, and evict. It replaces the current `SessionManager`
which only manages `SessionWorkingSet` objects.

```python
@dataclass
class ResearchContext:
    """The persistent research state — one per authenticated user.

    This is the single object that flows through the entire pipeline.
    Every component reads from or writes to the ResearchContext.
    For anonymous users, a transient ResearchContext is created in
    memory (keyed by session_id) with the same structure.
    """
    user_id: str | None
    created_at: float
    last_active: float

    buyer: BuyerState
    market: MarketSnapshot
    property: PropertyState

    # Computed on load for returning users, None otherwise
    market_delta: MarketDelta | None = None

@dataclass
class TurnState:
    """Ephemeral per-turn state. Not persisted. Not an entity.

    Created fresh for each turn, accumulates facts and job history
    during the turn, then promotes relevant state to ResearchContext
    before the context is persisted.
    """
    turn_count: int = 0
    job_history: list[TurnPlan] = field(default_factory=list)
    fact_accumulator: AnalysisAccumulator = field(default_factory=AnalysisAccumulator)

    def promote(self, context: ResearchContext) -> list[str]:
        """Promote accumulated state to the persistent ResearchContext.

        Called at end of each turn. Returns descriptions of what was promoted.
        """
        ...

class ResearchContextStore:
    """Manages research context lifecycle.

    For authenticated users: loads from DB (one per user), persists after
    each turn that changes state. For anonymous users: in-memory with
    TTL-based eviction (keyed by session_id).
    """

    def __init__(
        self,
        data_layer: DataLayer,
        ttl_seconds: int = 1800,
    ):
        ...

    def load_or_create(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> ResearchContext:
        """Load an existing research context or create a new one.

        For authenticated users (user_id provided):
        - If a persisted context exists: load BuyerState (with confidence
          decay), load prior MarketSnapshot, load PropertyState (filter
          intent, analyses, focus property). Snapshot fresh market data
          and compute delta if stale (>4 hours).
        - If no persisted context: create empty context.

        For anonymous users (session_id only):
        - Look up in-memory cache by session_id.
        - If not found, create empty context.

        The returning-user flow (Section 6.8.6) is implicit: loading a
        persisted context with a stale market snapshot triggers delta
        computation. The delta is stored on the ResearchContext and
        consumed by the PromptAssembler to compose a return briefing.
        """
        ...

    def persist(self, context: ResearchContext) -> None:
        """Persist research context for authenticated users.

        Saves BuyerState, MarketSnapshot, and PropertyState to the
        database. Called after every turn that changes state. TurnState
        is not persisted — it promotes to ResearchContext first.
        """
        ...
```

### 7.4 Data Contracts

The components communicate through well-defined data types. These are the
contracts between components — changing one requires updating both the producer
and consumer.

#### 7.4.1 BuyerProfile and BuyerState (`state/buyer.py`)

```python
@dataclass
class FieldSource:
    """Provenance for a single buyer profile field."""
    source: Literal["explicit", "extracted", "inferred", "intake_form"]
    confidence: float          # 0.0–1.0
    evidence: str              # What the buyer said or what was inferred from
    extracted_at: float        # timestamp
    stale: bool = False        # True after confidence decay on resume

@dataclass
class BuyerProfile:
    """The buyer's financial and situational profile.

    Every numeric field has a companion FieldSource for provenance.
    Fields are None until extracted — not defaulted to zero.
    """
    intent: Literal["occupy", "invest"] | None = None
    intent_source: FieldSource | None = None

    capital: int | None = None
    capital_source: FieldSource | None = None

    equity: int | None = None
    equity_source: FieldSource | None = None

    income: int | None = None
    income_source: FieldSource | None = None

    current_rent: int | None = None
    current_rent_source: FieldSource | None = None

    owns_current_home: bool | None = None
    owns_current_home_source: FieldSource | None = None

    is_first_time_buyer: bool | None = None
    is_first_time_buyer_source: FieldSource | None = None

    sophistication: Literal["novice", "informed", "professional"] | None = None
    sophistication_source: FieldSource | None = None

    signals: list[Signal] = field(default_factory=list)

    def apply_extraction(self, result: ExtractionResult) -> list[str]:
        """Apply extracted signals to the profile.

        Only updates fields where the extraction is more confident than
        the existing value. Returns a list of field names that changed.
        """
        ...

    def apply_confidence_decay(self, factor: float = 0.8) -> None:
        """Decay all field confidences. Called when loading a returning user's profile."""
        ...

    def known_factor_count(self) -> int:
        """Count of non-None primary factors (intent, capital, equity, income)."""
        ...

@dataclass
class BuyerState:
    """Complete buyer state container."""
    profile: BuyerProfile
    segment_id: str | None = None
    segment_confidence: float = 0.0
    segment_history: list[SegmentTransition] = field(default_factory=list)

    def record_transition(
        self,
        from_segment: str | None,
        to_segment: str,
        confidence: float,
        trigger: Signal | None,
    ) -> None:
        """Record a segment transition in the history."""
        ...
```

#### 7.4.2 MarketSnapshot (`state/market.py`)

```python
@dataclass
class BerkeleyWideMetrics:
    median_sale_price: int
    median_list_price: int
    median_ppsf: float
    median_dom: int
    avg_sale_to_list: float
    inventory: int
    months_of_supply: float
    homes_sold: int

@dataclass
class NeighborhoodMetrics:
    median_price: int
    yoy_price_change_pct: float
    sale_count: int
    median_ppsf: float
    avg_sale_to_list: float
    median_dom: int

@dataclass
class MarketSnapshot:
    snapshot_at: float
    mortgage_rate_30yr: float
    conforming_limit: int
    berkeley_wide: BerkeleyWideMetrics
    neighborhoods: dict[str, NeighborhoodMetrics]
    prior_snapshot: "MarketSnapshot | None" = None

    def compute_delta(self) -> "MarketDelta | None":
        """Compute the delta from prior_snapshot to this snapshot."""
        if self.prior_snapshot is None:
            return None
        ...

@dataclass
class MarketDelta:
    rate_change: float
    rate_change_pct: float
    median_price_change: int
    median_price_change_pct: float
    inventory_change: int
    dom_change: int
    sale_to_list_change: float

    rate_material: bool          # |rate_change| > 0.125
    price_material: bool         # |price_change_pct| > 2%
    inventory_material: bool     # |inventory_change_pct| > 10%
```

#### 7.4.3 PropertyState (`state/property.py`)

```python
@dataclass
class FilterIntent:
    criteria: dict              # Mirrors search_properties parameters
    description: str            # Human-readable
    created_at: float

@dataclass
class FocusProperty:
    property_id: int
    address: str
    last_known_status: Literal["active", "pending", "sold", "unknown"]
    status_checked_at: float
    property_context: dict      # Full property details

@dataclass
class AnalysisRecord:
    tool_name: str
    result_summary: str
    conclusion: str | None
    computed_at: float
    market_snapshot_at: float    # For staleness detection

@dataclass
class PropertyAnalysis:
    property_id: int
    address: str
    analyses: dict[str, AnalysisRecord]  # Keyed by analysis type

@dataclass
class PropertyState:
    """The buyer's property research portfolio.

    Combines what they're looking at (filter intent, working set) with
    what they've learned (analyses, conclusions).
    """
    filter_intent: FilterIntent | None = None
    working_set: SessionWorkingSet = field(default_factory=SessionWorkingSet)
    focus_property: FocusProperty | None = None
    analyses: dict[int, PropertyAnalysis] = field(default_factory=dict)

    def record_analysis(
        self,
        property_id: int,
        address: str,
        tool_name: str,
        result_summary: str,
        conclusion: str | None,
        market_snapshot_at: float,
    ) -> None:
        """Record an analysis conclusion for a property."""
        ...

    def get_stale_analyses(
        self,
        current_snapshot_at: float,
        material_delta: MarketDelta | None,
    ) -> list[tuple[int, str, AnalysisRecord]]:
        """Find analyses that may need re-computation.

        Returns (property_id, analysis_type, record) tuples for analyses
        where the market snapshot has changed materially since computation.
        """
        ...
```

**Note:** `PropertyState.working_set` reuses the existing `SessionWorkingSet`
class for the filter stack and property record management. The working set is
a well-designed component that doesn't need replacement — it needs a home in
the proper state hierarchy.

#### 7.4.4 TurnState (ephemeral, defined in `state/context.py`)

TurnState is not a separate module — it lives in `state/context.py` alongside
ResearchContext. It is defined in Section 7.3.8 above.

TurnState is created fresh for each turn, not for each "session" or "conversation."
It accumulates facts and job history during the turn, then promotes relevant
state to ResearchContext at the end of the turn. The promotion criteria
(from Section 6.8.4):

- Buyer factors → BuyerState.profile (always)
- Segment changes → BuyerState.segment_id (always)
- Property analyses → PropertyState.analyses (if engaged meaningfully)
- Filter operations → PropertyState.filter_intent (always)
- Focus property → PropertyState.focus_property (if drilled in)

Because promotion happens after every turn (not at "session end"), the
ResearchContext is always up to date. There is no risk of losing state
because a "session" expired or the user closed the browser.

### 7.5 API Layer Changes

The API layer changes are substantial but contained. The Faketor endpoints are
updated to use the Orchestrator, and the request/response models are extended
to support buyer context.

#### 7.5.1 Updated Request Model

```python
class BuyerContext(BaseModel):
    """Buyer information from the frontend.

    This is the buyer-side complement to the existing property context.
    It's optional — the system works without it (anonymous users start
    with an empty buyer profile). When provided, it seeds the
    BuyerProfile with explicit, high-confidence values.
    """
    intent: Literal["occupy", "invest"] | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    capital: int | None = None
    income: int | None = None
    current_rent: int | None = None
    is_first_time_buyer: bool | None = None
    owns_current_home: bool | None = None

class FaketorChatRequest(BaseModel):
    """Updated chat request model.

    Key changes from current model:
    - buyer_context added (optional, for intake-form seeding)
    - session_id is optional — server generates if absent
    - Property fields remain for backward compatibility but are
      secondary to the research context's PropertyState
    """
    message: str
    session_id: str | None = None      # Optional — server generates if absent
    history: list[dict] = []
    buyer_context: BuyerContext | None = None

    # Property context (backward-compat — may be superseded by research context)
    latitude: float | None = None      # Was required, now optional
    longitude: float | None = None
    address: str | None = None
    neighborhood: str | None = None
    zip_code: str | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: float | None = None
    lot_size_sqft: float | None = None
    year_built: float | None = None
    property_type: str | None = None
    property_category: str | None = None
```

**Why latitude/longitude become optional:** The current model requires lat/lon
because the system is property-first. The redesign is buyer-first — a buyer can
start a conversation without having a specific property in mind ("What's the
market like in North Berkeley?" or "Can I afford to buy here?"). The property
context is provided when the buyer has one, not as a prerequisite for conversation.

#### 7.5.2 Updated Endpoint

```python
@app.post("/api/faketor/chat/stream")
async def faketor_chat_stream(req: FaketorChatRequest):
    """SSE streaming Faketor chat with segment-aware orchestration.

    The endpoint is the thin boundary between HTTP and the Orchestrator.
    It:
    1. Resolves session_id (use provided, or generate new)
    2. Extracts user_id from the auth token (if authenticated)
    3. Seeds buyer context from the request (if provided)
    4. Delegates to the Orchestrator
    5. Wraps Orchestrator SSE events into HTTP SSE format
    """
    session_id = req.session_id or str(uuid.uuid4())
    user_id = get_current_user_id(req)  # None for anonymous

    def event_generator():
        # Always emit session_id first so the client can capture it
        yield f"event: session_id\ndata: {safe_json_dumps({'session_id': session_id})}\n\n"

        for event in orchestrator.run_turn(
            session_id=session_id,
            user_id=user_id,
            message=req.message,
            history=req.history,
            property_context=_resolve_property_context(req),
            buyer_context=req.buyer_context,
        ):
            yield f"event: {event.type}\ndata: {safe_json_dumps(event.data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
```

**Session ID ownership:** The server owns session creation. The `session_id` is a
lightweight correlation ID for grouping messages within a single browser tab or CLI
session — it is not the primary key for state. For authenticated users, state is
keyed by `user_id` (one ResearchContext per user). For anonymous users, `session_id`
keys the in-memory cache. If the client provides a `session_id`, the server uses it.
If the client doesn't provide one, the server generates a UUID and emits it as the
first SSE event (`session_id`). This means any chat frontend — CLI, Slack bot,
mobile app, or a completely different React app — can use the API without
understanding state management upfront.

**New SSE event types:**

| Event | Data | When |
|-------|------|------|
| `session_id` | `{session_id}` | Always first — client captures for subsequent requests |
| `segment_update` | `{segment_id, confidence, profile_summary}` | After classification or transition |
| `resume_briefing` | `{market_changes, property_changes, stale_analyses}` | First turn when returning user has stale market data |
| `pre_execution_start` | `{analyses: [{name, description}]}` | Before pre-execution phase |
| `pre_execution_complete` | `{results_count, elapsed_ms}` | After pre-execution |
| `text_delta` | `{text}` | During LLM streaming (unchanged) |
| `tool_start` | `{name, label}` | When LLM calls a tool (unchanged) |
| `tool_result` | `{name, block}` | After tool execution (unchanged) |
| `working_set` | `{count, sample, filters}` | When working set changes (unchanged) |
| `discussed_property` | `{property_id, address}` | When a property is discussed (unchanged) |
| `done` | `{reply, tool_calls, blocks}` | Turn complete (unchanged) |
| `error` | `{message}` | Error (unchanged) |

The existing event types are preserved for backward compatibility. New event types
are additive — the frontend can ignore them until it's ready to render them.

#### 7.5.3 No Separate Resume Endpoint

There is no `/api/faketor/session/resume` endpoint. The return flow is handled
implicitly: when an authenticated user sends their first message, the Orchestrator
loads their ResearchContext, detects stale market data, computes the delta, and
includes the return briefing in the response. The frontend receives a
`resume_briefing` SSE event and can render it as a structured "welcome back"
card. This eliminates a round-trip and simplifies the API surface — the client
doesn't need to know whether the user is "returning" or not.

### 7.6 Persistence Schema

The research context model requires database tables for authenticated user
persistence. These are additive — no existing tables are modified.

```sql
-- Buyer profiles (one per user)
CREATE TABLE IF NOT EXISTS buyer_profiles (
    user_id         TEXT PRIMARY KEY REFERENCES users(id),
    profile_json    TEXT NOT NULL,          -- JSON-serialized BuyerProfile
    segment_id      TEXT,
    segment_conf    REAL DEFAULT 0.0,
    segment_history TEXT,                   -- JSON array of SegmentTransition
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Research contexts (one per user — market + property state)
CREATE TABLE IF NOT EXISTS research_contexts (
    user_id         TEXT PRIMARY KEY REFERENCES users(id),
    market_json     TEXT NOT NULL,          -- JSON-serialized MarketSnapshot
    property_json   TEXT NOT NULL,          -- JSON-serialized PropertyState
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-property analysis conclusions (persistent across interactions)
CREATE TABLE IF NOT EXISTS property_analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(id),
    property_id     INTEGER NOT NULL,
    address         TEXT,
    analysis_type   TEXT NOT NULL,          -- e.g. "price_prediction", "rent_vs_buy"
    tool_name       TEXT NOT NULL,
    result_summary  TEXT,
    conclusion      TEXT,
    computed_at     TIMESTAMP,
    snapshot_at     TIMESTAMP,             -- market snapshot used
    UNIQUE(user_id, property_id, analysis_type)
);

CREATE INDEX IF NOT EXISTS idx_property_analyses_user
    ON property_analyses(user_id);
CREATE INDEX IF NOT EXISTS idx_property_analyses_property
    ON property_analyses(user_id, property_id);
```

Note the key simplification: `research_contexts` has `user_id` as its PRIMARY KEY,
not `(user_id, session_id)`. There is exactly one research context per user.
The `buyer_profiles` table is separated because buyer profile data has a different
update frequency and could be shared with other features (e.g., personalized
recommendations) independently of the market/property research state.

### 7.7 Frontend Integration

The frontend changes needed are significant but can be phased separately from the
backend. The backend changes are designed to be backward-compatible with the current
frontend through the existing SSE event types.

#### 7.7.1 Current Frontend Architecture

The Chat page (`ui/src/pages/Chat.tsx`) is the primary interface. It:
- Manages a `messages` state array of `ChatMessage` objects
- Generates a session ID via `crypto.randomUUID()` per conversation
- Sends the active property's lat/lon/address in every request
- Handles SSE streaming with tool chips and block rendering
- Uses `PropertyContext` for tracked properties and working set state

#### 7.7.2 Frontend Changes (Phased)

**Phase 1: Backend-only changes, no frontend changes required.**

The new backend Orchestrator works with the existing frontend because:
- The same SSE event types are emitted
- `FaketorChatRequest` still accepts the old field format (lat/lon required) — backward compat
- Session ID is already generated client-side
- New SSE event types (`segment_update`, `resume_briefing`) are ignored by the
  existing frontend (EventSource ignores unknown event types)

**Phase 2: Buyer context intake (frontend change).**

Add an optional intake step before or during the first chat turn:

```typescript
// New component: BuyerIntakeModal or inline questionnaire
interface BuyerIntakeData {
    intent?: 'occupy' | 'invest';
    budget_min?: number;
    budget_max?: number;
    capital?: number;
    income?: number;
    current_rent?: number;
    is_first_time_buyer?: boolean;
}

// Sent as buyer_context in FaketorChatRequest
```

The intake form is optional. Buyers who skip it get the extraction-based flow.
Buyers who fill it out get high-confidence segment classification from turn 1.

**Phase 3: Segment-aware UI elements (frontend change).**

- Display the detected segment badge (subtle, non-intrusive)
- Show the return briefing when a returning user's first turn triggers a delta
- Render pre-execution progress indicators
- Surface stale analysis warnings

**Phase 4: Return experience (frontend change).**

- Handle `resume_briefing` SSE event to display "welcome back" card
- Market and property delta display when the user returns after time away
- No separate resume flow needed — the first message triggers it automatically

#### 7.7.3 PropertyContext Evolution

The current `PropertyContext` React context manages:
- `activeProperty`: The property the user is viewing
- `trackedProperties`: Properties tracked during the conversation
- `workingSetMeta`: Working set metadata from the backend

This evolves to include buyer state:

```typescript
// New: BuyerContext (separate React context, not mixed with PropertyContext)
interface BuyerContextData {
    segment?: string;
    segmentConfidence?: number;
    profileSummary?: string;
    intakeCompleted: boolean;
}
```

Buyer context is a separate React context because it has a different lifecycle
(persists across property changes) and different consumers (the chat interface
uses it, the property detail views don't).

### 7.8 Migration Strategy

The architecture change is significant. It must be done incrementally — the system
must work at every intermediate step, not just at the end.

#### 7.8.1 Migration Phases

**Phase A: Package structure and DataLayer.**

1. Create the `faketor/` package directory structure
2. Move `accumulator.py` and `facts.py` (no changes needed)
3. Create `DataLayer` as a facade over existing `AppState` infrastructure
4. Create `faketor/__init__.py` that re-exports `FaketorService` from the original
   location — zero behavior change

At this point, everything works exactly as before. The package exists but isn't used.

**Phase B: State containers.**

1. Create `state/buyer.py`, `state/market.py`, `state/property.py` with their
   data classes
2. Create `state/context.py` with `ResearchContext`, `TurnState`, and
   `ResearchContextStore` that wraps the existing `SessionManager` and adds
   `BuyerState` and `MarketSnapshot`
3. Wire `ResearchContextStore` into the API layer alongside the existing `SessionManager`
4. Run both in parallel — new state is computed but not yet used by the LLM

At this point, research contexts have the new state containers but nothing reads from them.

**Phase C: Extraction and Classification.**

1. Create `extraction.py` with the signal extractor
2. Create `classification.py` with the segment classifier
3. Wire them into the existing chat flow as a pre-step:
   - Before calling `FaketorService.chat_stream()`, run extraction + classification
   - Store the result in the `ResearchContext.buyer`
   - Log segment classifications for monitoring
4. The existing system prompt is unchanged — extraction runs but doesn't affect behavior

At this point, the system classifies segments on every turn but doesn't act on them.
This is the observability phase — we can monitor classifications and tune the extraction
prompt before it affects user-facing behavior.

**Phase D: Prompt assembly.**

1. Create the `prompts/` directory with all component modules
2. Create `prompts/__init__.py` with the `assemble()` function
3. Create per-segment template files
4. Switch the system prompt from the monolithic `SYSTEM_PROMPT` to
   `PromptAssembler.assemble()`, gated by a feature flag
5. A/B test: run both prompts in parallel (the old monolithic and the new composed)
   and compare quality

At this point, the system prompt is segment-aware for flagged users. The old prompt
is the fallback.

**Phase E: Pre-execution and Orchestrator.**

1. Create `tools/preexecution.py`
2. Create `jobs.py` with the job resolver
3. Create `orchestrator.py` with `TurnOrchestrator`
4. Wire the Orchestrator into the API endpoint, gated by the same feature flag
5. The Orchestrator calls the same tools through the same `DataLayer` — the only
   difference is the pipeline around the LLM call

At this point, the full pipeline is active for flagged users. The old path is
the fallback.

**Phase F: Gap tools.**

1. Implement gap tools (G-1 through G-10) in `tools/new/`
2. Register them in the tool definitions and fact computers
3. Add them to the proactive analysis registry
4. These tools are only invoked by the pre-executor for classified segments —
   they don't appear in the LLM's tool list until they're mature enough for
   reactive use

**Phase G: Persistence.**

1. Create the persistence schema (Section 7.6)
2. Implement `ResearchContextStore.persist()` and
   `ResearchContextStore.load_or_create()` with database backing
3. Implement the returning-user flow (stale detection, delta computation,
   return briefing prompt component)
4. This is the phase where cross-interaction continuity becomes real

**Phase H: Frontend integration.**

1. Implement buyer intake UI
2. Implement return briefing display
3. Implement segment badge

#### 7.8.2 Feature Flag Strategy

The migration uses a single feature flag: `USE_SEGMENT_ORCHESTRATION`.

```python
# In config.py
USE_SEGMENT_ORCHESTRATION = os.getenv("USE_SEGMENT_ORCHESTRATION", "false").lower() == "true"
```

When `false`: the current `FaketorService.chat_stream()` path is used. The new
infrastructure runs in shadow mode (extraction + classification + logging, no
user-visible behavior change).

When `true`: the `TurnOrchestrator.run_turn()` path is used. The full segment-aware
pipeline is active.

This allows:
- Incremental deployment (flag on for internal users, off for production)
- Easy rollback (flag off = instant revert)
- A/B testing (flag on for 10% of users, measure quality metrics)
- Shadow monitoring (classification runs always, even when flag is off)

#### 7.8.3 Backward Compatibility Guarantees

During migration, these invariants are maintained:

1. **The existing frontend works without changes** through Phase E. All current
   SSE event types are preserved with the same data format.

2. **Anonymous users are unaffected.** They get extraction and classification
   but no persistence — the segment-aware behavior is the only visible change,
   and it's additive (better framing, not different data).

3. **No database migrations are required until Phase G.** The persistence tables
   are additive — no existing tables are modified.

4. **The existing tool executor is wrapped, not replaced.** The new `ToolExecutor`
   delegates to the same underlying functions. Tool results are identical.

5. **The accumulator and facts modules are unchanged.** They move files but don't
   change behavior.

### 7.9 Testing Strategy

The architecture is designed for testability. Each component has a well-defined
interface, takes structured inputs, and produces structured outputs. Most components
are pure functions or stateless services that can be tested in isolation.

#### 7.9.1 Unit Tests

| Component | Test Strategy | Example |
|-----------|--------------|---------|
| `SegmentClassifier` | Pure function — given profile + market, assert segment + confidence. No mocks needed. | `test_stretcher_classification()`: profile with occupy intent, $100K capital, $650K market → stretcher at ~0.55 |
| `JobResolver` | Pure function — given segment + request type + context, assert turn plan. | `test_stretcher_property_eval()`: stretcher segment + property_evaluation → true_cost + rent_vs_buy in proactive |
| `PromptAssembler` | Pure function — given research context, assert prompt contains expected fragments. | `test_market_context_rendering()`: snapshot with 6.12% rate → prompt contains "6.12%" |
| Prompt templates | Pure function — given profile + confidence, assert segment block format. | `test_stretcher_template()`: profile with rent $2800 → prompt contains "$2,800/mo rent" |
| `BuyerProfile` | Data class methods — test `apply_extraction()`, `apply_confidence_decay()`. | `test_confidence_decay()`: field at 0.9 → 0.72 after decay |
| `MarketDelta` | Pure computation — given two snapshots, assert delta fields and materiality flags. | `test_rate_material()`: 6.12% → 5.87% → rate_material = True |
| `FilterIntent` | Serialization roundtrip — to_dict → from_dict preserves all fields. | |

#### 7.9.2 Integration Tests

| Test | What It Covers |
|------|---------------|
| `test_full_turn_stretcher` | End-to-end turn with mocked LLM: extraction → classification → job resolution → prompt assembly. Assert the composed prompt contains stretcher-specific blocks. |
| `test_segment_transition` | Two turns: turn 1 → stretcher, turn 2 with income info → reclassification. Assert transition is logged and prompt updates. |
| `test_returning_user` | Create research context with market snapshot A, load context with stale snapshot (>4h). Assert delta computation and return briefing generation. |
| `test_pre_execution` | Turn plan with 3 proactive analyses. Assert all three run, facts are computed, and prompt fragment is correct. |
| `test_property_state_persistence` | Create research context, run analysis, persist, reload. Assert analysis record survives roundtrip. |

#### 7.9.3 Extraction Quality Tests

Signal extraction is the one non-deterministic component. Testing it requires
a curated set of input/output pairs:

```python
EXTRACTION_TEST_CASES = [
    {
        "message": "I'm renting now, paying $2,800/month. I have about $100K saved up.",
        "expected": {
            "current_rent": 2800,
            "capital": 100000,
            "owns_current_home": False,
            "intent": None,  # Not stated — don't hallucinate
        },
    },
    {
        "message": "Looking at this as an investment. I own my place in Oakland.",
        "expected": {
            "intent": "invest",
            "owns_current_home": True,
            "capital": None,  # Not stated — don't infer
        },
    },
    # ... 30-50 curated test cases
]
```

These tests run against the real extraction LLM (haiku) but are structured as
assertions: the extraction must return the expected fields with reasonable
confidence. They serve as a regression suite for extraction prompt tuning.

### 7.10 Observability

#### 7.10.1 Structured Logging

Every step in the pipeline emits structured log entries:

```python
logger.info(
    "segment_classification",
    extra={
        "user_id": context.user_id,
        "segment_id": result.segment_id,
        "confidence": result.confidence,
        "factor_coverage": result.factor_coverage,
        "profile_summary": profile.summary(),
        "prior_segment": context.buyer.segment_id,
        "transition": result.segment_id != context.buyer.segment_id,
    },
)
```

Key log events:
- `signal_extraction`: What was extracted, from which message, with what confidence
- `segment_classification`: Segment, confidence, factor coverage, transition flag
- `job_resolution`: Turn plan, proactive analyses selected, request type
- `pre_execution`: Which analyses ran, elapsed time, success/failure
- `segment_transition`: Old segment → new segment, triggering evidence
- `returning_user`: Market delta, property delta, stale analysis count

#### 7.10.2 Metrics

| Metric | Type | Purpose |
|--------|------|---------|
| `faketor.extraction.duration_ms` | Histogram | Extraction LLM latency |
| `faketor.classification.segment` | Counter (labels: segment_id) | Segment distribution |
| `faketor.classification.confidence` | Histogram | Confidence distribution |
| `faketor.pre_execution.count` | Counter | How many proactive analyses per turn |
| `faketor.pre_execution.duration_ms` | Histogram | Pre-execution latency |
| `faketor.turn.iterations` | Histogram | LLM iterations per turn |
| `faketor.turn.total_duration_ms` | Histogram | Total turn latency |
| `faketor.returning_user.count` | Counter | How many returning users triggered a delta briefing |
| `faketor.transition.count` | Counter (labels: from, to) | Segment transition frequency |

---

## 8. Implementation Plan

Section 7 specified the components and migration phases. This section sequences the
work into concrete implementation tickets, estimates effort, identifies dependencies
and risks, and defines the acceptance criteria for each phase.

### 8.1 Guiding Principles

1. **Ship value early.** The migration phases (A through H) are ordered so that each
   phase delivers measurable value — not just scaffolding. Phase C (extraction +
   classification) produces observability data. Phase D (prompt assembly) produces
   better responses. Phase E (orchestrator) produces the full pipeline.

2. **Never break production.** Every phase leaves the system functional. The feature
   flag strategy means production users are unaffected until the new path is
   explicitly enabled.

3. **Test the hard parts first.** Signal extraction (the LLM call) and segment
   classification (the decision tree) are the riskiest components — they determine
   the quality of every downstream decision. These ship in Phase C, before prompt
   assembly or pre-execution, so they can be monitored and tuned independently.

4. **Data model before behavior.** State containers (Phase B) exist before any
   component writes to them. This allows incremental adoption — components populate
   state as they're built, and downstream consumers read state as they're built.

5. **Gap tools are independently valuable.** The 10 gap tools (G-1 through G-10) and
   7 enhancements (E-1 through E-7) can be built and shipped as reactive tools before
   the segment-aware pipeline is active. A user who asks Faketor for a rent-vs-buy
   analysis benefits from G-1 regardless of whether segment detection is running.

### 8.2 Phase Breakdown

#### Phase A: Package Structure and DataLayer

**Goal:** Create the `faketor/` package and `DataLayer` facade without changing any
behavior. This is pure scaffolding — the system works exactly as before.

**Tickets:**

| # | Ticket | Description | Effort | Depends On |
|---|--------|-------------|--------|------------|
| A-1 | Create `faketor/` package | Create directory structure from Section 7.1. Move `accumulator.py` and `facts.py`. Create `__init__.py` that re-exports `FaketorService` from original location. | S | — |
| A-2 | Create `DataLayer` facade | Implement `DataLayer` class (Section 7.3.7) wrapping existing `AppState` infrastructure. Wire it into `lifespan` startup alongside `AppState`. | M | A-1 |
| A-3 | Create tool registry | Move `FAKETOR_TOOLS` definitions and `TOOL_TO_BLOCK_TYPE` mapping from `faketor.py` to `tools/definitions.py`. Verify existing tests pass. | S | A-1 |

**Acceptance criteria:**
- All existing tests pass
- `from homebuyer.services.faketor import FaketorService` still works
- `DataLayer` methods return identical results to direct `AppState` calls
- No user-visible behavior change

**Estimated duration:** 1-2 days

---

#### Phase B: State Containers

**Goal:** Create the state containers and `ResearchContextStore`. Research contexts
carry buyer, market, and property state — but nothing reads from them yet.

**Tickets:**

| # | Ticket | Description | Effort | Depends On |
|---|--------|-------------|--------|------------|
| B-1 | `BuyerProfile` and `BuyerState` | Implement `state/buyer.py`: `FieldSource`, `BuyerProfile`, `BuyerState`, `SegmentTransition`. Include `apply_extraction()`, `apply_confidence_decay()`, `known_factor_count()`, serialization. | M | A-1 |
| B-2 | `MarketSnapshot` and `MarketDelta` | Implement `state/market.py`: `BerkeleyWideMetrics`, `NeighborhoodMetrics`, `MarketSnapshot`, `MarketDelta`. Include `compute_delta()` with materiality flags. Implement `DataLayer.snapshot_market()` to populate from DB. | M | A-2 |
| B-3 | `PropertyState` | Implement `state/property.py`: `FilterIntent`, `FocusProperty`, `AnalysisRecord`, `PropertyAnalysis`, `PropertyState`. The `PropertyState.working_set` field wraps existing `SessionWorkingSet`. Include `record_analysis()` and `get_stale_analyses()`. | M | A-1 |
| B-4 | `ResearchContext`, `TurnState`, and `ResearchContextStore` | Implement `state/context.py`: `ResearchContext` (3 persistent containers), `TurnState` (ephemeral with `promote()`), `ResearchContextStore` (wraps existing `SessionManager`, adds buyer/market/property state). Wire into API layer alongside existing `SessionManager`. | M | B-1, B-2, B-3 |
| B-5 | State container unit tests | Test `BuyerProfile.apply_confidence_decay()`, `MarketDelta.compute_delta()` with materiality flags, `PropertyState.get_stale_analyses()`, `FilterIntent` serialization roundtrip, `ResearchContext` lifecycle, `TurnState.promote()`. | M | B-1 through B-4 |

**Acceptance criteria:**
- All state containers instantiate and serialize correctly
- `ResearchContextStore` creates contexts with all three persistent containers
- `MarketSnapshot` populates from real database queries
- Confidence decay computes correctly (0.9 × 0.8 = 0.72)
- Market delta materiality flags fire at correct thresholds
- All existing tests still pass

**Estimated duration:** 3-4 days

---

#### Phase C: Extraction and Classification

**Goal:** Run signal extraction and segment classification on every turn. Results are
stored in `BuyerState` and logged — but don't affect the LLM conversation yet. This
is the observability phase: we monitor classification accuracy before it drives behavior.

**Tickets:**

| # | Ticket | Description | Effort | Depends On |
|---|--------|-------------|--------|------------|
| C-1 | Signal extractor | Implement `extraction.py`: `SignalExtractor` class with haiku-based extraction. Define the extraction prompt, `ExtractionResult` output schema, `Signal` type. Include `extract()` for user messages and `extract_from_output()` for LLM responses. | L | A-2 |
| C-2 | Segment classifier | Implement `classification.py`: `SegmentClassifier` with the deterministic decision tree from Section 6.5.2. Include `classify()` and `should_transition()`. Pure functions — no LLM, no DB, no side effects. | M | B-1, B-2 |
| C-3 | Wire into chat flow (shadow mode) | Add extraction + classification as a pre-step in the existing `faketor_chat_stream` endpoint. Run before `FaketorService.chat_stream()`. Store results in `ResearchContext.buyer`. Log classifications. No behavior change — existing system prompt is unchanged. | M | C-1, C-2, B-4 |
| C-4 | Extraction quality test suite | Create 30-50 curated test cases (Section 7.9.3). Run against real haiku. Validate extraction accuracy on intent, capital, equity, income, current_rent, owns_current_home, is_first_time_buyer, sophistication. | L | C-1 |
| C-5 | Classification unit tests | Test every segment path in the decision tree. Test transitions: higher confidence replaces lower, equal confidence requires explicit evidence. Test edge cases: all fields null → null segment, single field → low confidence. | M | C-2 |
| C-6 | Observability instrumentation | Add structured logging for `signal_extraction` and `segment_classification` events (Section 7.10.1). Add metrics: `faketor.extraction.duration_ms`, `faketor.classification.segment`, `faketor.classification.confidence`. | S | C-3 |

**Acceptance criteria:**
- Extraction runs on every turn without perceptible latency increase (< 300ms)
- Extraction correctly identifies intent, capital, and income from natural language
- Extraction does NOT hallucinate fields that aren't stated
- Classifier produces correct segments for all 11 paths in the decision tree
- Shadow mode has zero impact on user-facing behavior
- Structured logs capture classification data for analysis

**Estimated duration:** 5-7 days

**Risk:** Extraction quality may require multiple prompt iterations. Budget 2-3 days
of prompt tuning within this phase. The quality test suite (C-4) gates Phase D — if
extraction accuracy is below 80% on the curated test set, prompt tuning continues
before moving on.

---

#### Phase D: Prompt Assembly

**Goal:** Replace the monolithic `SYSTEM_PROMPT` with the composable prompt assembler.
Feature-flagged: old prompt is the default, new prompt is opt-in.

**Tickets:**

| # | Ticket | Description | Effort | Depends On |
|---|--------|-------------|--------|------------|
| D-1 | Prompt component modules | Create `prompts/personality.py`, `prompts/data_model.py`, `prompts/tools.py`, `prompts/market.py`, `prompts/segment.py`, `prompts/property.py`, `prompts/preexecuted.py`. Each module has a `render()` function that takes typed inputs and returns a string. | L | B-2, B-3 |
| D-2 | Segment prompt templates | Create `prompts/templates/` with one file per segment (11 files). Each renders the segment-specific prompt block from Section 6.7.3: tone, framing rules, proactive behavior, term definitions policy. | L | D-1 |
| D-3 | Low-confidence fallback | Implement the generic prompt block for confidence < 0.3 (Section 6.7.4). Includes natural elicitation questions. | S | D-1 |
| D-4 | `PromptAssembler` | Implement `prompts/__init__.py` with `assemble()` function that composes all components (Section 7.3.6). | M | D-1, D-2, D-3 |
| D-5 | Feature flag + integration | Add `USE_SEGMENT_ORCHESTRATION` flag. When enabled, use `PromptAssembler.assemble()` instead of `SYSTEM_PROMPT`. When disabled, use existing prompt (zero change). | S | D-4, C-3 |
| D-6 | Prompt assembly tests | Test each component independently: given inputs, assert output contains expected fragments. Test full assembly: given a research context, assert composed prompt has all expected sections in order. | M | D-4 |
| D-7 | Baseline quality comparison | Run 10-20 representative conversations through both prompt paths (old monolithic vs. new composed). Compare response quality qualitatively. Document findings. | M | D-5 |

**Acceptance criteria:**
- Composed prompt produces responses of equal or better quality than monolithic prompt
- Each prompt component renders correctly in isolation
- Segment-specific prompt blocks match the templates from Section 6.7.3
- Feature flag cleanly switches between old and new prompt paths
- Market context prompt includes frozen snapshot data, not live queries
- No regression in response quality on the baseline conversation set

**Estimated duration:** 5-7 days

---

#### Phase E: Pre-Execution and Orchestrator

**Goal:** Build the `TurnOrchestrator`, `JobResolver`, and `PreExecutor`. This is the
phase where the full pipeline activates — extraction → classification → job resolution
→ pre-execution → prompt assembly → LLM loop → post-processing. Feature-flagged.

**Tickets:**

| # | Ticket | Description | Effort | Depends On |
|---|--------|-------------|--------|------------|
| E-1 | Request classifier | Implement `JobResolver.classify_request()` — pattern-based classification of user messages into `RequestType` (Section 6.6.2). | S | — |
| E-2 | Proactive analysis registry | Create the `PROACTIVE_ANALYSES` lookup table mapping (segment, request_type) → analyses (Section 7.3.4). Data-driven, not code. | M | — |
| E-3 | `JobResolver` | Implement full `JobResolver.resolve()`: classify request, look up proactive analyses, build `TurnPlan` with framing directive and secondary nudge. | M | E-1, E-2 |
| E-4 | `PreExecutor` | Implement `tools/preexecution.py`: execute proactive analyses from `TurnPlan`, compute facts, build prompt fragment. Handle dependency ordering and graceful failure. | M | E-3, A-2 |
| E-5 | `ToolExecutor` refactor | Create `tools/executor.py` wrapping existing `_make_session_tool_executor` with typed `ToolResult` output. Integrate with `ResearchContext` state instead of bare `SessionWorkingSet`. | M | B-4 |
| E-6 | `TurnOrchestrator` | Implement `orchestrator.py` with the full 9-step pipeline (Section 7.3.1). Wire extraction, classification, job resolution, pre-execution, prompt assembly, LLM loop, post-processing, and persistence. | L | C-1, C-2, E-3, E-4, E-5, D-4 |
| E-7 | Post-processor | Implement post-processing step: extract signals from LLM response (`extract_from_output`), promote TurnState conclusions to `ResearchContext` (PropertyState, BuyerState). | M | C-1, B-3, B-4 |
| E-8 | Wire Orchestrator into API | Update `faketor_chat_stream` endpoint to use `TurnOrchestrator.run_turn()` when feature flag is enabled. Emit new SSE event types (`segment_update`, `pre_execution_start`, `pre_execution_complete`). Preserve all existing SSE event types. | M | E-6 |
| E-9 | Integration tests | Test full turn pipeline with mocked LLM: Stretcher conversation, Competitive Bidder conversation, segment transition mid-conversation. Assert prompt composition, pre-execution, and state updates. | L | E-6 |

**Acceptance criteria:**
- Full pipeline executes for all 11 segments without errors
- Pre-execution adds < 500ms latency for typical proactive analysis sets (1-3 tools)
- Existing SSE event types maintain the same data format
- Feature flag cleanly switches between old `FaketorService` and new `TurnOrchestrator`
- Segment-appropriate proactive analyses fire for the correct (segment, request_type) pairs
- Post-processing correctly promotes analysis conclusions to `PropertyState`
- No regression in conversation quality compared to Phase D baseline

**Estimated duration:** 7-10 days

---

#### Phase F: Gap Tools

**Goal:** Implement the 10 new tools (G-1 through G-10) and 7 enhancements (E-1
through E-7) identified in Section 5.4. These are independently valuable — they
improve Faketor's capabilities regardless of segment detection.

**Sub-phase F.1: High-priority gap tools (segment-enabling)**

These tools are required for the core segment experiences. Without them, segment
detection changes the prompt framing but doesn't unlock new analyses.

| # | Ticket | Tool | Description | Effort | Priority |
|---|--------|------|-------------|--------|----------|
| F-1 | G-4: True cost | `true_cost` | All-in monthly ownership cost: P&I + property tax + hazard insurance + earthquake insurance (construction-type-aware) + maintenance reserve (age-based) + PMI (if applicable) + HOA. Compares to current rent if known. | M | **Critical** — enables Stretcher, First-Time, DPC segments |
| F-2 | G-1: Rent vs. buy | `rent_vs_buy` | Breakeven analysis: ownership cost (from G-4) vs. renting trajectory. Models rent escalation, appreciation, equity buildup, tax benefits, opportunity cost on down payment. Produces a crossover point. | L | **Critical** — primary job for Stretcher segment |
| F-3 | G-2: PMI model | `pmi_model` | PMI cost at buyer's down payment %, months until PMI drops off (equity → 80% LTV via appreciation + principal paydown), buy-now-vs-wait race between savings rate and market appreciation. | M | **Critical** — primary job for DPC segment |
| F-4 | G-3: Rate penalty | `rate_penalty` | Takes existing mortgage (balance, rate, term) and computes: current payment, payment at market rate, delta in dollars and % of income, rate scenarios (at what rate does penalty shrink to tolerable?). | M | **Critical** — primary job for Equity-Trapped segment |
| F-5 | G-5: Competition | `competition_assessment` | Aggregates competitive dynamics for a neighborhood/price-band: sale-to-list ratios, DOM distribution, % above/below asking, inventory trend, absorption rate. Synthesizes into a competition score. | M | **High** — primary job for Competitive Bidder segment |

**Sub-phase F.2: Investment gap tools**

These tools serve Invest segments. They can be built in parallel with F.1.

| # | Ticket | Tool | Description | Effort | Priority |
|---|--------|------|-------------|--------|----------|
| F-6 | G-6: Dual property | `dual_property_model` | Two-property combined cash flow: primary residence + investment target. Models HELOC/refi cost, combined expenses, stress tests (vacancy, rate increase, maintenance spike). | L | High — enables Equity-Leveraging segment |
| F-7 | G-7: Yield ranking | `yield_ranking` | Ranks working set by leverage spread (cap rate − borrowing cost), DSCR, and cash-on-cash at specified down payment and rate. | M | High — enables Leveraged Investor segment |
| F-8 | G-8: Stress test | `appreciation_stress_test` | Models breakeven between negative carry and appreciation under multiple scenarios. Downside modeling if prices decline. Refinance scenario. Exit analysis at year N. | L | High — enables Appreciation Bettor segment |

**Sub-phase F.3: Lifestyle and market expansion tools**

These serve broader needs and can be deferred further.

| # | Ticket | Tool | Description | Effort | Priority |
|---|--------|------|-------------|--------|----------|
| F-9 | G-9: Lifestyle | `neighborhood_lifestyle` | Qualitative neighborhood matching for Occupy segments. Initial implementation: structured data per neighborhood (commute, walkability, schools, character). Future: integration with external data sources. | M | Medium |
| F-10 | G-10: Adjacent markets | `adjacent_market_comparison` | What the buyer's budget buys in Oakland, El Cerrito, Albany, Richmond vs. Berkeley. Requires expanding data footprint or providing qualitative comparison. | L | Medium — data dependency |

**Sub-phase F.4: Enhancements to existing tools**

| # | Ticket | Enhancement | Description | Effort |
|---|--------|-------------|-------------|--------|
| F-11 | E-1 + E-2: Rental expenses | Add earthquake insurance (construction-type-aware) and maintenance reserve to `estimate_rental_income` operating expenses. | M |
| F-12 | E-3: Carrying costs | Add carrying cost period to `analyze_investment_scenarios` for ADU/SB9 scenarios. Model 6-18 months of no income during permitting + construction. | M |
| F-13 | E-4: SHAP exposure | Surface SHAP feature contributions more prominently in `get_price_prediction` output. Add segment-aware interpretation hints. | S |
| F-14 | E-5: Rate sensitivity | Add rate sensitivity context to `get_market_summary`: monthly P&I at median price for common down payment levels, income required at standard DTI. | M |
| F-15 | E-6: Rate penalty dimension | Add rate-penalty output to `estimate_sell_vs_hold` for homeowners. | M |
| F-16 | E-7: Affordability filtering | Add estimated monthly cost filtering to `search_properties` and `update_working_set`. Requires integrating G-4 (true cost) into the search pipeline. | L |

**Acceptance criteria (per tool):**
- Tool produces correct output for 5+ test cases
- Fact computer is registered and produces meaningful facts
- Tool is available for reactive use (in FAKETOR_TOOLS)
- Tool is registered in the proactive analysis registry for relevant segments
- Tool output is enriched with `_facts` for Claude's context

**Estimated duration:**
- F.1 (critical): 7-10 days
- F.2 (investment): 5-7 days (can overlap with F.1)
- F.3 (lifestyle/markets): 5-7 days (can be deferred)
- F.4 (enhancements): 5-7 days (can overlap with F.1/F.2)
- **Total with parallelism: 12-17 days**

---

#### Phase G: Persistence

**Goal:** Authenticated users' research contexts persist across interactions.
Returning users get automatic delta detection and briefing.

**Tickets:**

| # | Ticket | Description | Effort | Depends On |
|---|--------|-------------|--------|------------|
| G-1 | Persistence schema | Add `buyer_profiles`, `research_contexts`, and `property_analyses` tables (Section 7.6). Write migration SQL. Handle SQLite/PostgreSQL dialect differences. | M | — |
| G-2 | `ResearchContextStore.persist()` | Implement research context persistence for authenticated users. Serialize `BuyerState`, `MarketSnapshot`, `PropertyState` to their respective tables. Called after each turn that changes state. | M | G-1, B-4 |
| G-3 | `ResearchContextStore.load_or_create()` with DB | Implement loading persisted state for returning users. Apply confidence decay to `BuyerProfile`. Load `MarketSnapshot` and detect staleness (>4 hours). Load `FilterIntent` and re-execute against current data. Compute `MarketDelta` if stale. | L | G-2 |
| G-4 | Return briefing in prompt | Add return briefing as a prompt component. When `ResearchContext.market_delta` is non-null (stale data detected on load), inject a RETURN CONTEXT block into the system prompt. Includes market delta, property delta, focus property status, stale analysis flags. | L | G-3, B-2, D-4 |
| G-5 | Persistence tests | Test full roundtrip: create context → populate state → persist → load → verify state matches. Test returning user: persist with snapshot A → load with snapshot B (>4h later) → verify delta. Test authenticated vs. anonymous paths. | L | G-3, G-4 |

**Acceptance criteria:**
- Returning authenticated user's `BuyerProfile` loads with confidence decay applied
- `MarketDelta` correctly identifies material changes when snapshot is stale
- `FilterIntent` re-executes and property delta is computed
- Focus property status is checked and surfaced
- Stale analyses are flagged with the correct market snapshot comparison
- Anonymous users are unaffected (nothing persists)
- Return briefing accurately summarizes what changed
- No separate resume endpoint needed — handled by `load_or_create()`

**Estimated duration:** 5-7 days

---

#### Phase H: Frontend Integration

**Goal:** The frontend takes advantage of the segment-aware pipeline: buyer intake,
segment display, and return briefing.

**Tickets:**

| # | Ticket | Description | Effort | Depends On |
|---|--------|-------------|--------|------------|
| H-1 | Handle new SSE events | Update Chat.tsx SSE handler to recognize `segment_update`, `resume_briefing`, `pre_execution_start`, `pre_execution_complete` events. Store segment data. Display pre-execution progress. | M | E-8 |
| H-2 | `BuyerContext` provider | Create new React context for buyer state (Section 7.7.3). Separate from `PropertyContext`. Populated from `segment_update` SSE events. | M | H-1 |
| H-3 | Buyer intake component | Optional intake modal/inline form: intent, budget range, capital, income, current rent, first-time buyer flag. Sends as `buyer_context` in `FaketorChatRequest`. Skippable. | L | H-2 |
| H-4 | Segment badge | Subtle segment indicator in the chat UI. Shows detected segment and confidence. Non-intrusive — informational only. | S | H-2 |
| H-5 | Return briefing display | When a returning user's first turn triggers a `resume_briefing` SSE event, render it as a structured "welcome back" card showing market changes, property changes, and stale analysis warnings. | M | G-4 |
| H-6 | Update `FaketorChatRequest` | Update `api.ts` to send `buyer_context` when intake is completed. Make `latitude`/`longitude` optional (the backend now accepts conversations without a property focus). | M | H-3 |

**Acceptance criteria:**
- Intake form seeds segment classification from turn 1
- Segment badge updates in real-time as classification changes
- Return briefing renders clearly when a returning user's first response includes it
- All existing chat functionality continues to work unchanged

**Estimated duration:** 7-10 days

---

### 8.3 Dependency Graph

```
Phase A (scaffold)
    │
    ▼
Phase B (state) ──────────────────────────────────────────────┐
    │                                                          │
    ▼                                                          │
Phase C (extract + classify) ───────────────────┐              │
    │                                            │              │
    ▼                                            │              │
Phase D (prompt assembly)                        │              │
    │                                            │              │
    ▼                                            ▼              │
Phase E (orchestrator) ◄────────────── Phase F (gap tools)     │
    │                                      │                    │
    ▼                                      │                    ▼
Phase G (persistence) ◄───────────────────┘         Phase H (frontend)
    │                                                    │
    └────────────────────────────────────────────────────┘
                    H-5 (return briefing) depends on G
```

**Key parallelism opportunities:**

1. **F.1 and F.2 can start during Phase D.** Gap tools don't depend on the
   orchestrator — they're standalone functions that the existing `FaketorService`
   can call reactively. Building them early means they're ready when the orchestrator
   needs them for pre-execution.

2. **H-1 through H-4 can start during Phase E.** The frontend can handle new SSE
   events and display segment data before persistence is complete.

3. **F.4 (enhancements) is independent.** Existing tool improvements can happen at
   any point — they don't depend on the new architecture.

### 8.4 Effort Summary

| Phase | Description | Estimated Days | Dependencies |
|-------|-------------|---------------|--------------|
| **A** | Package structure + DataLayer | 1-2 | — |
| **B** | State containers | 3-4 | A |
| **C** | Extraction + Classification | 5-7 | A, B |
| **D** | Prompt Assembly | 5-7 | B, C |
| **E** | Pre-execution + Orchestrator | 7-10 | C, D |
| **F** | Gap Tools (all sub-phases) | 12-17 | A (for DataLayer) |
| **G** | Persistence | 5-7 | B, E |
| **H** | Frontend Integration | 5-7 | E, G (for return briefing) |
| | | | |
| **Total (sequential)** | | **42-58 days** | |
| **Total (with parallelism)** | | **30-42 days** | F overlaps D-E; H overlaps G |

### 8.5 Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Extraction quality is poor** | Medium | High — bad extraction → bad classification → wrong segment behavior | Extensive test suite (C-4). Prompt iteration budget. Shadow mode allows monitoring before activation. Haiku may need to be replaced with Sonnet for extraction if quality is insufficient (cost tradeoff). |
| **Extraction latency is unacceptable** | Low | Medium — adds perceived delay to every turn | Haiku is fast (~200ms). If too slow, explore caching extraction results for repeated patterns, or skip extraction when the message is clearly a property question with no buyer signals. |
| **Segment classification accuracy is low** | Low | High — incorrect segments produce incorrect behavior | The classifier is deterministic and testable. The risk is in the extraction quality (upstream), not in the classification logic. Classification tests cover all 11 paths exhaustively. |
| **Prompt assembly produces worse responses** | Medium | High — regression in response quality | A/B comparison in Phase D (D-7). Feature flag allows instant rollback. The composed prompt should reproduce the monolithic prompt's content while adding segment-aware blocks — it should be strictly better, not different. |
| **Pre-execution increases latency noticeably** | Medium | Medium — adds 500ms-2s for proactive tools | Each proactive tool call is a local function call (no LLM, just DB queries and computation). Expected latency: 50-200ms per tool. For 3 tools: 150-600ms. If too slow, run tools concurrently or reduce proactive set for latency-sensitive sessions. |
| **State model is too complex** | Low | Medium — development velocity slows | The state model has four containers with clear boundaries. Each is independently simple. The complexity is in the interactions, which are tested at the integration level. |
| **Persistence schema migration issues** | Low | Low — additive tables, no modifications | Schema is additive. No existing tables are changed. Migration is CREATE TABLE IF NOT EXISTS. PostgreSQL/SQLite dialect translation follows existing patterns in `database.py`. |
| **Feature flag creates code path divergence** | Medium | Low — temporary, resolved when migration completes | The flag gates a single decision point (which orchestrator to use). Code paths don't diverge deeply — they share the same tool executor, data layer, and response format. Flag is removed after migration is validated. |
| **Gap tools are harder than expected** | Medium | Medium — delays Phase F | Gap tools are well-specified in Section 5.4 with clear inputs and outputs. The main risk is G-6 (dual-property model) which involves multi-property cash flow modeling that's more complex than single-property tools. Budget extra time for G-6. |
| **Frontend changes lag backend** | Medium | Low — backend is backward-compatible | The backend works with the existing frontend through all phases. Frontend changes are additive enhancements, not requirements. The system delivers value through better prompt framing even without frontend changes. |

### 8.6 Quality Gates

Each phase has a quality gate that must pass before the next phase begins. These
gates are not just "tests pass" — they validate that the phase's output is ready
to support downstream phases.

| Phase | Quality Gate |
|-------|-------------|
| **A** | All existing tests pass. `DataLayer` parity test: every method returns identical results to direct `AppState` calls for 10 representative inputs. |
| **B** | State container tests pass. `MarketSnapshot` produces valid data from real DB. Confidence decay and materiality thresholds compute correctly. `TurnState.promote()` correctly moves state to `ResearchContext`. |
| **C** | Extraction accuracy ≥ 80% on curated test set. Extraction does not hallucinate fields in ≥ 95% of test cases. Classifier covers all 11 segments. Shadow mode produces valid logs. |
| **D** | Composed prompt reproduces ≥ 90% of the monolithic prompt's content for generic (non-segment) cases. Segment-specific prompt blocks match Section 6.7.3 templates. A/B comparison shows no regression. |
| **E** | Full pipeline executes without errors for 10 representative conversations (2 per segment category: occupy/invest). Pre-execution latency < 1s for typical proactive sets. All existing SSE events maintain format. |
| **F** | Each gap tool has ≥ 5 passing test cases. Tool results include facts. Proactive analysis registry entries exist for all tool × segment combinations. |
| **G** | Roundtrip persistence test passes: create → populate → persist → load → verify. Returning user flow produces correct delta for 5 test scenarios. Anonymous users remain unaffected. |
| **H** | Intake form seeds classification correctly. Segment badge updates on `segment_update` events. Return briefing renders for returning users. All existing chat functionality unchanged. |

### 8.7 Success Metrics

How do we know the redesign is working? These metrics can be measured once Phase E
is active for a meaningful subset of users.

#### 8.7.1 Classification Quality

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Extraction field accuracy | ≥ 85% on curated test set | Automated test suite (C-4) |
| Extraction hallucination rate | ≤ 5% | Automated test: fields extracted that weren't stated |
| Segment stability | ≥ 80% of users maintain same segment across turns | Log analysis: segment_transition events / total users |
| Classification confidence distribution | Mean ≥ 0.5 by turn 3 | Histogram of `faketor.classification.confidence` by turn |

#### 8.7.2 Response Quality

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Proactive analysis relevance | ≥ 70% of pre-executed analyses referenced by LLM | Log analysis: pre-execution results that appear in LLM response text |
| Iteration reduction | ≥ 30% fewer LLM iterations for segment-identified turns | Histogram comparison: `faketor.turn.iterations` for flagged vs. unflagged |
| Conversation depth | Average turns per interaction ≥ 3 | Log analysis: turn counts per interaction window |

#### 8.7.3 System Performance

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Extraction latency | p95 < 400ms | `faketor.extraction.duration_ms` histogram |
| Pre-execution latency | p95 < 1000ms | `faketor.pre_execution.duration_ms` histogram |
| Total turn latency (first token) | p95 < 3000ms (vs. current ~2000ms) | `faketor.turn.total_duration_ms` histogram |

#### 8.7.4 Business Metrics (Longer Term)

| Metric | Target | How to Measure |
|--------|--------|---------------|
| User return rate | ≥ 15% of authenticated users return after initial interaction | Returning user count / unique authenticated users |
| Buyer profile completion | ≥ 40% of users have 3+ buyer factors extracted by turn 5 | Log analysis: `BuyerProfile.known_factor_count()` by turn |
| Cross-interaction continuity | Return briefing delivered for ≥ 80% of returning users | `faketor.returning_user.count` vs. returning user count |

### 8.8 Recommended Build Sequence

Given the dependency graph and parallelism opportunities, the recommended build
sequence for a single developer:

```
Week 1:     Phase A (1-2 days) → Phase B (3-4 days)
Week 2-3:   Phase C (5-7 days) + begin F.4 enhancements (parallel)
Week 3-4:   Phase D (5-7 days) + F.1 critical gap tools (parallel)
Week 5-6:   Phase E (7-10 days) + F.2 investment gap tools (parallel)
Week 7-8:   Phase G (5-7 days) + F.3 lifestyle tools (if capacity)
Week 8-9:   Phase H (5-7 days)
```

**First value delivery:** End of Week 3 — extraction + classification running in
shadow mode, providing observability data about buyer segments. This data informs
decisions about prompt tuning and proactive analysis priorities.

**Second value delivery:** End of Week 4 — segment-aware prompts active behind
feature flag. Faketor begins tailoring tone and framing to detected segments.

**Third value delivery:** End of Week 6 — full orchestrator with pre-execution
and gap tools. Faketor proactively runs segment-relevant analyses and delivers
richer, more targeted responses.

**Full delivery:** End of Week 9 — persistence, returning-user flow, and frontend
integration complete. Returning users get a seamless "welcome back" experience
with market and property deltas, delivered automatically on their first turn.

### 8.9 What This Document Does Not Cover

This design document specifies the segment-aware orchestration redesign. It
intentionally does not cover:

1. **Marketing page integration.** The Marketing page (`ui/src/pages/Marketing.tsx`)
   may need updates to reflect new capabilities. This is a separate concern.

2. **Analytics dashboard.** The observability metrics (Section 7.10) need a dashboard
   for monitoring. This is an infrastructure concern, not a design concern.

3. **A/B testing infrastructure.** The feature flag strategy requires an A/B testing
   framework to measure the difference between old and new paths. This may be as
   simple as random flag assignment or may require a proper experimentation platform.

4. **Model retraining.** The ML price prediction model is unchanged by this redesign.
   If gap tools (particularly G-1 rent-vs-buy and G-8 stress test) reveal that the
   model's predictions need refinement, that's a separate workstream.

5. **Data expansion.** G-9 (neighborhood lifestyle) and G-10 (adjacent market
   comparison) require data that doesn't exist in the current system. Sourcing and
   integrating this data is a separate project.

6. **Mobile/responsive design.** The frontend changes assume the current desktop-first
   layout. Responsive adaptations are a separate concern.

---

## Appendix: Document Change Log

| Date | Section | Change |
|------|---------|--------|
| 2026-03-15 | 1-4 | Initial drafts of Buyer Model, Segment Definitions, Jobs to Be Done, Competing Solutions |
| 2026-03-15 | 5 | Tool Audit: inventory, segment × tool matrix, gap analysis (G-1 through G-10), enhancements (E-1 through E-7), proactive invocation rules, iteration budget |
| 2026-03-15 | 6 | Workflow Design: initial draft, then full rewrite to remove accommodation of existing architecture. Revised state model from 3 to 4 containers (MarketSnapshot separated from PropertyState, ResearchState collapsed into PropertyState). Added session resume flow with market/property delta. |
| 2026-03-15 | 7 | Orchestration Architecture: module layout, component specifications, data contracts, API changes, persistence schema, frontend integration, migration strategy, testing strategy, observability |
| 2026-03-15 | 8 | Implementation Plan: phased tickets, effort estimates, dependency graph, risk register, quality gates, success metrics, recommended build sequence |
| 2026-03-15 | 6-8 | Research Context revision: replaced session/conversation/thread model with single ResearchContext per user. Dropped separate resume endpoint, ConversationState entity, session_snapshots table. Updated all component specs, data contracts, API layer, persistence schema, migration phases, and implementation tickets to use ResearchContext + TurnState model. |
