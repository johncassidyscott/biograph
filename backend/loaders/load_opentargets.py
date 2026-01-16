"""Load disease-target associations from OpenTargets Platform GraphQL API."""
import os
import json
import requests
import time
from backend.app.db import get_conn
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
    """Load disease-target associations from OpenTargets Platform with retry."""
    
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
    print(f"Loading real disease-target associations from OpenTargets...\n")
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            total_associations = 0
            
            for disease in diseases:
                if disease["mesh"] not in TARGET_MESH_IDS:
                    continue
                
                print(f"Fetching associations for {disease['name']} ({disease['efo']})...")
                
                page_index = 0
                page_limit = 5
                disease_found = False
                
                while page_index < page_limit:
                    variables = {
                        "efoId": disease["efo"],
                        "index": page_index,
                        "size": 100
                    }
                    
                    try:
                        resp = requests.post(
                            DEFAULT_ENDPOINT,
                            json={"query": QUERY, "variables": variables},
                            timeout=60,
                            headers={"User-Agent": "biograph/0.1"}
                        )
                        resp.raise_for_status()
                        
                        data = resp.json()
                        
                        # Check for GraphQL errors
                        if "errors" in data and data["errors"]:
                            error_msg = data["errors"][0].get("message", "unknown")
                            print(f"  GraphQL error: {error_msg}")
                            break
                        
                        # Extract disease and associations
                        response_data = data.get("data")
                        if not response_data:
                            print(f"  No data in response")
                            break
                        
                        disease_data = response_data.get("disease")
                        if not disease_data:
                            print(f"  Disease {disease['efo']} not found in OpenTargets")
                            break
                        
                        disease_found = True
                        associated_targets = disease_data.get("associatedTargets", {})
                        rows = associated_targets.get("rows", [])
                        count = associated_targets.get("count", 0)
                        
                        if not rows:
                            print(f"  Finished: {total_associations} total associations loaded for this disease")
                            break
                        
                        print(f"  Page {page_index + 1}: {len(rows)} associations (total available: {count})")
                        
                        for row in rows:
                            target = row.get("target", {})
                            target_id = target.get("id")
                            symbol = target.get("approvedSymbol", "")
                            name = target.get("approvedName", "")
                            score = row.get("score", 0)
                            
                            if target_id and symbol:
                                # Insert/update target
                                cur.execute(
                                    "INSERT INTO entity (kind, canonical_id, name, source) VALUES (%s, %s, %s, %s) "
                                    "ON CONFLICT (kind, canonical_id) DO UPDATE SET name = excluded.name, updated_at = now()",
                                    ("target", f"OPENTARGETS:{target_id}", name or symbol, "opentargets")
                                )
                                
                                # Insert edge disease -> target
                                cur.execute(
                                    "INSERT INTO edge (src_id, dst_id, type, props) "
                                    "SELECT e1.id, e2.id, %s, %s "
                                    "FROM entity e1, entity e2 "
                                    "WHERE e1.canonical_id = %s AND e2.canonical_id = %s "
                                    "ON CONFLICT DO NOTHING",
                                    ("associated_with", json.dumps({"score": score}),
                                     f"MESH:{disease['mesh']}", f"OPENTARGETS:{target_id}")
                                )
                                total_associations += 1
                        
                        page_index += 1
                        conn.commit()
                        time.sleep(0.5)  # Rate limit
                        
                    except requests.RequestException as e:
                        print(f"  Request error (retry in 5s): {e}")
                        time.sleep(5)
                    except json.JSONDecodeError as e:
                        print(f"  JSON decode error: {e}")
                        break
                
                if not disease_found:
                    print(f"  WARNING: Could not find disease {disease['efo']} in OpenTargets")
    
    print(f"\nOpenTargets: Total real associations loaded: {total_associations}")

if __name__ == "__main__":
    load_opentargets()
