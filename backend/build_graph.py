#!/usr/bin/env python3
"""
BioGraph POC Builder
Loads all data sources in the correct order to build the knowledge graph.
"""
import datetime as dt
import sys
from app.db import get_conn

def check_database():
    """Verify database connection and schema"""
    print("🔍 Checking database connection...")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM entity")
                count = cur.fetchone()[0]
                print(f"✓ Database connected. Current entities: {count:,}")
                return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def load_mesh_data():
    """Step 1: Load MeSH foundation and promote diseases"""
    print("\n" + "="*60)
    print("STEP 1: Loading MeSH Diseases")
    print("="*60)
    from loaders.load_mesh import load_mesh
    load_mesh(year=2026, promote_diseases=True)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'disease'")
            count = cur.fetchone()[0]
            print(f"✓ Diseases loaded: {count:,}")

def load_chembl_data():
    """Step 2: Load ChEMBL drugs and targets"""
    print("\n" + "="*60)
    print("STEP 2: Loading Drugs and Targets from ChEMBL")
    print("="*60)
    from loaders.load_chembl import load_chembl_drugs

    # POC drug list
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

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'drug'")
            drug_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'target'")
            target_count = cur.fetchone()[0]
            print(f"✓ Drugs: {drug_count:,}, Targets: {target_count:,}")

def load_ctgov_data():
    """Step 3: Load ClinicalTrials.gov data"""
    print("\n" + "="*60)
    print("STEP 3: Loading Clinical Trials")
    print("="*60)
    from loaders.load_ctgov import load_ctgov

    # POC queries from your spec
    queries = [
        "obesity",
        "alzheimer disease",
        "KRAS AND non-small cell lung cancer",
    ]

    # Jan 2024 - Jan 2025 time window
    min_d = dt.date(2024, 1, 1)
    max_d = dt.date(2025, 1, 31)

    load_ctgov(
        condition_queries=queries,
        min_last_update=min_d,
        max_last_update=max_d
    )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trial")
            count = cur.fetchone()[0]
            print(f"✓ Trials loaded: {count:,}")

def show_summary():
    """Show final graph statistics"""
    print("\n" + "="*60)
    print("GRAPH SUMMARY")
    print("="*60)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Entity counts by kind
            cur.execute("""
                SELECT kind, COUNT(*) as count
                FROM entity
                GROUP BY kind
                ORDER BY count DESC
            """)
            print("\nEntities by type:")
            total_entities = 0
            for row in cur.fetchall():
                print(f"  {row[0]:15s}: {row[1]:,}")
                total_entities += row[1]

            # Edge counts
            cur.execute("SELECT COUNT(*) FROM edge")
            edge_count = cur.fetchone()[0]
            print(f"\nTotal edges: {edge_count:,}")

            # Edge breakdown by source
            cur.execute("""
                SELECT source, COUNT(*) as count
                FROM edge
                GROUP BY source
                ORDER BY count DESC
            """)
            print("\nEdges by source:")
            for row in cur.fetchall():
                source = row[0] or 'unknown'
                print(f"  {source:15s}: {row[1]:,}")

            print(f"\n{'='*60}")
            print(f"Total entities: {total_entities:,}")
            print(f"Total edges: {edge_count:,}")
            print(f"Total triples: {edge_count:,}")
            print(f"{'='*60}\n")

def main():
    """Build the complete POC graph"""
    print("""
╔══════════════════════════════════════════════════════════╗
║           BioGraph POC Knowledge Graph Builder           ║
║                                                          ║
║  Disease areas: Obesity, Alzheimer's, KRAS Oncology    ║
║  Time window: Jan 2024 - Jan 2025                       ║
╚══════════════════════════════════════════════════════════╝
""")

    if not check_database():
        sys.exit(1)

    # Step 1: MeSH diseases (foundation)
    load_mesh_data()

    # Step 2: ChEMBL drugs and targets
    load_chembl_data()

    # Step 3: Clinical trials
    load_ctgov_data()

    # TODO: Add more loaders here as we build them:
    # - OpenTargets drug-target-disease associations
    # - Company data (SEC EDGAR)
    # - PubMed publications

    # Summary
    show_summary()

    print("✅ POC Graph build complete!\n")

if __name__ == "__main__":
    main()
