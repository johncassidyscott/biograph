#!/usr/bin/env python3
"""
Explanation Materialization (v8.1 Fix #2)

Materializes fixed explanation chains as first-class queryable objects.

Per spec: Explanation is the ONLY query surface for UI.
- No free graph traversal
- All queries read from explanation table
- Raw assertions are admin-only

Fixed chain: Issuer → DrugProgram → Target → Disease
"""
from typing import Dict
from datetime import date, datetime
from ..app.db import get_conn

def compute_chain_strength(
    issuer_drug_confidence: float,
    drug_target_confidence: float,
    target_disease_confidence: float
) -> float:
    """
    Compute overall chain strength score.

    Simple multiplicative model (can be enhanced).
    """
    return issuer_drug_confidence * drug_target_confidence * target_disease_confidence

def materialize_explanations_for_date(as_of_date: date = None) -> Dict[str, int]:
    """
    Materialize all valid explanation chains for a given date.

    Per spec Fix #2: Explanation is first-class, the ONLY UI query surface.

    Args:
        as_of_date: Snapshot date (default: today)

    Returns:
        Stats dict with counts
    """
    if as_of_date is None:
        as_of_date = date.today()

    stats = {'explanations_created': 0, 'issuers_processed': 0}

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Find all complete chains: Issuer → Drug → Target → Disease
            # Using views over assertions (Fix #4)
            cur.execute("""
                SELECT
                    id_a.issuer_id,
                    id_a.drug_program_id,
                    dt_a.target_id,
                    td_a.disease_id,
                    id_a.assertion_id AS issuer_drug_assertion_id,
                    dt_a.assertion_id AS drug_target_assertion_id,
                    td_a.assertion_id AS target_disease_assertion_id,
                    id_a.confidence AS issuer_drug_conf,
                    dt_a.confidence AS drug_target_conf,
                    td_a.association_score AS target_disease_conf
                FROM issuer_drug id_a
                JOIN drug_target dt_a ON id_a.drug_program_id = dt_a.drug_program_id
                JOIN target_disease td_a ON dt_a.target_id = td_a.target_id
                WHERE id_a.retracted_at IS NULL
                  AND dt_a.retracted_at IS NULL
                  AND td_a.retracted_at IS NULL
            """)

            chains = cur.fetchall()

            print(f"Found {len(chains)} valid explanation chains")

            for chain in chains:
                # Compute strength score
                strength = compute_chain_strength(
                    chain['issuer_drug_conf'] or 0.5,
                    chain['drug_target_conf'] or 0.5,
                    chain['target_disease_conf'] or 0.5
                )

                # Generate deterministic explanation_id
                explanation_id = (
                    f"{chain['issuer_id']}_{chain['drug_program_id']}_"
                    f"{chain['target_id']}_{chain['disease_id']}_{as_of_date}"
                )

                # Insert/update explanation
                cur.execute("""
                    INSERT INTO explanation
                    (explanation_id, issuer_id, drug_program_id, target_id, disease_id,
                     as_of_date, strength_score, issuer_drug_assertion_id,
                     drug_target_assertion_id, target_disease_assertion_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (issuer_id, drug_program_id, target_id, disease_id, as_of_date)
                    DO UPDATE SET
                        strength_score = EXCLUDED.strength_score,
                        issuer_drug_assertion_id = EXCLUDED.issuer_drug_assertion_id,
                        drug_target_assertion_id = EXCLUDED.drug_target_assertion_id,
                        target_disease_assertion_id = EXCLUDED.target_disease_assertion_id,
                        updated_at = NOW()
                    RETURNING explanation_id
                """, (
                    explanation_id,
                    chain['issuer_id'],
                    chain['drug_program_id'],
                    chain['target_id'],
                    chain['disease_id'],
                    as_of_date,
                    strength,
                    chain['issuer_drug_assertion_id'],
                    chain['drug_target_assertion_id'],
                    chain['target_disease_assertion_id']
                ))

                if cur.fetchone():
                    stats['explanations_created'] += 1

            conn.commit()

    print(f"\n{'='*60}")
    print(f"Explanation Materialization Complete")
    print(f"{'='*60}")
    print(f"Explanations created: {stats['explanations_created']}")
    print(f"As of date: {as_of_date}")

    return stats

def get_explanation_changes_since(since_date: date, as_of_date: date = None) -> Dict:
    """
    Get what changed since a prior date (investor use case: "what changed since Q3?").

    Per Fix #8: As-of time semantics.

    Args:
        since_date: Prior snapshot date
        as_of_date: Current snapshot date (default: today)

    Returns:
        Dict with added, removed, changed explanations
    """
    if as_of_date is None:
        as_of_date = date.today()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # New explanations
            cur.execute("""
                SELECT *
                FROM explanation
                WHERE as_of_date = %s
                  AND (issuer_id, drug_program_id, target_id, disease_id) NOT IN (
                      SELECT issuer_id, drug_program_id, target_id, disease_id
                      FROM explanation
                      WHERE as_of_date = %s
                  )
            """, (as_of_date, since_date))

            added = cur.fetchall()

            # Removed explanations
            cur.execute("""
                SELECT *
                FROM explanation
                WHERE as_of_date = %s
                  AND (issuer_id, drug_program_id, target_id, disease_id) NOT IN (
                      SELECT issuer_id, drug_program_id, target_id, disease_id
                      FROM explanation
                      WHERE as_of_date = %s
                  )
            """, (since_date, as_of_date))

            removed = cur.fetchall()

            # Changed strength
            cur.execute("""
                SELECT
                    curr.*,
                    prev.strength_score AS prev_strength_score,
                    (curr.strength_score - prev.strength_score) AS strength_delta
                FROM explanation curr
                JOIN explanation prev ON
                    curr.issuer_id = prev.issuer_id AND
                    curr.drug_program_id = prev.drug_program_id AND
                    curr.target_id = prev.target_id AND
                    curr.disease_id = prev.disease_id
                WHERE curr.as_of_date = %s
                  AND prev.as_of_date = %s
                  AND ABS(curr.strength_score - prev.strength_score) > 0.05
            """, (as_of_date, since_date))

            changed = cur.fetchall()

    return {
        'added': added,
        'removed': removed,
        'changed': changed,
        'since_date': since_date,
        'as_of_date': as_of_date
    }

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        as_of_date = date.fromisoformat(sys.argv[1])
    else:
        as_of_date = date.today()

    materialize_explanations_for_date(as_of_date)
