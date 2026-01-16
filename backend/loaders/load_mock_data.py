"""Load mock drug-target and disease-target associations for testing."""
import json
from backend.app.db import get_conn
from backend.loaders.target_mesh import TARGET_MESH_IDS

def load_mock_chembl():
    """Insert mock drugs and targets linked to target diseases."""
    
    mock_drugs = [
        ("CHEMBL1234567", "Pembrolizumab", "immunology"),
        ("CHEMBL2345678", "Bortezomib", "oncology"),
        ("CHEMBL3456789", "Infliximab", "immunology"),
        ("CHEMBL4567890", "Dupilumab", "immunology"),
        ("CHEMBL5678901", "Ustekinumab", "immunology"),
        ("CHEMBL6789012", "Sacubitril", "cardiometabolic"),
        ("CHEMBL7890123", "Aducanumab", "neuroscience"),
    ]
    
    mock_targets = [
        ("CHEMBL_T001", "PDCD1", "PD-1"),
        ("CHEMBL_T002", "PSMB5", "Proteasome"),
        ("CHEMBL_T003", "TNF", "TNF-alpha"),
        ("CHEMBL_T004", "IL4R", "IL-4 Receptor"),
        ("CHEMBL_T005", "IL12B", "IL-12/23"),
        ("CHEMBL_T006", "NEP", "Neprilysin"),
        ("CHEMBL_T007", "APP", "Amyloid Precursor Protein"),
    ]
    
    mock_associations = [
        ("CHEMBL1234567", "CHEMBL_T001", "D002289", 0.85),
        ("CHEMBL2345678", "CHEMBL_T002", "D009101", 0.90),
        ("CHEMBL3456789", "CHEMBL_T003", "D001172", 0.88),
        ("CHEMBL4567890", "CHEMBL_T004", "D003876", 0.92),
        ("CHEMBL5678901", "CHEMBL_T005", "D015212", 0.87),
        ("CHEMBL6789012", "CHEMBL_T006", "D006333", 0.84),
        ("CHEMBL7890123", "CHEMBL_T007", "D000544", 0.89),
    ]
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            drugs_inserted = 0
            targets_inserted = 0
            edges_inserted = 0
            
            for chembl_id, name, ta in mock_drugs:
                cur.execute(
                    "INSERT INTO entity (kind, canonical_id, name, source) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (kind, canonical_id) DO UPDATE SET name = excluded.name, updated_at = now()",
                    ("drug", chembl_id, name, "mock_chembl")
                )
                drugs_inserted += 1
            
            for target_id, symbol, name in mock_targets:
                cur.execute(
                    "INSERT INTO entity (kind, canonical_id, name, source) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (kind, canonical_id) DO UPDATE SET name = excluded.name, updated_at = now()",
                    ("target", target_id, name, "mock_chembl")
                )
                targets_inserted += 1
            
            for drug_id, target_id, mesh_id, score in mock_associations:
                cur.execute(
                    "INSERT INTO edge (src_id, dst_id, type, props) "
                    "SELECT e1.id, e2.id, %s, %s "
                    "FROM entity e1, entity e2 "
                    "WHERE e1.canonical_id = %s AND e2.canonical_id = %s "
                    "ON CONFLICT DO NOTHING",
                    ("inhibits", json.dumps({"score": score, "mesh_id": mesh_id}), drug_id, target_id)
                )
                edges_inserted += 1
            
            conn.commit()
    
    print(f"Mock ChEMBL: Drugs: {drugs_inserted}, Targets: {targets_inserted}, Edges: {edges_inserted}")

def load_mock_opentargets():
    """Insert mock disease-target associations."""
    
    mock_associations = [
        ("D002289", "CHEMBL_T001", 0.85),
        ("D009101", "CHEMBL_T002", 0.90),
        ("D015179", "CHEMBL_T002", 0.78),
        ("D001172", "CHEMBL_T003", 0.88),
        ("D003876", "CHEMBL_T004", 0.92),
        ("D015212", "CHEMBL_T005", 0.87),
        ("D006333", "CHEMBL_T006", 0.84),
        ("D000544", "CHEMBL_T007", 0.89),
    ]
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            edges_inserted = 0
            
            for mesh_id, target_id, score in mock_associations:
                cur.execute(
                    "INSERT INTO edge (src_id, dst_id, type, props) "
                    "SELECT e1.id, e2.id, %s, %s "
                    "FROM entity e1, entity e2 "
                    "WHERE e1.canonical_id = %s AND e2.canonical_id = %s "
                    "ON CONFLICT DO NOTHING",
                    ("associated_with", json.dumps({"score": score}), f"MESH:{mesh_id}", target_id)
                )
                edges_inserted += 1
            
            conn.commit()
    
    print(f"Mock OpenTargets: Disease-target associations: {edges_inserted}")

if __name__ == "__main__":
    load_mock_chembl()
    load_mock_opentargets()
