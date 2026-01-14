#!/usr/bin/env python3
"""
ChEMBL drug loader - focused on POC disease areas:
- Obesity/Metabolic: GLP-1 agonists, GIPR agonists
- Alzheimer's: Anti-amyloid antibodies, cholinesterase inhibitors
- KRAS Oncology: KRAS inhibitors

Uses ChEMBL REST API to fetch drug molecules and their targets.
API docs: https://www.ebi.ac.uk/chembl/api/data/docs
"""
import json
import time
import urllib.request
import urllib.parse
from typing import Any, Dict, List, Optional, Set
from app.db import get_conn

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"

def chembl_get(endpoint: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Call ChEMBL REST API"""
    params = params or {}
    params["format"] = "json"
    url = f"{CHEMBL_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"

    with urllib.request.urlopen(url) as r:
        data = json.loads(r.read().decode("utf-8"))

    time.sleep(0.2)  # Be polite
    return data

def get_molecule_by_chembl_id(chembl_id: str) -> Optional[Dict[str, Any]]:
    """Get molecule details by ChEMBL ID"""
    try:
        data = chembl_get(f"molecule/{chembl_id}")
        return data
    except Exception as e:
        print(f"Warning: Could not fetch {chembl_id}: {e}")
        return None

def search_molecules_by_name(name: str) -> List[Dict[str, Any]]:
    """Search for molecules by name"""
    try:
        data = chembl_get("molecule/search", {"q": name})
        molecules = data.get("molecules", [])
        return molecules
    except Exception as e:
        print(f"Warning: Search failed for '{name}': {e}")
        return []

def get_molecule_targets(chembl_id: str) -> List[Dict[str, Any]]:
    """Get targets for a molecule"""
    try:
        data = chembl_get(f"mechanism", {"molecule_chembl_id": chembl_id})
        mechanisms = data.get("mechanisms", []) or []
        return mechanisms
    except Exception as e:
        print(f"Warning: Could not fetch targets for {chembl_id}: {e}")
        return []

def load_chembl_drugs(drug_list: List[Dict[str, str]]) -> None:
    """
    Load specific drugs into the graph.

    drug_list format:
    [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448"},
        ...
    ]
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted_drugs = 0
            inserted_targets = 0
            inserted_edges = 0

            for drug_spec in drug_list:
                name = drug_spec.get("name")
                chembl_id = drug_spec.get("chembl_id")

                if not chembl_id:
                    print(f"Skipping {name}: no ChEMBL ID")
                    continue

                print(f"\nProcessing: {name} ({chembl_id})")

                # Get molecule details
                mol = get_molecule_by_chembl_id(chembl_id)
                if not mol:
                    continue

                pref_name = mol.get("pref_name") or name
                max_phase = mol.get("max_phase")  # 0-4, or None

                # Insert drug entity
                canonical_id = f"CHEMBL:{chembl_id}"
                cur.execute(
                    """
                    INSERT INTO entity (kind, canonical_id, name)
                    VALUES ('drug', %s, %s)
                    ON CONFLICT (kind, canonical_id) DO UPDATE
                      SET name = EXCLUDED.name,
                          updated_at = NOW()
                    RETURNING id
                    """,
                    (canonical_id, pref_name),
                )
                drug_entity_id = cur.fetchone()[0]
                inserted_drugs += 1

                # Add synonyms as aliases
                synonyms = mol.get("molecule_synonyms", []) or []
                for syn in synonyms[:10]:  # Limit to first 10
                    syn_name = syn.get("molecule_synonym")
                    if syn_name and syn_name.lower() != pref_name.lower():
                        cur.execute(
                            """
                            INSERT INTO alias (entity_id, alias, source)
                            VALUES (%s, %s, 'chembl')
                            ON CONFLICT DO NOTHING
                            """,
                            (drug_entity_id, syn_name),
                        )

                # Get targets via mechanism of action
                mechanisms = get_molecule_targets(chembl_id)
                for mech in mechanisms:
                    target_chembl_id = mech.get("target_chembl_id")
                    action_type = mech.get("action_type")

                    if not target_chembl_id:
                        continue

                    # Get target details
                    try:
                        target_data = chembl_get(f"target/{target_chembl_id}")
                    except:
                        continue

                    target_name = target_data.get("pref_name", target_chembl_id)
                    target_type = target_data.get("target_type")

                    # Get UniProt accessions
                    components = target_data.get("target_components", []) or []
                    uniprot_ids = []
                    for comp in components:
                        for xref in comp.get("target_component_xrefs", []) or []:
                            if xref.get("xref_src_db") == "UniProt":
                                uniprot_ids.append(xref.get("xref_id"))

                    # Prefer UniProt ID, fallback to ChEMBL target ID
                    if uniprot_ids:
                        target_canonical_id = f"UNIPROT:{uniprot_ids[0]}"
                    else:
                        target_canonical_id = f"CHEMBL_TARGET:{target_chembl_id}"

                    # Insert target entity
                    cur.execute(
                        """
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES ('target', %s, %s)
                        ON CONFLICT (kind, canonical_id) DO UPDATE
                          SET name = EXCLUDED.name,
                              updated_at = NOW()
                        RETURNING id
                        """,
                        (target_canonical_id, target_name),
                    )
                    target_entity_id = cur.fetchone()[0]
                    inserted_targets += 1

                    # Create edge: drug --targets--> target (confidence 1.0 - canonical source)
                    cur.execute(
                        """
                        INSERT INTO edge (src_id, predicate, dst_id, source, confidence)
                        VALUES (%s, 'targets', %s, 'chembl', 1.0)
                        ON CONFLICT (src_id, predicate, dst_id) DO UPDATE
                          SET confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                        """,
                        (drug_entity_id, target_entity_id),
                    )
                    inserted_edges += cur.rowcount

                    print(f"  → {target_name} ({action_type or 'unknown action'})")

            conn.commit()

    print(f"\n✓ Drugs inserted: {inserted_drugs}")
    print(f"✓ Targets inserted: {inserted_targets}")
    print(f"✓ Drug-target edges: {inserted_edges}")

if __name__ == "__main__":
    # POC drug list for the three disease areas
    # You can expand this list as needed
    poc_drugs = [
        # Obesity/Metabolic
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448"},
        {"name": "Liraglutide", "chembl_id": "CHEMBL1201580"},
        {"name": "Dulaglutide", "chembl_id": "CHEMBL2107834"},

        # Alzheimer's Disease
        {"name": "Donepezil", "chembl_id": "CHEMBL502"},
        {"name": "Rivastigmine", "chembl_id": "CHEMBL636"},
        {"name": "Galantamine", "chembl_id": "CHEMBL659"},
        {"name": "Memantine", "chembl_id": "CHEMBL1201384"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL2366541"},
        {"name": "Aducanumab", "chembl_id": "CHEMBL4297072"},

        # KRAS Oncology
        {"name": "Sotorasib", "chembl_id": "CHEMBL4297299"},
        {"name": "Adagrasib", "chembl_id": "CHEMBL4594668"},
    ]

    load_chembl_drugs(poc_drugs)
