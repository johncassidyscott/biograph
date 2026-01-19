#!/usr/bin/env python3
"""
Phase 0: Universe Loader (v8.1)

Loads curated list of issuers with issuer identity model.

Per v8.1 Fix #1:
- Issuer is internal stable key
- CIK is linked via issuer_cik_history
- Changes are MANUAL only (no automated inference)
"""
import csv
from datetime import datetime, date
from typing import List, Dict
from ..app.db import get_conn

def normalize_cik(cik: str) -> str:
    """Normalize CIK to 10-digit zero-padded string."""
    return str(cik).strip().zfill(10)

def generate_issuer_id(cik: str, ticker: str = None) -> str:
    """
    Generate deterministic issuer_id.

    Format: ISS_{CIK}
    This is stable even if CIK changes (manual update process).
    """
    return f"ISS_{normalize_cik(cik)}"

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
        Dict with 'inserted', 'updated', 'discarded' counts
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
                ticker = row.get('ticker', '')
                universe_id = row.get('universe_id', default_universe_id)
                start_date = row.get('start_date', date.today().isoformat())

                # Generate issuer_id
                issuer_id = generate_issuer_id(cik, ticker)

                try:
                    # Insert issuer (idempotent)
                    cur.execute("""
                        INSERT INTO issuer (issuer_id, primary_cik, notes)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (issuer_id) DO UPDATE
                        SET primary_cik = EXCLUDED.primary_cik,
                            notes = EXCLUDED.notes
                        RETURNING issuer_id
                    """, (issuer_id, cik, row.get('notes', '')))

                    cur.fetchone()

                    # Insert CIK history
                    cur.execute("""
                        INSERT INTO issuer_cik_history
                        (issuer_id, cik, start_date, source, observed_at, notes)
                        VALUES (%s, %s, %s, 'manual', NOW(), 'Initial load')
                        ON CONFLICT (issuer_id, cik, start_date) DO NOTHING
                    """, (issuer_id, cik, start_date))

                    # Insert universe membership
                    cur.execute("""
                        INSERT INTO universe_membership
                        (issuer_id, universe_id, start_date, notes)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (issuer_id, universe_id, start_date) DO NOTHING
                        RETURNING id
                    """, (issuer_id, universe_id, start_date, row.get('notes', '')))

                    if cur.fetchone():
                        stats['inserted'] += 1
                        print(f"  ✓ {row['company_name']} ({ticker or 'N/A'}) → {issuer_id} (CIK: {cik})")
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

def get_universe_issuers(universe_id: str = None) -> List[tuple]:
    """
    Get list of issuers currently in universe.

    Args:
        universe_id: Filter by universe (None = all universes)

    Returns:
        List of (issuer_id, cik) tuples
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if universe_id:
                cur.execute("""
                    SELECT DISTINCT i.issuer_id, i.primary_cik
                    FROM issuer i
                    JOIN universe_membership um ON i.issuer_id = um.issuer_id
                    WHERE um.universe_id = %s AND um.end_date IS NULL
                    ORDER BY i.issuer_id
                """, (universe_id,))
            else:
                cur.execute("""
                    SELECT DISTINCT i.issuer_id, i.primary_cik
                    FROM issuer i
                    JOIN universe_membership um ON i.issuer_id = um.issuer_id
                    WHERE um.end_date IS NULL
                    ORDER BY i.issuer_id
                """)

            return [(row['issuer_id'], row['primary_cik']) for row in cur.fetchall()]

def update_issuer_cik(
    issuer_id: str,
    new_cik: str,
    effective_date: date,
    source: str = 'manual',
    notes: str = ''
) -> bool:
    """
    Update issuer's CIK (e.g., after merger/spinoff).

    This is a MANUAL operation per spec.

    Args:
        issuer_id: Issuer to update
        new_cik: New CIK
        effective_date: When change became effective
        source: Source of change (default: 'manual')
        notes: Explanation

    Returns:
        True if successful
    """
    new_cik = normalize_cik(new_cik)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # End current CIK
            cur.execute("""
                UPDATE issuer_cik_history
                SET end_date = %s
                WHERE issuer_id = %s AND end_date IS NULL
            """, (effective_date, issuer_id))

            # Add new CIK
            cur.execute("""
                INSERT INTO issuer_cik_history
                (issuer_id, cik, start_date, source, observed_at, notes)
                VALUES (%s, %s, %s, %s, NOW(), %s)
            """, (issuer_id, new_cik, effective_date, source, notes))

            # Update primary CIK
            cur.execute("""
                UPDATE issuer
                SET primary_cik = %s
                WHERE issuer_id = %s
            """, (new_cik, issuer_id))

            conn.commit()

            print(f"✓ Updated {issuer_id} → CIK {new_cik} (effective: {effective_date})")
            return True

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python load_universe_v8_1.py <csv_file> [universe_id]")
        sys.exit(1)

    csv_path = sys.argv[1]
    universe_id = sys.argv[2] if len(sys.argv) > 2 else "xbi"

    load_universe_from_csv(csv_path, universe_id)
