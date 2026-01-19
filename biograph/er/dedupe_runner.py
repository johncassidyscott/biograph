"""
BioGraph MVP v8.3 - Minimal Rules-First Entity Resolution

Per Section 32B: Minimum Viable ER (LOCKED)
- Within-issuer-only duplicate suggestions
- NO cross-issuer matching
- NO automated merges

Implementation:
1. Exact match (case-insensitive)
2. Levenshtein distance < 3
3. Token overlap > 70%

Guardrails (Contract F):
- ER operates within issuer ONLY
- NEVER crosses issuers
- NEVER auto-merges
- Creates duplicate_suggestion records only (status='pending')
"""

from typing import Any, List, Tuple, Set
import logging

logger = logging.getLogger(__name__)


def find_duplicates_for_issuer(cursor: Any, issuer_id: str) -> None:
    """
    Find duplicate drug_program candidates within a single issuer.

    Per Section 32B: Within-issuer-only duplicate suggestions.
    Per Contract F: ER operates within issuer ONLY. Never crosses issuers.

    Args:
        cursor: Database cursor
        issuer_id: Issuer ID to process

    Creates:
        - duplicate_suggestion records (status='pending')
        - Similarity scores stored in features_json

    Does NOT:
        - Merge entities
        - Compare across issuers
        - Auto-accept suggestions
    """
    logger.info("er.find_duplicates", issuer_id=issuer_id)

    # Get all drug_programs for this issuer
    cursor.execute("""
        SELECT drug_program_id, name, slug
        FROM drug_program
        WHERE issuer_id = %s
        AND deleted_at IS NULL
        ORDER BY drug_program_id
    """, (issuer_id,))

    programs = cursor.fetchall()

    if len(programs) < 2:
        logger.debug("er.no_duplicates", issuer_id=issuer_id, program_count=len(programs))
        return

    logger.debug("er.comparing_programs", issuer_id=issuer_id, program_count=len(programs))

    # Find duplicates using rules-first similarity
    duplicates_found = 0

    for i in range(len(programs)):
        for j in range(i + 1, len(programs)):
            prog1_id, prog1_name, prog1_slug = programs[i]
            prog2_id, prog2_name, prog2_slug = programs[j]

            # Compute similarity
            similarity = compute_similarity(prog1_name, prog2_name)

            # Threshold: 0.7 or higher = potential duplicate
            if similarity >= 0.7:
                # Create duplicate_suggestion
                cursor.execute("""
                    INSERT INTO duplicate_suggestion
                    (entity1_type, entity1_id, entity2_type, entity2_id,
                     similarity_score, features_json, status, created_by)
                    VALUES ('drug_program', %s, 'drug_program', %s, %s, %s, 'pending', 'er_rules_first')
                    ON CONFLICT (entity1_type, entity1_id, entity2_type, entity2_id)
                    DO UPDATE SET
                        similarity_score = EXCLUDED.similarity_score,
                        features_json = EXCLUDED.features_json,
                        updated_at = NOW()
                """, (
                    prog1_id,
                    prog2_id,
                    similarity,
                    {
                        'entity1_name': prog1_name,
                        'entity2_name': prog2_name,
                        'exact_match': prog1_name.lower() == prog2_name.lower(),
                        'levenshtein': levenshtein_distance(prog1_name.lower(), prog2_name.lower()),
                        'token_overlap': token_overlap_ratio(prog1_name, prog2_name),
                        'similarity': similarity
                    }
                ))

                duplicates_found += 1

                logger.debug(
                    "er.duplicate_found",
                    issuer_id=issuer_id,
                    prog1=prog1_name,
                    prog2=prog2_name,
                    similarity=similarity
                )

    logger.info(
        "er.completed",
        issuer_id=issuer_id,
        programs=len(programs),
        duplicates=duplicates_found
    )


def compute_similarity(name1: str, name2: str) -> float:
    """
    Compute similarity between two entity names.

    Per Section 32B.3:
    - Exact match (case-insensitive) → 1.0
    - Levenshtein distance < 3 → 0.9
    - Token overlap > 70% → 0.8

    Args:
        name1: First name
        name2: Second name

    Returns:
        Similarity score 0.0-1.0
    """
    name1_lower = name1.lower().strip()
    name2_lower = name2.lower().strip()

    # 1. Exact match (case-insensitive)
    if name1_lower == name2_lower:
        return 1.0

    # 2. Levenshtein distance < 3
    lev_dist = levenshtein_distance(name1_lower, name2_lower)

    if lev_dist < 3:
        return 0.9

    # 3. Token overlap > 70%
    token_overlap = token_overlap_ratio(name1, name2)

    if token_overlap > 0.7:
        return 0.8

    # 4. Partial token overlap
    if token_overlap > 0.5:
        return 0.6

    # 5. Similar length and some overlap
    len_diff = abs(len(name1_lower) - len(name2_lower))
    max_len = max(len(name1_lower), len(name2_lower))

    if len_diff < 5 and token_overlap > 0.3:
        return 0.5

    # No similarity
    return 0.0


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Compute Levenshtein distance (edit distance) between two strings.

    Uses dynamic programming (Wagner-Fischer algorithm).

    Args:
        s1: First string
        s2: Second string

    Returns:
        Edit distance (integer)
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    # Initialize matrix
    previous_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        current_row = [i + 1]

        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)

            current_row.append(min(insertions, deletions, substitutions))

        previous_row = current_row

    return previous_row[-1]


def token_overlap_ratio(name1: str, name2: str) -> float:
    """
    Compute token overlap ratio (Jaccard similarity).

    Args:
        name1: First name
        name2: Second name

    Returns:
        Token overlap ratio 0.0-1.0
    """
    # Tokenize (split on whitespace and punctuation)
    tokens1 = set(tokenize(name1.lower()))
    tokens2 = set(tokenize(name2.lower()))

    if not tokens1 or not tokens2:
        return 0.0

    # Jaccard similarity: intersection / union
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    return len(intersection) / len(union) if union else 0.0


def tokenize(text: str) -> List[str]:
    """
    Tokenize text into words.

    Args:
        text: Input text

    Returns:
        List of tokens (words)
    """
    import re

    # Split on whitespace and punctuation
    tokens = re.split(r'[\s\-_,\.;:]+', text)

    # Filter out empty tokens and single-char tokens
    tokens = [t for t in tokens if len(t) > 1]

    return tokens
