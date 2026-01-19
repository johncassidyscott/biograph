#!/usr/bin/env python3
"""
Phase 0: Universe Loader
Loads the curated list of companies that define the in-scope universe.

Per spec section 2.1: Universe = curated list of indexed/ETF-listed US issuers
"""
import csv
from datetime import datetime
from typing import List, Dict
from ..app.db import get_conn

def normalize_cik(cik: str) -> str:
    """Normalize CIK to 10-digit zero-padded string."""
    return str(cik).strip().zfill(10)

def load_universe_from_csv(csv_path: str, default_universe_id: str = "xbi") -> Dict[str, int]:
    """
    Load universe from CSV file.

    Expected columns:
    - company_name (required)
    - ticker (required)
    - exchange (required)
    - cik (required)
    - universe_id (optional, defaults to default_universe_id)
    - start_date (optional, defaults to today)
    - notes (optional)

    Returns:
        Dict with 'inserted' and 'updated' counts
    """
    stats = {'inserted': 0, 'updated': 0, 'discarded': 0}

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        companies = list(reader)

    print(f"Processing {len(companies)} companies from {csv_path}")

    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in companies:
                # Validate required fields
                if not all([row.get('company_name'), row.get('cik')]):
                    print(f"⚠ Skipping row with missing data: {row}")
                    stats['discarded'] += 1
                    continue

                cik = normalize_cik(row['cik'])
                universe_id = row.get('universe_id', default_universe_id)
                start_date = row.get('start_date', datetime.now().date().isoformat())

                # Insert into universe_membership
                try:
                    cur.execute("""
                        INSERT INTO universe_membership
                        (company_cik, universe_id, start_date, notes)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (company_cik, universe_id, start_date)
                        DO NOTHING
                        RETURNING id
                    """, (cik, universe_id, start_date, row.get('notes', '')))

                    if cur.fetchone():
                        stats['inserted'] += 1
                        print(f"  ✓ {row['company_name']} ({row.get('ticker', 'N/A')}) → {cik}")
                    else:
                        stats['updated'] += 1

                except Exception as e:
                    print(f"  ✗ Error processing {row['company_name']}: {e}")
                    stats['discarded'] += 1
                    conn.rollback()
                    continue

            conn.commit()

    print(f"\n{'='*60}")
    print(f"Universe Loading Complete")
    print(f"{'='*60}")
    print(f"Inserted: {stats['inserted']}")
    print(f"Skipped (already exists): {stats['updated']}")
    print(f"Discarded: {stats['discarded']}")

    return stats

def get_universe_companies(universe_id: str = None) -> List[str]:
    """
    Get list of CIKs currently in universe.

    Args:
        universe_id: Filter by universe (None = all universes)

    Returns:
        List of CIK strings
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if universe_id:
                cur.execute("""
                    SELECT DISTINCT company_cik
                    FROM universe_membership
                    WHERE universe_id = %s AND end_date IS NULL
                    ORDER BY company_cik
                """, (universe_id,))
            else:
                cur.execute("""
                    SELECT DISTINCT company_cik
                    FROM universe_membership
                    WHERE end_date IS NULL
                    ORDER BY company_cik
                """)

            return [row['company_cik'] for row in cur.fetchall()]

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python load_universe.py <csv_file> [universe_id]")
        sys.exit(1)

    csv_path = sys.argv[1]
    universe_id = sys.argv[2] if len(sys.argv) > 2 else "xbi"

    load_universe_from_csv(csv_path, universe_id)
