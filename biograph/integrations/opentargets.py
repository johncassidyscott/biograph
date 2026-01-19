"""
BioGraph MVP v8.2 - OpenTargets Resolver

Per Section 23C.1 of the spec, this module resolves target and disease labels
from OpenTargets Platform API.

Storage Strategy (Thin Durable Core):
- Store ONLY stable IDs locally (Ensembl gene IDs, EFO/MONDO disease IDs)
- Resolve labels LIVE via GraphQL API
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

# OpenTargets Platform GraphQL API
OPENTARGETS_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"

# Query timeout (seconds)
REQUEST_TIMEOUT = 10


def fetch_target_live(target_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch target label from OpenTargets Platform API.

    Uses GraphQL to fetch:
    - approvedSymbol (gene symbol)
    - approvedName (full name)
    - biotype

    Args:
        target_id: Ensembl gene ID (e.g., 'ENSG00000141510')

    Returns:
        Dict with target data, or None on failure
    """
    query = """
    query Target($ensemblId: String!) {
      target(ensemblId: $ensemblId) {
        id
        approvedSymbol
        approvedName
        biotype
      }
    }
    """

    variables = {"ensemblId": target_id}

    try:
        logger.debug(f"Fetching target from OpenTargets: {target_id}")

        response = requests.post(
            OPENTARGETS_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            logger.warning(f"OpenTargets GraphQL errors for {target_id}: {data['errors']}")
            return None

        target = data.get("data", {}).get("target")

        if not target:
            logger.warning(f"Target not found in OpenTargets: {target_id}")
            return None

        # Extract fields
        return {
            "id": target_id,
            "label": target.get("approvedSymbol") or target.get("approvedName") or target_id,
            "gene_symbol": target.get("approvedSymbol"),
            "name": target.get("approvedName"),
            "biotype": target.get("biotype"),
            "source": "opentargets"
        }

    except requests.exceptions.Timeout:
        logger.error(f"OpenTargets API timeout for target {target_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenTargets API error for target {target_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching target {target_id}: {e}")
        return None


def fetch_disease_live(disease_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch disease label from OpenTargets Platform API.

    Uses GraphQL to fetch:
    - name (disease name)
    - therapeuticAreas (list of therapeutic area names)

    Args:
        disease_id: EFO or MONDO ID (e.g., 'EFO_0000400', 'MONDO_0007254')

    Returns:
        Dict with disease data, or None on failure
    """
    query = """
    query Disease($efoId: String!) {
      disease(efoId: $efoId) {
        id
        name
        therapeuticAreas {
          id
          name
        }
      }
    }
    """

    variables = {"efoId": disease_id}

    try:
        logger.debug(f"Fetching disease from OpenTargets: {disease_id}")

        response = requests.post(
            OPENTARGETS_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            logger.warning(f"OpenTargets GraphQL errors for {disease_id}: {data['errors']}")
            return None

        disease = data.get("data", {}).get("disease")

        if not disease:
            logger.warning(f"Disease not found in OpenTargets: {disease_id}")
            return None

        # Extract therapeutic areas
        therapeutic_areas = disease.get("therapeuticAreas", [])
        therapeutic_area_names = [ta.get("name") for ta in therapeutic_areas if ta.get("name")]

        return {
            "id": disease_id,
            "label": disease.get("name") or disease_id,
            "name": disease.get("name"),
            "therapeutic_areas": therapeutic_area_names,
            "source": "opentargets"
        }

    except requests.exceptions.Timeout:
        logger.error(f"OpenTargets API timeout for disease {disease_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenTargets API error for disease {disease_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching disease {disease_id}: {e}")
        return None


def get_target_label(cursor: Any, target_id: str, ttl_days: int = 30) -> Dict[str, Any]:
    """
    Get target label (cached or live).

    Per Section 23H: Check cache first, fetch live on miss, fallback to ID on failure.

    Args:
        cursor: Database cursor
        target_id: Ensembl gene ID
        ttl_days: Cache TTL (default: 30 days)

    Returns:
        Dict with target data (always succeeds via fallback)
    """
    return cached_resolve_with_fallback(
        cursor=cursor,
        source=CacheSource.OPENTARGETS,
        entity_id=target_id,
        resolver_fn=fetch_target_live,
        fallback_label=target_id,
        ttl_days=ttl_days
    )


def get_disease_label(cursor: Any, disease_id: str, ttl_days: int = 30) -> Dict[str, Any]:
    """
    Get disease label (cached or live).

    Per Section 23H: Check cache first, fetch live on miss, fallback to ID on failure.

    Args:
        cursor: Database cursor
        disease_id: EFO or MONDO ID
        ttl_days: Cache TTL (default: 30 days)

    Returns:
        Dict with disease data (always succeeds via fallback)
    """
    return cached_resolve_with_fallback(
        cursor=cursor,
        source=CacheSource.OPENTARGETS,
        entity_id=disease_id,
        resolver_fn=fetch_disease_live,
        fallback_label=disease_id,
        ttl_days=ttl_days
    )


def batch_resolve_targets(cursor: Any, target_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch resolve multiple targets.

    Useful for resolving all targets in an explanation at once.

    Args:
        cursor: Database cursor
        target_ids: List of Ensembl gene IDs

    Returns:
        Dict mapping target_id → target data
    """
    results = {}

    for target_id in target_ids:
        results[target_id] = get_target_label(cursor, target_id)

    return results


def batch_resolve_diseases(cursor: Any, disease_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch resolve multiple diseases.

    Useful for resolving all diseases in an explanation at once.

    Args:
        cursor: Database cursor
        disease_ids: List of EFO/MONDO IDs

    Returns:
        Dict mapping disease_id → disease data
    """
    results = {}

    for disease_id in disease_ids:
        results[disease_id] = get_disease_label(cursor, disease_id)

    return results


def validate_target_id(target_id: str) -> bool:
    """
    Validate target ID format.

    OpenTargets uses Ensembl gene IDs (format: ENSG[0-9]{11}).

    Args:
        target_id: Target ID to validate

    Returns:
        True if valid Ensembl ID format
    """
    import re
    return bool(re.match(r'^ENSG\d{11}$', target_id))


def validate_disease_id(disease_id: str) -> bool:
    """
    Validate disease ID format.

    OpenTargets uses EFO or MONDO IDs (format: EFO_[0-9]+ or MONDO_[0-9]+).

    Args:
        disease_id: Disease ID to validate

    Returns:
        True if valid EFO or MONDO ID format
    """
    import re
    return bool(re.match(r'^(EFO|MONDO)_\d+$', disease_id))
