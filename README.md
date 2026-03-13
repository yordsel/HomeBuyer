# HomeBuyer

**Berkeley-specific real estate analytics for people who want the truth.**

HomeBuyer is a side project that started because one person wanted to understand Berkeley real estate and got slightly carried away. It combines ML price predictions, an AI-powered property analyst, neighborhood analytics, zoning intelligence, and investment scenario modeling into a single tool that tells you what a house is actually worth — not what someone trying to earn a commission wants you to believe.

This is not a real estate brokerage. This is not financial advice. This is a developer with too much free time and strong opinions about housing prices.

## What It Is

- An **ML price prediction model** trained on 5 years of Berkeley sales data with ~$95K median absolute error
- An **AI property analyst** (Faketor) powered by Claude with 18 tools for comps, zoning, permits, rental estimates, investment analysis, and more
- A **neighborhood analytics dashboard** with median prices, trends, days on market, and sale-to-list ratios for every Berkeley neighborhood
- A **zoning and development tool** covering ADU feasibility, SB 9 lot splits, Middle Housing rules, and setback requirements
- An **affordability calculator** that tells you what you can actually afford (spoiler: it's less than you think)
- An **investment prospectus generator** that models flip, rent, and hold scenarios with actual math

## What It Isn't

- A licensed real estate brokerage or advisory service
- A substitute for professional real estate, legal, or financial advice
- A guarantee of anything — the model is good but it's not omniscient
- A way to make money (we certainly haven't)

For the full legal version, see the [Terms and Conditions](https://homebuyer-jzci.onrender.com) (accessible from the app's login and settings pages).

## Data Sources

HomeBuyer pulls from a variety of public and third-party data sources:

**Public (free):**
- [Redfin](https://www.redfin.com/) — Property sales history and market metrics via their GIS-CSV API and Data Center
- [FRED](https://fred.stlouisfed.org/) — 30-year and 15-year mortgage rates, plus economic indicators (NASDAQ, 10-year Treasury, CPI, consumer sentiment, unemployment)
- [U.S. Census Bureau](https://data.census.gov/) — American Community Survey median income by zip code
- [Berkeley Open Data](https://data.cityofberkeley.info/) — BESO energy benchmarking and parcel boundaries
- [Berkeley Municipal Code](https://berkeley.municipal.codes/BMC/23) — Zoning regulations (Title 23)
- [City of Berkeley](https://berkeleyca.gov/) — Transfer tax rates, permitting info, Middle Housing policy
- [Accela Citizen Access](https://aca-prod.accela.com/BERKELEY/) — Building permit records
- [Berkeley Rent Board](https://rentboard.berkeleyca.gov/) — Rent control information
- [FHFA](https://www.fhfa.gov/) — Conforming loan limits

**Third-party (paid, required for full functionality):**
- [RentCast](https://www.rentcast.io/) — Property details, sale history enrichment, and rental estimates
- [Anthropic Claude API](https://www.anthropic.com/) — Powers the Faketor AI agent

> **Rebuilding note:** If you're looking to rebuild or fork this project, you'll need a paid property data service like [RentCast](https://www.rentcast.io/) or [ATTOM](https://www.attomdata.com/) to get the enriched property data that makes the ML model work well. The free public data sources alone won't give you enough features for accurate predictions.

## Services & Tools

For a detailed breakdown of the API endpoints, Faketor AI tools, CLI data pipeline, and ML model architecture, see **[SERVICES.md](SERVICES.md)**.

## Getting Started

```bash
# Clone the repo
git clone https://github.com/yordsel/HomeBuyer.git
cd HomeBuyer

# Ask Claude to get things up and running
# (it knows the project structure and will handle dependencies,
#  database setup, and dev server configuration)
```

That's it. Claude knows this codebase. Tell it what you want to do and it'll figure out the rest — install Python and Node dependencies, initialize the database, seed the data, and start the dev servers.

You'll need:
- Python 3.12+
- Node.js 18+
- API keys for any third-party services you want to use (see [SERVICES.md](SERVICES.md#environment-variables))

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, FastAPI, Uvicorn |
| Frontend | TypeScript, React, Vite, Tailwind CSS |
| ML | scikit-learn (HistGradientBoosting), SHAP |
| Maps | Leaflet, react-leaflet |
| AI | Anthropic Claude (via Faketor agent) |
| Database | PostgreSQL (production), SQLite (development) |
| Email | Resend |
| Auth | JWT + bcrypt, Google OAuth |
| Scraping | Playwright, BeautifulSoup4 |
| Deployment | Render |

## License

This is a side project. Use it, learn from it, fork it. Just don't pretend it's financial advice.
