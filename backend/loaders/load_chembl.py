"""Load drug and target data from ChEMBL."""
import requests
import pandas as pd
from backend.app.db import get_conn
from backend.loaders.filter_utils import filter_to_target_mesh
from backend.loaders.target_mesh import TARGET_MESH_IDS

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"

def load_chembl():
    """Load drugs and their targets from ChEMBL, filtered to target MeSH IDs."""
    
    print(f"Loading ChEMBL data filtered to {len(TARGET_MESH_IDS)} target MeSH IDs...")
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            drugs_inserted = 0
            targets_inserted = 0
            edges_inserted = 0
            
            # Fetch target data from ChEMBL API (all targets first, filter after)
            try:
                print("Fetching targets from ChEMBL...")
                targets_resp = requests.get(f"{CHEMBL_BASE}/target", params={"limit": 10000}, timeout=30)
                targets_resp.raise_for_status()
                targets_data = targets_resp.json()
                
                # Convert to DataFrame for filtering
                targets_list = targets_data.get("results", [])
                if targets_list:
                    df_targets = pd.DataFrame(targets_list)
                    
                    # Filter to targets with MeSH IDs in our target set
                    if "cross_references" in df_targets.columns:
                        df_targets = df_targets[df_targets["cross_references"].apply(
                            lambda cr: any(
                                ref.get("xref_id") in TARGET_MESH_IDS 
                                for ref in (cr if isinstance(cr, list) else [])
                                if isinstance(ref, dict) and ref.get("xref_src") == "MeSH"
                            )
                        )]
                        print(f"Filtered to {len(df_targets)} targets with target MeSH IDs")
                    
                    # Insert targets
                    for _, row in df_targets.iterrows():
                        chembl_id = row.get("target_chembl_id")
                        name = row.get("pref_name", "")
                        if chembl_id and name:
                            cur.execute(
                                """
                                INSERT INTO entity (kind, canonical_id, name, source)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (kind, canonical_id) DO UPDATE
                                SET name = excluded.name, updated_at = now()
                                """,
                                ("target", f"CHEMBL:{chembl_id}", name, "chembl")
                            )
                            targets_inserted += 1
                    
                    conn.commit()
                
                # Fetch drugs linked to filtered targets (simplified; full implementation needs drug-target assay data)
                print("ChEMBL: Targets inserted successfully")
                
            except requests.RequestException as e:
                print(f"Error fetching ChEMBL data: {e}")
    
    print(f"ChEMBL: Drugs inserted: {drugs_inserted}, Targets: {targets_inserted}, Edges: {edges_inserted}")

if __name__ == "__main__":
    load_chembl()
