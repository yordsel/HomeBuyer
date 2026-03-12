"""Collector for Berkeley regulation data from official municipal sources.

Scrapes zoning ordinances, housing policy pages, and regulation details
from official Berkeley sources and writes structured JSON files used by
the ``lookup_regulation`` tool.

Uses Playwright (headless Chromium) for berkeley.municipal.codes (which
blocks raw HTTP requests) and ``requests`` for berkeleyca.gov pages.

Pipeline:  load seed  →  scrape web sources  →  merge  →  write JSON
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from homebuyer.config import (
    BERKELEYCA_BESO_INFO_URL,
    BERKELEYCA_MIDDLE_HOUSING_URL,
    BERKELEYCA_PERMITTING_URL,
    BERKELEYCA_TRANSFER_TAX_URL,
    BMC_TITLE_23_BASE,
    BMC_ZONING_SECTIONS,
    REGULATIONS_DIR,
    REGULATIONS_SEED_DIR,
    REGULATIONS_SOURCES_DIR,
    RENT_BOARD_RENT_CONTROL_URL,
    RENT_BOARD_URL,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

# Polite delay between page loads (seconds)
_REQUEST_DELAY = 2.0


class RegulationCollector:
    """Collects Berkeley regulation data from official sources.

    Uses Playwright (headless Chromium) for berkeley.municipal.codes
    and ``requests`` for berkeleyca.gov / rentboard.berkeleyca.gov.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.regulations_dir = data_dir / "regulations"
        self.seed_dir = self.regulations_dir / "seed"
        self.sources_dir = self.regulations_dir / "sources"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(
        self,
        scrape: bool = True,
        seed_only: bool = False,
    ) -> dict[str, Any]:
        """Run the regulation data pipeline.

        Args:
            scrape: If True, scrape web sources and merge with seed.
            seed_only: If True, just copy seed files to output (no scraping).

        Returns:
            Summary dict with counts and status.
        """
        self._ensure_dirs()
        started = datetime.now(timezone.utc)

        # 1. Load seed data
        seed_zones, seed_categories = self._load_seed()
        if not seed_zones and not seed_categories:
            return {
                "success": False,
                "error": (
                    "No seed data found. Run with --generate-seed first "
                    "to convert hardcoded KB to seed JSON."
                ),
            }

        if seed_only:
            self._write_json(seed_zones, seed_categories)
            return {
                "success": True,
                "zones": len(seed_zones),
                "categories": len(seed_categories),
                "mode": "seed_only",
                "duration_s": (datetime.now(timezone.utc) - started).total_seconds(),
            }

        # 2. Scrape web sources
        scraped: dict[str, Any] = {}
        if scrape:
            scraped = self._scrape_all()

        # 3. Merge scraped data into seed
        final_zones, final_categories = self._merge(
            seed_zones, seed_categories, scraped
        )

        # 4. Write output JSON
        self._write_json(final_zones, final_categories)

        return {
            "success": True,
            "zones": len(final_zones),
            "categories": len(final_categories),
            "scraped_sources": list(scraped.keys()),
            "mode": "scrape" if scrape else "seed_only",
            "duration_s": (datetime.now(timezone.utc) - started).total_seconds(),
        }

    def generate_seed_from_hardcoded(self) -> None:
        """One-time migration: convert current hardcoded KB dicts to seed JSON.

        Imports the existing ``ZONE_DEFINITIONS`` and ``REGULATIONS`` from
        the hardcoded module, adds provenance fields, and writes seed files.
        """
        # Import from the current hardcoded module
        from homebuyer.services.berkeley_regulations import (
            REGULATIONS,
            ZONE_DEFINITIONS,
        )

        self._ensure_dirs()
        now = datetime.now(timezone.utc).isoformat()

        # --- Zones seed ---
        zones_seed: dict[str, Any] = {
            "$meta": {
                "schema_version": 1,
                "generated_at": now,
                "generator": "generate_seed_from_hardcoded",
                "description": (
                    "Seed zone definitions converted from hardcoded "
                    "berkeley_regulations.py"
                ),
            }
        }
        for code, zone in ZONE_DEFINITIONS.items():
            entry = dict(zone)
            entry["source_url"] = BMC_TITLE_23_BASE
            entry["source_document"] = "Berkeley Municipal Code Title 23"
            entry["last_verified"] = now
            zones_seed[code] = entry

        # --- Categories seed ---
        cats_seed: dict[str, Any] = {
            "$meta": {
                "schema_version": 1,
                "generated_at": now,
                "generator": "generate_seed_from_hardcoded",
                "description": (
                    "Seed regulation categories converted from hardcoded "
                    "berkeley_regulations.py"
                ),
            }
        }

        # Map category keys to keyword lists (from the hardcoded _KEYWORD_MAP)
        _category_keywords: dict[str, list[str]] = {
            "adu_rules": [
                "adu", "accessory dwelling", "jadu", "junior adu",
                "granny flat", "in-law",
            ],
            "sb9_lot_splitting": [
                "sb9", "sb 9", "lot split", "lot splitting",
            ],
            "middle_housing": [
                "middle housing", "duplex", "triplex", "fourplex",
                "cottage court",
            ],
            "beso": ["beso", "energy audit", "energy assessment", "emissions"],
            "transfer_tax": ["transfer tax", "city tax", "real estate tax"],
            "rent_control": [
                "rent control", "rent stabilization", "tenant",
                "eviction", "vacancy decontrol",
            ],
            "permitting": [
                "permit", "permitting", "building permit", "plan check",
            ],
            "hillside_overlay": [
                "hillside", "h suffix", "hill overlay", "fire hazard",
            ],
            "zoning_codes": ["zoning", "zone code", "zoning code"],
        }

        for key, cat in REGULATIONS.items():
            entry = dict(cat)
            entry["source_url"] = entry.get("source", BMC_TITLE_23_BASE)
            entry["source_document"] = entry.get("source", "Berkeley Municipal Code")
            entry["last_verified"] = now
            entry["keywords"] = _category_keywords.get(key, [])
            cats_seed[key] = entry

        # Write seed files
        zones_path = self.seed_dir / "zones_seed.json"
        cats_path = self.seed_dir / "categories_seed.json"

        with open(zones_path, "w") as f:
            json.dump(zones_seed, f, indent=2, default=str)
        logger.info("Wrote %d zone definitions to %s", len(zones_seed) - 1, zones_path)

        with open(cats_path, "w") as f:
            json.dump(cats_seed, f, indent=2, default=str)
        logger.info(
            "Wrote %d regulation categories to %s", len(cats_seed) - 1, cats_path
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        """Create output directories if they don't exist."""
        self.regulations_dir.mkdir(parents=True, exist_ok=True)
        self.seed_dir.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(parents=True, exist_ok=True)

    def _load_seed(self) -> tuple[dict, dict]:
        """Load curated baseline from seed JSON files."""
        zones: dict = {}
        cats: dict = {}

        zones_path = self.seed_dir / "zones_seed.json"
        cats_path = self.seed_dir / "categories_seed.json"

        if zones_path.exists():
            with open(zones_path) as f:
                raw = json.load(f)
            zones = {k: v for k, v in raw.items() if not k.startswith("$")}
            logger.debug("Loaded %d zones from seed", len(zones))

        if cats_path.exists():
            with open(cats_path) as f:
                raw = json.load(f)
            cats = {k: v for k, v in raw.items() if not k.startswith("$")}
            logger.debug("Loaded %d categories from seed", len(cats))

        return zones, cats

    # ------------------------------------------------------------------
    # Scraping orchestrator
    # ------------------------------------------------------------------

    def _scrape_all(self) -> dict[str, Any]:
        """Run all scrapers and return combined results."""
        results: dict[str, Any] = {}

        # Playwright scrapers for berkeley.municipal.codes
        try:
            bmc_data = self._scrape_municipal_code_with_playwright()
            if bmc_data:
                results["municipal_code"] = bmc_data
        except Exception:
            logger.warning(
                "Playwright scraping of municipal code failed — "
                "falling back to seed data",
                exc_info=True,
            )

        # HTTP scrapers for berkeleyca.gov (accessible without Playwright)
        for name, scraper in [
            ("middle_housing", self._scrape_middle_housing),
            ("transfer_tax", self._scrape_transfer_tax),
            ("rent_board", self._scrape_rent_board),
            ("beso", self._scrape_beso_page),
            ("permitting", self._scrape_permitting_page),
        ]:
            try:
                data = scraper()
                if data:
                    results[name] = data
            except Exception:
                logger.warning("Scraper %s failed", name, exc_info=True)

        return results

    # ------------------------------------------------------------------
    # Playwright scrapers (berkeley.municipal.codes — blocked by 403)
    # ------------------------------------------------------------------

    def _scrape_municipal_code_with_playwright(self) -> dict[str, Any]:
        """Use Playwright to scrape Title 23 zoning sections.

        Launches headless Chromium, visits each section URL, extracts
        zone names, development standards, and regulation text.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning(
                "Playwright not installed — skipping municipal code scraping. "
                "Install with: pip install playwright && playwright install chromium"
            )
            return {}

        results: dict[str, Any] = {"zones": {}, "categories": {}}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            # Scrape each zoning section
            for section_name, url in BMC_ZONING_SECTIONS.items():
                try:
                    logger.info("Scraping municipal code: %s", section_name)
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    time.sleep(_REQUEST_DELAY)

                    html = page.content()
                    text = page.inner_text("body")

                    # Cache raw HTML for debugging
                    cache_path = self.sources_dir / f"bmc_{section_name}.html"
                    with open(cache_path, "w") as f:
                        f.write(html)

                    # Parse based on section type
                    if section_name in ("residential", "commercial", "manufacturing"):
                        zones = self._parse_zoning_section(html, text, section_name)
                        results["zones"].update(zones)
                    elif section_name == "adu":
                        adu_data = self._parse_adu_section(html, text)
                        if adu_data:
                            results["categories"]["adu_rules"] = adu_data
                    elif section_name == "hillside":
                        hillside_data = self._parse_hillside_section(html, text)
                        if hillside_data:
                            results["categories"]["hillside_overlay"] = hillside_data

                except Exception:
                    logger.warning(
                        "Failed to scrape section %s", section_name, exc_info=True
                    )

            browser.close()

        return results

    def _parse_zoning_section(
        self, html: str, text: str, section_name: str
    ) -> dict[str, dict]:
        """Parse a zoning division page for zone definitions.

        Extracts zone codes, names, and development standards from
        the municipal code HTML.
        """
        zones: dict[str, dict] = {}
        soup = BeautifulSoup(html, "lxml")
        now = datetime.now(timezone.utc).isoformat()

        # Look for section headings that contain zone code patterns
        # Municipal code structure: "23.202.020 R-1 Single Family Residential"
        zone_pattern = re.compile(
            r"(R-[1-5][AH]*|ES-R|MU-?R|MULI|C-[A-Z]{1,3}(?:\s*\(H\))?|M)\b"
            r"\s*[-–—]?\s*(.+)",
            re.IGNORECASE,
        )

        # Find headings and content sections
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
            heading_text = heading.get_text(strip=True)
            m = zone_pattern.search(heading_text)
            if not m:
                continue

            zone_code = m.group(1).upper()
            zone_name = m.group(2).strip().rstrip(".")

            # Get the content following this heading
            content_parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ("h1", "h2", "h3", "h4", "h5"):
                    break
                content_parts.append(sibling.get_text(strip=True))

            content = " ".join(content_parts)[:500]  # Limit length

            zone_entry: dict[str, Any] = {
                "name": zone_name,
                "source_url": BMC_ZONING_SECTIONS.get(
                    section_name, BMC_TITLE_23_BASE
                ),
                "source_document": f"BMC Title 23, {section_name.title()} Districts",
                "last_verified": now,
            }

            # Extract numeric development standards from content
            height_match = re.search(
                r"(?:max(?:imum)?|height)\s*(?:limit)?\s*[:=]?\s*(\d+)\s*(?:ft|feet)",
                content,
                re.IGNORECASE,
            )
            if height_match:
                zone_entry["max_height_ft"] = int(height_match.group(1))

            coverage_match = re.search(
                r"(?:lot\s*coverage|coverage)\s*[:=]?\s*(\d+)\s*%",
                content,
                re.IGNORECASE,
            )
            if coverage_match:
                zone_entry["lot_coverage_pct"] = int(coverage_match.group(1))

            if content:
                zone_entry["scraped_description"] = content[:300]

            zones[zone_code] = zone_entry

        # Also try extracting from tables (development standards tables)
        for table in soup.find_all("table"):
            self._extract_standards_from_table(table, zones, now)

        if zones:
            logger.info(
                "Extracted %d zone definitions from %s", len(zones), section_name
            )

        return zones

    def _extract_standards_from_table(
        self, table: Any, zones: dict, now: str
    ) -> None:
        """Extract development standards from HTML tables."""
        rows = table.find_all("tr")
        if len(rows) < 2:
            return

        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue

            # Check if first cell looks like a zone code
            zone_match = re.match(
                r"(R-[1-5][AH]*|ES-R|MU-?R|MULI|C-[A-Z]{1,3}(?:\s*\(H\))?|M)\b",
                cells[0],
                re.IGNORECASE,
            )
            if not zone_match:
                continue

            zone_code = zone_match.group(1).upper()
            if zone_code not in zones:
                zones[zone_code] = {
                    "source_url": BMC_TITLE_23_BASE,
                    "source_document": "BMC Title 23 Development Standards Table",
                    "last_verified": now,
                }

            # Map headers to values
            for i, header in enumerate(headers):
                if i >= len(cells):
                    break
                val = cells[i].strip()
                if not val or val == "-":
                    continue
                if "height" in header:
                    num = re.search(r"(\d+)", val)
                    if num:
                        zones[zone_code]["max_height_ft"] = int(num.group(1))
                elif "coverage" in header:
                    num = re.search(r"(\d+)", val)
                    if num:
                        zones[zone_code]["lot_coverage_pct"] = int(num.group(1))
                elif "unit" in header or "density" in header:
                    zones[zone_code]["max_units_base_scraped"] = val

    def _parse_adu_section(self, html: str, text: str) -> dict[str, Any]:
        """Parse BMC 23.306.030 for ADU development standards."""
        result: dict[str, Any] = {
            "source_url": BMC_ZONING_SECTIONS["adu"],
            "source_document": "BMC Ch. 23.306.030",
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "key_numbers": {},
        }

        # Extract specific ADU numbers from text
        patterns = {
            "max_adu_1br_sqft": r"(?:one[- ]bedroom|1[- ]?(?:BR|bedroom)).*?(\d{3,4})\s*(?:sq|square)",
            "max_adu_2br_sqft": r"(?:two[- ]bedroom|2[- ]?(?:BR|bedroom)).*?(\d{3,4})\s*(?:sq|square)",
            "max_jadu_sqft": r"(?:junior|JADU).*?(\d{3,4})\s*(?:sq|square)",
            "max_height_ft": r"(?:height|tall).*?(\d{2})\s*(?:ft|feet)",
        }

        for key, pattern in patterns.items():
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                result["key_numbers"][key] = int(m.group(1))

        if result["key_numbers"]:
            logger.info("Extracted ADU key_numbers: %s", result["key_numbers"])

        return result

    def _parse_hillside_section(self, html: str, text: str) -> dict[str, Any]:
        """Parse BMC 23.210 for hillside overlay rules."""
        result: dict[str, Any] = {
            "source_url": BMC_ZONING_SECTIONS["hillside"],
            "source_document": "BMC Ch. 23.210",
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "key_numbers": {},
        }

        # Extract hillside-specific numbers
        adu_height = re.search(r"(?:ADU|accessory).*?(\d{2})\s*(?:ft|feet)", text, re.IGNORECASE)
        if adu_height:
            result["key_numbers"]["adu_max_height_hillside"] = f"{adu_height.group(1)} ft"

        coverage = re.search(r"ES-R.*?(\d{1,2})\s*%\s*(?:lot\s*)?coverage", text, re.IGNORECASE)
        if coverage:
            result["key_numbers"]["es_r_lot_coverage"] = f"{coverage.group(1)}%"

        return result

    # ------------------------------------------------------------------
    # HTTP scrapers (berkeleyca.gov — accessible without Playwright)
    # ------------------------------------------------------------------

    def _fetch_page(self, url: str, cache_name: str) -> Optional[BeautifulSoup]:
        """Fetch a page, cache its HTML, and return parsed soup."""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("Failed to fetch %s", url, exc_info=True)
            return None

        # Cache raw HTML
        cache_path = self.sources_dir / f"{cache_name}.html"
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(resp.text)

        time.sleep(_REQUEST_DELAY)
        return BeautifulSoup(resp.text, "lxml")

    def _scrape_middle_housing(self) -> dict[str, Any]:
        """Scrape berkeleyca.gov middle housing page for current data."""
        soup = self._fetch_page(BERKELEYCA_MIDDLE_HOUSING_URL, "middle_housing")
        if not soup:
            return {}

        text = soup.get_text(" ", strip=True)
        result: dict[str, Any] = {
            "category": "middle_housing",
            "source_url": BERKELEYCA_MIDDLE_HOUSING_URL,
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "key_numbers": {},
        }

        # Extract unit limits
        r1_match = re.search(r"R-1[^H].*?(?:up\s+to\s+)?(\d)\s*units?", text, re.IGNORECASE)
        if r1_match:
            result["key_numbers"]["r1_max_units"] = int(r1_match.group(1))

        # Lot coverage
        coverage_match = re.search(r"(\d{2})%\s*(?:max(?:imum)?)?\s*(?:lot\s*)?coverage", text, re.IGNORECASE)
        if coverage_match:
            result["key_numbers"]["lot_coverage_pct"] = int(coverage_match.group(1))

        # Height
        height_match = re.search(r"(\d{2})\s*(?:ft|feet)\s*(?:max(?:imum)?)?", text, re.IGNORECASE)
        if height_match:
            result["key_numbers"]["max_height_ft"] = int(height_match.group(1))

        # Effective date
        date_match = re.search(r"(?:effective|became effective)\s+([\w]+\s+\d{1,2},?\s*\d{4})", text, re.IGNORECASE)
        if date_match:
            result["key_numbers"]["effective_date"] = date_match.group(1)

        # Ministerial approval days
        days_match = re.search(r"(\d{2})\s*(?:day|business day)s?\s*(?:ministerial|approval)", text, re.IGNORECASE)
        if days_match:
            result["key_numbers"]["fast_track_days"] = int(days_match.group(1))

        if result["key_numbers"]:
            logger.info("Middle housing scraped: %s", result["key_numbers"])

        return result

    def _scrape_transfer_tax(self) -> dict[str, Any]:
        """Scrape berkeleyca.gov transfer tax page for rates."""
        soup = self._fetch_page(BERKELEYCA_TRANSFER_TAX_URL, "transfer_tax")
        if not soup:
            return {}

        text = soup.get_text(" ", strip=True)
        result: dict[str, Any] = {
            "category": "transfer_tax",
            "source_url": BERKELEYCA_TRANSFER_TAX_URL,
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "key_numbers": {},
        }

        # Extract tax rates (e.g., "1.5%" or "2.5%")
        rates = re.findall(r"(\d+\.?\d*)\s*%", text)
        if rates:
            result["key_numbers"]["rates_found"] = [f"{r}%" for r in rates[:5]]

        # Threshold amounts
        thresholds = re.findall(r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:million)?", text)
        if thresholds:
            result["key_numbers"]["thresholds_found"] = thresholds[:5]

        return result

    def _scrape_rent_board(self) -> dict[str, Any]:
        """Scrape rentboard.berkeleyca.gov for rent control info."""
        soup = self._fetch_page(RENT_BOARD_URL, "rent_board_home")
        if not soup:
            return {}

        text = soup.get_text(" ", strip=True)
        result: dict[str, Any] = {
            "category": "rent_control",
            "source_url": RENT_BOARD_URL,
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "key_numbers": {},
        }

        # Try to find AGA (Annual General Adjustment) percentage
        aga_match = re.search(
            r"(?:annual\s+general\s+adjustment|AGA).*?(\d+\.?\d*)\s*%",
            text,
            re.IGNORECASE,
        )
        if aga_match:
            result["key_numbers"]["annual_general_adjustment"] = f"{aga_match.group(1)}%"

        # Also try the rent control 101 page for more details
        soup2 = self._fetch_page(RENT_BOARD_RENT_CONTROL_URL, "rent_control_101")
        if soup2:
            text2 = soup2.get_text(" ", strip=True)
            # Units covered
            units_match = re.search(r"([\d,]+)\s*(?:rental\s*)?units?\s*(?:covered|registered)", text2, re.IGNORECASE)
            if units_match:
                result["key_numbers"]["units_covered"] = units_match.group(1)

        return result

    def _scrape_beso_page(self) -> dict[str, Any]:
        """Scrape berkeleyca.gov BESO page for current thresholds."""
        soup = self._fetch_page(BERKELEYCA_BESO_INFO_URL, "beso_info")
        if not soup:
            return {}

        text = soup.get_text(" ", strip=True)
        result: dict[str, Any] = {
            "category": "beso",
            "source_url": BERKELEYCA_BESO_INFO_URL,
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "key_numbers": {},
        }

        # Minimum building size
        sqft_match = re.search(r"(\d{3,})\s*(?:sq|square)\s*(?:ft|feet)", text, re.IGNORECASE)
        if sqft_match:
            result["key_numbers"]["min_building_sqft"] = int(sqft_match.group(1))

        # Escrow deposit
        deposit_match = re.search(r"\$\s*([\d,]+)\s*(?:escrow|deposit)", text, re.IGNORECASE)
        if deposit_match:
            result["key_numbers"]["escrow_deposit"] = f"${deposit_match.group(1)}"

        return result

    def _scrape_permitting_page(self) -> dict[str, Any]:
        """Scrape berkeleyca.gov permit process page."""
        soup = self._fetch_page(BERKELEYCA_PERMITTING_URL, "permitting")
        if not soup:
            return {}

        text = soup.get_text(" ", strip=True)
        result: dict[str, Any] = {
            "category": "permitting",
            "source_url": BERKELEYCA_PERMITTING_URL,
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "key_numbers": {},
        }

        # ADU permit timeline
        adu_days = re.search(r"ADU.*?(\d{2})\s*days?", text, re.IGNORECASE)
        if adu_days:
            result["key_numbers"]["adu_permit_days"] = int(adu_days.group(1))

        return result

    # ------------------------------------------------------------------
    # Merge logic
    # ------------------------------------------------------------------

    def _merge(
        self,
        seed_zones: dict,
        seed_categories: dict,
        scraped: dict[str, Any],
    ) -> tuple[dict, dict]:
        """Merge scraped data into seed. Seed is authoritative for text
        fields; scraped data updates key_numbers and last_verified.

        Rules:
        - Seed wins for: name, description, title, summary, details
        - Scraped updates: key_numbers (individual values), last_verified
        - New zones/categories in scraped only → logged, not auto-added
        """
        now = datetime.now(timezone.utc).isoformat()
        final_zones = {k: dict(v) for k, v in seed_zones.items()}
        final_categories = {k: dict(v) for k, v in seed_categories.items()}

        # Merge zone data from municipal code scraping
        bmc_data = scraped.get("municipal_code", {})
        scraped_zones = bmc_data.get("zones", {})
        for zone_code, zone_scraped in scraped_zones.items():
            if zone_code in final_zones:
                # Update numeric fields only
                for field in ("max_height_ft", "lot_coverage_pct"):
                    if field in zone_scraped:
                        final_zones[zone_code][field] = zone_scraped[field]
                final_zones[zone_code]["last_verified"] = now
                final_zones[zone_code]["source_url"] = zone_scraped.get(
                    "source_url", final_zones[zone_code].get("source_url", "")
                )
            else:
                logger.warning(
                    "New zone %s found in scraping but not in seed — "
                    "requires manual review",
                    zone_code,
                )

        # Merge category data from all scrapers
        for source_name, source_data in scraped.items():
            cat_key = source_data.get("category")
            if not cat_key or cat_key not in final_categories:
                # Also check municipal code categories
                if source_name == "municipal_code":
                    for ckey, cdata in bmc_data.get("categories", {}).items():
                        if ckey in final_categories:
                            self._merge_category_numbers(
                                final_categories[ckey], cdata, now
                            )
                continue

            self._merge_category_numbers(
                final_categories[cat_key], source_data, now
            )

        return final_zones, final_categories

    def _merge_category_numbers(
        self, target: dict, scraped: dict, now: str
    ) -> None:
        """Merge scraped key_numbers into a category entry."""
        scraped_numbers = scraped.get("key_numbers", {})
        if not scraped_numbers:
            return

        if "key_numbers" not in target:
            target["key_numbers"] = {}

        for k, v in scraped_numbers.items():
            target["key_numbers"][k] = v

        target["last_verified"] = now
        if "source_url" in scraped:
            target["source_url"] = scraped["source_url"]

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------

    def _write_json(self, zones: dict, categories: dict) -> None:
        """Write final JSON files with $meta header."""
        now = datetime.now(timezone.utc).isoformat()

        zones_out = {
            "$meta": {
                "schema_version": 1,
                "generated_at": now,
                "generator": "homebuyer collect regulations",
                "total_zones": len(zones),
            }
        }
        zones_out.update(zones)

        cats_out = {
            "$meta": {
                "schema_version": 1,
                "generated_at": now,
                "generator": "homebuyer collect regulations",
                "total_categories": len(categories),
            }
        }
        cats_out.update(categories)

        zones_path = self.regulations_dir / "zones.json"
        cats_path = self.regulations_dir / "categories.json"

        with open(zones_path, "w") as f:
            json.dump(zones_out, f, indent=2, default=str)
        logger.info("Wrote %d zones to %s", len(zones), zones_path)

        with open(cats_path, "w") as f:
            json.dump(cats_out, f, indent=2, default=str)
        logger.info("Wrote %d categories to %s", len(categories), cats_path)
