"""
BioGraph MVP v8.2 - Therapeutic Area Mapping

Per Section 24C of the spec, this module maps diseases to Therapeutic Areas (TAs)
using MeSH tree numbers or EFO/MONDO IDs.

Therapeutic Area Taxonomy (8 Fixed Categories):
1. ONC (Oncology) — Cancer
2. IMM (Immunology) — Autoimmune, inflammation
3. CNS (Central Nervous System) — Neurology, psychiatry
4. CVM (Cardiovascular/Metabolic) — Heart, diabetes, obesity
5. ID (Infectious Disease) — Viral, bacterial, fungal
6. RARE (Rare Disease) — Orphan diseases
7. RES (Respiratory) — Lung, asthma, COPD
8. REN (Renal) — Kidney diseases

Mapping Strategy:
- Deterministic: Same input → Same TA
- Database-driven: Uses therapeutic_area_mapping table
- Multi-source: MeSH tree prefixes + EFO/MONDO IDs
- Priority-based: Highest priority match wins
- Fallback: 'UNKNOWN' if no match

This is presentation layer ONLY - does NOT affect linkage confidence.
"""

from typing import Any, Dict, Optional, List, Set
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TherapeuticArea(Enum):
    """Therapeutic Area codes (8 fixed categories)."""
    ONC = "ONC"    # Oncology
    IMM = "IMM"    # Immunology
    CNS = "CNS"    # Central Nervous System
    CVM = "CVM"    # Cardiovascular/Metabolic
    ID = "ID"      # Infectious Disease
    RARE = "RARE"  # Rare Disease
    RES = "RES"    # Respiratory
    REN = "REN"    # Renal
    UNKNOWN = "UNKNOWN"  # No mapping found


class TAMappingResult:
    """Result of TA mapping operation."""

    def __init__(
        self,
        primary_ta: TherapeuticArea,
        all_tas: List[TherapeuticArea],
        disease_id: Optional[str] = None,
        mesh_ids: Optional[List[str]] = None,
        mapping_source: str = "database"
    ):
        self.primary_ta = primary_ta
        self.all_tas = all_tas
        self.disease_id = disease_id
        self.mesh_ids = mesh_ids
        self.mapping_source = mapping_source

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "primary_ta": self.primary_ta.value,
            "all_tas": [ta.value for ta in self.all_tas],
            "disease_id": self.disease_id,
            "mesh_ids": self.mesh_ids,
            "mapping_source": self.mapping_source
        }

    def __repr__(self) -> str:
        return f"TAMappingResult(primary={self.primary_ta.value}, all={[ta.value for ta in self.all_tas]})"


def map_disease_to_ta(cursor: Any, disease_id: str) -> TAMappingResult:
    """
    Map disease to Therapeutic Area using EFO/MONDO ID.

    Uses database function get_disease_therapeutic_area() which:
    - Tries EFO mapping first (if disease_id starts with 'EFO_')
    - Falls back to MONDO mapping (if starts with 'MONDO_')
    - Returns NULL if no match

    Args:
        cursor: Database cursor
        disease_id: EFO or MONDO ID (e.g., 'EFO_0000400', 'MONDO_0007254')

    Returns:
        TAMappingResult with primary TA and all TAs
    """
    try:
        logger.debug(f"Mapping disease to TA: {disease_id}")

        # Call database function
        cursor.execute(
            "SELECT get_disease_therapeutic_area(%s)",
            (disease_id,)
        )

        result = cursor.fetchone()
        ta_code = result[0] if result and result[0] else None

        if ta_code:
            primary_ta = TherapeuticArea(ta_code)
            logger.debug(f"Mapped {disease_id} → {ta_code}")
        else:
            primary_ta = TherapeuticArea.UNKNOWN
            logger.debug(f"No TA mapping found for {disease_id}, using UNKNOWN")

        return TAMappingResult(
            primary_ta=primary_ta,
            all_tas=[primary_ta],
            disease_id=disease_id,
            mapping_source="ontology_id"
        )

    except Exception as e:
        logger.error(f"Error mapping disease {disease_id}: {e}")
        return TAMappingResult(
            primary_ta=TherapeuticArea.UNKNOWN,
            all_tas=[TherapeuticArea.UNKNOWN],
            disease_id=disease_id,
            mapping_source="error"
        )


def map_mesh_to_ta(cursor: Any, mesh_ids: List[str]) -> TAMappingResult:
    """
    Map MeSH IDs to Therapeutic Area using tree numbers.

    Uses database function map_mesh_to_ta() which:
    - Accepts array of MeSH IDs (descriptors or tree numbers)
    - Returns highest priority TA match
    - Returns NULL if no match

    Args:
        cursor: Database cursor
        mesh_ids: List of MeSH IDs (e.g., ['D008175', 'C04.557.470'])

    Returns:
        TAMappingResult with primary TA and all TAs
    """
    try:
        logger.debug(f"Mapping MeSH IDs to TA: {mesh_ids}")

        if not mesh_ids:
            logger.warning("Empty MeSH ID list provided")
            return TAMappingResult(
                primary_ta=TherapeuticArea.UNKNOWN,
                all_tas=[TherapeuticArea.UNKNOWN],
                mesh_ids=mesh_ids,
                mapping_source="mesh"
            )

        # Call database function
        cursor.execute(
            "SELECT map_mesh_to_ta(%s)",
            (mesh_ids,)
        )

        result = cursor.fetchone()
        ta_code = result[0] if result and result[0] else None

        if ta_code:
            primary_ta = TherapeuticArea(ta_code)
            logger.debug(f"Mapped MeSH {mesh_ids} → {ta_code}")
        else:
            primary_ta = TherapeuticArea.UNKNOWN
            logger.debug(f"No TA mapping found for MeSH {mesh_ids}, using UNKNOWN")

        return TAMappingResult(
            primary_ta=primary_ta,
            all_tas=[primary_ta],
            mesh_ids=mesh_ids,
            mapping_source="mesh"
        )

    except Exception as e:
        logger.error(f"Error mapping MeSH {mesh_ids}: {e}")
        return TAMappingResult(
            primary_ta=TherapeuticArea.UNKNOWN,
            all_tas=[TherapeuticArea.UNKNOWN],
            mesh_ids=mesh_ids,
            mapping_source="error"
        )


def get_all_mesh_ta_mappings(cursor: Any, mesh_ids: List[str]) -> List[TherapeuticArea]:
    """
    Get ALL matching TAs for a list of MeSH IDs (not just primary).

    Useful for showing all applicable TAs for a disease.

    Args:
        cursor: Database cursor
        mesh_ids: List of MeSH IDs

    Returns:
        List of all matching TAs (deduplicated, sorted)
    """
    try:
        if not mesh_ids:
            return [TherapeuticArea.UNKNOWN]

        # Query all matching TAs
        cursor.execute("""
            SELECT DISTINCT ta_code
            FROM therapeutic_area_mapping
            WHERE ontology_type = 'mesh_tree'
            AND EXISTS (
                SELECT 1 FROM unnest(%s::text[]) AS mesh_id
                WHERE mesh_id LIKE ontology_value
            )
            ORDER BY ta_code
        """, (mesh_ids,))

        rows = cursor.fetchall()

        if not rows:
            return [TherapeuticArea.UNKNOWN]

        tas = [TherapeuticArea(row[0]) for row in rows]
        logger.debug(f"Found {len(tas)} TAs for MeSH {mesh_ids}: {[ta.value for ta in tas]}")

        return tas

    except Exception as e:
        logger.error(f"Error getting all MeSH TAs for {mesh_ids}: {e}")
        return [TherapeuticArea.UNKNOWN]


def map_disease_comprehensive(
    cursor: Any,
    disease_id: Optional[str] = None,
    mesh_ids: Optional[List[str]] = None
) -> TAMappingResult:
    """
    Comprehensive disease → TA mapping using all available sources.

    Strategy:
    1. Try EFO/MONDO ID mapping first (if disease_id provided)
    2. Fall back to MeSH mapping (if mesh_ids provided)
    3. Return UNKNOWN if no match

    Args:
        cursor: Database cursor
        disease_id: Optional EFO/MONDO ID
        mesh_ids: Optional list of MeSH IDs

    Returns:
        TAMappingResult with best available mapping
    """
    # Try ontology ID first
    if disease_id:
        result = map_disease_to_ta(cursor, disease_id)
        if result.primary_ta != TherapeuticArea.UNKNOWN:
            # Add MeSH info if available
            result.mesh_ids = mesh_ids
            return result

    # Fall back to MeSH
    if mesh_ids:
        result = map_mesh_to_ta(cursor, mesh_ids)
        result.disease_id = disease_id
        return result

    # No mapping possible
    logger.warning(f"No TA mapping sources for disease_id={disease_id}, mesh_ids={mesh_ids}")
    return TAMappingResult(
        primary_ta=TherapeuticArea.UNKNOWN,
        all_tas=[TherapeuticArea.UNKNOWN],
        disease_id=disease_id,
        mesh_ids=mesh_ids,
        mapping_source="none"
    )


def batch_map_diseases_to_ta(
    cursor: Any,
    disease_ids: List[str]
) -> Dict[str, TAMappingResult]:
    """
    Batch map multiple diseases to TAs.

    More efficient than calling map_disease_to_ta() individually.

    Args:
        cursor: Database cursor
        disease_ids: List of EFO/MONDO IDs

    Returns:
        Dict mapping disease_id → TAMappingResult
    """
    results = {}

    for disease_id in disease_ids:
        results[disease_id] = map_disease_to_ta(cursor, disease_id)

    return results


def get_ta_display_name(ta: TherapeuticArea) -> str:
    """
    Get human-readable display name for TA.

    Args:
        ta: TherapeuticArea enum value

    Returns:
        Display name string
    """
    display_names = {
        TherapeuticArea.ONC: "Oncology",
        TherapeuticArea.IMM: "Immunology",
        TherapeuticArea.CNS: "Central Nervous System",
        TherapeuticArea.CVM: "Cardiovascular/Metabolic",
        TherapeuticArea.ID: "Infectious Disease",
        TherapeuticArea.RARE: "Rare Disease",
        TherapeuticArea.RES: "Respiratory",
        TherapeuticArea.REN: "Renal",
        TherapeuticArea.UNKNOWN: "Unknown"
    }

    return display_names.get(ta, ta.value)


def get_ta_description(ta: TherapeuticArea) -> str:
    """
    Get detailed description for TA.

    Args:
        ta: TherapeuticArea enum value

    Returns:
        Description string
    """
    descriptions = {
        TherapeuticArea.ONC: "Cancer and neoplasms",
        TherapeuticArea.IMM: "Autoimmune diseases, inflammation, and immune disorders",
        TherapeuticArea.CNS: "Neurological and psychiatric conditions",
        TherapeuticArea.CVM: "Cardiovascular diseases, diabetes, and metabolic disorders",
        TherapeuticArea.ID: "Viral, bacterial, fungal, and parasitic infections",
        TherapeuticArea.RARE: "Orphan and rare diseases",
        TherapeuticArea.RES: "Respiratory diseases including asthma and COPD",
        TherapeuticArea.REN: "Kidney diseases and renal disorders",
        TherapeuticArea.UNKNOWN: "Therapeutic area could not be determined"
    }

    return descriptions.get(ta, ta.value)


def validate_ta_code(ta_code: str) -> bool:
    """
    Validate TA code format.

    Args:
        ta_code: TA code to validate

    Returns:
        True if valid TA code
    """
    try:
        TherapeuticArea(ta_code)
        return True
    except ValueError:
        return False


def get_all_tas() -> List[TherapeuticArea]:
    """
    Get list of all valid TAs (excluding UNKNOWN).

    Returns:
        List of TherapeuticArea enum values
    """
    return [
        TherapeuticArea.ONC,
        TherapeuticArea.IMM,
        TherapeuticArea.CNS,
        TherapeuticArea.CVM,
        TherapeuticArea.ID,
        TherapeuticArea.RARE,
        TherapeuticArea.RES,
        TherapeuticArea.REN
    ]


def get_ta_summary(cursor: Any) -> Dict[str, Any]:
    """
    Get summary statistics for TA mappings in database.

    Args:
        cursor: Database cursor

    Returns:
        Dict with TA mapping statistics
    """
    try:
        # Get count of mappings per TA
        cursor.execute("""
            SELECT ta_code, COUNT(*) as mapping_count
            FROM therapeutic_area_mapping
            GROUP BY ta_code
            ORDER BY ta_code
        """)

        ta_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Get total mappings
        cursor.execute("SELECT COUNT(*) FROM therapeutic_area_mapping")
        total_mappings = cursor.fetchone()[0]

        # Get count by ontology type
        cursor.execute("""
            SELECT ontology_type, COUNT(*) as count
            FROM therapeutic_area_mapping
            GROUP BY ontology_type
            ORDER BY ontology_type
        """)

        type_counts = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "total_mappings": total_mappings,
            "ta_counts": ta_counts,
            "ontology_type_counts": type_counts
        }

    except Exception as e:
        logger.error(f"Error getting TA summary: {e}")
        return {
            "total_mappings": 0,
            "ta_counts": {},
            "ontology_type_counts": {},
            "error": str(e)
        }
