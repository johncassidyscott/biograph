#!/usr/bin/env python3
import sys, argparse, importlib, runpy
from app.db import get_conn
def check_database():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur: cur.execute("SELECT 1")
        print("✓ Database OK"); return True
    except Exception as e:
        print(f"✗ DB error: {e}"); return False
def load_mesh_data():
    print("\nSTEP 1: Loading MeSH")
    from loaders.load_mesh import load_mesh
    load_mesh(year=2026, promote_diseases=True)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'disease'")
            print(f"✓ Diseases: {cur.fetchone()['count']:,}")
def load_chembl_data():
    print("\nSTEP 2: Loading ChEMBL")
    from loaders.load_chembl import load_chembl_drugs
    poc_drugs = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297735"},
        {"name": "Donepezil", "chembl_id": "CHEMBL521"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL4698148"},
        {"name": "Gefitinib", "chembl_id": "CHEMBL939"},
        {"name": "Erlotinib", "chembl_id": "CHEMBL741"},
        {"name": "Trametinib", "chembl_id": "CHEMBL1788406"},
    ]
    load_chembl_drugs(poc_drugs)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'drug'"); drugs = cur.fetchone()['count']
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'target'"); targets = cur.fetchone()['count']
            print(f"✓ Drugs: {drugs:,}, Targets: {targets:,}")
def load_companies_data():
    print("\nSTEP 3: Loading Companies")
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
            print(f"✓ Companies: {cur.fetchone()['count']:,}")
def load_opentargets_data():
    print("\nSTEP 4: Loading OpenTargets")
    from loaders.load_opentargets import load_opentargets
    load_opentargets()
def show_summary():
    print("\n===== SUMMARY =====")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT kind, COUNT(*) c FROM entity GROUP BY kind ORDER BY c DESC")
            for row in cur.fetchall(): print(f"  {row['kind']:15s}: {row['c']:,}")
            cur.execute("SELECT COUNT(*) c FROM edge"); print(f"\n  Total edges: {cur.fetchone()['c']:,}")
def main():
    parser = argparse.ArgumentParser(description="BioGraph Builder (no CT.gov)")
    parser.add_argument("--steps", help="mesh,chembl,companies,opentargets,summary")
    args = parser.parse_args()
    if not check_database(): sys.exit(1)
    steps = {
        "mesh": load_mesh_data,
        "chembl": load_chembl_data,
        "companies": load_companies_data,
        "opentargets": load_opentargets_data,
        "summary": show_summary,
    }
    if args.steps:
        for s in args.steps.split(","):
            fn = steps.get(s.strip())
            fn() if fn else print(f"Unknown step: {s}")
        return
    load_mesh_data(); load_chembl_data(); load_companies_data(); load_opentargets_data(); show_summary()
if __name__ == "__main__": main()
