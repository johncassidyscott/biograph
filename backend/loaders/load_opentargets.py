"""Load disease-target associations from OpenTargets Platform GraphQL API."""
import os
import json
import requests
import pandas as pd
from backend.app.db import get_conn
from backend.loaders.filter_utils import filter_to_target_mesh
from backend.loaders.target_mesh import TARGET_MESH_IDS

DEFAULT_ENDPOINT = os.environ.get(
    "OPENTARGETS_URL",
    "https://api.platform.opentargets.org/api/v4/graphql"
)

QUERY = """
query diseaseAssociations($efoId: String!, $index: Int!, $size: Int!) {
  disease(efoId: $efoId) {
    id
    name
    associatedTargets(page: { index: $index, size: $size }) {
      count
      rows {
        target {
          id
          approvedSymbol
          approvedName
        }
        score
      }
    }
  }
}
"""

def load_opentargets():
    """Load disease-target associations from OpenTargets Platform, filtered to target MeSH IDs."""
    
    # Map our 8 target MeSH IDs to OpenTargets EFO/MONDO IDs (manual mapping)
    diseases = [
        {"mesh": "D002289", "name": "NSCLC", "efo": "EFO_0003060"},
        {"mesh": "D009101", "name": "Multiple Myeloma", "efo": "EFO_0000756"},
        {"mesh": "D015179", "name": "Colorectal Cancer", "efo": "EFO_0005842"},
        {"mesh": "D001172", "name": "Rheumatoid Arthritis", "efo": "EFO_0000684"},
        {"mesh": "D003876", "name": "Atopic Dermatitis", "efo": "EFO_0000274"},
        {"mesh": "D015212", "name": "Inflammatory Bowel Disease", "efo": "EFO_0003767"},
        {"mesh": "D006333", "name": "Heart Failure", "efo": "EFO_0000358"},
        {"mesh": "D000544", "name": "Alzheimer Disease", "efo": "MONDO_0004975"},
    ]
    
    print(f"Using endpoint: {DEFAULT_ENDPOINT}")
    print(f"Loading associations for {len(diseases)} target diseases (MeSH: {len(TARGET_MESH_IDS)})")
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            total_associations = 0
            
            for disease in diseases:
                if disease["mesh"] not in TARGET_MESH_IDS:
                    print(f"Skipping {disease['name']} (not in target set)")
                    continue
                
                print(f"Fetching associations for {disease['name']} ({disease['mesh']})...")
                
                try:
                    # Fetch disease entity
                    cur.execute(
                        "INSERT INTO entity (kind, canonical_id, name, source) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (kind, canonical_id) DO UPDATE SET name = excluded.name, updated_at = now()",
                        ("disease", f"OPENTARGETS:{disease['efo']}", disease['name'], "opentargets")
                    )
                    
                    # Paginate through associations
                    page_size = 100
                    page_index = 0
                    max_pages = 5  # Limit to avoid long fetches
                    
                    while page_index < max_pages:
                        variables = {
                            "efoId": disease["efo"],
                            "index": page_index,
                            "size": page_size
                        }
                        
                        resp = requests.post(
                            DEFAULT_ENDPOINT,
                            json={"query": QUERY, "variables": variables},
                            timeout=30
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        
                        if "errors" in data:
                            print(f"  GraphQL error: {data['errors']}")
                            break
                        
                        disease_data = data.get("data", {}).get("disease", {})
                        associated_targets = disease_data.get("associatedTargets", {})
                        rows = associated_targets.get("rows", [])
                        
                        if not rows:
                            break
                        
                        # Insert targets and edges
                        for row in rows:
                            target = row.get("target", {})
                            target_id = target.get("id")
                            target_symbol = target.get("approvedSymbol", "")
                            target_name = target.get("approvedName", "")
                            score = row.get("score", 0)
                            
                            if target_id and target_symbol:
                                # Insert target
                                cur.execute(
                                    "INSERT INTO entity (kind, canonical_id, name, source) VALUES (%s, %s, %s, %s) "
                                    "ON CONFLICT (kind, canonical_id) DO UPDATE SET name = excluded.name, updated_at = now()",
                                    ("target", f"OPENTARGETS:{target_id}", target_name or target_symbol, "opentargets")
                                )
                                
                                # Insert edge (disease -> target)
                                cur.execute(
                                    "INSERT INTO edge (src_id, dst_id, type, props) "
                                    "SELECT e1.id, e2.id, %s, %s "
                                    "FROM entity e1, entity e2 "
                                    "WHERE e1.canonical_id = %s AND e2.canonical_id = %s "
                                    "ON CONFLICT DO NOTHING",
                                    ("associated_with", json.dumps({"score": score}), 
                                     f"OPENTARGETS:{disease['efo']}", f"OPENTARGETS:{target_id}")
                                )
                                total_associations += 1
                        
                        page_index += 1
                        conn.commit()
                    
                except requests.RequestException as e:
                    print(f"  Error fetching OpenTargets data for {disease['name']}: {e}")
    
    print(f"OpenTargets: Total associations loaded: {total_associations}")

if __name__ == "__main__":
    load_opentargets()
