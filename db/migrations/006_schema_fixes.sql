-- BioGraph MVP v8.3 - Schema Fixes
-- Fixes discovered during testing
--
-- Changes:
-- 1. Add unique constraint on candidate for NER deduplication
-- 2. Add CHECK constraint on news_item snippet length
-- 3. Fix rollback_batch_operation to satisfy deleted_not_current constraint

-- ============================================================================
-- SECTION 1: CANDIDATE UNIQUE CONSTRAINT
-- ============================================================================

-- Add unique index for NER deduplication (required for ON CONFLICT)
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_unique
ON candidate(issuer_id, entity_type, normalized_name, source_type, source_id);

-- ============================================================================
-- SECTION 2: NEWS ITEM SNIPPET CONSTRAINT
-- ============================================================================

-- Add CHECK constraint for snippet length (200 char max per Section 24D)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'news_item'::regclass
        AND conname = 'check_snippet_length'
    ) THEN
        ALTER TABLE news_item
        ADD CONSTRAINT check_snippet_length
        CHECK (LENGTH(snippet) <= 200 OR snippet IS NULL);
    END IF;
END $$;

-- ============================================================================
-- SECTION 3: FIX ROLLBACK FUNCTION
-- ============================================================================

-- Update rollback_batch_operation to also set is_current=false
-- This satisfies the check_drug_program_deleted_not_current constraint
CREATE OR REPLACE FUNCTION rollback_batch_operation(p_batch_id TEXT)
RETURNS VOID AS $$
DECLARE
    v_status TEXT;
BEGIN
    -- Check batch exists and is completed
    SELECT status INTO v_status FROM batch_operation WHERE batch_id = p_batch_id;

    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Batch operation % not found', p_batch_id;
    END IF;

    IF v_status NOT IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'Cannot rollback batch % with status %', p_batch_id, v_status;
    END IF;

    -- Soft delete all records created in this batch
    -- Also set is_current=false to satisfy constraints
    UPDATE evidence SET deleted_at = NOW() WHERE batch_id = p_batch_id AND deleted_at IS NULL;
    UPDATE assertion SET deleted_at = NOW() WHERE batch_id = p_batch_id AND deleted_at IS NULL;
    UPDATE drug_program SET deleted_at = NOW(), is_current = false
        WHERE batch_id = p_batch_id AND deleted_at IS NULL;
    UPDATE candidate SET deleted_at = NOW() WHERE batch_id = p_batch_id AND deleted_at IS NULL;

    -- Mark batch as rolled back
    UPDATE batch_operation
    SET status = 'rolled_back', completed_at = NOW()
    WHERE batch_id = p_batch_id;

    RAISE NOTICE 'Rolled back batch operation %', p_batch_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 4: UNIVERSE MEMBERSHIP CONSTRAINT
-- ============================================================================

-- Add unique constraint for universe membership deduplication
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'universe_membership'::regclass
        AND conname = 'universe_membership_unique'
    ) THEN
        ALTER TABLE universe_membership
        ADD CONSTRAINT universe_membership_unique
        UNIQUE (issuer_id, universe_id);
    END IF;
END $$;

-- ============================================================================
-- SECTION 5: VALIDATION
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Migration 006 (Schema Fixes) completed successfully';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Changes applied:';
    RAISE NOTICE '  - Added unique index on candidate table';
    RAISE NOTICE '  - Added snippet length CHECK on news_item';
    RAISE NOTICE '  - Fixed rollback_batch_operation function';
    RAISE NOTICE '==================================================';
END $$;
