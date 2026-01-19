#!/usr/bin/env python3
"""
BioGraph Company Universe CSV Loader

Loads company/issuer data from CSV into the BioGraph database.

Usage:
    python scripts/load_company_universe.py --csv path/to/universe.csv

CSV Schema (see docs/CSV_SCHEMAS.md for details):
    Required columns:
        - cik: 10-digit SEC CIK (e.g., "0000078003")
        - company_name: SEC legal name

    Optional columns:
        - ticker: Stock ticker symbol
        - exchange: Exchange (NYSE, NASDAQ, etc.)
        - universe_id: Universe membership (e.g., "xbi", "ibb")
        - revenue_usd: Annual revenue in USD
        - employees: Employee count
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from typing import Optional

import psycopg
from psycopg.rows import dict_row


def get_database_url() -> str:
    """Get database URL from environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable not set")
    return url


def format_cik(cik: str) -> str:
    """Format CIK as 10-digit zero-padded string."""
    # Remove any leading zeros and re-pad
    return str(int(cik)).zfill(10)


def format_issuer_id(cik: str) -> str:
    """Generate issuer_id from CIK."""
    return f"ISS_{format_cik(cik)}"


def load_csv(filepath: str) -> list[dict]:
    """Load and validate CSV file."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"CSV file not found: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV file is empty")

    # Validate required columns
    required = {'cik', 'company_name'}
    headers = set(rows[0].keys())
    missing = required - headers
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return rows


def create_batch_operation(
    conn: psycopg.Connection,
    operation_type: str = "csv_ingest"
) -> str:
    """Create batch operation for audit tracking."""
    batch_id = f"batch_{operation_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO batch_operation (batch_id, operation_type, status)
            VALUES (%s, %s, 'running')
        """, (batch_id, operation_type))

    return batch_id


def complete_batch_operation(
    conn: psycopg.Connection,
    batch_id: str,
    status: str = "completed"
):
    """Mark batch operation as complete."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE batch_operation
            SET status = %s, completed_at = NOW()
            WHERE batch_id = %s
        """, (status, batch_id))


def insert_company(
    cur: psycopg.Cursor,
    cik: str,
    company_name: str,
    ticker: Optional[str] = None,
    exchange: Optional[str] = None,
    revenue_usd: Optional[float] = None,
    employees: Optional[int] = None
) -> bool:
    """Insert company record. Returns True if inserted, False if already exists."""
    try:
        cur.execute("""
            INSERT INTO company (cik, sec_legal_name, ticker, exchange, revenue_usd, employees)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (cik) DO UPDATE SET
                sec_legal_name = EXCLUDED.sec_legal_name,
                ticker = COALESCE(EXCLUDED.ticker, company.ticker),
                exchange = COALESCE(EXCLUDED.exchange, company.exchange),
                revenue_usd = COALESCE(EXCLUDED.revenue_usd, company.revenue_usd),
                employees = COALESCE(EXCLUDED.employees, company.employees),
                updated_at = NOW()
        """, (cik, company_name, ticker, exchange, revenue_usd, employees))
        return True
    except Exception as e:
        print(f"  Error inserting company {cik}: {e}")
        return False


def insert_issuer(
    cur: psycopg.Cursor,
    issuer_id: str,
    primary_cik: str,
    batch_id: str
) -> bool:
    """Insert issuer record. Returns True if inserted, False if already exists."""
    try:
        cur.execute("""
            INSERT INTO issuer (issuer_id, primary_cik)
            VALUES (%s, %s)
            ON CONFLICT (issuer_id) DO UPDATE SET
                primary_cik = EXCLUDED.primary_cik
        """, (issuer_id, primary_cik))
        return True
    except Exception as e:
        print(f"  Error inserting issuer {issuer_id}: {e}")
        return False


def insert_universe_membership(
    cur: psycopg.Cursor,
    issuer_id: str,
    universe_id: str
) -> bool:
    """Insert universe membership record."""
    try:
        cur.execute("""
            INSERT INTO universe_membership (issuer_id, universe_id, start_date)
            VALUES (%s, %s, CURRENT_DATE)
            ON CONFLICT (issuer_id, universe_id) DO NOTHING
        """, (issuer_id, universe_id))
        return True
    except Exception as e:
        print(f"  Error inserting membership {issuer_id}/{universe_id}: {e}")
        return False


def load_universe_csv(
    conn: psycopg.Connection,
    rows: list[dict],
    batch_id: str,
    dry_run: bool = False
) -> dict:
    """Load universe data from parsed CSV rows."""
    stats = {
        "companies_inserted": 0,
        "companies_updated": 0,
        "issuers_created": 0,
        "memberships_created": 0,
        "errors": 0
    }

    with conn.cursor() as cur:
        for i, row in enumerate(rows, 1):
            try:
                # Extract and normalize fields
                cik = format_cik(row['cik'])
                company_name = row['company_name'].strip()
                issuer_id = format_issuer_id(cik)

                ticker = row.get('ticker', '').strip() or None
                exchange = row.get('exchange', '').strip() or None
                universe_id = row.get('universe_id', '').strip() or None

                revenue = row.get('revenue_usd', '').strip()
                revenue_usd = float(revenue) if revenue else None

                emp = row.get('employees', '').strip()
                employees = int(emp) if emp else None

                if dry_run:
                    print(f"[DRY RUN] Would insert: {cik} - {company_name}")
                    continue

                # Insert company
                insert_company(cur, cik, company_name, ticker, exchange, revenue_usd, employees)
                stats["companies_inserted"] += 1

                # Insert issuer
                insert_issuer(cur, issuer_id, cik, batch_id)
                stats["issuers_created"] += 1

                # Insert universe membership if specified
                if universe_id:
                    insert_universe_membership(cur, issuer_id, universe_id)
                    stats["memberships_created"] += 1

                if i % 100 == 0:
                    print(f"  Processed {i}/{len(rows)} rows...")

            except Exception as e:
                stats["errors"] += 1
                print(f"  Error on row {i}: {e}")
                continue

    return stats


def main():
    parser = argparse.ArgumentParser(description="Load company universe from CSV")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually insert data")
    parser.add_argument("--database-url", help="Database URL (or set DATABASE_URL env var)")
    args = parser.parse_args()

    # Get database URL
    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set. Use --database-url or set environment variable.")
        sys.exit(1)

    print(f"Loading CSV: {args.csv}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Load and validate CSV
    try:
        rows = load_csv(args.csv)
        print(f"Loaded {len(rows)} rows from CSV")
    except Exception as e:
        print(f"Error loading CSV: {e}")
        sys.exit(1)

    # Connect to database
    try:
        conn = psycopg.connect(db_url)
        conn.autocommit = False
        print("Connected to database")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

    try:
        # Create batch operation
        batch_id = create_batch_operation(conn, "csv_universe_ingest")
        print(f"Created batch operation: {batch_id}")

        # Load data
        print("\nLoading data...")
        stats = load_universe_csv(conn, rows, batch_id, dry_run=args.dry_run)

        if args.dry_run:
            print("\n[DRY RUN] No changes committed")
            conn.rollback()
        else:
            # Complete batch and commit
            complete_batch_operation(conn, batch_id, "completed")
            conn.commit()

            print("\n=== Load Complete ===")
            print(f"Companies inserted/updated: {stats['companies_inserted']}")
            print(f"Issuers created: {stats['issuers_created']}")
            print(f"Universe memberships: {stats['memberships_created']}")
            print(f"Errors: {stats['errors']}")
            print(f"Batch ID: {batch_id}")

    except Exception as e:
        print(f"\nError during load: {e}")
        conn.rollback()
        if not args.dry_run:
            complete_batch_operation(conn, batch_id, "failed")
            conn.commit()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
