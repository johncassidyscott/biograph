#!/usr/bin/env python3
"""
Entity Enrichment Pipeline - Enrich entities with external data sources.

This script:
1. Finds entities needing enrichment (no description or identifiers)
2. Queries Wikidata, ChEMBL, UMLS for each entity
3. Updates entity with description, identifiers, classifications
4. Logs all enrichment attempts for debugging

Usage:
    python scripts/enrich_entities.py [--kind drug] [--limit 100]

Options:
    --kind: Only enrich specific entity type (drug, disease, company)
    --limit: Maximum entities to enrich (default: no limit)
    --force: Re-enrich entities that already have data
"""

import sys
import os
import argparse
from typing import Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_conn
from services import (
    get_wikidata_service,
    get_chembl_service,
    get_umls_service
)

def get_entities_needing_enrichment(kind: Optional[str] = None, limit: Optional[int] = None, force: bool = False) -> List[Dict]:
    """Get entities that need enrichment"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if force:
                # Re-enrich all
                query = "SELECT id, kind, canonical_id, name, description FROM entity"
                params = []

                if kind:
                    query += " WHERE kind = %s"
                    params.append(kind)

                query += " ORDER BY id"

                if limit:
                    query += " LIMIT %s"
                    params.append(limit)

                cur.execute(query, params)
            else:
                # Only entities needing enrichment
                cur.execute("""
                    SELECT id, kind, canonical_id, name, description
                    FROM entities_needing_enrichment
                    WHERE ($1::text IS NULL OR kind = $1)
                    ORDER BY created_at DESC
                    LIMIT $2
                """, (kind, limit or 1000000))

            return [dict(row) for row in cur.fetchall()]

def save_entity_identifiers(entity_id: int, identifiers: Dict[str, str], source: str) -> None:
    """Save external identifiers for an entity"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for identifier_type, identifier_value in identifiers.items():
                if identifier_value:
                    cur.execute("""
                        INSERT INTO entity_identifier (entity_id, identifier_type, identifier, source, verified_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (entity_id, identifier_type)
                        DO UPDATE SET
                            identifier = EXCLUDED.identifier,
                            verified_at = NOW()
                    """, (entity_id, identifier_type, identifier_value, source))
        conn.commit()

def save_entity_classifications(entity_id: int, classifications: Dict[str, str], source: str) -> None:
    """Save industry classifications for an entity"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for classification_type, code in classifications.items():
                if code:
                    cur.execute("""
                        INSERT INTO entity_classification (entity_id, classification_type, code, is_primary, source)
                        VALUES (%s, %s, %s, true, %s)
                        ON CONFLICT (entity_id, classification_type, code)
                        DO UPDATE SET is_primary = true
                    """, (entity_id, classification_type, code, source))
        conn.commit()

def update_entity_description(entity_id: int, description: str) -> None:
    """Update entity description"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE entity
                SET description = %s,
                    updated_at = NOW()
                WHERE id = %s AND (description IS NULL OR description = '')
            """, (description, entity_id))
        conn.commit()

def log_enrichment(entity_id: int, enrichment_type: str, status: str, response_data: Optional[Dict] = None, error_message: Optional[str] = None) -> None:
    """Log enrichment attempt"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO entity_enrichment_log (entity_id, enrichment_type, status, response_data, error_message)
                VALUES (%s, %s, %s, %s, %s)
            """, (entity_id, enrichment_type, status, response_data, error_message))
        conn.commit()

def enrich_drug(entity: Dict, chembl_service, wikidata_service) -> int:
    """Enrich a drug entity"""
    entity_id = entity['id']
    name = entity['name']
    enriched = 0

    # Try ChEMBL first (most authoritative for drugs)
    try:
        chembl_data = chembl_service.enrich_drug(name)
        if chembl_data:
            # Update description
            if chembl_data.get('description') and not entity.get('description'):
                update_entity_description(entity_id, chembl_data['description'])
                enriched += 1

            # Save ChEMBL ID as identifier
            save_entity_identifiers(entity_id, {'chembl': chembl_data['chembl_id']}, 'chembl')

            log_enrichment(entity_id, 'chembl', 'success', chembl_data)
            print(f"    ✓ ChEMBL: {chembl_data['chembl_id']}")
    except Exception as e:
        log_enrichment(entity_id, 'chembl', 'error', error_message=str(e))
        print(f"    ✗ ChEMBL error: {e}")

    # Try Wikidata
    try:
        wikidata_data = wikidata_service.enrich_drug(name)
        if wikidata_data:
            # Update description if we don't have one yet
            if wikidata_data.get('description') and not entity.get('description'):
                update_entity_description(entity_id, wikidata_data['description'])
                enriched += 1

            # Save identifiers
            if wikidata_data.get('identifiers'):
                save_entity_identifiers(entity_id, wikidata_data['identifiers'], 'wikidata')

            log_enrichment(entity_id, 'wikidata', 'success', wikidata_data)
            print(f"    ✓ Wikidata: {wikidata_data['qid']} ({len(wikidata_data.get('identifiers', {}))} identifiers)")
    except Exception as e:
        log_enrichment(entity_id, 'wikidata', 'error', error_message=str(e))
        print(f"    ✗ Wikidata error: {e}")

    return enriched

def enrich_disease(entity: Dict, umls_service, wikidata_service) -> int:
    """Enrich a disease entity"""
    entity_id = entity['id']
    name = entity['name']
    enriched = 0

    # Try UMLS first if API key available
    if umls_service.api_key:
        try:
            umls_data = umls_service.enrich_medical_term(name)
            if umls_data:
                # Update description
                if umls_data.get('description') and not entity.get('description'):
                    update_entity_description(entity_id, umls_data['description'])
                    enriched += 1

                # Save UMLS CUI and MeSH mapping
                identifiers = {'umls_cui': umls_data['cui']}
                if umls_data.get('mesh_id'):
                    identifiers['mesh'] = umls_data['mesh_id']

                save_entity_identifiers(entity_id, identifiers, 'umls')

                log_enrichment(entity_id, 'umls', 'success', umls_data)
                print(f"    ✓ UMLS: {umls_data['cui']} (MeSH: {umls_data.get('mesh_id', 'N/A')})")
        except Exception as e:
            log_enrichment(entity_id, 'umls', 'error', error_message=str(e))
            print(f"    ✗ UMLS error: {e}")

    # Try Wikidata
    try:
        wikidata_data = wikidata_service.enrich_disease(name)
        if wikidata_data:
            if wikidata_data.get('description') and not entity.get('description'):
                update_entity_description(entity_id, wikidata_data['description'])
                enriched += 1

            if wikidata_data.get('identifiers'):
                save_entity_identifiers(entity_id, wikidata_data['identifiers'], 'wikidata')

            log_enrichment(entity_id, 'wikidata', 'success', wikidata_data)
            print(f"    ✓ Wikidata: {wikidata_data['qid']}")
    except Exception as e:
        log_enrichment(entity_id, 'wikidata', 'error', error_message=str(e))
        print(f"    ✗ Wikidata error: {e}")

    return enriched

def enrich_company(entity: Dict, wikidata_service) -> int:
    """Enrich a company entity"""
    entity_id = entity['id']
    name = entity['name']
    enriched = 0

    # Wikidata is excellent for companies
    try:
        wikidata_data = wikidata_service.enrich_company(name)
        if wikidata_data:
            # Update description
            if wikidata_data.get('description') and not entity.get('description'):
                update_entity_description(entity_id, wikidata_data['description'])
                enriched += 1

            # Save identifiers (LEI, PermID, OpenCorporates, etc.)
            if wikidata_data.get('identifiers'):
                identifiers = wikidata_data['identifiers']
                save_entity_identifiers(entity_id, identifiers, 'wikidata')

                # Save NAICS/SIC codes as classifications
                classifications = {}
                if 'naics' in identifiers:
                    classifications['naics'] = identifiers.pop('naics')
                if 'sic' in identifiers:
                    classifications['sic'] = identifiers.pop('sic')

                if classifications:
                    save_entity_classifications(entity_id, classifications, 'wikidata')

            log_enrichment(entity_id, 'wikidata', 'success', wikidata_data)
            print(f"    ✓ Wikidata: {wikidata_data['qid']} (LEI: {wikidata_data.get('identifiers', {}).get('lei', 'N/A')})")
    except Exception as e:
        log_enrichment(entity_id, 'wikidata', 'error', error_message=str(e))
        print(f"    ✗ Wikidata error: {e}")

    return enriched

def main():
    parser = argparse.ArgumentParser(description="Enrich entities with external data")
    parser.add_argument("--kind", type=str, choices=["drug", "disease", "company"], help="Only enrich specific entity type")
    parser.add_argument("--limit", type=int, help="Maximum entities to enrich")
    parser.add_argument("--force", action="store_true", help="Re-enrich entities that already have data")
    args = parser.parse_args()

    print("=" * 80)
    print("BIOGRAPH ENTITY ENRICHMENT")
    print("=" * 80)

    # Initialize services
    print("\n[1/3] Initializing enrichment services...")
    wikidata = get_wikidata_service()
    chembl = get_chembl_service()
    umls = get_umls_service()

    if not umls.api_key:
        print("  ⚠️  UMLS API key not found (disease enrichment limited)")

    # Get entities needing enrichment
    print(f"\n[2/3] Finding entities needing enrichment...")
    entities = get_entities_needing_enrichment(kind=args.kind, limit=args.limit, force=args.force)

    if not entities:
        print("✓ No entities need enrichment!")
        return

    print(f"  Found {len(entities):,} entities")

    # Enrich each entity
    print(f"\n[3/3] Enriching entities...")
    total_enriched = 0

    for idx, entity in enumerate(entities, 1):
        print(f"\n  [{idx}/{len(entities)}] {entity['kind']}: {entity['name']}")

        try:
            if entity['kind'] == 'drug':
                enriched = enrich_drug(entity, chembl, wikidata)
            elif entity['kind'] == 'disease':
                enriched = enrich_disease(entity, umls, wikidata)
            elif entity['kind'] == 'company':
                enriched = enrich_company(entity, wikidata)
            else:
                print(f"    ⊘ Unsupported entity type: {entity['kind']}")
                continue

            total_enriched += enriched

        except Exception as e:
            print(f"    ✗ Enrichment failed: {e}")

    print("\n" + "=" * 80)
    print(f"✓ ENRICHMENT COMPLETE: {total_enriched} entities enriched")
    print("=" * 80)

if __name__ == "__main__":
    main()
