"""Glossary data collector.

Copies curated seed JSON files to the live glossary location, then optionally
fetches live data from structured sources (FHFA conforming loan limits) and
merges updated ``key_numbers`` into the appropriate glossary terms.

Usage:
    homebuyer collect glossary              # seed + FHFA fetch + merge
    homebuyer collect glossary --seed-only  # seed copy only, no network
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

from homebuyer.utils.file_utils import load_json_data
from homebuyer.config import (
    ALAMEDA_FIPS_COUNTY,
    ALAMEDA_FIPS_STATE,
    FHFA_LOAN_LIMITS_URL,
    FHFA_LOAN_LIMITS_YEAR,
    GLOSSARY_DIR,
    GLOSSARY_SEED_DIR,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class GlossaryCollector:
    """Collect and assemble glossary JSON from seed files + live sources."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.glossary_dir = GLOSSARY_DIR if data_dir is None else data_dir / "glossary"
        self.seed_dir = GLOSSARY_SEED_DIR if data_dir is None else data_dir / "glossary" / "seed"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self, *, seed_only: bool = False) -> dict[str, Any]:
        """Run the full glossary pipeline.

        1. Copy seed files to live location.
        2. (unless seed_only) Fetch FHFA loan limits and merge into live JSON.
        3. Write final JSON with ``$meta`` headers and ``last_verified`` stamps.

        Returns summary dict with counts and any scraped data.
        """
        self.glossary_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Copy seed → live
        copied = self._copy_seed_files()

        if seed_only:
            return {"copied": copied, "scraped": {}}

        # Step 2: Load live JSON (just copied from seed)
        financial = self._load_json("financial_terms.json")
        realestate = self._load_json("realestate_terms.json")

        # Step 3: Fetch live data
        scraped: dict[str, Any] = {}
        fhfa_data = self._fetch_fhfa_loan_limits()
        if fhfa_data:
            scraped["fhfa"] = fhfa_data

        # Step 4: Merge scraped data into live terms
        if scraped:
            self._merge(financial, realestate, scraped)

        # Step 5: Write final JSON
        self._write_json("financial_terms.json", financial, "financial")
        self._write_json("realestate_terms.json", realestate, "realestate")

        return {
            "copied": copied,
            "scraped": scraped,
            "financial_terms": len(financial),
            "realestate_terms": len(realestate),
        }

    # ------------------------------------------------------------------
    # Seed file management
    # ------------------------------------------------------------------

    def _copy_seed_files(self) -> int:
        """Copy seed files to live location. Returns count of files copied."""
        if not self.seed_dir.exists():
            logger.warning("Seed directory not found: %s", self.seed_dir)
            return 0

        copied = 0
        for seed_file in self.seed_dir.glob("*_seed.json"):
            live_name = seed_file.name.replace("_seed", "")
            dest = self.glossary_dir / live_name
            shutil.copy2(seed_file, dest)
            logger.info("Copied %s -> %s", seed_file.name, live_name)
            copied += 1

        return copied

    def _load_json(self, filename: str) -> dict:
        """Load a live glossary JSON, stripping ``$meta``."""
        path = self.glossary_dir / filename
        if not path.exists():
            logger.warning("Glossary file not found: %s", path)
            return {}
        return load_json_data(path)

    # ------------------------------------------------------------------
    # FHFA conforming loan limits
    # ------------------------------------------------------------------

    def _fetch_fhfa_loan_limits(self) -> dict[str, Any] | None:
        """Download FHFA XLSX and extract Alameda County loan limits.

        Returns dict with key_numbers and metadata, or None on failure.
        """
        try:
            import pandas as pd
        except ImportError:
            logger.warning("pandas not available — skipping FHFA fetch")
            return None

        try:
            import openpyxl  # noqa: F401 — needed as pandas engine
        except ImportError:
            logger.warning("openpyxl not available — skipping FHFA fetch")
            return None

        logger.info("Fetching FHFA loan limits from %s", FHFA_LOAN_LIMITS_URL)
        try:
            resp = requests.get(
                FHFA_LOAN_LIMITS_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("FHFA download failed: %s", e)
            return None

        try:
            df = pd.read_excel(BytesIO(resp.content), engine="openpyxl", header=1)
            # Clean column names (FHFA uses newlines in headers)
            df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]

            # Find Alameda County
            alameda = df[
                (df["FIPS State Code"].astype(str).str.zfill(2) == ALAMEDA_FIPS_STATE)
                & (df["FIPS County Code"].astype(str).str.zfill(3) == ALAMEDA_FIPS_COUNTY)
            ]

            if alameda.empty:
                logger.warning("Alameda County not found in FHFA data")
                return None

            row = alameda.iloc[0]
            one_unit = int(row["One-Unit Limit"])
            two_unit = int(row["Two-Unit Limit"])
            three_unit = int(row["Three-Unit Limit"])
            four_unit = int(row["Four-Unit Limit"])

            # National baseline (most common 1-unit limit)
            baseline = int(df["One-Unit Limit"].mode().iloc[0])

            logger.info(
                "FHFA %d: Alameda 1-unit=$%s, baseline=$%s",
                FHFA_LOAN_LIMITS_YEAR,
                f"{one_unit:,}",
                f"{baseline:,}",
            )

            return {
                "year": FHFA_LOAN_LIMITS_YEAR,
                "source_url": FHFA_LOAN_LIMITS_URL,
                "alameda_county": {
                    "one_unit_limit": one_unit,
                    "two_unit_limit": two_unit,
                    "three_unit_limit": three_unit,
                    "four_unit_limit": four_unit,
                },
                "national_baseline": {
                    "one_unit_limit": baseline,
                },
            }

        except Exception as e:
            logger.warning("FHFA XLSX parsing failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Merge logic
    # ------------------------------------------------------------------

    def _merge(
        self,
        financial: dict,
        realestate: dict,
        scraped: dict[str, Any],
    ) -> None:
        """Merge scraped data into glossary terms.

        Rules (same as regulation collector):
        - Seed text wins (definition, example, berkeley_context)
        - Scraped data updates key_numbers values and last_verified
        """
        now = datetime.now(timezone.utc).isoformat()
        fhfa = scraped.get("fhfa")

        if fhfa:
            year = fhfa["year"]
            alameda = fhfa["alameda_county"]
            baseline = fhfa["national_baseline"]

            # Update conforming_vs_jumbo term
            if "conforming_vs_jumbo" in financial:
                term = financial["conforming_vs_jumbo"]
                if "key_numbers" not in term:
                    term["key_numbers"] = {}
                term["key_numbers"][f"{year}_conforming_limit_high_cost"] = (
                    f"${alameda['one_unit_limit']:,}"
                )
                term["key_numbers"][f"{year}_national_baseline"] = (
                    f"${baseline['one_unit_limit']:,}"
                )
                term["last_verified"] = now
                term["source"] = (
                    f"FHFA (Federal Housing Finance Agency) — {year}"
                )

            # Update FHA term (same limits in high-cost areas)
            if "fha" in financial:
                term = financial["fha"]
                if "key_numbers" not in term:
                    term["key_numbers"] = {}
                term["key_numbers"][f"{year}_limit_alameda"] = (
                    f"${alameda['one_unit_limit']:,}"
                )
                term["last_verified"] = now

            # Update VA term (no limit for full entitlement, but good to note)
            # VA doesn't use conforming limits for full-entitlement borrowers,
            # so we just stamp last_verified.
            if "va" in financial:
                financial["va"]["last_verified"] = now

            # Update conforming_vs_jumbo with multi-unit limits too
            if "conforming_vs_jumbo" in financial:
                term = financial["conforming_vs_jumbo"]
                term["key_numbers"][f"{year}_2unit_limit_high_cost"] = (
                    f"${alameda['two_unit_limit']:,}"
                )
                term["key_numbers"][f"{year}_3unit_limit_high_cost"] = (
                    f"${alameda['three_unit_limit']:,}"
                )
                term["key_numbers"][f"{year}_4unit_limit_high_cost"] = (
                    f"${alameda['four_unit_limit']:,}"
                )

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------

    def _write_json(self, filename: str, terms: dict, label: str) -> None:
        """Write final glossary JSON with ``$meta`` header."""
        now = datetime.now(timezone.utc).isoformat()

        output = {
            "$meta": {
                "schema_version": 1,
                "generated_at": now,
                "generator": "homebuyer collect glossary",
                "total_terms": len(terms),
            }
        }
        output.update(terms)

        path = self.glossary_dir / filename
        with open(path, "w") as f:
            json.dump(output, f, indent=2, default=str)

        logger.info("Wrote %d %s terms to %s", len(terms), label, path)
