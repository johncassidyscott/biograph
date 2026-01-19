"""
BioGraph MVP v8.2 - Schema Hardening Tests (Python)

Tests for migration 002 features:
- Batch operation tracking and rollback
- Entity versioning
- Soft deletes
- New constraints and indexes

These tests complement the SQL test file.
"""

import pytest
import psycopg
from datetime import datetime, date
from typing import Any


@pytest.fixture
def test_issuer(db_conn: Any) -> str:
    """Create a test issuer for schema tests."""
    issuer_id = 'ISS_SCHEMA_TEST'
    with db_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO issuer (issuer_id, primary_cik, notes)
            VALUES (%s, '0000999999', 'Test issuer for schema hardening tests')
            ON CONFLICT (issuer_id) DO NOTHING
        """, (issuer_id,))
    db_conn.commit()

    yield issuer_id

    # Cleanup
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM issuer WHERE issuer_id = %s", (issuer_id,))
    db_conn.commit()


class TestBatchOperationTracking:
    """Tests for batch operation tracking and rollback."""

    def test_create_batch_operation(self, db_conn: Any, test_issuer: str):
        """Test creating a batch operation."""
        batch_id = 'test_batch_001'

        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO batch_operation (
                    batch_id, operation_type, issuer_id, status, metadata
                ) VALUES (%s, %s, %s, %s, %s)
            """, (batch_id, 'filing_ingest', test_issuer, 'running', '{"test": true}'))

            # Verify batch was created
            cur.execute("SELECT batch_id, status FROM batch_operation WHERE batch_id = %s", (batch_id,))
            row = cur.fetchone()

            assert row is not None
            assert row[0] == batch_id
            assert row[1] == 'running'

        db_conn.rollback()

    def test_batch_rollback_function(self, db_conn: Any, test_issuer: str):
        """Test the rollback_batch_operation function."""
        batch_id = 'test_batch_rollback_001'

        with db_conn.cursor() as cur:
            # Create batch
            cur.execute("""
                INSERT INTO batch_operation (
                    batch_id, operation_type, issuer_id, status, completed_at
                ) VALUES (%s, %s, %s, %s, NOW())
            """, (batch_id, 'test_ingest', test_issuer, 'completed'))

            # Create drug program in batch
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name, batch_id
                ) VALUES (%s, %s, %s, %s, %s)
            """, (
                f'CIK:0000999999:PROG:test_rollback',
                test_issuer,
                'test_rollback',
                'Test Rollback Drug',
                batch_id
            ))

            # Verify drug program exists and is active
            cur.execute("""
                SELECT COUNT(*) FROM drug_program
                WHERE batch_id = %s AND deleted_at IS NULL
            """, (batch_id,))
            assert cur.fetchone()[0] == 1

            # Execute rollback
            cur.execute("SELECT rollback_batch_operation(%s)", (batch_id,))

            # Verify batch status changed
            cur.execute("SELECT status FROM batch_operation WHERE batch_id = %s", (batch_id,))
            assert cur.fetchone()[0] == 'rolled_back'

            # Verify drug program is soft deleted
            cur.execute("""
                SELECT COUNT(*) FROM drug_program
                WHERE batch_id = %s AND deleted_at IS NULL
            """, (batch_id,))
            assert cur.fetchone()[0] == 0

            # Verify drug program still exists (soft delete)
            cur.execute("""
                SELECT COUNT(*) FROM drug_program
                WHERE batch_id = %s AND deleted_at IS NOT NULL
            """, (batch_id,))
            assert cur.fetchone()[0] == 1

        db_conn.rollback()


class TestEntityVersioning:
    """Tests for entity versioning infrastructure."""

    def test_initial_version_defaults(self, db_conn: Any, test_issuer: str):
        """Test that new entities get version_id=1 and is_current=TRUE."""
        drug_id = f'CIK:0000999999:PROG:version_test_001'

        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name
                ) VALUES (%s, %s, %s, %s)
            """, (drug_id, test_issuer, 'version_test_001', 'Version Test Drug'))

            # Verify defaults
            cur.execute("""
                SELECT version_id, is_current, valid_from
                FROM drug_program
                WHERE drug_program_id = %s
            """, (drug_id,))

            row = cur.fetchone()
            assert row[0] == 1  # version_id
            assert row[1] is True  # is_current
            assert row[2] is not None  # valid_from

        db_conn.rollback()

    def test_create_new_version(self, db_conn: Any, test_issuer: str):
        """Test creating a new version of an entity using supersedes pattern."""
        drug_id_v1 = f'CIK:0000999999:PROG:version_test_v1'
        drug_id_v2 = f'CIK:0000999999:PROG:version_test_v2'

        with db_conn.cursor() as cur:
            # Create v1
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name, version_id, is_current
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (drug_id_v1, test_issuer, 'version_test_v1', 'Version Test v1', 1, True))

            # Mark v1 as not current (valid_to must be > valid_from)
            cur.execute("""
                UPDATE drug_program
                SET is_current = FALSE, valid_to = NOW() + INTERVAL '1 second'
                WHERE drug_program_id = %s
            """, (drug_id_v1,))

            # Create v2 that supersedes v1
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name,
                    version_id, supersedes_id, is_current
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                drug_id_v2, test_issuer, 'version_test_v2',
                'Version Test v2 (Updated)',
                1, drug_id_v1, True
            ))

            # Verify both versions exist
            cur.execute("""
                SELECT COUNT(*) FROM drug_program
                WHERE drug_program_id IN (%s, %s)
            """, (drug_id_v1, drug_id_v2))
            assert cur.fetchone()[0] == 2

            # Verify only v2 is current
            cur.execute("""
                SELECT drug_program_id FROM drug_program
                WHERE drug_program_id IN (%s, %s) AND is_current = TRUE
            """, (drug_id_v1, drug_id_v2))
            assert cur.fetchone()[0] == drug_id_v2

        db_conn.rollback()

    def test_cannot_have_multiple_current_versions(self, db_conn: Any, test_issuer: str):
        """Test that unique constraint prevents multiple current versions."""
        drug_id = f'CIK:0000999999:PROG:version_test_003'

        with db_conn.cursor() as cur:
            # Create v1 (current)
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name,
                    version_id, is_current
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (drug_id, test_issuer, 'version_test_003', 'Version Test v1', 1, True))

            # Try to create v2 (also current) - should fail
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute("""
                    INSERT INTO drug_program (
                        drug_program_id, issuer_id, slug, name,
                        version_id, is_current
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (drug_id, test_issuer, 'version_test_003', 'Version Test v2', 2, True))

        db_conn.rollback()


class TestSoftDeletes:
    """Tests for soft delete functionality."""

    def test_soft_delete_drug_program(self, db_conn: Any, test_issuer: str):
        """Test soft deleting a drug program."""
        drug_id = f'CIK:0000999999:PROG:soft_delete_test'

        with db_conn.cursor() as cur:
            # Create drug program
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name
                ) VALUES (%s, %s, %s, %s)
            """, (drug_id, test_issuer, 'soft_delete_test', 'Soft Delete Test'))

            # Verify it exists
            cur.execute("""
                SELECT COUNT(*) FROM drug_program
                WHERE drug_program_id = %s AND deleted_at IS NULL
            """, (drug_id,))
            assert cur.fetchone()[0] == 1

            # Soft delete it (must also set is_current=false per constraint)
            cur.execute("""
                UPDATE drug_program
                SET deleted_at = NOW(),
                    deleted_by = 'test_suite',
                    deletion_reason = 'test_soft_delete',
                    is_current = false
                WHERE drug_program_id = %s
            """, (drug_id,))

            # Verify it's marked deleted
            cur.execute("""
                SELECT COUNT(*) FROM drug_program
                WHERE drug_program_id = %s AND deleted_at IS NOT NULL
            """, (drug_id,))
            assert cur.fetchone()[0] == 1

            # Verify it's not in active view
            cur.execute("""
                SELECT COUNT(*) FROM active_drug_programs
                WHERE drug_program_id = %s
            """, (drug_id,))
            assert cur.fetchone()[0] == 0

        db_conn.rollback()

    def test_soft_delete_evidence(self, db_conn: Any):
        """Test soft deleting evidence."""
        with db_conn.cursor() as cur:
            # Create evidence
            cur.execute("""
                INSERT INTO evidence (
                    source_system, source_record_id, observed_at, license, uri
                ) VALUES (%s, %s, NOW(), %s, %s)
                RETURNING evidence_id
            """, ('sec_edgar', 'test_soft_delete_001', 'PUBLIC_DOMAIN', 'http://test.com'))

            evidence_id = cur.fetchone()[0]

            # Soft delete
            cur.execute("""
                UPDATE evidence
                SET deleted_at = NOW(),
                    deleted_by = 'test_suite',
                    deletion_reason = 'test'
                WHERE evidence_id = %s
            """, (evidence_id,))

            # Verify not in active view
            cur.execute("""
                SELECT COUNT(*) FROM active_evidence
                WHERE evidence_id = %s
            """, (evidence_id,))
            assert cur.fetchone()[0] == 0

        db_conn.rollback()

    def test_deleted_entity_cannot_be_current(self, db_conn: Any, test_issuer: str):
        """Test that deleted entities cannot be marked as current."""
        drug_id = f'CIK:0000999999:PROG:deleted_not_current'

        with db_conn.cursor() as cur:
            # Try to create entity that is both deleted and current - should fail
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO drug_program (
                        drug_program_id, issuer_id, slug, name,
                        deleted_at, is_current
                    ) VALUES (%s, %s, %s, %s, NOW(), TRUE)
                """, (drug_id, test_issuer, 'deleted_not_current', 'Test'))

        db_conn.rollback()


class TestConstraints:
    """Tests for new schema constraints."""

    def test_version_id_must_be_positive(self, db_conn: Any, test_issuer: str):
        """Test that version_id must be > 0."""
        drug_id = f'CIK:0000999999:PROG:negative_version'

        with db_conn.cursor() as cur:
            # Try to create with version_id = 0
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO drug_program (
                        drug_program_id, issuer_id, slug, name, version_id
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (drug_id, test_issuer, 'negative_version', 'Test', 0))

            # Try to create with version_id = -1
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO drug_program (
                        drug_program_id, issuer_id, slug, name, version_id
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (drug_id, test_issuer, 'negative_version', 'Test', -1))

        db_conn.rollback()

    def test_valid_date_range_must_be_valid(self, db_conn: Any, test_issuer: str):
        """Test that valid_to must be after valid_from."""
        drug_id = f'CIK:0000999999:PROG:invalid_range'

        with db_conn.cursor() as cur:
            # Try to create with valid_to before valid_from
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO drug_program (
                        drug_program_id, issuer_id, slug, name,
                        valid_from, valid_to
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    drug_id, test_issuer, 'invalid_range', 'Test',
                    '2024-12-31', '2024-01-01'
                ))

        db_conn.rollback()


class TestViews:
    """Tests for active record views."""

    def test_active_drug_programs_view(self, db_conn: Any, test_issuer: str):
        """Test that active_drug_programs view filters correctly."""
        drug_id_active = f'CIK:0000999999:PROG:view_test_active'
        drug_id_deleted = f'CIK:0000999999:PROG:view_test_deleted'

        with db_conn.cursor() as cur:
            # Create active drug program
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name
                ) VALUES (%s, %s, %s, %s)
            """, (drug_id_active, test_issuer, 'view_test_active', 'Active'))

            # Create deleted drug program (must set is_current=false per constraint)
            cur.execute("""
                INSERT INTO drug_program (
                    drug_program_id, issuer_id, slug, name, deleted_at, is_current
                ) VALUES (%s, %s, %s, %s, NOW(), false)
            """, (drug_id_deleted, test_issuer, 'view_test_deleted', 'Deleted'))

            # Verify only active in view
            cur.execute("""
                SELECT drug_program_id FROM active_drug_programs
                WHERE issuer_id = %s
            """, (test_issuer,))

            results = [row[0] for row in cur.fetchall()]
            assert drug_id_active in results
            assert drug_id_deleted not in results

        db_conn.rollback()

    def test_active_evidence_view(self, db_conn: Any):
        """Test that active_evidence view filters correctly."""
        with db_conn.cursor() as cur:
            # Create active evidence
            cur.execute("""
                INSERT INTO evidence (
                    source_system, source_record_id, observed_at, license, uri
                ) VALUES (%s, %s, NOW(), %s, %s)
                RETURNING evidence_id
            """, ('sec_edgar', 'view_test_active', 'PUBLIC_DOMAIN', 'http://test.com'))
            active_id = cur.fetchone()[0]

            # Create deleted evidence
            cur.execute("""
                INSERT INTO evidence (
                    source_system, source_record_id, observed_at, license, uri, deleted_at
                ) VALUES (%s, %s, NOW(), %s, %s, NOW())
                RETURNING evidence_id
            """, ('sec_edgar', 'view_test_deleted', 'PUBLIC_DOMAIN', 'http://test.com'))
            deleted_id = cur.fetchone()[0]

            # Verify only active in view
            cur.execute("SELECT evidence_id FROM active_evidence")
            results = [row[0] for row in cur.fetchall()]

            assert active_id in results
            assert deleted_id not in results

        db_conn.rollback()


class TestIndexes:
    """Tests to verify critical indexes exist."""

    def test_critical_indexes_exist(self, db_conn: Any):
        """Test that critical indexes were created."""
        expected_indexes = [
            'idx_drug_program_version',
            'idx_drug_program_current',
            'idx_drug_program_deleted',
            'idx_drug_program_batch',
            'idx_evidence_deleted',
            'idx_evidence_batch',
            'idx_assertion_deleted',
            'idx_assertion_batch',
            'idx_assertion_version',
        ]

        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public'
                AND indexname = ANY(%s)
            """, (expected_indexes,))

            results = [row[0] for row in cur.fetchall()]

            for index_name in expected_indexes:
                assert index_name in results, f"Missing index: {index_name}"


class TestEnumTypes:
    """Tests for enum types."""

    def test_enum_types_exist(self, db_conn: Any):
        """Test that all enum types were created."""
        expected_enums = [
            'source_system_type',
            'entity_type_enum',
            'predicate_enum',
            'curation_status_enum',
            'nlp_run_status_enum',
            'development_stage_enum',
            'drug_type_enum',
        ]

        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT typname FROM pg_type
                WHERE typtype = 'e'
                AND typname = ANY(%s)
            """, (expected_enums,))

            results = [row[0] for row in cur.fetchall()]

            for enum_name in expected_enums:
                assert enum_name in results, f"Missing enum: {enum_name}"
