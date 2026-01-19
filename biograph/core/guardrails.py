"""
Guardrails for BioGraph MVP v8.2 Contract Enforcement

These functions enforce the non-negotiable contracts from:
docs/spec/BioGraph_Master_Spec_v8.2_MVP.txt

Every write path MUST call these guardrails before committing.

CONTRACTS:
- Evidence license required (Section 14)
- Assertion requires evidence (Section 8)
- News cannot be sole source of assertion (Section 21)
"""
from typing import Any


def require_license(cursor: Any, evidence_id: int) -> None:
    """
    Validate that evidence has a commercial-safe license.

    This is also enforced by DB trigger validate_evidence_license(),
    but this function provides application-level validation with
    clearer error messages.

    Args:
        cursor: Database cursor
        evidence_id: Evidence ID to validate

    Raises:
        ValueError: If evidence has no license or bad license
    """
    cursor.execute("""
        SELECT e.license, la.is_commercial_safe
        FROM evidence e
        LEFT JOIN license_allowlist la ON e.license = la.license
        WHERE e.evidence_id = %s
    """, (evidence_id,))

    row = cursor.fetchone()

    if not row:
        raise ValueError(f"Evidence {evidence_id} not found")

    license_code, is_safe = row

    if not license_code:
        raise ValueError(f"Evidence {evidence_id} has no license")

    if not is_safe:
        raise ValueError(
            f"Evidence {evidence_id} has non-commercial license: {license_code}"
        )


def require_assertion_has_evidence(cursor: Any, assertion_id: int) -> None:
    """
    Validate that assertion has at least one evidence record.

    Per Section 8: "Assertions REQUIRE >=1 evidence record"

    This is enforced at application level (not DB constraint, as it would
    prevent transactional creation pattern). Call this BEFORE commit.

    Args:
        cursor: Database cursor
        assertion_id: Assertion ID to validate

    Raises:
        ValueError: If assertion has no evidence
    """
    cursor.execute("""
        SELECT COUNT(*) FROM assertion_evidence
        WHERE assertion_id = %s
    """, (assertion_id,))

    count = cursor.fetchone()[0]

    if count == 0:
        raise ValueError(
            f"Assertion {assertion_id} has no evidence. "
            f"Per spec Section 8, assertions REQUIRE >=1 evidence record."
        )


def forbid_news_only_assertions(cursor: Any, assertion_id: int) -> None:
    """
    Validate that assertion is not supported ONLY by news evidence.

    Per Section 21: "Assertions may ONLY be created from:
    1) SEC filings and EDGAR exhibits
    2) Open Targets
    3) ChEMBL

    News metadata may NEVER be the sole source of an assertion."

    Args:
        cursor: Database cursor
        assertion_id: Assertion ID to validate

    Raises:
        ValueError: If assertion has only news_metadata evidence
    """
    cursor.execute("""
        SELECT
            COUNT(*) as total_evidence,
            COUNT(*) FILTER (WHERE e.source_system = 'news_metadata') as news_evidence
        FROM assertion_evidence ae
        JOIN evidence e ON ae.evidence_id = e.evidence_id
        WHERE ae.assertion_id = %s
    """, (assertion_id,))

    row = cursor.fetchone()
    total, news = row

    if total == 0:
        raise ValueError(f"Assertion {assertion_id} has no evidence")

    if total == news:
        raise ValueError(
            f"Assertion {assertion_id} cannot have only news_metadata evidence. "
            f"Per spec Section 21, news can only reinforce assertions grounded in "
            f"filings, OpenTargets, or ChEMBL."
        )


def validate_assertion_before_commit(cursor: Any, assertion_id: int) -> None:
    """
    Run all assertion validation checks before commit.

    This is the main entry point for assertion validation.
    Call this at the end of any transaction that creates/modifies assertions.

    Args:
        cursor: Database cursor
        assertion_id: Assertion ID to validate

    Raises:
        ValueError: If any validation fails
    """
    require_assertion_has_evidence(cursor, assertion_id)
    forbid_news_only_assertions(cursor, assertion_id)


def validate_all_pending_assertions(cursor: Any) -> None:
    """
    Validate all assertions in current transaction.

    Useful for batch operations. Checks all assertions that have been
    created/modified but not yet validated.

    Args:
        cursor: Database cursor

    Raises:
        ValueError: If any assertion fails validation
    """
    # Get all assertion IDs from current transaction
    # (This is a simplified version; in practice, you'd track modified IDs)
    cursor.execute("""
        SELECT assertion_id FROM assertion
        WHERE created_at > NOW() - INTERVAL '1 minute'
        ORDER BY assertion_id
    """)

    for row in cursor.fetchall():
        assertion_id = row[0]
        validate_assertion_before_commit(cursor, assertion_id)
