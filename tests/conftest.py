"""
Shared pytest fixtures for BioGraph MVP test suite.
"""

import pytest
import psycopg
import os
from typing import Any


@pytest.fixture(scope='session')
def db_url() -> str:
    """Get database URL from environment."""
    return os.getenv('DATABASE_URL', 'postgresql://localhost/biograph_test')


@pytest.fixture
def db_conn(db_url: str):
    """
    Provide a test database connection with automatic transaction rollback.

    Each test runs in a transaction that is rolled back at the end,
    ensuring test isolation and cleanup.
    """
    with psycopg.connect(db_url) as conn:
        # Disable autocommit to use transactions
        conn.autocommit = False

        yield conn

        # Rollback transaction after test completes
        conn.rollback()


@pytest.fixture(scope='session')
def db_migrations_applied(db_url: str) -> bool:
    """
    Verify that database migrations have been applied.

    This is a session-scoped fixture that runs once before all tests.
    """
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # Check that critical tables exist
            cur.execute("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN (
                    'issuer',
                    'evidence',
                    'assertion',
                    'explanation',
                    'drug_program',
                    'target',
                    'disease',
                    'batch_operation'
                )
            """)

            count = cur.fetchone()[0]

            if count < 8:
                raise RuntimeError(
                    f"Database migrations not applied. Found {count}/8 required tables. "
                    f"Run migrations first:\n"
                    f"  psql $DATABASE_URL < db/migrations/001_complete_schema.sql\n"
                    f"  psql $DATABASE_URL < db/migrations/002_schema_hardening.sql"
                )

    return True


@pytest.fixture(autouse=True)
def require_migrations(db_migrations_applied: bool):
    """
    Automatically require migrations for all tests.

    This ensures tests fail fast if migrations haven't been applied.
    """
    assert db_migrations_applied, "Database migrations must be applied before running tests"
