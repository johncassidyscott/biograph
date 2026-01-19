"""
BioGraph MVP v8.2 - MeSH Resolver

Per Section 24B of the spec, this module resolves MeSH (Medical Subject Headings)
labels and tree numbers from NLM APIs.

Storage Strategy (Thin Durable Core):
- Store ONLY MeSH IDs locally (from PubMed)
- Resolve labels and tree numbers LIVE via NLM E-utilities API
- Cache results in lookup_cache (TTL: 90 days - MeSH updates yearly)
- Fallback to ID on fetch failure

MeSH Tree Structure:
- Hierarchical codes (e.g., 'C04.557.470' = lung cancer)
- Tree prefixes map to disease categories
- Used for Therapeutic Area mapping

This is presentation layer ONLY - does NOT affect linkage confidence.
"""

from typing import Any, Dict, Optional, List
import logging
import requests
import xml.etree.ElementTree as ET
from biograph.core.lookup_cache import (
    LookupCache,
    CacheSource,
    make_cache_key,
    cached_resolve_with_fallback
)

logger = logging.getLogger(__name__)

# NLM E-utilities API
EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Query timeout (seconds)
REQUEST_TIMEOUT = 10


def fetch_mesh_live(mesh_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch MeSH descriptor from NLM E-utilities API.

    Uses esum mary to fetch:
    - Descriptor Name (MeSH term)
    - Tree Numbers (hierarchical codes)

    Args:
        mesh_id: MeSH Descriptor ID (e.g., 'D008175' or just 'C04.557')

    Returns:
        Dict with MeSH data, or None on failure
    """
    import re

    # MeSH IDs can be:
    # - Descriptor IDs (D######)
    # - Supplementary Concept IDs (C######)
    # - Tree numbers (e.g., C04.557.470)

    # Check if it's a tree number (letter + 2 digits + optional .### segments)
    # Tree numbers: A01, C04, C04.557, C04.557.470
    # NOT tree numbers: D009369 (6 digits), C000656388 (7+ digits)
    is_tree_number = bool(re.match(r'^[A-Z]\d{2}(\.\d{3})*$', mesh_id))

    if is_tree_number:
        # Tree numbers can't be fetched via API - return minimal entry
        return {
            "id": mesh_id,
            "label": mesh_id,  # Fallback to ID
            "tree_numbers": [mesh_id],
            "source": "mesh",
            "is_tree_number": True
        }

    # Only fetch via API for descriptor IDs (D######) and supplementary concept IDs (C######)
    if not mesh_id.startswith('D') and not (mesh_id.startswith('C') and mesh_id[1:].isdigit()):
        # Unknown format - return as-is
        return {
            "id": mesh_id,
            "label": mesh_id,
            "tree_numbers": [],
            "source": "mesh",
            "is_fallback": True
        }

    try:
        logger.debug(f"Fetching MeSH descriptor from NLM: {mesh_id}")

        # Use esummary to get MeSH descriptor summary
        # Database: mesh
        url = f"{EUTILS_BASE_URL}/esummary.fcgi"
        params = {
            "db": "mesh",
            "id": mesh_id,
            "retmode": "xml"
        }

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        # Handle 404 or errors
        if response.status_code == 404:
            logger.warning(f"MeSH descriptor not found: {mesh_id}")
            return None

        response.raise_for_status()

        # Parse XML response
        root = ET.fromstring(response.content)

        # Check for errors
        error = root.find(".//ERROR")
        if error is not None:
            logger.warning(f"MeSH API error for {mesh_id}: {error.text}")
            return None

        # Extract descriptor name
        ds_meshterms = root.find(".//DS_MeshTerms")
        descriptor_name = None

        if ds_meshterms is not None:
            # DS_MeshTerms contains comma-separated terms
            # First term is usually the main descriptor
            terms = ds_meshterms.text
            if terms:
                descriptor_name = terms.split(',')[0].strip()

        # Fallback: try Item[@Name='DS_MeshTerms']
        if not descriptor_name:
            item = root.find(".//Item[@Name='DS_MeshTerms']")
            if item is not None and item.text:
                descriptor_name = item.text.split(',')[0].strip()

        # Extract tree numbers (if available in API response)
        # Note: E-utilities esummary may not return tree numbers
        # We may need to use a different approach or accept that tree numbers
        # will be fetched separately if needed

        tree_numbers = []
        # Try to find tree number elements
        for item in root.findall(".//Item[@Name='TreeNumber']"):
            if item.text:
                tree_numbers.append(item.text.strip())

        if not descriptor_name:
            logger.warning(f"Could not extract descriptor name for {mesh_id}")
            return None

        return {
            "id": mesh_id,
            "label": descriptor_name,
            "tree_numbers": tree_numbers if tree_numbers else [],
            "source": "mesh"
        }

    except requests.exceptions.Timeout:
        logger.error(f"MeSH API timeout for {mesh_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"MeSH API error for {mesh_id}: {e}")
        return None
    except ET.ParseError as e:
        logger.error(f"MeSH XML parse error for {mesh_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching MeSH {mesh_id}: {e}")
        return None


def get_mesh_label(cursor: Any, mesh_id: str, ttl_days: int = 90) -> Dict[str, Any]:
    """
    Get MeSH label (cached or live).

    Per Section 24B: Check cache first, fetch live on miss, fallback to ID on failure.
    TTL: 90 days (MeSH updates yearly).

    Args:
        cursor: Database cursor
        mesh_id: MeSH Descriptor ID or tree number
        ttl_days: Cache TTL (default: 90 days)

    Returns:
        Dict with MeSH data (always succeeds via fallback)
    """
    # Check if this looks like a MeSH ID
    # MeSH IDs: D######, C######, or tree numbers (e.g., C04.557.470)

    return cached_resolve_with_fallback(
        cursor=cursor,
        source=CacheSource.OPENTARGETS,  # Using OPENTARGETS cache source for now
        # TODO: Add MESH to CacheSource enum in future
        entity_id=mesh_id,
        resolver_fn=fetch_mesh_live,
        fallback_label=mesh_id,
        ttl_days=ttl_days
    )


def batch_resolve_mesh(cursor: Any, mesh_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch resolve multiple MeSH descriptors.

    Args:
        cursor: Database cursor
        mesh_ids: List of MeSH IDs

    Returns:
        Dict mapping mesh_id → mesh data
    """
    results = {}

    for mesh_id in mesh_ids:
        results[mesh_id] = get_mesh_label(cursor, mesh_id)

    return results


def validate_mesh_id(mesh_id: str) -> bool:
    """
    Validate MeSH ID format.

    MeSH IDs can be:
    - Descriptor IDs: D followed by 6 digits (e.g., 'D008175')
    - Supplementary Concept IDs: C followed by 6 digits (e.g., 'C000656388')
    - Tree numbers: Hierarchical codes (e.g., 'C04.557.470')

    Args:
        mesh_id: MeSH ID to validate

    Returns:
        True if valid MeSH ID format
    """
    import re

    # Descriptor ID: D followed by 6 digits
    if re.match(r'^D\d{6}$', mesh_id):
        return True

    # Supplementary Concept ID: C followed by 6+ digits
    if re.match(r'^C\d{6,}$', mesh_id):
        return True

    # Tree number: Letter followed by numbers and dots
    # Examples: C04, C04.557, C04.557.470
    if re.match(r'^[A-Z]\d{2}(\.\d{3})*$', mesh_id):
        return True

    return False


def extract_tree_prefix(tree_number: str, max_levels: int = 2) -> str:
    """
    Extract tree prefix from MeSH tree number for TA mapping.

    Examples:
    - 'C04.557.470' → 'C04' (level 1)
    - 'C04.557.470' → 'C04.557' (level 2)

    Args:
        tree_number: MeSH tree number (e.g., 'C04.557.470')
        max_levels: Maximum tree depth to extract (default: 2)

    Returns:
        Tree prefix string
    """
    parts = tree_number.split('.')

    # Take up to max_levels parts (level 1 = first part only, level 2 = first two parts)
    prefix_parts = parts[:min(max_levels, len(parts))]

    return '.'.join(prefix_parts)


def get_mesh_tree_prefixes(tree_numbers: List[str], max_levels: int = 2) -> List[str]:
    """
    Get all tree prefixes from a list of tree numbers.

    Used for TA mapping.

    Args:
        tree_numbers: List of MeSH tree numbers
        max_levels: Maximum tree depth

    Returns:
        List of unique tree prefixes
    """
    prefixes = set()

    for tree_number in tree_numbers:
        for level in range(1, max_levels + 1):
            prefix = extract_tree_prefix(tree_number, level)
            prefixes.add(prefix)

    return sorted(prefixes)
