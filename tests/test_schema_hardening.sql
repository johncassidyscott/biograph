-- BioGraph MVP v8.2 - Schema Hardening Tests
-- Tests for migration 002 features:
-- - Batch operation tracking and rollback
-- - Entity versioning
-- - Soft deletes
-- - New constraints and indexes

-- ============================================================================
-- TEST 1: Batch Operation Tracking
-- ============================================================================

-- Create a batch operation
INSERT INTO batch_operation (
    batch_id,
    operation_type,
    issuer_id,
    status,
    metadata
) VALUES (
    'test_filing_ingest_2024_001',
    'filing_ingest',
    'ISS_TEST001',
    'running',
    '{"source": "test_suite"}'::jsonb
);

-- Verify batch was created
SELECT
    CASE
        WHEN COUNT(*) = 1 THEN 'PASS: Batch operation created'
        ELSE 'FAIL: Batch operation not created'
    END AS test_result
FROM batch_operation
WHERE batch_id = 'test_filing_ingest_2024_001';

-- ============================================================================
-- TEST 2: Soft Deletes
-- ============================================================================

-- Create test data
INSERT INTO issuer (issuer_id, primary_cik, notes)
VALUES ('ISS_TEST002', '0000000002', 'Test issuer for soft delete');

INSERT INTO drug_program (
    drug_program_id,
    issuer_id,
    slug,
    name,
    batch_id
) VALUES (
    'CIK:0000000002:PROG:test_drug',
    'ISS_TEST002',
    'test_drug',
    'Test Drug for Soft Delete',
    'test_filing_ingest_2024_001'
);

-- Verify drug program was created
SELECT
    CASE
        WHEN COUNT(*) = 1 THEN 'PASS: Drug program created'
        ELSE 'FAIL: Drug program not created'
    END AS test_result
FROM drug_program
WHERE drug_program_id = 'CIK:0000000002:PROG:test_drug'
AND deleted_at IS NULL;

-- Soft delete the drug program
UPDATE drug_program
SET deleted_at = NOW(),
    deleted_by = 'test_suite',
    deletion_reason = 'test_soft_delete'
WHERE drug_program_id = 'CIK:0000000002:PROG:test_drug';

-- Verify drug program is soft deleted (still exists in table)
SELECT
    CASE
        WHEN COUNT(*) = 1 THEN 'PASS: Drug program soft deleted (record exists)'
        ELSE 'FAIL: Drug program hard deleted (record missing)'
    END AS test_result
FROM drug_program
WHERE drug_program_id = 'CIK:0000000002:PROG:test_drug';

-- Verify drug program is NOT in active view
SELECT
    CASE
        WHEN COUNT(*) = 0 THEN 'PASS: Soft deleted drug program not in active view'
        ELSE 'FAIL: Soft deleted drug program still in active view'
    END AS test_result
FROM active_drug_programs
WHERE drug_program_id = 'CIK:0000000002:PROG:test_drug';

-- ============================================================================
-- TEST 3: Entity Versioning
-- ============================================================================

-- Create initial version of drug program
INSERT INTO drug_program (
    drug_program_id,
    issuer_id,
    slug,
    name,
    version_id,
    is_current,
    valid_from
) VALUES (
    'CIK:0000000002:PROG:versioned_drug',
    'ISS_TEST002',
    'versioned_drug',
    'Versioned Drug v1',
    1,
    TRUE,
    NOW()
);

-- Verify initial version
SELECT
    CASE
        WHEN version_id = 1 AND is_current = TRUE THEN 'PASS: Initial version created'
        ELSE 'FAIL: Initial version incorrect'
    END AS test_result
FROM drug_program
WHERE drug_program_id = 'CIK:0000000002:PROG:versioned_drug';

-- Create new version (mark old as not current, create new)
UPDATE drug_program
SET is_current = FALSE,
    valid_to = NOW()
WHERE drug_program_id = 'CIK:0000000002:PROG:versioned_drug'
AND version_id = 1;

INSERT INTO drug_program (
    drug_program_id,
    issuer_id,
    slug,
    name,
    version_id,
    supersedes_id,
    is_current,
    valid_from
) VALUES (
    'CIK:0000000002:PROG:versioned_drug',
    'ISS_TEST002',
    'versioned_drug',
    'Versioned Drug v2 (Updated Name)',
    2,
    'CIK:0000000002:PROG:versioned_drug',  -- Points to previous version
    TRUE,
    NOW()
);

-- Verify version chain
SELECT
    CASE
        WHEN COUNT(*) = 2 THEN 'PASS: Two versions exist'
        ELSE 'FAIL: Version chain incorrect'
    END AS test_result
FROM drug_program
WHERE drug_program_id = 'CIK:0000000002:PROG:versioned_drug';

-- Verify only one current version
SELECT
    CASE
        WHEN COUNT(*) = 1 AND MAX(version_id) = 2 THEN 'PASS: Only v2 is current'
        ELSE 'FAIL: Multiple current versions or wrong version current'
    END AS test_result
FROM drug_program
WHERE drug_program_id = 'CIK:0000000002:PROG:versioned_drug'
AND is_current = TRUE;

-- ============================================================================
-- TEST 4: Batch Rollback
-- ============================================================================

-- Create evidence in the batch
INSERT INTO evidence (
    source_system,
    source_record_id,
    observed_at,
    license,
    uri,
    batch_id
) VALUES (
    'sec_edgar',
    'test_rollback_001',
    NOW(),
    'PUBLIC_DOMAIN',
    'http://test.com/rollback',
    'test_filing_ingest_2024_001'
);

-- Verify evidence was created
SELECT
    CASE
        WHEN COUNT(*) = 1 THEN 'PASS: Evidence created in batch'
        ELSE 'FAIL: Evidence not created'
    END AS test_result
FROM evidence
WHERE batch_id = 'test_filing_ingest_2024_001'
AND deleted_at IS NULL;

-- Mark batch as completed
UPDATE batch_operation
SET status = 'completed',
    completed_at = NOW(),
    rows_inserted = 2
WHERE batch_id = 'test_filing_ingest_2024_001';

-- Execute rollback
SELECT rollback_batch_operation('test_filing_ingest_2024_001');

-- Verify batch status
SELECT
    CASE
        WHEN status = 'rolled_back' THEN 'PASS: Batch marked as rolled_back'
        ELSE 'FAIL: Batch status incorrect: ' || status
    END AS test_result
FROM batch_operation
WHERE batch_id = 'test_filing_ingest_2024_001';

-- Verify evidence is soft deleted
SELECT
    CASE
        WHEN COUNT(*) = 0 THEN 'PASS: Evidence soft deleted after rollback'
        ELSE 'FAIL: Evidence still active after rollback'
    END AS test_result
FROM active_evidence
WHERE batch_id = 'test_filing_ingest_2024_001';

-- Verify drug program is soft deleted
SELECT
    CASE
        WHEN COUNT(*) = 0 THEN 'PASS: Drug program soft deleted after rollback'
        ELSE 'FAIL: Drug program still active after rollback'
    END AS test_result
FROM active_drug_programs
WHERE batch_id = 'test_filing_ingest_2024_001';

-- ============================================================================
-- TEST 5: Constraint Validation
-- ============================================================================

-- Test: Cannot have multiple current versions of same entity
BEGIN;
    INSERT INTO drug_program (
        drug_program_id,
        issuer_id,
        slug,
        name,
        version_id,
        is_current
    ) VALUES (
        'CIK:0000000002:PROG:duplicate_current',
        'ISS_TEST002',
        'duplicate_current',
        'Test v1',
        1,
        TRUE
    );

    -- This should fail due to unique constraint
    INSERT INTO drug_program (
        drug_program_id,
        issuer_id,
        slug,
        name,
        version_id,
        is_current
    ) VALUES (
        'CIK:0000000002:PROG:duplicate_current',
        'ISS_TEST002',
        'duplicate_current',
        'Test v2',
        2,
        TRUE
    );

    -- If we get here, test failed
    SELECT 'FAIL: Multiple current versions allowed (should have raised error)' AS test_result;
    ROLLBACK;
EXCEPTION
    WHEN unique_violation THEN
        SELECT 'PASS: Cannot create multiple current versions (constraint works)' AS test_result;
        ROLLBACK;
END;

-- Test: Deleted records cannot be current
BEGIN;
    INSERT INTO drug_program (
        drug_program_id,
        issuer_id,
        slug,
        name,
        deleted_at,
        is_current
    ) VALUES (
        'CIK:0000000002:PROG:deleted_and_current',
        'ISS_TEST002',
        'deleted_and_current',
        'Test',
        NOW(),
        TRUE
    );

    -- If we get here, test failed
    SELECT 'FAIL: Deleted record allowed to be current (should have raised error)' AS test_result;
    ROLLBACK;
EXCEPTION
    WHEN check_violation THEN
        SELECT 'PASS: Deleted records cannot be current (constraint works)' AS test_result;
        ROLLBACK;
END;

-- Test: Version ID must be positive
BEGIN;
    INSERT INTO drug_program (
        drug_program_id,
        issuer_id,
        slug,
        name,
        version_id
    ) VALUES (
        'CIK:0000000002:PROG:negative_version',
        'ISS_TEST002',
        'negative_version',
        'Test',
        0
    );

    SELECT 'FAIL: Zero version_id allowed (should have raised error)' AS test_result;
    ROLLBACK;
EXCEPTION
    WHEN check_violation THEN
        SELECT 'PASS: Version ID must be positive (constraint works)' AS test_result;
        ROLLBACK;
END;

-- Test: Valid date range must be valid
BEGIN;
    INSERT INTO drug_program (
        drug_program_id,
        issuer_id,
        slug,
        name,
        valid_from,
        valid_to
    ) VALUES (
        'CIK:0000000002:PROG:invalid_range',
        'ISS_TEST002',
        'invalid_range',
        'Test',
        '2024-12-31'::timestamptz,
        '2024-01-01'::timestamptz
    );

    SELECT 'FAIL: Invalid date range allowed (should have raised error)' AS test_result;
    ROLLBACK;
EXCEPTION
    WHEN check_violation THEN
        SELECT 'PASS: Valid date range enforced (constraint works)' AS test_result;
        ROLLBACK;
END;

-- ============================================================================
-- TEST 6: Index Validation
-- ============================================================================

-- Verify critical indexes exist
SELECT
    CASE
        WHEN COUNT(*) >= 6 THEN 'PASS: Critical drug_program indexes exist'
        ELSE 'FAIL: Missing drug_program indexes'
    END AS test_result
FROM pg_indexes
WHERE schemaname = 'public'
AND tablename = 'drug_program'
AND indexname IN (
    'idx_drug_program_version',
    'idx_drug_program_current',
    'idx_drug_program_deleted',
    'idx_drug_program_batch',
    'idx_drug_program_issuer_active',
    'idx_drug_program_one_current'
);

-- Verify evidence indexes
SELECT
    CASE
        WHEN COUNT(*) >= 4 THEN 'PASS: Critical evidence indexes exist'
        ELSE 'FAIL: Missing evidence indexes'
    END AS test_result
FROM pg_indexes
WHERE schemaname = 'public'
AND tablename = 'evidence'
AND indexname IN (
    'idx_evidence_deleted',
    'idx_evidence_batch',
    'idx_evidence_source_license'
);

-- Verify assertion indexes
SELECT
    CASE
        WHEN COUNT(*) >= 6 THEN 'PASS: Critical assertion indexes exist'
        ELSE 'FAIL: Missing assertion indexes'
    END AS test_result
FROM pg_indexes
WHERE schemaname = 'public'
AND tablename = 'assertion'
AND indexname IN (
    'idx_assertion_deleted',
    'idx_assertion_batch',
    'idx_assertion_version',
    'idx_assertion_subject_active',
    'idx_assertion_object_active',
    'idx_assertion_confidence'
);

-- ============================================================================
-- TEST 7: View Validation
-- ============================================================================

-- Verify active views exist
SELECT
    CASE
        WHEN COUNT(*) >= 5 THEN 'PASS: All active record views exist'
        ELSE 'FAIL: Missing active record views'
    END AS test_result
FROM information_schema.views
WHERE table_schema = 'public'
AND table_name IN (
    'active_drug_programs',
    'active_assertions',
    'active_evidence',
    'active_explanations',
    'pending_candidates'
);

-- ============================================================================
-- TEST 8: Enum Type Validation
-- ============================================================================

-- Verify enum types exist
SELECT
    CASE
        WHEN COUNT(*) >= 7 THEN 'PASS: All enum types created'
        ELSE 'FAIL: Missing enum types'
    END AS test_result
FROM pg_type
WHERE typtype = 'e'
AND typname IN (
    'source_system_type',
    'entity_type_enum',
    'predicate_enum',
    'curation_status_enum',
    'nlp_run_status_enum',
    'development_stage_enum',
    'drug_type_enum'
);

-- ============================================================================
-- CLEANUP
-- ============================================================================

-- Clean up test data
DELETE FROM drug_program WHERE issuer_id = 'ISS_TEST002';
DELETE FROM evidence WHERE batch_id = 'test_filing_ingest_2024_001';
DELETE FROM batch_operation WHERE batch_id = 'test_filing_ingest_2024_001';
DELETE FROM issuer WHERE issuer_id = 'ISS_TEST002';

-- ============================================================================
-- TEST SUMMARY
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Schema Hardening Tests Completed';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Tests Executed:';
    RAISE NOTICE '  1. Batch operation tracking';
    RAISE NOTICE '  2. Soft deletes';
    RAISE NOTICE '  3. Entity versioning';
    RAISE NOTICE '  4. Batch rollback';
    RAISE NOTICE '  5. Constraint validation';
    RAISE NOTICE '  6. Index validation';
    RAISE NOTICE '  7. View validation';
    RAISE NOTICE '  8. Enum type validation';
    RAISE NOTICE '==================================================';
END $$;
