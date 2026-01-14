#!/usr/bin/env python3
"""
OpenTargets loader - fetch drug-target-disease associations
Links drugs to diseases via therapeutic targets with evidence scores.

Uses OpenTargets GraphQL API.
API docs: https://platform-docs.opentargets.org/data-access/graphql-api
"""
import json
import urllib.request
from typing import Any, Dict, List, Optional
from app.db import get_conn

OPENTARGETS_API = "https://api.platform.opentargets.org/api/v4/graphql"

def opentargets_query(query: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
    """Execute a GraphQL query against OpenTargets API"""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    req = urllib.request.Request(
        OPENTARGETS_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read().decode("utf-8"))

    return result

def get_disease_associations(disease_id: str, min_score: float = 0.5) -> List[Dict[str, Any]]:
    """
    Get drug-target associations for a disease.

    disease_id: EFO ID like "EFO_0001360" (for obesity)
    min_score: minimum overall association score (0.0 to 1.0)
    """
    query = """
    query DiseaseAssociations($diseaseId: String!, $minScore: Float!) {
      disease(efoId: $diseaseId) {
        id
        name
        associatedTargets(page: {size: 100}) {
          count
          rows {
            target {
              id
              approvedSymbol
              proteinIds {
                id
                source
              }
            }
            score
          }
        }
      }
    }
    """

    variables = {
        "diseaseId": disease_id,
        "minScore": min_score
    }

    try:
        result = opentargets_query(query, variables)
        disease = result.get("data", {}).get("disease", {})
        if not disease:
            return []

        targets = disease.get("associatedTargets", {}).get("rows", []) or []
        # Filter by min_score
        return [t for t in targets if t.get("score", 0) >= min_score]

    except Exception as e:
        print(f"Warning: Could not fetch associations for {disease_id}: {e}")
        return []

def get_known_drugs_for_target(target_id: str) -> List[Dict[str, Any]]:
    """
    Get known drugs for a target.

    target_id: Ensembl gene ID like "ENSG00000112164" (for GLP1R)
    """
    query = """
    query TargetDrugs($targetId: String!) {
      target(ensemblId: $targetId) {
        id
        approvedSymbol
        knownDrugs(page: {size: 50}) {
          count
          rows {
            drug {
              id
              name
              drugType
            }
            phase
          }
        }
      }
    }
    """

    variables = {"targetId": target_id}

    try:
        result = opentargets_query(query, variables)
        target = result.get("data", {}).get("target", {})
        if not target:
            return []

        known_drugs = target.get("knownDrugs", {}).get("rows", []) or []
        return known_drugs

    except Exception as e:
        print(f"Warning: Could not fetch drugs for {target_id}: {e}")
        return []

def load_opentargets_associations(disease_mappings: List[Dict[str, str]], min_score: float = 0.3) -> None:
    """
    Load drug-target-disease associations from OpenTargets.

    disease_mappings format:
    [
        {"mesh_id": "D009765", "efo_id": "EFO_0001360", "name": "Obesity"},
        ...
    ]
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted_edges = 0

            for disease_map in disease_mappings:
                mesh_id = disease_map.get("mesh_id")
                efo_id = disease_map.get("efo_id")
                disease_name = disease_map.get("name")

                if not mesh_id or not efo_id:
                    continue

                print(f"\nProcessing disease: {disease_name} ({efo_id})")

                # Get disease entity ID from our database
                cur.execute(
                    """
                    SELECT id FROM entity
                    WHERE kind = 'disease' AND canonical_id = %s
                    """,
                    (f"MESH:{mesh_id}",)
                )
                result = cur.fetchone()
                if not result:
                    print(f"  Warning: Disease {mesh_id} not found in database")
                    continue

                disease_entity_id = result[0]

                # Get targets associated with this disease
                associations = get_disease_associations(efo_id, min_score=min_score)
                print(f"  Found {len(associations)} target associations")

                for assoc in associations:
                    target = assoc.get("target", {})
                    target_id = target.get("id")  # Ensembl ID
                    target_symbol = target.get("approvedSymbol", target_id)
                    score = assoc.get("score", 0)

                    # Get UniProt ID if available
                    protein_ids = target.get("proteinIds", []) or []
                    uniprot_id = None
                    for pid in protein_ids:
                        if pid.get("source") == "uniprot_swissprot":
                            uniprot_id = pid.get("id")
                            break

                    # Prefer UniProt, fallback to Ensembl
                    if uniprot_id:
                        target_canonical_id = f"UNIPROT:{uniprot_id}"
                    else:
                        target_canonical_id = f"ENSEMBL:{target_id}"

                    # Upsert target entity
                    cur.execute(
                        """
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES ('target', %s, %s)
                        ON CONFLICT (kind, canonical_id) DO UPDATE
                          SET name = EXCLUDED.name,
                              updated_at = NOW()
                        RETURNING id
                        """,
                        (target_canonical_id, target_symbol),
                    )
                    target_entity_id = cur.fetchone()['id']

                    # Create edge: target --associated_with--> disease
                    cur.execute(
                        """
                        INSERT INTO edge (src_id, predicate, dst_id, source)
                        VALUES (%s, 'associated_with', %s, 'opentargets')
                        ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                        """,
                        (target_entity_id, disease_entity_id),
                    )
                    inserted_edges += cur.rowcount

                    # Get known drugs for this target
                    known_drugs = get_known_drugs_for_target(target_id)

                    for drug_info in known_drugs[:5]:  # Limit to top 5 per target
                        drug = drug_info.get("drug", {})
                        drug_id = drug.get("id")  # ChEMBL ID
                        drug_name = drug.get("name", drug_id)
                        phase = drug_info.get("phase", 0)

                        if not drug_id or not drug_id.startswith("CHEMBL"):
                            continue

                        drug_canonical_id = f"CHEMBL:{drug_id.replace('CHEMBL', '')}"

                        # Upsert drug entity
                        cur.execute(
                            """
                            INSERT INTO entity (kind, canonical_id, name)
                            VALUES ('drug', %s, %s)
                            ON CONFLICT (kind, canonical_id) DO UPDATE
                              SET name = EXCLUDED.name,
                              updated_at = NOW()
                            RETURNING id
                            """,
                            (drug_canonical_id, drug_name),
                        )
                        drug_entity_id = cur.fetchone()['id']

                        # Create edge: drug --treats--> disease (if phase >= 3)
                        if phase >= 3:
                            cur.execute(
                                """
                                INSERT INTO edge (src_id, predicate, dst_id, source)
                                VALUES (%s, 'treats', %s, 'opentargets')
                                ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                                """,
                                (drug_entity_id, disease_entity_id),
                            )
                            inserted_edges += cur.rowcount

            conn.commit()

    print(f"\n✓ Edges inserted: {inserted_edges}")

if __name__ == "__main__":
    # POC disease mappings (MESH ID -> EFO ID)
    # EFO IDs found via: https://www.ebi.ac.uk/efo/
    poc_diseases = [
        {"mesh_id": "D009765", "efo_id": "EFO_0001360", "name": "Obesity"},
        {"mesh_id": "D000544", "efo_id": "EFO_0000249", "name": "Alzheimer's Disease"},
        # Note: KRAS-specific NSCLC might not have a single EFO ID
        # Use general NSCLC as proxy
        {"mesh_id": "D002289", "efo_id": "EFO_0003060", "name": "Non-small cell lung cancer"},
    ]

    load_opentargets_associations(poc_diseases, min_score=0.3)
