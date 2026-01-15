#!/usr/bin/env python3
"""
BioGraph data pipeline - loads MeSH, ChEMBL, Companies, and OpenTargets.
Skips ClinicalTrials.gov to avoid long processing times.
"""
import sys
import argparse
from app.db import get_conn

def check_database() -> bool:
    """Verify database connection."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        print("✓ Database connection OK")
        return True
    except Exception as e:
        print(f"✗ Database error: {e}")
        return False

def load_mesh_data():
    """Load MeSH disease taxonomy."""
    print("\n" + "="*60)
    print("STEP 1: Loading MeSH Diseases")
    print("="*60)
    from loaders.load_mesh import load_mesh
    load_mesh(year=2026, promote_diseases=True)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'disease'")
            count = cur.fetchone()['count']
            print(f"✓ Diseases loaded: {count:,}")

def load_chembl_data():
    """Load ChEMBL drugs and targets."""
    print("\n" + "="*60)
    print("STEP 2: Loading ChEMBL Drugs")
    print("="*60)
    from loaders.load_chembl import load_chembl_drugs
    
    poc_drugs = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297735"},
        {"name": "Donepezil", "chembl_id": "CHEMBL521"},
        {"name": "Gefitinib", "chembl_id": "CHEMBL939"},
        {"name": "Erlotinib", "chembl_id": "CHEMBL741"},
    ]
    
    load_chembl_drugs(poc_drugs)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'drug'")
            drugs = cur.fetchone()['count']
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'target'")
            targets = cur.fetchone()['count']
            print(f"✓ Drugs: {drugs:,}, Targets: {targets:,}")

def load_companies_data():
    """Load pharmaceutical companies."""
    print("\n" + "="*60)
    print("STEP 3: Loading Companies")
    print("="*60)
    from loaders.load_companies import load_companies
    
    companies = [
        {"name": "Novo Nordisk", "cik": "0001120193"},
        {"name": "Eli Lilly and Company", "cik": "0000059478"},
        {"name": "Pfizer Inc.", "cik": "0000078003"},
        {"name": "Biogen Inc.", "cik": "0000875045"},
        {"name": "AstraZeneca PLC", "cik": "0000901832"},
        {"name": "F. Hoffmann-La Roche Ltd", "cik": "0001168715"},
    ]
    
    load_companies(companies)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'company'")
            count = cur.fetchone()['count']
            print(f"✓ Companies loaded: {count:,}")

def load_opentargets_data():
    """Load OpenTargets disease-target associations."""
    print("\n" + "="*60)
    print("STEP 4: Loading OpenTargets")
    print("="*60)
    from loaders.load_opentargets import load_opentargets
    load_opentargets()

def show_summary():
    """Display graph statistics."""
    print("\n" + "="*60)
    print("GRAPH SUMMARY")
    print("="*60)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT kind, COUNT(*) as count 
                FROM entity 
                GROUP BY kind 
                ORDER BY count DESC
            """)
            print("\nEntities:")
            for row in cur.fetchall():
                print(f"  {row['kind']:15s}: {row['count']:,}")
            
            cur.execute("SELECT COUNT(*) as count FROM edge")
            edge_count = cur.fetchone()['count']
            print(f"\nEdges: {edge_count:,}")

def main():
    parser = argparse.ArgumentParser(
        description="BioGraph data pipeline (excludes ClinicalTrials.gov)"
    )
    parser.add_argument(
        "--steps",
        help="Comma-separated steps: mesh,chembl,companies,opentargets,summary"
    )
    args = parser.parse_args()
    
    if not check_database():
        sys.exit(1)
    
    steps = {
        "mesh": load_mesh_data,
        "chembl": load_chembl_data,
        "companies": load_companies_data,
        "opentargets": load_opentargets_data,
        "summary": show_summary,
    }
    
    if args.steps:
        step_names = [s.strip() for s in args.steps.split(",")]
        for step_name in step_names:
            if step_name in steps:
                steps[step_name]()
            else:
                print(f"Unknown step: {step_name}")
                print(f"Available: {', '.join(steps.keys())}")
        return
    
    load_mesh_data()
    load_chembl_data()
    load_companies_data()
    load_opentargets_data()
    show_summary()

if __name__ == "__main__":
    main()
