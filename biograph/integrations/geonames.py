"""
BioGraph MVP v8.2 - GeoNames Resolver

Per Section 23C.3 of the spec, this module resolves location labels from GeoNames.

Storage Strategy (Thin Durable Core):
- Store ONLY GeoNames IDs locally (in location references)
- Resolve labels LIVE via REST API
- Cache results in lookup_cache (TTL: 30 days)
- Fallback to ID on fetch failure

This is presentation layer ONLY - does NOT affect linkage confidence.

Configuration:
- Requires GEONAMES_USERNAME environment variable
- Register for free at: https://www.geonames.org/login
"""

from typing import Any, Dict, Optional
import logging
import requests
import os
from biograph.core.lookup_cache import (
    LookupCache,
    CacheSource,
    make_cache_key,
    cached_resolve_with_fallback
)

logger = logging.getLogger(__name__)

# GeoNames API base URL
GEONAMES_API_URL = "http://api.geonames.org"

# Query timeout (seconds)
REQUEST_TIMEOUT = 10

# GeoNames username (from environment)
GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "demo")


def fetch_location_live(geonames_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch location label from GeoNames API.

    Fetches:
    - name (place name)
    - countryCode (ISO country code)
    - countryName (country name)
    - fcode (feature code, e.g., 'PPL' for populated place)

    Args:
        geonames_id: GeoNames ID (numeric string, e.g., '5128581')

    Returns:
        Dict with location data, or None on failure
    """
    if not GEONAMES_USERNAME or GEONAMES_USERNAME == "demo":
        logger.warning(
            "Using demo GeoNames username. Set GEONAMES_USERNAME env var for production. "
            "Register at: https://www.geonames.org/login"
        )

    # GeoNames get API endpoint
    url = f"{GEONAMES_API_URL}/getJSON"
    params = {
        "geonameId": geonames_id,
        "username": GEONAMES_USERNAME
    }

    try:
        logger.debug(f"Fetching location from GeoNames: {geonames_id}")

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        response.raise_for_status()
        data = response.json()

        # Check for API errors
        if "status" in data:
            # GeoNames returns errors as {"status": {"message": "...", "value": ...}}
            error_msg = data["status"].get("message", "Unknown error")
            logger.error(f"GeoNames API error for {geonames_id}: {error_msg}")
            return None

        # Extract fields
        name = data.get("name")
        country_code = data.get("countryCode")
        country_name = data.get("countryName")
        fcode = data.get("fcode")

        if not name:
            logger.warning(f"Location not found in GeoNames: {geonames_id}")
            return None

        # Build label: "Name, Country" (e.g., "New York, United States")
        if country_name:
            label = f"{name}, {country_name}"
        else:
            label = name

        return {
            "id": geonames_id,
            "label": label,
            "name": name,
            "country_code": country_code,
            "country_name": country_name,
            "fcode": fcode,
            "source": "geonames"
        }

    except requests.exceptions.Timeout:
        logger.error(f"GeoNames API timeout for location {geonames_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"GeoNames API error for location {geonames_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching location {geonames_id}: {e}")
        return None


def get_geonames_label(cursor: Any, geonames_id: str, ttl_days: int = 30) -> Dict[str, Any]:
    """
    Get GeoNames location label (cached or live).

    Per Section 23H: Check cache first, fetch live on miss, fallback to ID on failure.

    Args:
        cursor: Database cursor
        geonames_id: GeoNames ID
        ttl_days: Cache TTL (default: 30 days)

    Returns:
        Dict with location data (always succeeds via fallback)
    """
    return cached_resolve_with_fallback(
        cursor=cursor,
        source=CacheSource.GEONAMES,
        entity_id=geonames_id,
        resolver_fn=fetch_location_live,
        fallback_label=f"GeoNames:{geonames_id}",
        ttl_days=ttl_days
    )


def batch_resolve_locations(cursor: Any, geonames_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch resolve multiple GeoNames locations.

    Args:
        cursor: Database cursor
        geonames_ids: List of GeoNames IDs

    Returns:
        Dict mapping geonames_id → location data
    """
    results = {}

    for geonames_id in geonames_ids:
        results[geonames_id] = get_geonames_label(cursor, geonames_id)

    return results


def validate_geonames_id(geonames_id: str) -> bool:
    """
    Validate GeoNames ID format.

    GeoNames IDs are numeric strings (e.g., '5128581').

    Args:
        geonames_id: GeoNames ID to validate

    Returns:
        True if valid GeoNames ID format
    """
    return geonames_id.isdigit() and len(geonames_id) > 0
