"""Collector for Berkeley building permits from the Accela Citizen Access portal.

Scrapes permit records from the public portal at aca-prod.accela.com/BERKELEY.
No login or API key is required — the portal provides unauthenticated search
for building permit records by address.

Uses Playwright (headless Chromium) because the portal is an ASP.NET WebForms
application with strict ViewState validation that prevents raw HTTP scraping.
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional

from homebuyer.config import (
    ACCELA_BATCH_SIZE,
    ACCELA_DETAIL_BASE,
    ACCELA_REQUEST_DELAY,
    ACCELA_SEARCH_URL,
)
from homebuyer.storage.database import Database
from homebuyer.storage.models import BuildingPermit, CollectionResult

logger = logging.getLogger(__name__)

# Regex to split "1529 Ada St" → ("1529", "Ada")
_ADDRESS_RE = re.compile(
    r"^(\d+)\s+"
    r"(.+?)"
    r"(?:\s+(?:St|Ave|Dr|Rd|Way|Blvd|Ct|Pl|Ln|Cir|Ter|Loop|Pkwy))?\.?$",
    re.IGNORECASE,
)

# ASP.NET form selectors
_SEL_STREET_NAME = "#ctl00_PlaceHolderMain_generalSearchForm_txtGSStreetName"
_SEL_STREET_NUM_FROM = "#ctl00_PlaceHolderMain_generalSearchForm_txtGSNumber_ChildControl0"
_SEL_SEARCH_BTN = "#ctl00_PlaceHolderMain_btnNewSearch"
_SEL_START_DATE = "ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate"
_SEL_END_DATE = "ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate"


def parse_address(address: str) -> tuple[str, str]:
    """Split a street address into (street_number, street_name).

    >>> parse_address("1529 Ada St")
    ('1529', 'Ada')
    >>> parse_address("2144 Edison Ave")
    ('2144', 'Edison')
    """
    m = _ADDRESS_RE.match(address.strip())
    if m:
        return m.group(1), m.group(2).strip()

    # Fallback: split on first space
    parts = address.strip().split(None, 1)
    if len(parts) >= 2 and parts[0].isdigit():
        # Remove trailing street type
        name = re.sub(
            r"\s+(?:St|Ave|Dr|Rd|Way|Blvd|Ct|Pl|Ln|Cir|Ter|Loop|Pkwy)\.?$",
            "",
            parts[1],
            flags=re.IGNORECASE,
        )
        return parts[0], name.strip()

    raise ValueError(f"Cannot parse address: {address!r}")


def extract_permit_data(
    page, permit_url: str, filed_date: str | None = None
) -> Optional[BuildingPermit]:
    """Navigate to a permit detail page and extract structured data.

    Args:
        page: A Playwright Page object.
        permit_url: Full URL to the permit detail page.
        filed_date: Optional date from search results (MM/DD/YYYY).

    Returns:
        A BuildingPermit or None if extraction fails.
    """
    try:
        page.goto(permit_url, wait_until="networkidle", timeout=30000)
    except Exception as e:
        logger.warning("Failed to load permit page %s: %s", permit_url, e)
        return None

    html = page.content()
    body_text = page.inner_text("body")

    data: dict = {"detail_url": permit_url}

    # Record number and type
    record_match = re.search(
        r"Record\s+(B\d{4}-\d+(?:-REV\d+)?|ESR-\d+-\d+):\s*\n\s*(.+)", body_text
    )
    if record_match:
        data["record_number"] = record_match.group(1).strip()
        data["permit_type"] = record_match.group(2).strip()
    else:
        # Try a broader pattern
        record_match2 = re.search(r"Record\s+([A-Z0-9]+-[A-Z0-9-]+):", body_text)
        if record_match2:
            data["record_number"] = record_match2.group(1).strip()
        else:
            logger.warning("Could not extract record number from %s", permit_url)
            return None

    # Filed date: prefer date from search results (MM/DD/YYYY), fall back to
    # year extracted from record number (B{YYYY}-xxxxx → YYYY-01-01)
    if filed_date:
        try:
            from datetime import datetime as _dt

            parsed = _dt.strptime(filed_date, "%m/%d/%Y")
            data["filed_date"] = parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

    if "filed_date" not in data:
        record_num = data.get("record_number", "")
        year_match = re.match(r"B(\d{4})-", record_num)
        if year_match:
            data["filed_date"] = f"{year_match.group(1)}-01-01"
        elif record_num.startswith("ESR-"):
            esr_year_match = re.match(r"ESR-(\d{2})-", record_num)
            if esr_year_match:
                yr = int(esr_year_match.group(1))
                full_year = 2000 + yr if yr < 50 else 1900 + yr
                data["filed_date"] = f"{full_year}-01-01"

    # Status
    status_match = re.search(r"Record Status:\s*(.+)", body_text)
    if status_match:
        data["status"] = status_match.group(1).strip()

    # Address
    addr_section = re.search(r"Work Location\s*\n\s*(.+)\n\s*(\d{5})", body_text)
    if addr_section:
        data["address"] = addr_section.group(1).strip()
        data["zip_code"] = addr_section.group(2).strip()

    # Parcel ID
    parcel_match = re.search(r"PARCEL ID:\s*(\d+)", body_text)
    if parcel_match:
        data["parcel_id"] = parcel_match.group(1)

    # Project Description
    desc_match = re.search(
        r"Project Description:\s*\n\s*(.+?)(?:\n\s*Owner:|\n\s*More Details|$)",
        body_text,
        re.DOTALL,
    )
    if desc_match:
        data["description"] = re.sub(r"\s+", " ", desc_match.group(1)).strip()

    # Owner
    owner_match = re.search(r"Owner:\s*\n\s*(.+?)(?:\s*\*|\n)", body_text)
    if owner_match:
        data["owner_name"] = owner_match.group(1).strip()

    # Contractor CSLB#
    cslb_match = re.search(r"State CSLB #:\s*(\d+)", body_text)
    if cslb_match:
        data["contractor_cslb"] = cslb_match.group(1)

    # Job Value from ASI section (in raw HTML)
    # HTML structure: <h2>Job Value($):</h2></span><span class="ACA_SmLabel...">$34,350.00</span>
    job_val_match = re.search(
        r"Job Value\(\$\):</h2></span>\s*<span[^>]*>\$?([\d,]+\.?\d*)", html
    )
    if not job_val_match:
        # Fallback: try plain text pattern (for alternate page layouts)
        job_val_match = re.search(r"Job Value\(\$\):\s*\$?([\d,]+\.?\d*)", html)
    if job_val_match:
        try:
            data["job_value"] = float(job_val_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Construction Type from ASI section
    # HTML structure: <h2>Construction Type:</h2></span><span class="ACA_SmLabel...">10-NA</span>
    const_type_match = re.search(
        r"Construction Type:</h2></span>\s*<span[^>]*>([^<]+)", html
    )
    if not const_type_match:
        # Fallback: try plain text pattern
        const_type_match = re.search(r"Construction Type:\s*([^\s<]+)", html)
    if const_type_match:
        data["construction_type"] = const_type_match.group(1).strip()

    # Ensure we have the required fields
    if "record_number" not in data or "address" not in data:
        logger.warning(
            "Missing required fields for permit at %s (have: %s)",
            permit_url,
            list(data.keys()),
        )
        return None

    return BuildingPermit(**data)


class AccelaPermitCollector:
    """Scrape Berkeley building permits from the Accela Citizen Access portal.

    Uses Playwright (headless Chromium) because the portal is ASP.NET
    WebForms with strict ViewState validation that prevents raw HTTP scraping.

    Usage:
        with Database(db_path) as db:
            collector = AccelaPermitCollector(db)
            result = collector.collect(limit_addresses=10)
            print(result)
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def collect(
        self,
        start_date: str = "01/01/2000",
        end_date: str | None = None,
        limit_addresses: int | None = None,
        force: bool = False,
    ) -> CollectionResult:
        """Collect permits for all addresses in the property_sales table.

        Args:
            start_date: Earliest permit date to search (MM/DD/YYYY).
            end_date: Latest permit date (default: today).
            limit_addresses: Max number of addresses to process (for testing).
            force: Re-collect even if address already has permit data.

        Returns:
            A CollectionResult summarizing what was collected.
        """
        from playwright.sync_api import sync_playwright

        if end_date is None:
            end_date = datetime.now().strftime("%m/%d/%Y")

        result = CollectionResult(source="accela_permits", started_at=datetime.now())
        run_id = self.db.start_collection_run(
            "accela_permits",
            {"start_date": start_date, "end_date": end_date, "limit": limit_addresses},
        )

        # Get all unique addresses from property_sales
        rows = self.db.fetchall(
            "SELECT DISTINCT address FROM property_sales WHERE address IS NOT NULL"
        )
        all_addresses = [dict(row)["address"] for row in rows]

        # Filter out already-collected addresses (unless force=True)
        if not force:
            collected = self.db.get_collected_permit_addresses()
            addresses = [
                a for a in all_addresses
                if a.upper().strip() not in collected
            ]
            logger.info(
                "Permits: %d total addresses, %d already collected, %d remaining.",
                len(all_addresses),
                len(collected),
                len(addresses),
            )
        else:
            addresses = all_addresses
            logger.info("Permits: %d addresses (force re-collect).", len(addresses))

        if limit_addresses is not None:
            addresses = addresses[:limit_addresses]

        total = len(addresses)
        if total == 0:
            logger.info("No addresses to process.")
            result.completed_at = datetime.now()
            self.db.complete_collection_run(run_id, result)
            return result

        logger.info("Processing %d addresses...", total)
        pending_permits: list[BuildingPermit] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            try:
                for idx, address in enumerate(addresses, 1):
                    try:
                        street_number, street_name = parse_address(address)
                    except ValueError as e:
                        logger.warning("[%d/%d] %s — skipping: %s", idx, total, address, e)
                        continue

                    try:
                        permits = self._search_address(
                            browser, street_number, street_name, start_date, end_date
                        )
                    except KeyboardInterrupt:
                        logger.info("Interrupted at address %d/%d.", idx, total)
                        break
                    except Exception as e:
                        logger.warning(
                            "[%d/%d] %s — search error: %s", idx, total, address, e
                        )
                        result.errors.append(f"{address}: {e}")
                        continue

                    result.records_fetched += len(permits)
                    pending_permits.extend(permits)

                    logger.info(
                        "[%d/%d] %s → %d permits found",
                        idx,
                        total,
                        address,
                        len(permits),
                    )

                    # Batch upsert periodically
                    if len(pending_permits) >= ACCELA_BATCH_SIZE:
                        inserted, dups = self.db.upsert_permits_batch(pending_permits)
                        result.records_inserted += inserted
                        result.records_duplicates += dups
                        pending_permits.clear()

            finally:
                # Upsert any remaining permits
                if pending_permits:
                    inserted, dups = self.db.upsert_permits_batch(pending_permits)
                    result.records_inserted += inserted
                    result.records_duplicates += dups
                    pending_permits.clear()

                browser.close()

        result.completed_at = datetime.now()
        self.db.complete_collection_run(run_id, result)

        logger.info(
            "Permits: %d fetched, %d inserted, %d duplicates, %d errors.",
            result.records_fetched,
            result.records_inserted,
            result.records_duplicates,
            len(result.errors),
        )
        return result

    def collect_for_address(
        self,
        address: str,
        start_date: str = "01/01/2000",
        end_date: str | None = None,
    ) -> list[BuildingPermit]:
        """Collect permits for a single address.

        Args:
            address: Full street address (e.g., "1529 Ada St").
            start_date: Earliest permit date (MM/DD/YYYY).
            end_date: Latest permit date (default: today).

        Returns:
            List of BuildingPermit records found.
        """
        from playwright.sync_api import sync_playwright

        if end_date is None:
            end_date = datetime.now().strftime("%m/%d/%Y")

        street_number, street_name = parse_address(address)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                permits = self._search_address(
                    browser, street_number, street_name, start_date, end_date
                )
            finally:
                browser.close()

        # Save to database
        if permits:
            inserted, dups = self.db.upsert_permits_batch(permits)
            logger.info(
                "Address %s: %d permits found, %d inserted, %d duplicates.",
                address,
                len(permits),
                inserted,
                dups,
            )

        return permits

    def _search_address(
        self,
        browser,
        street_number: str,
        street_name: str,
        start_date: str,
        end_date: str,
    ) -> list[BuildingPermit]:
        """Search for permits at a specific address and extract detail data.

        Args:
            browser: A Playwright Browser instance.
            street_number: House number (e.g., "1529").
            street_name: Street name without suffix (e.g., "Ada").
            start_date: Search date range start (MM/DD/YYYY).
            end_date: Search date range end (MM/DD/YYYY).

        Returns:
            List of BuildingPermit records.
        """
        page = browser.new_page()

        try:
            # Navigate to search page
            page.goto(ACCELA_SEARCH_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_selector(_SEL_STREET_NAME, timeout=10000)

            # Fill search form
            page.fill(_SEL_STREET_NUM_FROM, street_number)
            page.fill(_SEL_STREET_NAME, street_name)

            # Set date range via JavaScript (ASP.NET controls need direct value set)
            page.evaluate(
                f"""
                document.getElementById('{_SEL_START_DATE}').value = '{start_date}';
                document.getElementById('{_SEL_END_DATE}').value = '{end_date}';
                """
            )

            # Click search
            page.click(_SEL_SEARCH_BTN)
            time.sleep(ACCELA_REQUEST_DELAY + 1)
            page.wait_for_load_state("networkidle", timeout=15000)

            # Collect result links from all pages
            permit_links = self._collect_result_links(page)

        finally:
            page.close()

        if not permit_links:
            return []

        # Fetch detail for each permit
        permits: list[BuildingPermit] = []
        for record_number, href, filed_date in permit_links:
            detail_url = (
                f"{ACCELA_DETAIL_BASE}{href}" if href.startswith("/") else href
            )

            detail_page = browser.new_page()
            try:
                permit = extract_permit_data(detail_page, detail_url, filed_date)
                if permit is not None:
                    permits.append(permit)
                time.sleep(ACCELA_REQUEST_DELAY)
            except Exception as e:
                logger.warning(
                    "Error extracting detail for %s: %s", record_number, e
                )
            finally:
                detail_page.close()

        return permits

    def _collect_result_links(
        self, page
    ) -> list[tuple[str, str, str | None]]:
        """Collect all (record_number, href, filed_date) from search results, handling pagination.

        Extracts the Date column from the search results table for each permit
        to provide a precise filed_date instead of estimating from the record number.

        Args:
            page: The Playwright Page after search submission.

        Returns:
            List of (record_number, href, filed_date) tuples.
            filed_date is in MM/DD/YYYY format or None.
        """
        all_links: list[tuple[str, str, str | None]] = []
        page_num = 1

        while True:
            # Extract dates from the search results body text
            body_text = page.inner_text("body")
            date_list = re.findall(r"\d{2}/\d{2}/\d{4}", body_text)

            records = page.query_selector_all("a[href*='CapDetail']")
            for idx, rec in enumerate(records):
                text = rec.inner_text().strip()
                href = rec.get_attribute("href")
                if text and href:
                    # Match date by position: dates appear once per result row
                    filed_date = date_list[idx] if idx < len(date_list) else None
                    all_links.append((text, href, filed_date))

            # Check for pagination ("1-10 of 31")
            body_text = page.inner_text("body")
            total_match = re.search(r"(\d+)\s*-\s*(\d+)\s*of\s*(\d+)", body_text)

            if total_match:
                showing_end = int(total_match.group(2))
                total = int(total_match.group(3))

                if showing_end >= total:
                    break  # No more pages

                # Click "Next >" to go to next page
                next_link = page.query_selector("a:has-text('Next >')")
                if next_link:
                    next_link.click()
                    time.sleep(ACCELA_REQUEST_DELAY)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    page_num += 1
                else:
                    break
            else:
                break

            # Safety limit to prevent infinite loops
            if page_num > 20:
                logger.warning("Stopped pagination at page 20 (safety limit).")
                break

        return all_links
