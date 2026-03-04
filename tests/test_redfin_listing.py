"""Tests for the Redfin listing fetcher."""

import json

import pytest

from homebuyer.collectors.redfin_listing import (
    ListingFetcher,
    extract_address_from_url,
    extract_property_id,
)


# ---------------------------------------------------------------------------
# URL parsing tests
# ---------------------------------------------------------------------------


def test_extract_property_id_standard():
    """Extract property ID from standard Redfin URL."""
    url = "https://www.redfin.com/CA/Berkeley/1234-Cedar-St-94702/home/12345678"
    assert extract_property_id(url) == "12345678"


def test_extract_property_id_with_unit():
    """Extract property ID from URL with unit number."""
    url = "https://www.redfin.com/CA/Berkeley/1234-Cedar-St-Unit-2-94702/home/98765432"
    assert extract_property_id(url) == "98765432"


def test_extract_property_id_no_match():
    """Return None for non-Redfin URLs."""
    assert extract_property_id("https://zillow.com/homes/12345") is None
    assert extract_property_id("https://www.redfin.com/city/123") is None


def test_extract_address_from_url():
    """Extract address from URL path."""
    url = "https://www.redfin.com/CA/Berkeley/1234-Cedar-St-94702/home/12345678"
    addr = extract_address_from_url(url)
    assert addr is not None
    assert "Cedar" in addr
    assert "1234" in addr


def test_extract_address_from_url_no_match():
    """Return None for short URLs."""
    assert extract_address_from_url("https://www.redfin.com/") is None


# ---------------------------------------------------------------------------
# JSON-LD parsing tests
# ---------------------------------------------------------------------------


def test_parse_json_ld_single_family():
    """Parse a SingleFamilyResidence JSON-LD object."""
    fetcher = ListingFetcher.__new__(ListingFetcher)

    json_ld = {
        "@type": "SingleFamilyResidence",
        "address": {
            "streetAddress": "1234 Cedar St",
            "addressLocality": "Berkeley",
            "addressRegion": "CA",
            "postalCode": "94702",
        },
        "geo": {
            "latitude": 37.87,
            "longitude": -122.27,
        },
        "numberOfBedrooms": 3,
        "numberOfBathroomsTotal": 2,
        "floorSize": {"value": 1650},
        "yearBuilt": 1923,
        "lotSize": {"value": 5000},
        "offers": {"price": 1199000},
    }

    result = fetcher._parse_json_ld(json_ld)

    assert result is not None
    assert result["address"] == "1234 Cedar St"
    assert result["city"] == "Berkeley"
    assert result["state"] == "CA"
    assert result["zip_code"] == "94702"
    assert result["beds"] == 3.0
    assert result["baths"] == 2.0
    assert result["sqft"] == 1650
    assert result["year_built"] == 1923
    assert result["lot_size_sqft"] == 5000
    assert result["list_price"] == 1199000
    assert result["latitude"] == 37.87
    assert result["longitude"] == -122.27
    assert result["property_type"] == "Single Family Residential"


def test_parse_json_ld_ignores_irrelevant_types():
    """JSON-LD of non-property types returns None."""
    fetcher = ListingFetcher.__new__(ListingFetcher)

    json_ld = {
        "@type": "Organization",
        "name": "Redfin",
    }

    assert fetcher._parse_json_ld(json_ld) is None


def test_parse_json_ld_list_type():
    """Handle @type as a list."""
    fetcher = ListingFetcher.__new__(ListingFetcher)

    json_ld = {
        "@type": ["SingleFamilyResidence"],
        "address": {
            "streetAddress": "456 Oak Ave",
            "addressLocality": "Berkeley",
            "addressRegion": "CA",
            "postalCode": "94705",
        },
        "offers": {"price": 2000000},
    }

    result = fetcher._parse_json_ld(json_ld)
    assert result is not None
    assert result["address"] == "456 Oak Ave"
    assert result["list_price"] == 2000000


def test_parse_json_ld_missing_optional_fields():
    """Handle missing optional fields gracefully."""
    fetcher = ListingFetcher.__new__(ListingFetcher)

    json_ld = {
        "@type": "House",
        "address": {
            "streetAddress": "789 Elm Rd",
            "addressLocality": "Berkeley",
            "addressRegion": "CA",
            "postalCode": "94703",
        },
    }

    result = fetcher._parse_json_ld(json_ld)
    assert result is not None
    assert result["address"] == "789 Elm Rd"
    assert result.get("beds") is None
    assert result.get("baths") is None
    assert result.get("sqft") is None
    assert result.get("list_price") is None


# ---------------------------------------------------------------------------
# Stingray response parsing tests
# ---------------------------------------------------------------------------


def test_parse_stingray_response():
    """Parse a stingray API response."""
    fetcher = ListingFetcher.__new__(ListingFetcher)

    data = {
        "payload": {
            "listingDetail": {
                "basicInfo": {
                    "beds": 4,
                    "baths": 3,
                    "sqFt": 2200,
                    "yearBuilt": 1935,
                    "lotSqFt": 8000,
                    "price": 2500000,
                    "propertyType": "SINGLE_FAMILY_RESIDENTIAL",
                    "hoa": {"amount": 100},
                },
                "address": {
                    "streetAddress": "100 Highland Pl",
                    "city": "Berkeley",
                    "stateOrProvince": "CA",
                    "postalCode": "94708",
                    "latitude": 37.88,
                    "longitude": -122.26,
                },
            }
        }
    }

    result = fetcher._parse_stingray_response(data)

    assert result is not None
    assert result["address"] == "100 Highland Pl"
    assert result["beds"] == 4.0
    assert result["baths"] == 3.0
    assert result["sqft"] == 2200
    assert result["year_built"] == 1935
    assert result["list_price"] == 2500000
    assert result["hoa_per_month"] == 100
    assert result["property_type"] == "Single Family Residential"


def test_parse_stingray_empty_payload():
    """Empty payload returns None."""
    fetcher = ListingFetcher.__new__(ListingFetcher)

    assert fetcher._parse_stingray_response({}) is None
    assert fetcher._parse_stingray_response({"payload": {}}) is None


def test_fetch_listing_invalid_url():
    """Invalid URL raises ValueError."""
    fetcher = ListingFetcher.__new__(ListingFetcher)
    fetcher.session = None  # Won't be used

    with pytest.raises(ValueError, match="Could not extract property ID"):
        fetcher.fetch_listing("https://example.com/not-a-listing")
