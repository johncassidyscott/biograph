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

def load_companies_data():
    """Step 4: Load pharmaceutical companies"""
    print("\n" + "="*60)
    print("STEP 4: Loading Pharmaceutical Companies")
    print("="*60)
    from loaders.load_companies import load_companies

    poc_companies = [
        {"name": "Eli Lilly and Company", "cik": "0000059478", "develops": ["CHEMBL4297448"], "aliases": ["Eli Lilly", "Lilly"]},
        {"name": "Novo Nordisk A/S", "cik": "0000353278", "develops": ["CHEMBL2109743", "CHEMBL1201580", "CHEMBL2107834"], "aliases": ["Novo Nordisk", "Novo"]},
        {"name": "Eisai Co., Ltd.", "cik": "0001062822", "develops": ["CHEMBL2366541"], "aliases": ["Eisai"]},
        {"name": "Biogen Inc.", "cik": "0000875045", "develops": ["CHEMBL4297072"], "aliases": ["Biogen", "Biogen Idec"]},
        {"name": "Amgen Inc.", "cik": "0000318154", "develops": ["CHEMBL4297299"], "aliases": ["Amgen"]},
        {"name": "Mirati Therapeutics, Inc.", "cik": "0001440718", "develops": ["CHEMBL4594668"], "aliases": ["Mirati", "Mirati Therapeutics"]},
    ]

    load_companies(poc_companies)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'company' AND canonical_id LIKE 'CIK:%'")
            count = cur.fetchone()[0]
            print(f"✓ Companies with CIK: {count:,}")

def load_opentargets_data():
    """Step 5: Load OpenTargets drug-target-disease associations"""
    print("\n" + "="*60)
    print("STEP 5: Loading Drug-Target-Disease Associations")
    print("="*60)
    from loaders.load_opentargets import load_opentargets_associations

    # POC disease mappings (MESH ID -> EFO ID)
    poc_diseases = [
        {"mesh_id": "D009765", "efo_id": "EFO_0001360", "name": "Obesity"},
        {"mesh_id": "D000544", "efo_id": "EFO_0000249", "name": "Alzheimer's Disease"},
        {"mesh_id": "D002289", "efo_id": "EFO_0003060", "name": "Non-small cell lung cancer"},
    ]

    load_opentargets_associations(poc_diseases, min_score=0.3)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM edge WHERE source = 'opentargets'")
            count = cur.fetchone()[0]
            print(f"✓ OpenTargets associations: {count:,}")

def infer_drug_disease_data():
    """Step 6: Infer drug-disease relationships from trials"""
    print("\n" + "="*60)
    print("STEP 6: Inferring Drug-Disease Relationships")
    print("="*60)
    from loaders.infer_drug_disease import infer_drug_disease_relationships

    infer_drug_disease_relationships(min_phase=2)

def load_pubmed_data():
    """Step 7: Load recent PubMed publications"""
    print("\n" + "="*60)
    print("STEP 7: Loading Recent Publications")
    print("="*60)
    from loaders.load_pubmed import load_pubmed_for_drugs

    poc_queries = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743", "query": "Semaglutide AND (obesity OR weight loss)"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448", "query": "Tirzepatide AND (obesity OR diabetes)"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL2366541", "query": "Lecanemab AND Alzheimer"},
        {"name": "Sotorasib", "chembl_id": "CHEMBL4297299", "query": "Sotorasib AND (KRAS OR lung cancer)"},
    ]

    load_pubmed_for_drugs(poc_queries, max_per_drug=10)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'publication'")
            count = cur.fetchone()[0]
            print(f"✓ Publications: {count:,}")

def load_fda_data():
    """Step 8: Load FDA drug approvals"""
    print("\n" + "="*60)
    print("STEP 8: Loading FDA Drug Approvals")
    print("="*60)
    from loaders.load_fda import load_fda_approvals

    poc_drugs = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448"},
        {"name": "Liraglutide", "chembl_id": "CHEMBL1201580"},
        {"name": "Donepezil", "chembl_id": "CHEMBL502"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL2366541"},
        {"name": "Sotorasib", "chembl_id": "CHEMBL4297299"},
    ]

    load_fda_approvals(poc_drugs)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM drug_approval")
            count = cur.fetchone()[0]
            print(f"✓ FDA approvals: {count:,}")

def load_patents_data():
    """Step 9: Load USPTO patents"""
    print("\n" + "="*60)
    print("STEP 9: Loading USPTO Patents")
    print("="*60)
    from loaders.load_patents import load_patents

    poc_drugs = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL2366541"},
        {"name": "Sotorasib", "chembl_id": "CHEMBL4297299"},
        {"name": "Adagrasib", "chembl_id": "CHEMBL4594668"},
    ]

    load_patents(poc_drugs)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'patent'")
            count = cur.fetchone()[0]
            print(f"✓ Patents: {count:,}")

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

    # Step 4: Companies with CIK identifiers
    load_companies_data()

    # Step 5: OpenTargets drug-target-disease associations
    load_opentargets_data()

    # Step 6: Infer drug-disease relationships from trials
    infer_drug_disease_data()

    # Step 7: Recent PubMed publications
    load_pubmed_data()

    # Step 8: FDA drug approvals
    load_fda_data()

    # Step 9: USPTO patents
    load_patents_data()

    # Summary
    show_summary()

    print("✅ POC Graph build complete!\n")

if __name__ == "__main__":
    main()
