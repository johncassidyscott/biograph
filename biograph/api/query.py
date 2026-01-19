"""
API Query Layer for BioGraph MVP

Per Contract D: API reads explanations ONLY (Section 4)

Public endpoints must query explanation table, NOT raw assertions.
"""
from typing import Any, List, Dict
from datetime import date


def get_explanations_for_issuer(cursor: Any, issuer_id: str, as_of_date: date = None) -> List[Dict]:
    """
    Get explanation chains for an issuer.

    Per Contract D: This queries explanation table ONLY.
    Raw assertion table is admin/debug-only.

    Args:
        cursor: Database cursor
        issuer_id: Issuer ID
        as_of_date: Snapshot date (default: today)

    Returns:
        List of explanation records
    """
    if as_of_date is None:
        as_of_date = date.today()

    # CRITICAL: Query explanation table ONLY
    cursor.execute("""
        SELECT
            explanation_id,
            issuer_id,
            drug_program_id,
            target_id,
            disease_id,
            as_of_date,
            strength_score
        FROM explanation
        WHERE issuer_id = %s
          AND as_of_date = %s
        ORDER BY strength_score DESC
    """, (issuer_id, as_of_date))

    return cursor.fetchall()
