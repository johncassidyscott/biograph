#!/usr/bin/env python3
"""
Assertion Helper - Evidence-First Edge Creation

Provides utilities for creating assertions with evidence mediation.

Per v8.1 spec:
- Every assertion MUST have >=1 evidence record
- Confidence is computed automatically from evidence + rubric
- Assertions are effective-dated (asserted_at, retracted_at)
"""
from typing import Optional, Dict, List
from datetime import datetime, date
from ..app.db import get_conn

def create_evidence(
    source_system: str,
    source_record_id: str,
    license: str,
    observed_at: datetime,
    uri: Optional[str] = None,
    checksum: Optional[str] = None,
    snippet: Optional[str] = None,
    base_confidence: Optional[float] = None
) -> int:
    """
    Create an evidence record.

    Args:
        source_system: e.g., 'sec_edgar', 'opentargets', 'chembl'
        source_record_id: External ID in source system
        license: MUST be in license_allowlist (validated by trigger)
        observed_at: When fact was observed in source
        uri: Link to source
        checksum: Content hash
        snippet: Optional excerpt
        base_confidence: Source-specific confidence score

    Returns:
        evidence_id

    Raises:
        Exception if license not in allowlist (trigger enforced)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO evidence
                (source_system, source_record_id, observed_at, license, uri,
                 checksum, snippet, base_confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_system, source_record_id)
                DO UPDATE SET
                    observed_at = EXCLUDED.observed_at,
                    uri = EXCLUDED.uri,
                    checksum = EXCLUDED.checksum,
                    snippet = EXCLUDED.snippet,
                    base_confidence = EXCLUDED.base_confidence
                RETURNING evidence_id
            """, (
                source_system, source_record_id, observed_at, license,
                uri, checksum, snippet, base_confidence
            ))

            evidence_id = cur.fetchone()['evidence_id']
            conn.commit()

            return evidence_id

def create_assertion(
    subject_type: str,
    subject_id: str,
    predicate: str,
    object_type: str,
    object_id: str,
    evidence_ids: List[int],
    asserted_at: Optional[datetime] = None
) -> int:
    """
    Create an assertion with evidence.

    Per spec: An assertion is INVALID without evidence.

    Args:
        subject_type: e.g., 'issuer', 'drug_program', 'target'
        subject_id: ID of subject entity
        predicate: e.g., 'develops', 'targets', 'treats'
        object_type: e.g., 'drug_program', 'target', 'disease'
        object_id: ID of object entity
        evidence_ids: List of evidence_id (must be non-empty)
        asserted_at: When assertion became valid (default: now)

    Returns:
        assertion_id

    Raises:
        ValueError if evidence_ids is empty
    """
    if not evidence_ids:
        raise ValueError("Cannot create assertion without evidence")

    if asserted_at is None:
        asserted_at = datetime.now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Create assertion
            cur.execute("""
                INSERT INTO assertion
                (subject_type, subject_id, predicate, object_type, object_id, asserted_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING assertion_id
            """, (subject_type, subject_id, predicate, object_type, object_id, asserted_at))

            assertion_id = cur.fetchone()['assertion_id']

            # Link evidence
            for evidence_id in evidence_ids:
                cur.execute("""
                    INSERT INTO assertion_evidence (assertion_id, evidence_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (assertion_id, evidence_id))

            conn.commit()

            # Confidence is computed automatically by trigger
            return assertion_id

def retract_assertion(assertion_id: int, retracted_at: Optional[datetime] = None) -> bool:
    """
    Retract (invalidate) an assertion.

    Per spec: Assertions are effective-dated with retracted_at.

    Args:
        assertion_id: Assertion to retract
        retracted_at: When retraction became effective (default: now)

    Returns:
        True if successful
    """
    if retracted_at is None:
        retracted_at = datetime.now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE assertion
                SET retracted_at = %s,
                    updated_at = NOW()
                WHERE assertion_id = %s
                RETURNING assertion_id
            """, (retracted_at, assertion_id))

            result = cur.fetchone()
            conn.commit()

            return result is not None

def create_issuer_drug_assertion(
    issuer_id: str,
    drug_program_id: str,
    relationship: str,
    evidence_ids: List[int],
    asserted_at: Optional[datetime] = None
) -> int:
    """Create issuer → drug_program assertion."""
    return create_assertion(
        'issuer', issuer_id,
        relationship,
        'drug_program', drug_program_id,
        evidence_ids, asserted_at
    )

def create_drug_target_assertion(
    drug_program_id: str,
    target_id: str,
    interaction_type: str,
    evidence_ids: List[int],
    asserted_at: Optional[datetime] = None
) -> int:
    """Create drug_program → target assertion."""
    return create_assertion(
        'drug_program', drug_program_id,
        interaction_type,
        'target', target_id,
        evidence_ids, asserted_at
    )

def create_target_disease_assertion(
    target_id: str,
    disease_id: str,
    evidence_ids: List[int],
    asserted_at: Optional[datetime] = None
) -> int:
    """Create target → disease assertion."""
    return create_assertion(
        'target', target_id,
        'associated_with',
        'disease', disease_id,
        evidence_ids, asserted_at
    )

def create_issuer_location_assertion(
    issuer_id: str,
    location_id: str,
    location_type: str,
    evidence_ids: List[int],
    asserted_at: Optional[datetime] = None
) -> int:
    """Create issuer → location assertion."""
    return create_assertion(
        'issuer', issuer_id,
        location_type,
        'location', location_id,
        evidence_ids, asserted_at
    )

def get_assertion_evidence_chain(assertion_id: int) -> List[Dict]:
    """
    Get full evidence chain for an assertion (for audit).

    Returns list of evidence records with details.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.*
                FROM assertion_evidence ae
                JOIN evidence e ON ae.evidence_id = e.evidence_id
                WHERE ae.assertion_id = %s
                ORDER BY e.observed_at DESC
            """, (assertion_id,))

            return cur.fetchall()
