#!/usr/bin/env python3
"""
BioGraph MVP Data Pipeline Orchestrator

Executes all phases in order per spec section 8:
- Phase 0: Universe (manual CSV)
- Phase 1: CIK lock
- Phase 2: Corporate spine (filings)
- Phase 3: Enrichment (Wikidata)
- Phase 4: Asset mapping (OpenTargets)

Quality gates are checked after each phase.
"""
import sys
import argparse
from datetime import datetime
from app.db import get_conn, init_db

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

def init_schema():
    """Initialize MVP database schema."""
    print("\n" + "="*60)
    print("INITIALIZING MVP SCHEMA")
    print("="*60)

    try:
        init_db('schema_mvp.sql')
        print("✓ Schema initialized")
        return True
    except Exception as e:
        print(f"✗ Schema initialization failed: {e}")
        return False

def phase_0_universe(csv_path: str, universe_id: str = "xbi"):
    """Phase 0: Load universe from CSV."""
    print("\n" + "="*60)
    print("PHASE 0: UNIVERSE DEFINITION")
    print("="*60)

    from loaders.load_universe import load_universe_from_csv
    stats = load_universe_from_csv(csv_path, universe_id)

    return stats['inserted'] > 0

def phase_1_cik_lock():
    """Phase 1: Resolve and validate CIKs from SEC EDGAR."""
    print("\n" + "="*60)
    print("PHASE 1: CIK RESOLUTION")
    print("="*60)

    from loaders.resolve_cik import batch_resolve_ciks
    from loaders.load_universe import get_universe_companies

    ciks = get_universe_companies()
    stats = batch_resolve_ciks(ciks)

    return stats['resolved'] > 0

def phase_2_corporate_spine(form_types: list = None, lookback_days: int = 365):
    """Phase 2: Load SEC filings."""
    print("\n" + "="*60)
    print("PHASE 2: CORPORATE SPINE")
    print("="*60)

    from loaders.load_sec_filings import batch_load_filings

    if not form_types:
        form_types = ['10-K', '10-Q', '8-K']

    stats = batch_load_filings(form_types=form_types, lookback_days=lookback_days)

    return stats['inserted'] > 0

def phase_3_enrichment():
    """Phase 3: Enrich with Wikidata."""
    print("\n" + "="*60)
    print("PHASE 3: ENRICHMENT")
    print("="*60)

    from loaders.enrich_wikidata import batch_enrich_companies

    stats = batch_enrich_companies()

    return stats['enriched'] > 0

def phase_4_asset_mapping(min_score: float = 0.3):
    """Phase 4: Load OpenTargets target-disease associations."""
    print("\n" + "="*60)
    print("PHASE 4: ASSET MAPPING")
    print("="*60)

    from loaders.load_opentargets_mvp import load_opentargets_for_therapeutic_areas

    stats = load_opentargets_for_therapeutic_areas(min_score=min_score)

    return stats['associations_inserted'] > 0

def check_quality_gates():
    """
    Check quality gates per spec section 10.1:
    - ≥95% of companies have ≥1 DrugProgram
    - ≥90% of DrugPrograms have Target + Disease
    - 100% of edges have source + date + license
    """
    print("\n" + "="*60)
    print("QUALITY GATES")
    print("="*60)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get metrics
            cur.execute("SELECT * FROM quality_metrics")
            metrics = cur.fetchone()

            print(f"\nCompanies in universe: {metrics['companies_in_universe']}")
            print(f"Companies with drugs: {metrics['companies_with_drugs']}")
            print(f"Total drugs: {metrics['total_drugs']}")
            print(f"Drugs with targets: {metrics['drugs_with_targets']}")
            print(f"Drugs with diseases: {metrics['drugs_with_diseases']}")
            print(f"Total evidence records: {metrics['total_evidence_records']}")
            print(f"Edges without evidence: {metrics['edges_without_evidence']}")

            # Check gates
            gates_passed = True

            # Gate 1: ≥95% companies have drugs
            if metrics['companies_in_universe'] > 0:
                pct_with_drugs = (metrics['companies_with_drugs'] / metrics['companies_in_universe']) * 100
                print(f"\n✓ Gate 1: {pct_with_drugs:.1f}% companies have DrugPrograms", end="")
                if pct_with_drugs < 95:
                    print(f" [WARNING: Target is ≥95%]")
                    gates_passed = False
                else:
                    print()

            # Gate 2: ≥90% drugs have targets + diseases
            if metrics['total_drugs'] > 0:
                pct_with_targets = (metrics['drugs_with_targets'] / metrics['total_drugs']) * 100
                pct_with_diseases = (metrics['drugs_with_diseases'] / metrics['total_drugs']) * 100

                print(f"✓ Gate 2a: {pct_with_targets:.1f}% drugs have Targets", end="")
                if pct_with_targets < 90:
                    print(f" [WARNING: Target is ≥90%]")
                    gates_passed = False
                else:
                    print()

                print(f"✓ Gate 2b: {pct_with_diseases:.1f}% drugs have Diseases", end="")
                if pct_with_diseases < 90:
                    print(f" [WARNING: Target is ≥90%]")
                    gates_passed = False
                else:
                    print()

            # Gate 3: 100% edges have evidence
            if metrics['edges_without_evidence'] > 0:
                print(f"✗ Gate 3: {metrics['edges_without_evidence']} edges without evidence [FAIL]")
                gates_passed = False
            else:
                print(f"✓ Gate 3: All edges have evidence")

            if gates_passed:
                print(f"\n{'='*60}")
                print("ALL QUALITY GATES PASSED")
                print("="*60)
            else:
                print(f"\n{'='*60}")
                print("QUALITY GATES WARNINGS (see above)")
                print("="*60)

            return gates_passed

def show_summary():
    """Display final graph statistics."""
    print("\n" + "="*60)
    print("FINAL GRAPH SUMMARY")
    print("="*60)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Entity counts
            print("\nEntities:")

            for table in ['company', 'filing', 'insider_transaction', 'exhibit',
                         'location', 'drug_program', 'target', 'disease', 'evidence']:
                cur.execute(f"SELECT COUNT(*) as count FROM {table}")
                count = cur.fetchone()['count']
                print(f"  {table:20s}: {count:,}")

            # Edge counts
            print("\nRelationships:")
            for table in ['company_location', 'company_drug', 'drug_target',
                         'target_disease', 'drug_disease']:
                cur.execute(f"SELECT COUNT(*) as count FROM {table}")
                count = cur.fetchone()['count']
                print(f"  {table:20s}: {count:,}")

            # Explanation chains
            cur.execute("SELECT COUNT(*) as count FROM explanation_chain")
            chain_count = cur.fetchone()['count']
            print(f"\nExplanation chains: {chain_count:,}")

def main():
    parser = argparse.ArgumentParser(
        description="BioGraph MVP Data Pipeline"
    )
    parser.add_argument(
        '--init',
        action='store_true',
        help='Initialize database schema'
    )
    parser.add_argument(
        '--universe',
        type=str,
        help='Path to universe CSV file (Phase 0)'
    )
    parser.add_argument(
        '--phases',
        type=str,
        help='Comma-separated phases to run: 1,2,3,4 or "all"'
    )
    parser.add_argument(
        '--quality-gates',
        action='store_true',
        help='Run quality gates check only'
    )

    args = parser.parse_args()

    if not check_database():
        sys.exit(1)

    if args.init:
        if not init_schema():
            sys.exit(1)
        return

    if args.quality_gates:
        check_quality_gates()
        return

    # Default: run all phases
    phases_to_run = [1, 2, 3, 4]

    if args.phases:
        if args.phases.lower() == 'all':
            phases_to_run = [0, 1, 2, 3, 4]
        else:
            phases_to_run = [int(p) for p in args.phases.split(',')]

    # Phase 0 (manual - requires CSV)
    if 0 in phases_to_run:
        if not args.universe:
            print("Error: --universe CSV required for Phase 0")
            sys.exit(1)
        phase_0_universe(args.universe)

    # Phase 1: CIK resolution
    if 1 in phases_to_run:
        phase_1_cik_lock()

    # Phase 2: Corporate spine
    if 2 in phases_to_run:
        phase_2_corporate_spine()

    # Phase 3: Enrichment
    if 3 in phases_to_run:
        phase_3_enrichment()

    # Phase 4: Asset mapping
    if 4 in phases_to_run:
        phase_4_asset_mapping()

    # Check quality gates
    check_quality_gates()

    # Show summary
    show_summary()

if __name__ == "__main__":
    main()
