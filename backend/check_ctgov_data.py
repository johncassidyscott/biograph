#!/usr/bin/env python3
"""
Check CT.gov data load status
"""
from app.db import get_conn
from datetime import datetime

def check_ctgov_data():
    with get_conn() as conn:
        with conn.cursor() as cur:
            print("=" * 60)
            print("CT.gov Data Load Status")
            print("=" * 60)

            # Check trial count
            cur.execute('SELECT COUNT(*) FROM trial')
            trial_count = cur.fetchone()[0]
            print(f"\n✓ Trials in trial table: {trial_count:,}")

            # Check trial entities
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'trial'")
            trial_entity_count = cur.fetchone()[0]
            print(f"✓ Trial entities: {trial_entity_count:,}")

            # Check companies from CT.gov
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'company' AND canonical_id LIKE 'CTG_SPONSOR:%'")
            company_count = cur.fetchone()[0]
            print(f"✓ Companies (sponsors): {company_count:,}")

            # Check drugs from CT.gov
            cur.execute("SELECT COUNT(*) FROM entity WHERE kind = 'drug' AND canonical_id LIKE 'CTG_INT:%'")
            drug_count = cur.fetchone()[0]
            print(f"✓ Drugs (interventions): {drug_count:,}")

            # Check edges from CT.gov
            cur.execute("SELECT COUNT(*) FROM edge WHERE source = 'ctgov'")
            edge_count = cur.fetchone()[0]
            print(f"✓ Edges from CT.gov: {edge_count:,}")

            # Edge breakdown
            print("\nEdge breakdown:")
            cur.execute("""
                SELECT predicate, COUNT(*) as count
                FROM edge
                WHERE source = 'ctgov'
                GROUP BY predicate
                ORDER BY count DESC
            """)
            for row in cur.fetchall():
                print(f"  - {row[0]}: {row[1]:,}")

            # Phase distribution
            print("\nPhase distribution:")
            cur.execute("""
                SELECT
                    CASE
                        WHEN phase_min IS NULL THEN 'No phase'
                        ELSE 'Phase ' || phase_min::text
                    END as phase,
                    COUNT(*) as count
                FROM trial
                GROUP BY phase_min
                ORDER BY phase_min NULLS LAST
            """)
            for row in cur.fetchall():
                print(f"  - {row[0]}: {row[1]:,}")

            # Status distribution
            print("\nTop 5 statuses:")
            cur.execute("""
                SELECT overall_status, COUNT(*) as count
                FROM trial
                WHERE overall_status IS NOT NULL
                GROUP BY overall_status
                ORDER BY count DESC
                LIMIT 5
            """)
            for row in cur.fetchall():
                print(f"  - {row[0]}: {row[1]:,}")

            # Date range
            print("\nDate range:")
            cur.execute("""
                SELECT
                    MIN(last_update_posted) as earliest,
                    MAX(last_update_posted) as latest
                FROM trial
                WHERE last_update_posted IS NOT NULL
            """)
            row = cur.fetchone()
            if row[0] and row[1]:
                print(f"  Last updates: {row[0]} to {row[1]}")

            # Sample trials
            print("\nSample trials:")
            cur.execute("""
                SELECT nct_id, title, phase_min, overall_status, last_update_posted
                FROM trial
                ORDER BY last_update_posted DESC
                LIMIT 5
            """)
            for i, row in enumerate(cur.fetchall(), 1):
                title = (row[1][:50] + '...') if row[1] and len(row[1]) > 50 else (row[1] or 'No title')
                phase = f"Phase {row[2]}" if row[2] else 'N/A'
                status = row[3] or 'Unknown'
                date = row[4].strftime('%Y-%m-%d') if row[4] else 'N/A'
                print(f"\n  {i}. {row[0]}")
                print(f"     {title}")
                print(f"     {phase} | {status} | Updated: {date}")

            print("\n" + "=" * 60)

            if trial_count == 0:
                print("\n⚠️  WARNING: No trial data found!")
                print("   The CT.gov loader may not have run yet.")
            else:
                print(f"\n✅ SUCCESS: {trial_count:,} trials loaded")

if __name__ == "__main__":
    try:
        check_ctgov_data()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
