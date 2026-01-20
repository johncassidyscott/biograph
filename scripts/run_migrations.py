#!/usr/bin/env python3
"""
BioGraph Migration Runner

Runs all migration files in order from backend/migrations/

Usage:
    python scripts/run_migrations.py

Requirements:
    - DATABASE_URL environment variable must be set
    - Migration files must follow naming convention: NNN_name.sql
    - Migrations are idempotent (use CREATE TABLE IF NOT EXISTS where applicable)
"""

import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.db import get_conn
from dotenv import load_dotenv

load_dotenv()


def run_migrations(migrations_dir: Path = None):
    """
    Run all migration files in order.

    Args:
        migrations_dir: Path to migrations directory (default: backend/migrations)
    """
    if migrations_dir is None:
        migrations_dir = Path(__file__).parent.parent / 'backend' / 'migrations'

    if not migrations_dir.exists():
        print(f"❌ Error: Migrations directory not found: {migrations_dir}")
        sys.exit(1)

    # Get all .sql files sorted by name
    migration_files = sorted(migrations_dir.glob('*.sql'))

    if not migration_files:
        print(f"⚠️  Warning: No migration files found in {migrations_dir}")
        return

    print(f"📂 Found {len(migration_files)} migration(s)")
    print("=" * 60)

    with get_conn() as conn:
        for migration_file in migration_files:
            print(f"▶️  Running: {migration_file.name}...", end=' ')

            try:
                with open(migration_file, 'r', encoding='utf-8') as f:
                    sql = f.read()

                with conn.cursor() as cur:
                    cur.execute(sql)

                conn.commit()
                print("✅ Success")

            except Exception as e:
                print(f"❌ Failed")
                print(f"   Error: {e}")
                conn.rollback()
                print("\n⚠️  Migration halted. Fix the error and try again.")
                sys.exit(1)

    print("=" * 60)
    print("✅ All migrations completed successfully")


def verify_migrations():
    """Verify database schema after migrations."""
    print("\n🔍 Verifying database schema...")

    required_tables = [
        'entity',
        'edge',
        'mesh_descriptor',
        'evidence',
        'assertion',
        'assertion_evidence',
        'license_allowlist',
        'lookup_cache'
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for table in required_tables:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = %s
                    )
                """, (table,))

                exists = cur.fetchone()[0]

                if exists:
                    print(f"   ✅ {table}")
                else:
                    print(f"   ❌ {table} (MISSING)")

    print("\n✅ Schema verification complete")


if __name__ == '__main__':
    print("=" * 60)
    print("BioGraph Migration Runner")
    print("=" * 60)

    # Check DATABASE_URL
    if not os.getenv('DATABASE_URL'):
        print("❌ Error: DATABASE_URL environment variable not set")
        print("   Set it in .env or export it in your shell")
        sys.exit(1)

    try:
        run_migrations()
        verify_migrations()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
