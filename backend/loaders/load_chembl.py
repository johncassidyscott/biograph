"""Load drug and target data from ChEMBL."""
import requests
import time
from typing import List, Dict
from app.db import get_conn

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"

def load_chembl_drugs(drug_list: List[Dict[str, str]]):
    """Load drugs and their targets from ChEMBL."""
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            drugs_inserted = 0
            targets_inserted = 0
            edges_inserted = 0
            
            for drug in drug_list:
                name = drug["name"]
                chembl_id = drug["chembl_id"]
                
                print(f"\nProcessing: {name} ({chembl_id})")
                
                try:
                    url = f"{CHEMBL_BASE}/molecule/{chembl_id}.json"
                    r = requests.get(url, timeout=30)
                    r.raise_for_status()
                    mol_data = r.json()
                except Exception as e:
                    print(f"Warning: Could not fetch {chembl_id}: {e}")
                    continue
                
                cur.execute("""
                    INSERT INTO entity (external_id, kind, name, attributes)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (external_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        attributes = EXCLUDED.attributes
                    RETURNING id
                """, (
                    chembl_id,
                    'drug',
                    name,
                    {'chembl_id': chembl_id, 'max_phase': mol_data.get('max_phase')}
                ))
                drug_id = cur.fetchone()['id']
                drugs_inserted += 1
                
                try:
                    mech_url = f"{CHEMBL_BASE}/mechanism.json?molecule_chembl_id={chembl_id}"
                    r = requests.get(mech_url, timeout=30)
                    r.raise_for_status()
                    mechanisms = r.json().get('mechanisms', [])
                except Exception as e:
                    print(f"Warning: Could not fetch mechanisms: {e}")
                    mechanisms = []
                
                for mech in mechanisms:
                    target_chembl = mech.get('target_chembl_id')
                    if not target_chembl:
                        continue
                    
                    target_name = mech.get('target_name', 'Unknown')
                    action_type = mech.get('action_type', 'UNKNOWN')
                    
                    cur.execute("""
                        INSERT INTO entity (external_id, kind, name, attributes)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (external_id) DO UPDATE
                        SET name = EXCLUDED.name
                        RETURNING id
                    """, (
                        target_chembl,
                        'target',
                        target_name,
                        {'chembl_id': target_chembl}
                    ))
                    target_id = cur.fetchone()['id']
                    targets_inserted += 1
                    
                    cur.execute("""
                        INSERT INTO edge (source_id, target_id, relation, attributes)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (source_id, target_id, relation) DO NOTHING
                    """, (
                        drug_id,
                        target_id,
                        'targets',
                        {'action': action_type}
                    ))
                    edges_inserted += 1
                    print(f"  → {target_name} ({action_type})")
                
                time.sleep(0.5)
                conn.commit()
            
            print(f"\n✓ Drugs inserted: {drugs_inserted}")
            print(f"✓ Targets inserted: {targets_inserted}")
            print(f"✓ Drug-target edges: {edges_inserted}")
