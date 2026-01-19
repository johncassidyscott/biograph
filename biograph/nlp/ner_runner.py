"""
BioGraph MVP v8.3 - Minimal Rules-First NER

Per Section 32A: Minimum Viable NER (LOCKED)
- Dictionary + rules-first candidate extraction
- NO SciSpacy/UMLS required
- Outputs ONLY: nlp_run, mention, candidate + evidence
- NO canonical entity creation

Implementation:
1. Regex heuristics for SEC language (Phase 1/2/3, IND, BLA, NDA, "candidate", "program")
2. Drug name patterns: [A-Z]{3,} (all caps, 3+ letters)
3. Target gene patterns: [A-Z]{2,}[0-9]* (EGFR, TP53, etc.)
4. Disease patterns: common disease terms dictionary

Guardrails (Contract E):
- NEVER creates drug_program, target, disease (canonical entities)
- NEVER creates assertions
- Humans approve candidates via curation workflow
"""

import re
from typing import Any, List, Tuple, Dict
import logging

logger = logging.getLogger(__name__)

# Common disease terms (minimal dictionary)
DISEASE_TERMS = {
    'cancer', 'carcinoma', 'melanoma', 'leukemia', 'lymphoma', 'sarcoma',
    'diabetes', 'obesity', 'hypertension', 'alzheimer', 'parkinson',
    'breast cancer', 'lung cancer', 'prostate cancer', 'ovarian cancer',
    'colorectal cancer', 'pancreatic cancer', 'liver cancer',
    'heart disease', 'cardiovascular disease', 'stroke', 'heart failure',
    'asthma', 'copd', 'pneumonia', 'tuberculosis', 'covid', 'influenza',
    'arthritis', 'osteoporosis', 'multiple sclerosis', 'lupus', 'psoriasis',
    'hepatitis', 'cirrhosis', 'kidney disease', 'renal failure'
}

# Clinical development terms
CLINICAL_TERMS = {
    'phase 1', 'phase 2', 'phase 3', 'phase i', 'phase ii', 'phase iii',
    'ind application', 'bla', 'nda', 'clinical trial', 'investigational',
    'candidate', 'program', 'pipeline', 'development candidate'
}


def run_ner_on_text(
    cursor: Any,
    source_type: str,
    source_id: int,
    text: str,
    issuer_id: str
) -> None:
    """
    Run minimal rules-first NER on text and create candidates.

    Per Section 32A: Dictionary + rules-first (NO ML/SciSpacy).
    Per Contract E: Creates candidates ONLY (no canonical entities).

    Args:
        cursor: Database cursor
        source_type: 'filing', 'exhibit', 'news_headline'
        source_id: ID of source record
        text: Text to process
        issuer_id: Issuer ID for scoping candidates

    Creates:
        - nlp_run record (model_name='rules_first', model_version='1.0.0')
        - mention records (NER spans with offsets)
        - candidate records (normalized suggestions, status='pending')
        - evidence record (for provenance)

    Does NOT create:
        - drug_program, target, disease (canonical entities)
        - assertion (relationships)
    """
    logger.info(
        "ner.run",
        source_type=source_type,
        source_id=source_id,
        issuer_id=issuer_id,
        text_length=len(text)
    )

    # Create nlp_run record
    cursor.execute("""
        INSERT INTO nlp_run
        (source_type, source_id, model_name, model_version, status)
        VALUES (%s, %s, 'rules_first', '1.0.0', 'running')
        RETURNING run_id
    """, (source_type, source_id))

    run_id = cursor.fetchone()[0]

    # Create evidence record for provenance
    cursor.execute("""
        INSERT INTO evidence
        (source_system, source_record_id, observed_at, license, uri, snippet)
        VALUES (%s, %s, NOW(), 'PUBLIC_DOMAIN', %s, %s)
        RETURNING evidence_id
    """, (
        'sec_edgar' if source_type in ('filing', 'exhibit') else 'news_metadata',
        f"{source_type}_{source_id}",
        f"https://sec.gov/{source_type}/{source_id}",
        text[:200]  # 200 char snippet
    ))

    evidence_id = cursor.fetchone()[0]

    # Extract mentions using rules
    mentions = extract_mentions(text)

    logger.debug(
        "ner.mentions_extracted",
        run_id=run_id,
        mention_count=len(mentions)
    )

    # Create mention records and candidates
    mention_ids_by_candidate = {}

    for mention in mentions:
        # Insert mention
        cursor.execute("""
            INSERT INTO mention
            (run_id, entity_type, span_text, start_offset, end_offset, confidence)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING mention_id
        """, (
            run_id,
            mention['entity_type'],
            mention['text'],
            mention['start'],
            mention['end'],
            mention['confidence']
        ))

        mention_id = cursor.fetchone()[0]

        # Group by normalized name for candidate creation
        normalized = mention['normalized']
        entity_type = mention['entity_type']
        key = (entity_type, normalized)

        if key not in mention_ids_by_candidate:
            mention_ids_by_candidate[key] = []

        mention_ids_by_candidate[key].append(mention_id)

    # Create candidate records (one per unique normalized name)
    candidate_count = 0

    for (entity_type, normalized), mention_ids in mention_ids_by_candidate.items():
        cursor.execute("""
            INSERT INTO candidate
            (issuer_id, entity_type, normalized_name, source_type, source_id,
             mention_ids, status, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', 'ner_rules_first')
            ON CONFLICT (issuer_id, entity_type, normalized_name, source_type, source_id)
            DO UPDATE SET
                mention_ids = candidate.mention_ids || EXCLUDED.mention_ids,
                updated_at = NOW()
        """, (
            issuer_id,
            entity_type,
            normalized,
            source_type,
            source_id,
            mention_ids
        ))

        candidate_count += 1

    # Update nlp_run with counts
    cursor.execute("""
        UPDATE nlp_run
        SET mentions_extracted = %s,
            status = 'completed',
            completed_at = NOW()
        WHERE run_id = %s
    """, (len(mentions), run_id))

    logger.info(
        "ner.completed",
        run_id=run_id,
        mentions=len(mentions),
        candidates=candidate_count
    )


def extract_mentions(text: str) -> List[Dict]:
    """
    Extract entity mentions using rules-first approach.

    Per Section 32A:
    1. Drug name patterns (UPPERCASE 3+ letters, clinical terms)
    2. Target gene patterns (gene symbols)
    3. Disease patterns (disease term dictionary)

    Args:
        text: Input text

    Returns:
        List of mention dicts with:
        - entity_type: 'drug_program', 'target', 'disease'
        - text: Original span text
        - normalized: Normalized form
        - start: Start offset
        - end: End offset
        - confidence: 0.0-1.0 (rules = 0.8)
    """
    mentions = []

    # 1. Drug name patterns
    # Pattern: UPPERCASE words 3+ letters (e.g., KEYTRUDA, OPDIVO)
    drug_pattern = r'\b([A-Z]{3,})\b'

    for match in re.finditer(drug_pattern, text):
        drug_name = match.group(1)

        # Skip common acronyms
        if drug_name in {'FDA', 'SEC', 'USA', 'CEO', 'CFO', 'RNA', 'DNA', 'HIV', 'COVID'}:
            continue

        mentions.append({
            'entity_type': 'drug_program',
            'text': drug_name,
            'normalized': drug_name.lower(),
            'start': match.start(),
            'end': match.end(),
            'confidence': 0.7  # Lower confidence for UPPERCASE heuristic
        })

    # 2. Clinical development terms (Phase 1, IND, BLA, etc.)
    clinical_pattern = r'\b(Phase [123]|Phase [IiIiIiIi]{1,3}|IND|BLA|NDA|investigational|candidate|program)\b'

    for match in re.finditer(clinical_pattern, text, re.IGNORECASE):
        term = match.group(1)

        # Context: look for nearby drug names (within 50 chars)
        context_start = max(0, match.start() - 50)
        context_end = min(len(text), match.end() + 50)
        context = text[context_start:context_end]

        # Check if nearby UPPERCASE word exists
        nearby_drugs = re.findall(r'\b([A-Z]{3,})\b', context)

        if nearby_drugs:
            # Associate clinical term with nearby drug
            for drug in nearby_drugs:
                if drug not in {'FDA', 'SEC', 'USA', 'CEO', 'CFO'}:
                    mentions.append({
                        'entity_type': 'drug_program',
                        'text': f"{drug} ({term})",
                        'normalized': drug.lower(),
                        'start': match.start(),
                        'end': match.end(),
                        'confidence': 0.8  # Higher confidence with clinical context
                    })

    # 3. Target gene patterns (e.g., EGFR, TP53, PD-L1, HER2)
    gene_pattern = r'\b([A-Z]{2,}[0-9]*(?:-[A-Z0-9]+)?)\b'

    for match in re.finditer(gene_pattern, text):
        gene = match.group(1)

        # Filter: must be 2-10 chars, not common acronyms
        if len(gene) < 2 or len(gene) > 10:
            continue

        if gene in {'FDA', 'SEC', 'USA', 'CEO', 'CFO', 'RNA', 'DNA', 'HIV', 'COVID', 'LLC', 'INC'}:
            continue

        # Higher confidence if in target-related context
        context_start = max(0, match.start() - 100)
        context_end = min(len(text), match.end() + 100)
        context = text[context_start:context_end].lower()

        confidence = 0.6  # Base confidence

        if any(term in context for term in ['target', 'gene', 'protein', 'receptor', 'kinase', 'inhibitor']):
            confidence = 0.8  # Higher confidence with target context

        mentions.append({
            'entity_type': 'target',
            'text': gene,
            'normalized': gene.upper(),  # Normalize to UPPERCASE for genes
            'start': match.start(),
            'end': match.end(),
            'confidence': confidence
        })

    # 4. Disease patterns (dictionary-based)
    text_lower = text.lower()

    for disease in DISEASE_TERMS:
        # Find all occurrences
        pattern = r'\b' + re.escape(disease) + r'\b'

        for match in re.finditer(pattern, text_lower):
            mentions.append({
                'entity_type': 'disease',
                'text': text[match.start():match.end()],  # Original case
                'normalized': disease,  # Normalized lowercase
                'start': match.start(),
                'end': match.end(),
                'confidence': 0.9  # High confidence for dictionary match
            })

    # Remove duplicates (same entity_type + normalized + overlapping spans)
    mentions = deduplicate_mentions(mentions)

    return mentions


def deduplicate_mentions(mentions: List[Dict]) -> List[Dict]:
    """
    Remove duplicate mentions (overlapping spans of same type).

    Keep highest confidence mention for each span.

    Args:
        mentions: List of mention dicts

    Returns:
        Deduplicated list of mentions
    """
    # Sort by confidence (descending)
    mentions = sorted(mentions, key=lambda m: m['confidence'], reverse=True)

    unique = []
    used_spans = set()

    for mention in mentions:
        # Check if span overlaps with any used span of same type
        key = (mention['entity_type'], mention['start'], mention['end'])

        if key in used_spans:
            continue

        # Check for overlapping spans
        overlaps = False

        for used_start, used_end in [(m['start'], m['end']) for m in unique if m['entity_type'] == mention['entity_type']]:
            if (mention['start'] < used_end and mention['end'] > used_start):
                overlaps = True
                break

        if not overlaps:
            unique.append(mention)
            used_spans.add(key)

    return unique
