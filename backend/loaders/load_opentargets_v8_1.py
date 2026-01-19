#!/usr/bin/env python3
"""
Phase 4: OpenTargets Loader (v8.1 - Scope Locked)

Loads Target → Disease associations from OpenTargets Platform.

Per v8.1 Fix #5: SCOPE LOCK
- Whitelist ONLY: target identity IDs, disease identity IDs,
  high-level target-disease association, optional modality/tractability
- Explicitly do NOT ingest: genetics, pathways, variant networks

Per v8.1 Fix #4: Evidence-first assertion mediation
"""
import json
import time
from typing import Dict, List, Optional
from urllib import request
from datetime import datetime
from ..app.db import get_conn
from .assertion_helper import (
    create_evidence,
    create_target_disease_assertion
)

OPENTARGETS_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
USER_AGENT = "BioGraph/1.0 (biograph-support@example.com)"

# SCOPE LOCK: Whitelist of allowed OpenTargets fields (Fix #5)
ALLOWED_DISEASE_FIELDS = [
    'id', 'name', 'description', 'therapeuticAreas'
]

ALLOWED_TARGET_FIELDS = [
    'id', 'approvedSymbol', 'approvedName', 'proteinIds', 'targetClass'
]

ALLOWED_ASSOCIATION_FIELDS = [
    'score', 'id'  # Overall score only, no detailed datatype scores
]

# Optional: tractability for investor narrative
ALLOWED_TRACTABILITY_FIELDS = [
    'label', 'value'
]

def query_opentargets_graphql(query: str, variables: Optional[Dict] = None) -> Optional[Dict]:
    """Execute GraphQL query against OpenTargets Platform API."""
    payload = {
        'query': query,
        'variables': variables or {}
    }

    req = request.Request(
        OPENTARGETS_GRAPHQL_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT
        }
    )

    try:
        with request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get('data')

    except Exception as e:
        print(f"  ✗ OpenTargets query error: {e}")
        return None

def fetch_disease_info(disease_id: str) -> Optional[Dict]:
    """
    Fetch disease information from OpenTargets.

    SCOPE LOCKED to allowed fields only.
    """
    query = """
    query DiseaseInfo($diseaseId: String!) {
      disease(efoId: $diseaseId) {
        id
        name
        description
        therapeuticAreas {
          id
          name
        }
      }
    }
    """

    data = query_opentargets_graphql(query, {'diseaseId': disease_id})

    if not data or not data.get('disease'):
        return None

    disease = data['disease']

    # Extract only whitelisted fields
    return {
        'id': disease['id'],
        'name': disease['name'],
        'therapeutic_area': disease['therapeuticAreas'][0]['name'] if disease.get('therapeuticAreas') else None
    }

def fetch_target_info(target_id: str) -> Optional[Dict]:
    """
    Fetch target information from OpenTargets.

    SCOPE LOCKED to allowed fields only.
    """
    query = """
    query TargetInfo($targetId: String!) {
      target(ensemblId: $targetId) {
        id
        approvedSymbol
        approvedName
        proteinIds {
          id
          source
        }
        targetClass {
          id
          label
        }
      }
    }
    """

    data = query_opentargets_graphql(query, {'targetId': target_id})

    if not data or not data.get('target'):
        return None

    target = data['target']

    # Extract UniProt ID
    uniprot_id = None
    if target.get('proteinIds'):
        for protein in target['proteinIds']:
            if protein.get('source') == 'uniprot_swissprot':
                uniprot_id = protein['id']
                break

    # Extract only whitelisted fields
    return {
        'id': target['id'],
        'name': target['approvedName'],
        'gene_symbol': target['approvedSymbol'],
        'uniprot_id': uniprot_id,
        'target_class': target['targetClass'][0]['label'] if target.get('targetClass') else None
    }

def fetch_target_disease_associations(disease_id: str, min_score: float = 0.3) -> List[Dict]:
    """
    Fetch target-disease associations for a disease.

    SCOPE LOCKED: Only high-level score, no detailed datatype scores.
    """
    query = """
    query AssociatedTargets($diseaseId: String!, $size: Int!) {
      disease(efoId: $diseaseId) {
        associatedTargets(page: { size: $size }) {
          rows {
            target {
              id
              approvedSymbol
            }
            score
          }
        }
      }
    }
    """

    data = query_opentargets_graphql(query, {
        'diseaseId': disease_id,
        'size': 100
    })

    if not data or not data.get('disease'):
        return []

    targets = data['disease'].get('associatedTargets', {}).get('rows', [])

    # Extract only whitelisted association fields
    associations = []
    for row in targets:
        if row['score'] >= min_score:
            associations.append({
                'target_id': row['target']['id'],
                'gene_symbol': row['target']['approvedSymbol'],
                'association_score': row['score']
                # NO datatype scores, NO genetics, NO pathways
            })

    return associations

def load_target_disease_associations_for_disease(disease_id: str, min_score: float = 0.3) -> Dict[str, int]:
    """
    Load target-disease associations for a single disease.

    Uses assertion-evidence mediation (Fix #4).
    """
    stats = {'targets_inserted': 0, 'diseases_inserted': 0, 'associations_inserted': 0}

    # Fetch disease info
    disease_info = fetch_disease_info(disease_id)
    if not disease_info:
        print(f"  ⚠ Disease {disease_id} not found")
        return stats

    # Fetch associations
    associations = fetch_target_disease_associations(disease_id, min_score)

    if not associations:
        print(f"  ⚠ No associations found for {disease_info['name']}")
        return stats

    print(f"  → {disease_info['name']}: {len(associations)} targets")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Insert disease
            cur.execute("""
                INSERT INTO disease (disease_id, name, therapeutic_area)
                VALUES (%s, %s, %s)
                ON CONFLICT (disease_id) DO UPDATE
                SET name = EXCLUDED.name,
                    therapeutic_area = EXCLUDED.therapeutic_area
                RETURNING disease_id
            """, (disease_info['id'], disease_info['name'], disease_info['therapeutic_area']))

            if cur.fetchone():
                stats['diseases_inserted'] += 1

            # Process associations
            for assoc in associations:
                # Fetch target info
                target_info = fetch_target_info(assoc['target_id'])

                if not target_info:
                    continue

                # Insert target
                cur.execute("""
                    INSERT INTO target (target_id, name, gene_symbol, uniprot_id, target_class)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (target_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        gene_symbol = EXCLUDED.gene_symbol,
                        uniprot_id = EXCLUDED.uniprot_id,
                        target_class = EXCLUDED.target_class
                    RETURNING target_id
                """, (
                    target_info['id'],
                    target_info['name'],
                    target_info['gene_symbol'],
                    target_info['uniprot_id'],
                    target_info['target_class']
                ))

                if cur.fetchone():
                    stats['targets_inserted'] += 1

                # Create evidence record
                evidence_id = create_evidence(
                    source_system='opentargets',
                    source_record_id=f"{assoc['target_id']}_{disease_id}",
                    license='CC0',
                    observed_at=datetime.now(),
                    uri=f"https://platform.opentargets.org/target/{assoc['target_id']}/associations?id={disease_id}",
                    base_confidence=assoc['association_score']
                )

                # Create assertion (with evidence)
                assertion_id = create_target_disease_assertion(
                    target_id=assoc['target_id'],
                    disease_id=disease_id,
                    evidence_ids=[evidence_id]
                )

                stats['associations_inserted'] += 1

                # Rate limiting
                time.sleep(0.1)

            conn.commit()

    return stats

def load_opentargets_for_therapeutic_areas(
    therapeutic_areas: List[str] = None,
    min_score: float = 0.3
) -> Dict[str, int]:
    """
    Load OpenTargets data for specific therapeutic areas.

    SCOPE LOCKED to key disease areas relevant to universe.
    """
    # Default therapeutic areas for biopharma MVP
    if not therapeutic_areas:
        therapeutic_areas = [
            'EFO_0000319',   # Cardiovascular disease
            'EFO_0000540',   # Immune system disease
            'EFO_0000618',   # Nervous system disease
            'EFO_0001379',   # Endocrine system disease
            'MONDO_0045024', # Cancer
        ]

    total_stats = {
        'diseases_processed': 0,
        'targets_inserted': 0,
        'diseases_inserted': 0,
        'associations_inserted': 0
    }

    # Log start
    log_id = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ingestion_log
                (phase, source_system, records_processed, started_at, status, metadata)
                VALUES ('asset_mapping', 'opentargets', %s, NOW(), 'running', %s)
                RETURNING id
            """, (len(therapeutic_areas), json.dumps({'min_score': min_score, 'scope_locked': True})))
            log_id = cur.fetchone()['id']
            conn.commit()

    print(f"\n{'='*60}")
    print(f"Phase 4: OpenTargets Target-Disease Associations (SCOPE LOCKED)")
    print(f"{'='*60}")
    print(f"Loading {len(therapeutic_areas)} therapeutic areas (min score: {min_score})...")
    print(f"Whitelist: target/disease identity, high-level associations only")
    print(f"Blocked: genetics, pathways, variants")

    for i, disease_id in enumerate(therapeutic_areas, 1):
        print(f"\n[{i}/{len(therapeutic_areas)}] {disease_id}")

        try:
            stats = load_target_disease_associations_for_disease(disease_id, min_score)
            total_stats['diseases_processed'] += 1
            total_stats['targets_inserted'] += stats['targets_inserted']
            total_stats['diseases_inserted'] += stats['diseases_inserted']
            total_stats['associations_inserted'] += stats['associations_inserted']

            time.sleep(0.5)

        except Exception as e:
            print(f"  ✗ Error: {e}")

    # Update log
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ingestion_log
                SET records_inserted = %s,
                    completed_at = NOW(),
                    status = 'completed'
                WHERE id = %s
            """, (total_stats['associations_inserted'], log_id))
            conn.commit()

    print(f"\n{'='*60}")
    print(f"OpenTargets Loading Complete (Scope Locked)")
    print(f"{'='*60}")
    print(f"Diseases processed: {total_stats['diseases_processed']}")
    print(f"Targets inserted: {total_stats['targets_inserted']}")
    print(f"Associations inserted: {total_stats['associations_inserted']}")

    return total_stats

if __name__ == "__main__":
    import sys

    min_score = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3

    load_opentargets_for_therapeutic_areas(min_score=min_score)
