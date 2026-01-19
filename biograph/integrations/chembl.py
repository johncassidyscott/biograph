"""
BioGraph MVP v8.2 - ChEMBL Integration

Per Section 23C.2 of the spec, this module provides comprehensive ChEMBL integration.

ChEMBL is the MOST IMPORTANT integration for BioGraph as it provides:
- Drug-target interactions with binding affinity data
- Mechanism of action annotations
- Drug indications (disease associations)
- Clinical trial phase information
- Bioactivity data from assays

Storage Strategy (Thin Durable Core):
- Store ONLY ChEMBL IDs locally (as attribute in drug_program)
- Resolve labels LIVE via REST API
- Cache results in lookup_cache (TTL: 30 days)
- Fallback to ID on fetch failure

Evidence Creation:
- ChEMBL data CAN create assertions (Contract C allows ChEMBL)
- Evidence source_system = 'chembl'
- License = 'CC_BY_SA_3_0' (ChEMBL open data)

This module provides:
1. Molecule label resolution (presentation layer)
2. Drug-target interaction fetching
3. Mechanism of action fetching
4. Drug indication fetching
5. Evidence and assertion creation from ChEMBL data
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import logging
import re
import json
import requests
from psycopg.types.json import Json
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
REQUEST_TIMEOUT = 15

# ChEMBL license (CC BY-SA 3.0) - valid for evidence creation
CHEMBL_LICENSE = "CC-BY-SA-3.0"


class ActivityType(str, Enum):
    """ChEMBL activity types (standardized)."""
    IC50 = "IC50"           # Half maximal inhibitory concentration
    EC50 = "EC50"           # Half maximal effective concentration
    Ki = "Ki"               # Inhibitor constant
    Kd = "Kd"               # Dissociation constant
    POTENCY = "Potency"     # Potency measure
    ACTIVITY = "Activity"   # General activity


class MechanismAction(str, Enum):
    """Common mechanism of action types."""
    INHIBITOR = "INHIBITOR"
    AGONIST = "AGONIST"
    ANTAGONIST = "ANTAGONIST"
    MODULATOR = "MODULATOR"
    BLOCKER = "BLOCKER"
    ACTIVATOR = "ACTIVATOR"
    OPENER = "OPENER"
    BINDING_AGENT = "BINDING_AGENT"
    OTHER = "OTHER"


@dataclass
class DrugTargetInteraction:
    """Represents a drug-target interaction from ChEMBL."""
    chembl_id: str
    drug_name: str
    target_chembl_id: str
    target_name: str
    target_type: str  # e.g., 'SINGLE PROTEIN', 'PROTEIN COMPLEX'
    target_uniprot_id: Optional[str]
    mechanism_of_action: Optional[str]
    action_type: Optional[str]
    activity_type: Optional[str]
    activity_value: Optional[float]
    activity_units: Optional[str]
    assay_chembl_id: Optional[str]
    assay_description: Optional[str]
    document_chembl_id: Optional[str]
    reference: Optional[str]
    max_phase: Optional[int]


@dataclass
class DrugIndication:
    """Represents a drug indication (disease association) from ChEMBL."""
    chembl_id: str
    drug_name: str
    indication_name: str
    mesh_id: Optional[str]
    efo_id: Optional[str]
    max_phase_for_ind: int
    indication_refs: List[str]


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
    return bool(re.match(r'^CHEMBL\d+$', chembl_id))


# ============================================================================
# DRUG-TARGET INTERACTIONS
# ============================================================================

def fetch_drug_mechanisms(chembl_id: str) -> List[Dict[str, Any]]:
    """
    Fetch drug mechanisms of action from ChEMBL.

    Args:
        chembl_id: ChEMBL molecule ID

    Returns:
        List of mechanism dictionaries
    """
    url = f"{CHEMBL_REST_URL}/mechanism.json"
    params = {
        "molecule_chembl_id": chembl_id,
        "limit": 100
    }

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 404:
            return []

        response.raise_for_status()
        data = response.json()

        mechanisms = []
        for mech in data.get("mechanisms", []):
            mechanisms.append({
                "target_chembl_id": mech.get("target_chembl_id"),
                "target_name": mech.get("target_name"),
                "mechanism_of_action": mech.get("mechanism_of_action"),
                "action_type": mech.get("action_type"),
                "mechanism_refs": mech.get("mechanism_refs", []),
                "max_phase": mech.get("max_phase"),
                "molecule_chembl_id": mech.get("molecule_chembl_id"),
            })

        return mechanisms

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching mechanisms for {chembl_id}: {e}")
        return []


def fetch_drug_targets(chembl_id: str) -> List[Dict[str, Any]]:
    """
    Fetch drug-target associations from ChEMBL activities.

    Gets high-confidence activity data (IC50, Ki, Kd, EC50).

    Args:
        chembl_id: ChEMBL molecule ID

    Returns:
        List of target dictionaries with activity data
    """
    url = f"{CHEMBL_REST_URL}/activity.json"
    params = {
        "molecule_chembl_id": chembl_id,
        "standard_type__in": "IC50,Ki,Kd,EC50",  # High-confidence activity types
        "pchembl_value__isnull": "false",  # Only with pChEMBL values
        "limit": 100
    }

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 404:
            return []

        response.raise_for_status()
        data = response.json()

        # Group by target to get best activity per target
        targets_by_id = {}

        for activity in data.get("activities", []):
            target_id = activity.get("target_chembl_id")
            if not target_id:
                continue

            pchembl = activity.get("pchembl_value")
            if pchembl is None:
                continue

            # Keep the best (highest pChEMBL) activity per target
            if target_id not in targets_by_id or pchembl > targets_by_id[target_id].get("pchembl_value", 0):
                targets_by_id[target_id] = {
                    "target_chembl_id": target_id,
                    "target_name": activity.get("target_pref_name"),
                    "target_type": activity.get("target_type"),
                    "activity_type": activity.get("standard_type"),
                    "activity_value": activity.get("standard_value"),
                    "activity_units": activity.get("standard_units"),
                    "pchembl_value": pchembl,
                    "assay_chembl_id": activity.get("assay_chembl_id"),
                    "assay_description": activity.get("assay_description"),
                    "document_chembl_id": activity.get("document_chembl_id"),
                }

        return list(targets_by_id.values())

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching targets for {chembl_id}: {e}")
        return []


def fetch_target_details(target_chembl_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch target details from ChEMBL.

    Args:
        target_chembl_id: ChEMBL target ID

    Returns:
        Target details dict or None
    """
    url = f"{CHEMBL_REST_URL}/target/{target_chembl_id}.json"

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        # Extract UniProt IDs from components
        uniprot_ids = []
        for component in data.get("target_components", []):
            for xref in component.get("target_component_xrefs", []):
                if xref.get("xref_src_db") == "UniProt":
                    uniprot_ids.append(xref.get("xref_id"))

        return {
            "target_chembl_id": target_chembl_id,
            "pref_name": data.get("pref_name"),
            "target_type": data.get("target_type"),
            "organism": data.get("organism"),
            "species_group_flag": data.get("species_group_flag"),
            "uniprot_ids": uniprot_ids,
            "gene_names": [c.get("component_synonym") for c in data.get("target_components", [])
                          if c.get("component_synonym")]
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching target {target_chembl_id}: {e}")
        return None


# ============================================================================
# DRUG INDICATIONS
# ============================================================================

def fetch_drug_indications(chembl_id: str) -> List[DrugIndication]:
    """
    Fetch drug indications (disease associations) from ChEMBL.

    Args:
        chembl_id: ChEMBL molecule ID

    Returns:
        List of DrugIndication objects
    """
    url = f"{CHEMBL_REST_URL}/drug_indication.json"
    params = {
        "molecule_chembl_id": chembl_id,
        "limit": 100
    }

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 404:
            return []

        response.raise_for_status()
        data = response.json()

        # Get molecule name for labeling
        mol_data = fetch_molecule_live(chembl_id)
        drug_name = mol_data.get("label", chembl_id) if mol_data else chembl_id

        indications = []
        for ind in data.get("drug_indications", []):
            # Extract references
            refs = []
            for ref in ind.get("indication_refs", []):
                refs.append(ref.get("ref_url", ""))

            indications.append(DrugIndication(
                chembl_id=chembl_id,
                drug_name=drug_name,
                indication_name=ind.get("mesh_heading") or ind.get("efo_term") or "Unknown",
                mesh_id=ind.get("mesh_id"),
                efo_id=ind.get("efo_id"),
                max_phase_for_ind=ind.get("max_phase_for_ind", 0),
                indication_refs=refs
            ))

        return indications

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching indications for {chembl_id}: {e}")
        return []


# ============================================================================
# COMPREHENSIVE DRUG DATA
# ============================================================================

def fetch_comprehensive_drug_data(chembl_id: str) -> Dict[str, Any]:
    """
    Fetch comprehensive drug data from ChEMBL.

    This is the main function for importing a drug's complete profile.

    Args:
        chembl_id: ChEMBL molecule ID

    Returns:
        Dict containing:
        - molecule: Basic molecule info
        - mechanisms: List of mechanism of action entries
        - targets: List of target interactions
        - indications: List of disease indications
    """
    if not validate_chembl_id(chembl_id):
        raise ValueError(f"Invalid ChEMBL ID: {chembl_id}")

    logger.info(f"Fetching comprehensive data for {chembl_id}")

    # Fetch all data in parallel would be ideal, but for simplicity do sequential
    molecule = fetch_molecule_live(chembl_id)
    mechanisms = fetch_drug_mechanisms(chembl_id)
    targets = fetch_drug_targets(chembl_id)
    indications = fetch_drug_indications(chembl_id)

    return {
        "molecule": molecule,
        "mechanisms": mechanisms,
        "targets": targets,
        "indications": indications,
        "fetched_at": datetime.utcnow().isoformat()
    }


# ============================================================================
# EVIDENCE AND ASSERTION CREATION
# ============================================================================

def create_chembl_evidence(
    cursor: Any,
    chembl_id: str,
    source_record_type: str,  # 'mechanism', 'activity', 'indication'
    source_record_id: str,  # e.g., mechanism ID or activity ID
    snippet: str,
    batch_id: Optional[str] = None,
    document_chembl_id: Optional[str] = None
) -> int:
    """
    Create evidence record from ChEMBL data.

    Per Contract C, ChEMBL IS a valid source for creating assertions.

    Args:
        cursor: Database cursor
        chembl_id: ChEMBL molecule ID
        source_record_type: Type of ChEMBL record
        source_record_id: Specific record identifier
        snippet: Evidence snippet (max 200 chars)
        batch_id: Optional batch operation ID
        document_chembl_id: Optional ChEMBL document reference

    Returns:
        evidence_id
    """
    # Build URI
    uri = f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}"
    if document_chembl_id:
        uri = f"https://www.ebi.ac.uk/chembl/document_report_card/{document_chembl_id}"

    # Build full source record ID
    full_record_id = f"chembl:{chembl_id}:{source_record_type}:{source_record_id}"

    # Check for existing evidence
    cursor.execute("""
        SELECT evidence_id FROM evidence
        WHERE source_system = 'chembl' AND source_record_id = %s
    """, (full_record_id,))

    existing = cursor.fetchone()
    if existing:
        return existing[0]

    # Create new evidence
    cursor.execute("""
        INSERT INTO evidence (
            source_system, source_record_id, observed_at, license, uri, snippet, batch_id
        ) VALUES (
            'chembl', %s, NOW(), %s, %s, %s, %s
        )
        RETURNING evidence_id
    """, (full_record_id, CHEMBL_LICENSE, uri, snippet[:200], batch_id))

    return cursor.fetchone()[0]


def create_drug_target_assertion(
    cursor: Any,
    drug_program_id: str,
    target_id: str,
    evidence_id: int,
    mechanism: Optional[str] = None,
    action_type: Optional[str] = None
) -> int:
    """
    Create a drug-target assertion from ChEMBL data.

    Creates assertion: drug_program --targets--> target
    With optional mechanism metadata.

    Args:
        cursor: Database cursor
        drug_program_id: Drug program ID
        target_id: Target ID (OpenTargets ENSG ID preferred)
        evidence_id: Evidence ID to link
        mechanism: Optional mechanism of action
        action_type: Optional action type (INHIBITOR, AGONIST, etc.)

    Returns:
        assertion_id
    """
    # Determine predicate based on action type
    predicate = "targets"
    if action_type:
        action_lower = action_type.lower()
        if "inhibit" in action_lower:
            predicate = "inhibits"
        elif "agonist" in action_lower:
            predicate = "agonizes"
        elif "antagonist" in action_lower:
            predicate = "antagonizes"
        elif "modulator" in action_lower:
            predicate = "modulates"
        elif "blocker" in action_lower or "block" in action_lower:
            predicate = "blocks"

    # Check if assertion already exists
    cursor.execute("""
        SELECT assertion_id FROM assertion
        WHERE subject_type = 'drug_program'
          AND subject_id = %s
          AND predicate = %s
          AND object_type = 'target'
          AND object_id = %s
    """, (drug_program_id, predicate, target_id))

    existing = cursor.fetchone()
    if existing:
        assertion_id = existing[0]
        # Link evidence if not already linked
        cursor.execute("""
            INSERT INTO assertion_evidence (assertion_id, evidence_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (assertion_id, evidence_id))
        return assertion_id

    # Create new assertion
    cursor.execute("""
        INSERT INTO assertion (
            subject_type, subject_id, predicate, object_type, object_id, link_rationale_json
        ) VALUES (
            'drug_program', %s, %s, 'target', %s, %s
        )
        RETURNING assertion_id
    """, (
        drug_program_id,
        predicate,
        target_id,
        Json({"mechanism": mechanism, "action_type": action_type, "source": "chembl"})
    ))

    assertion_id = cursor.fetchone()[0]

    # Link evidence
    cursor.execute("""
        INSERT INTO assertion_evidence (assertion_id, evidence_id)
        VALUES (%s, %s)
    """, (assertion_id, evidence_id))

    return assertion_id


def create_drug_indication_assertion(
    cursor: Any,
    drug_program_id: str,
    disease_id: str,
    evidence_id: int,
    max_phase: int
) -> int:
    """
    Create a drug-indication assertion from ChEMBL data.

    Creates assertion: drug_program --indicated_for--> disease

    Args:
        cursor: Database cursor
        drug_program_id: Drug program ID
        disease_id: Disease ID (EFO or MONDO preferred)
        evidence_id: Evidence ID to link
        max_phase: Maximum clinical trial phase

    Returns:
        assertion_id
    """
    # Predicate indicates strength
    if max_phase >= 4:
        predicate = "approved_for"
    elif max_phase >= 3:
        predicate = "in_phase3_for"
    elif max_phase >= 2:
        predicate = "in_phase2_for"
    elif max_phase >= 1:
        predicate = "in_phase1_for"
    else:
        predicate = "indicated_for"

    # Check if assertion exists
    cursor.execute("""
        SELECT assertion_id FROM assertion
        WHERE subject_type = 'drug_program'
          AND subject_id = %s
          AND object_type = 'disease'
          AND object_id = %s
    """, (drug_program_id, disease_id))

    existing = cursor.fetchone()
    if existing:
        assertion_id = existing[0]
        # Update predicate if phase is higher
        cursor.execute("""
            UPDATE assertion SET predicate = %s, link_rationale_json = %s
            WHERE assertion_id = %s
              AND COALESCE((link_rationale_json->>'max_phase')::int, 0) < %s
        """, (predicate, Json({"max_phase": max_phase, "source": "chembl"}), assertion_id, max_phase))
        # Link evidence
        cursor.execute("""
            INSERT INTO assertion_evidence (assertion_id, evidence_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (assertion_id, evidence_id))
        return assertion_id

    # Create new assertion
    cursor.execute("""
        INSERT INTO assertion (
            subject_type, subject_id, predicate, object_type, object_id, link_rationale_json
        ) VALUES (
            'drug_program', %s, %s, 'disease', %s, %s
        )
        RETURNING assertion_id
    """, (
        drug_program_id,
        predicate,
        disease_id,
        Json({"max_phase": max_phase, "source": "chembl"})
    ))

    assertion_id = cursor.fetchone()[0]

    # Link evidence
    cursor.execute("""
        INSERT INTO assertion_evidence (assertion_id, evidence_id)
        VALUES (%s, %s)
    """, (assertion_id, evidence_id))

    return assertion_id


# ============================================================================
# IMPORT HELPERS
# ============================================================================

def import_chembl_drug(
    cursor: Any,
    chembl_id: str,
    issuer_id: str,
    batch_id: Optional[str] = None,
    create_targets: bool = True,
    create_diseases: bool = True
) -> Dict[str, Any]:
    """
    Import a drug from ChEMBL into BioGraph.

    This is the main import function that:
    1. Fetches comprehensive ChEMBL data
    2. Creates or updates drug_program
    3. Creates target entities (if requested)
    4. Creates disease entities (if requested)
    5. Creates evidence and assertions

    Args:
        cursor: Database cursor
        chembl_id: ChEMBL molecule ID
        issuer_id: Issuer ID to associate the drug with
        batch_id: Optional batch operation ID
        create_targets: Whether to create target entities
        create_diseases: Whether to create disease entities

    Returns:
        Dict with import statistics
    """
    stats = {
        "chembl_id": chembl_id,
        "drug_program_id": None,
        "targets_created": 0,
        "diseases_created": 0,
        "evidence_created": 0,
        "assertions_created": 0,
        "errors": []
    }

    try:
        # Fetch comprehensive data
        data = fetch_comprehensive_drug_data(chembl_id)

        if not data.get("molecule"):
            stats["errors"].append(f"Molecule not found: {chembl_id}")
            return stats

        molecule = data["molecule"]

        # Create or update drug_program
        drug_name = molecule.get("label", chembl_id)
        slug = re.sub(r'[^a-z0-9]+', '-', drug_name.lower()).strip('-')
        drug_program_id = f"CIK:{issuer_id.replace('ISS_', '')}:PROG:{slug}"

        cursor.execute("""
            INSERT INTO drug_program (drug_program_id, issuer_id, slug, name, attributes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (drug_program_id) DO UPDATE SET
                name = EXCLUDED.name,
                attributes = drug_program.attributes || EXCLUDED.attributes
            RETURNING drug_program_id
        """, (
            drug_program_id,
            issuer_id,
            slug,
            drug_name,
            Json({
                "chembl_id": chembl_id,
                "molecule_type": molecule.get("molecule_type"),
                "max_phase": molecule.get("max_phase"),
                "pref_name": molecule.get("pref_name")
            })
        ))

        stats["drug_program_id"] = cursor.fetchone()[0]

        # Process mechanisms and create target assertions
        for mech in data.get("mechanisms", []):
            target_chembl_id = mech.get("target_chembl_id")
            if not target_chembl_id:
                continue

            try:
                # Create evidence
                snippet = f"{drug_name} {mech.get('action_type', 'targets')} {mech.get('target_name', target_chembl_id)}"
                evidence_id = create_chembl_evidence(
                    cursor, chembl_id, "mechanism", target_chembl_id,
                    snippet, batch_id
                )
                stats["evidence_created"] += 1

                # Get or create target (use target_chembl_id as target_id for now)
                target_id = target_chembl_id
                if create_targets:
                    cursor.execute("""
                        INSERT INTO target (target_id, name, attributes)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (target_id) DO NOTHING
                    """, (target_id, mech.get("target_name", target_id), Json({"chembl_id": target_chembl_id})))
                    stats["targets_created"] += 1

                # Create assertion
                create_drug_target_assertion(
                    cursor, drug_program_id, target_id, evidence_id,
                    mech.get("mechanism_of_action"),
                    mech.get("action_type")
                )
                stats["assertions_created"] += 1

            except Exception as e:
                stats["errors"].append(f"Error processing mechanism {target_chembl_id}: {e}")

        # Process activity-based targets
        for target in data.get("targets", []):
            target_chembl_id = target.get("target_chembl_id")
            if not target_chembl_id:
                continue

            try:
                # Create evidence
                activity_str = f"{target.get('activity_type', '')} {target.get('activity_value', '')} {target.get('activity_units', '')}"
                snippet = f"{drug_name} has {activity_str.strip()} against {target.get('target_name', target_chembl_id)}"
                evidence_id = create_chembl_evidence(
                    cursor, chembl_id, "activity", target_chembl_id,
                    snippet, batch_id, target.get("document_chembl_id")
                )
                stats["evidence_created"] += 1

                # Get or create target
                target_id = target_chembl_id
                if create_targets:
                    cursor.execute("""
                        INSERT INTO target (target_id, name, attributes)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (target_id) DO NOTHING
                    """, (target_id, target.get("target_name", target_id), Json({
                        "chembl_id": target_chembl_id,
                        "target_type": target.get("target_type")
                    })))

                # Create assertion if not already from mechanism
                cursor.execute("""
                    SELECT 1 FROM assertion
                    WHERE subject_id = %s AND object_id = %s
                """, (drug_program_id, target_id))

                if not cursor.fetchone():
                    create_drug_target_assertion(
                        cursor, drug_program_id, target_id, evidence_id
                    )
                    stats["assertions_created"] += 1

            except Exception as e:
                stats["errors"].append(f"Error processing target {target_chembl_id}: {e}")

        # Process indications
        for indication in data.get("indications", []):
            try:
                # Prefer EFO ID, fallback to MeSH
                disease_id = indication.efo_id or indication.mesh_id
                if not disease_id:
                    continue

                # Create evidence
                snippet = f"{drug_name} indicated for {indication.indication_name} (Phase {indication.max_phase_for_ind})"
                evidence_id = create_chembl_evidence(
                    cursor, chembl_id, "indication", disease_id,
                    snippet, batch_id
                )
                stats["evidence_created"] += 1

                # Get or create disease
                if create_diseases:
                    cursor.execute("""
                        INSERT INTO disease (disease_id, name, attributes)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (disease_id) DO NOTHING
                    """, (disease_id, indication.indication_name, Json({
                        "mesh_id": indication.mesh_id,
                        "efo_id": indication.efo_id
                    })))
                    stats["diseases_created"] += 1

                # Create assertion
                create_drug_indication_assertion(
                    cursor, drug_program_id, disease_id, evidence_id,
                    indication.max_phase_for_ind
                )
                stats["assertions_created"] += 1

            except Exception as e:
                stats["errors"].append(f"Error processing indication {indication.indication_name}: {e}")

        logger.info(f"Imported {chembl_id}: {stats['assertions_created']} assertions created")

    except Exception as e:
        logger.error(f"Error importing {chembl_id}: {e}")
        stats["errors"].append(str(e))

    return stats


def search_chembl_molecules(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Search for molecules in ChEMBL.

    Args:
        query: Search query (drug name, synonyms, etc.)
        limit: Maximum results to return

    Returns:
        List of molecule summaries
    """
    url = f"{CHEMBL_REST_URL}/molecule/search.json"
    params = {
        "q": query,
        "limit": limit
    }

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        results = []
        for mol in data.get("molecules", []):
            results.append({
                "chembl_id": mol.get("molecule_chembl_id"),
                "pref_name": mol.get("pref_name"),
                "molecule_type": mol.get("molecule_type"),
                "max_phase": mol.get("max_phase"),
                "first_approval": mol.get("first_approval"),
                "oral": mol.get("oral"),
                "parenteral": mol.get("parenteral"),
                "topical": mol.get("topical")
            })

        return results

    except requests.exceptions.RequestException as e:
        logger.error(f"Error searching ChEMBL for '{query}': {e}")
        return []
