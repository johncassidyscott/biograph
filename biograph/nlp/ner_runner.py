"""
NER Runner for BioGraph MVP

Stub implementation for PR0. Full implementation in PR4.
"""
from typing import Any


def run_ner_on_text(cursor: Any, source_type: str, source_id: int, text: str, issuer_id: str) -> None:
    """
    Run NER on text and create candidates (NOT canonical entities).

    Per Contract E: ML suggests ONLY. Humans decide.
    This function must NEVER create drug_program, target, disease, or assertion.

    Args:
        cursor: Database cursor
        source_type: 'filing', 'exhibit', 'news_headline'
        source_id: ID of source record
        text: Text to process
        issuer_id: Issuer ID for scoping candidates

    Creates:
        - nlp_run record
        - mention records (NER spans)
        - candidate records (normalized suggestions, status='pending')
        - evidence records (for provenance)

    Does NOT create:
        - drug_program, target, disease (canonical entities)
        - assertion (relationships)
    """
    # Stub implementation for PR0
    # Full implementation in PR4 with spaCy + dictionaries

    # Create nlp_run
    cursor.execute("""
        INSERT INTO nlp_run
        (source_type, source_id, model_name, model_version, status)
        VALUES (%s, %s, 'stub', '0.1.0', 'completed')
        RETURNING run_id
    """, (source_type, source_id))

    run_id = cursor.fetchone()[0]

    # Create stub evidence for filing
    cursor.execute("""
        INSERT INTO evidence
        (source_system, source_record_id, observed_at, license, uri, snippet)
        VALUES ('sec_edgar', %s, NOW(), 'PUBLIC_DOMAIN',
                'http://sec.gov/stub', %s)
        RETURNING evidence_id
    """, (f"filing_{source_id}", text[:500]))

    evidence_id = cursor.fetchone()[0]

    # Create stub candidate (example: extract first word as drug candidate)
    first_word = text.split()[0] if text else 'unknown'

    cursor.execute("""
        INSERT INTO candidate
        (issuer_id, entity_type, normalized_name, source_type, source_id,
         mention_ids, status)
        VALUES (%s, 'drug_program', %s, %s, %s, ARRAY[]::bigint[], 'pending')
    """, (issuer_id, first_word, source_type, source_id))

    # Update nlp_run with count
    cursor.execute("""
        UPDATE nlp_run
        SET mentions_extracted = 1,
            completed_at = NOW()
        WHERE run_id = %s
    """, (run_id,))
