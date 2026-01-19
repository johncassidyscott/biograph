"""
ER Dedupe Runner for BioGraph MVP

Stub implementation for PR0. Full implementation in PR5.
"""
from typing import Any


def find_duplicates_for_issuer(cursor: Any, issuer_id: str) -> None:
    """
    Find duplicate drug_program candidates within a single issuer.

    Per Contract F: ER operates within issuer ONLY. Never crosses issuers.

    Args:
        cursor: Database cursor
        issuer_id: Issuer ID to process

    Creates:
        - duplicate_suggestion records (status='pending')
        - Features stored in features_json

    Does NOT:
        - Merge entities
        - Compare across issuers
        - Auto-accept suggestions
    """
    # Stub implementation for PR0
    # Full implementation in PR5 with Dedupe library

    # Get all drug_programs for this issuer
    cursor.execute("""
        SELECT drug_program_id, name, slug
        FROM drug_program
        WHERE issuer_id = %s
        ORDER BY drug_program_id
    """, (issuer_id,))

    programs = cursor.fetchall()

    # Stub: No duplicates found (full implementation will use Dedupe)
    # In PR5, this will compute pairwise similarities and create suggestions
    pass
