"""
BioGraph MVP v8.2 - ChEMBL Resolver

Per Section 23C.2 of the spec, this module resolves molecule labels from ChEMBL.

Storage Strategy (Thin Durable Core):
- Store ONLY ChEMBL IDs locally (as attribute in drug_program)
- Resolve labels LIVE via REST API
- Cache results in lookup_cache (TTL: 30 days)
- Fallback to ID on fetch failure

This is presentation layer ONLY - does NOT affect linkage confidence.
"""

from typing import Any, Dict, Optional
import logging
import requests
from biograph.core.lookup_cache import (
    LookupCache,
    CacheSource,
    make_cache_key,
    cached_resolve_with_fallback
)

logger = logging.getLogger(__name__)

# ChEMBL REST API
CHEMBL_REST_URL = "https://www.ebi.ac.uk/chembl/api/data"

# Query timeout (seconds)
REQUEST_TIMEOUT = 10


def fetch_molecule_live(chembl_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch molecule label from ChEMBL REST API.

    Fetches:
    - pref_name (preferred name)
    - molecule_type (e.g., 'Small molecule', 'Antibody')
    - max_phase (highest development phase)

    Args:
        chembl_id: ChEMBL ID (e.g., 'CHEMBL1201234')

    Returns:
        Dict with molecule data, or None on failure
    """
    # ChEMBL REST API endpoint
    url = f"{CHEMBL_REST_URL}/molecule/{chembl_id}.json"

    try:
        logger.debug(f"Fetching molecule from ChEMBL: {chembl_id}")

        response = requests.get(url, timeout=REQUEST_TIMEOUT)

        # Handle 404 (not found)
        if response.status_code == 404:
            logger.warning(f"Molecule not found in ChEMBL: {chembl_id}")
            return None

        response.raise_for_status()
        data = response.json()

        # Extract fields
        pref_name = data.get("pref_name")
        molecule_type = data.get("molecule_type")
        max_phase = data.get("max_phase")

        # Use pref_name as label, fallback to chembl_id
        label = pref_name or chembl_id

        return {
            "id": chembl_id,
            "label": label,
            "pref_name": pref_name,
            "molecule_type": molecule_type,
            "max_phase": max_phase,
            "source": "chembl"
        }

    except requests.exceptions.Timeout:
        logger.error(f"ChEMBL API timeout for molecule {chembl_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"ChEMBL API error for molecule {chembl_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching molecule {chembl_id}: {e}")
        return None


def get_chembl_label(cursor: Any, chembl_id: str, ttl_days: int = 30) -> Dict[str, Any]:
    """
    Get ChEMBL molecule label (cached or live).

    Per Section 23H: Check cache first, fetch live on miss, fallback to ID on failure.

    Args:
        cursor: Database cursor
        chembl_id: ChEMBL ID
        ttl_days: Cache TTL (default: 30 days)

    Returns:
        Dict with molecule data (always succeeds via fallback)
    """
    return cached_resolve_with_fallback(
        cursor=cursor,
        source=CacheSource.CHEMBL,
        entity_id=chembl_id,
        resolver_fn=fetch_molecule_live,
        fallback_label=chembl_id,
        ttl_days=ttl_days
    )


def batch_resolve_molecules(cursor: Any, chembl_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch resolve multiple ChEMBL molecules.

    Args:
        cursor: Database cursor
        chembl_ids: List of ChEMBL IDs

    Returns:
        Dict mapping chembl_id → molecule data
    """
    results = {}

    for chembl_id in chembl_ids:
        results[chembl_id] = get_chembl_label(cursor, chembl_id)

    return results


def validate_chembl_id(chembl_id: str) -> bool:
    """
    Validate ChEMBL ID format.

    ChEMBL IDs have format: CHEMBL[0-9]+ (e.g., CHEMBL1201234).

    Args:
        chembl_id: ChEMBL ID to validate

    Returns:
        True if valid ChEMBL ID format
    """
    import re
    return bool(re.match(r'^CHEMBL\d+$', chembl_id))
