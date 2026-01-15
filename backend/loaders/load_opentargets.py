"""Load disease-target associations from OpenTargets Platform GraphQL API."""
import os
import time
import json
import requests
from typing import List, Dict, Any

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

def _fetch_associations(efo_id: str, size: int = 200) -> List[Dict[str, Any]]:
    """Fetch all target associations for a disease via GraphQL pagination."""
    index = 0
    total = None
    rows = []
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    while True:
        payload = {
            "query": QUERY,
            "variables": {
                "efoId": efo_id,
                "index": index,
                "size": size
            }
        }
        
        try:
            r = requests.post(
                DEFAULT_ENDPOINT,
                headers=headers,
                data=json.dumps(payload),
                timeout=30
            )
            r.raise_for_status()
        except requests.HTTPError as e:
            print(f"  ✗ HTTP {r.status_code}: {e}")
            raise
        
        data = r.json()
        
        # Handle null disease (not found in OpenTargets)
        if not data.get("data") or not data["data"].get("disease"):
            print(f"  ⚠ Disease {efo_id} not found in OpenTargets")
            return []
        
        assoc = data["data"]["disease"]["associatedTargets"]
        
        if total is None:
            total = assoc["count"]
            print(f"  Total associations: {total:,}")
        
        batch = assoc.get("rows") or []
        rows.extend(batch)
        
        if len(rows) >= total or not batch:
            break
        
        index += 1
        time.sleep(0.2)
    
    return rows

def load_opentargets():
    """Load disease-target associations from OpenTargets Platform."""
    diseases = [
        {"name": "Obesity", "efo": "EFO_0001073"},
        {"name": "Type 2 Diabetes", "efo": "EFO_0001360"},
        {"name": "Alzheimer's Disease", "efo": "MONDO_0004975"},
        {"name": "Non-small cell lung cancer", "efo": "EFO_0003060"},
    ]
    
    print(f"Using endpoint: {DEFAULT_ENDPOINT}")
    total_associations = 0
    
    for disease in diseases:
        print(f"\n{disease['name']} ({disease['efo']})")
        try:
            rows = _fetch_associations(disease["efo"], size=200)
            print(f"  ✓ Fetched {len(rows):,} associations")
            total_associations += len(rows)
        except requests.HTTPError:
            print(f"  ✗ Failed to fetch {disease['efo']}")
            continue
        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue
    
    print(f"\n✓ Total associations fetched: {total_associations:,}")
    print("Note: Associations are fetched but not persisted to DB in this POC")
