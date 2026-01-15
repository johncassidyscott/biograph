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
                
                try:
                    cur.execute("""
                        INSERT INTO entity (canonical_id, kind, name)
                        VALUES (%s, %s, %s)
                        RETURNING id
                    """, (
                        f"chembl:{chembl_id}",
                        'drug',
                        name
                    ))
                    drug_id = cur.fetchone()['id']
                    drugs_inserted += 1
                except:
                    # Skip if already exists
                    cur.execute(
                        "SELECT id FROM entity WHERE canonical_id = %s",
                        (f"chembl:{chembl_id}",)
                    )
                    result = cur.fetchone()
                    if not result:
                        continue
                    drug_id = result['id']
                
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
                    
                    try:
                        cur.execute("""
                            INSERT INTO entity (canonical_id, kind, name)
                            VALUES (%s, %s, %s)
                            RETURNING id
                        """, (
                            f"chembl:{target_chembl}",
                            'target',
                            target_name
                        ))
                        target_id = cur.fetchone()['id']
                        targets_inserted += 1
                    except:
                        cur.execute(
                            "SELECT id FROM entity WHERE canonical_id = %s",
                            (f"chembl:{target_chembl}",)
                        )
                        result = cur.fetchone()
                        if not result:
                            continue
                        target_id = result['id']
                    
                    try:
                        cur.execute("""
                            INSERT INTO edge (source_id, target_id, relation)
                            VALUES (%s, %s, %s)
                        """, (
                            drug_id,
                            target_id,
                            f'targets ({action_type})'
                        ))
                        edges_inserted += 1
                    except:
                        pass  # Skip if edge already exists
                    
                    print(f"  → {target_name} ({action_type})")
                
                time.sleep(0.5)
                conn.commit()
            
            print(f"\n✓ Drugs inserted: {drugs_inserted}")
            print(f"✓ Targets inserted: {targets_inserted}")
            print(f"✓ Drug-target edges: {edges_inserted}")
