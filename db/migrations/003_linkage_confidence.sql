-- BioGraph MVP v8.2 - Linkage Confidence (Section 22)
-- Adds user-facing confidence fields to assertions
--
-- Changes:
-- 1. Add confidence fields to assertion table (nullable for now)
-- 2. Add link_method enum type
-- 3. Add confidence band enum type
-- 4. Add support_type for assertion_evidence
-- 5. Create confidence computation helper views
-- 6. Add backfill function

-- ============================================================================
-- SECTION 1: ENUM TYPES
-- ============================================================================

-- Link method enum (how the assertion was created)
CREATE TYPE link_method_enum AS ENUM (
    'DETERMINISTIC',        -- Exact ID match from authoritative source
    'CURATED',             -- Human curator approved
    'ML_SUGGESTED_APPROVED' -- ML suggested, then curator approved
);

-- Confidence band enum (user-facing)
CREATE TYPE link_confidence_band_enum AS ENUM (
    'HIGH',      -- score >= 0.90
    'MEDIUM',    -- 0.75 <= score < 0.90
    'LOW'        -- score < 0.75
);

-- Evidence support type enum (for assertion_evidence)
CREATE TYPE evidence_support_type_enum AS ENUM (
    'PRIMARY',    -- Direct evidence for the assertion
    'SECONDARY',  -- Supporting/corroborating evidence
    'CONTEXT'     -- Contextual/background evidence (e.g., news)
);

-- ============================================================================
-- SECTION 2: ASSERTION TABLE UPDATES
-- ============================================================================

-- Add confidence fields to assertion table
-- These are nullable for now to allow backfilling existing assertions

ALTER TABLE assertion
    ADD COLUMN IF NOT EXISTS link_confidence_score NUMERIC
        CHECK (link_confidence_score >= 0 AND link_confidence_score <= 1),
    ADD COLUMN IF NOT EXISTS link_confidence_band link_confidence_band_enum,
    ADD COLUMN IF NOT EXISTS link_method link_method_enum,
    ADD COLUMN IF NOT EXISTS link_rationale_json JSONB,
    ADD COLUMN IF NOT EXISTS curator_delta NUMERIC DEFAULT 0
        CHECK (curator_delta >= -0.10 AND curator_delta <= 0.10);

-- Add indexes for confidence queries
CREATE INDEX IF NOT EXISTS idx_assertion_confidence_band
    ON assertion(link_confidence_band)
    WHERE retracted_at IS NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_assertion_method
    ON assertion(link_method)
    WHERE retracted_at IS NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_assertion_score
    ON assertion(link_confidence_score DESC)
    WHERE retracted_at IS NULL AND deleted_at IS NULL;

-- Add index on rationale JSON for method lookups
CREATE INDEX IF NOT EXISTS idx_assertion_rationale_method
    ON assertion USING gin(link_rationale_json jsonb_path_ops)
    WHERE link_rationale_json IS NOT NULL;

-- ============================================================================
-- SECTION 3: ASSERTION_EVIDENCE TABLE UPDATES
-- ============================================================================

-- Add support type to assertion_evidence
ALTER TABLE assertion_evidence
    ADD COLUMN IF NOT EXISTS support_type evidence_support_type_enum DEFAULT 'PRIMARY';

-- Add index for filtering by support type
CREATE INDEX IF NOT EXISTS idx_assertion_evidence_support_type
    ON assertion_evidence(assertion_id, support_type);

-- ============================================================================
-- SECTION 4: CONFIDENCE COMPUTATION HELPERS
-- ============================================================================

-- Helper function: Get confidence band from score
CREATE OR REPLACE FUNCTION get_confidence_band(score NUMERIC)
RETURNS link_confidence_band_enum AS $$
BEGIN
    IF score >= 0.90 THEN
        RETURN 'HIGH'::link_confidence_band_enum;
    ELSIF score >= 0.75 THEN
        RETURN 'MEDIUM'::link_confidence_band_enum;
    ELSE
        RETURN 'LOW'::link_confidence_band_enum;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Helper view: Evidence summary by assertion
CREATE OR REPLACE VIEW assertion_evidence_summary AS
SELECT
    a.assertion_id,
    COUNT(DISTINCT ae.evidence_id) as evidence_count,
    COUNT(DISTINCT ae.evidence_id) FILTER (WHERE ae.support_type = 'PRIMARY') as primary_evidence_count,
    COUNT(DISTINCT e.source_system) as source_system_count,
    jsonb_object_agg(
        e.source_system,
        COUNT(*)
    ) FILTER (WHERE e.source_system IS NOT NULL) as evidence_by_source,
    -- Check if NEWS_METADATA is the only source (violation)
    BOOL_AND(e.source_system = 'news_metadata') as is_news_only,
    -- Source tier counts
    COUNT(*) FILTER (WHERE e.source_system IN ('sec_edgar', 'sec_edgar_exhibit')) as sec_evidence_count,
    COUNT(*) FILTER (WHERE e.source_system IN ('opentargets', 'chembl')) as curated_evidence_count,
    COUNT(*) FILTER (WHERE e.source_system = 'news_metadata') as news_evidence_count
FROM assertion a
LEFT JOIN assertion_evidence ae ON a.assertion_id = ae.assertion_id
LEFT JOIN evidence e ON ae.evidence_id = e.evidence_id AND e.deleted_at IS NULL
WHERE a.deleted_at IS NULL AND a.retracted_at IS NULL
GROUP BY a.assertion_id;

-- ============================================================================
-- SECTION 5: CONFIDENCE COMPUTATION FUNCTION
-- ============================================================================

-- Compute link confidence for an assertion
-- This is a simplified version; full implementation in biograph/core/confidence.py
CREATE OR REPLACE FUNCTION compute_link_confidence(
    p_assertion_id BIGINT,
    p_method link_method_enum DEFAULT 'CURATED'::link_method_enum
)
RETURNS TABLE (
    score NUMERIC,
    band link_confidence_band_enum,
    rationale JSONB
) AS $$
DECLARE
    v_base_score NUMERIC;
    v_evidence_count INTEGER;
    v_sec_count INTEGER;
    v_curated_count INTEGER;
    v_news_count INTEGER;
    v_is_news_only BOOLEAN;
    v_evidence_bonus NUMERIC;
    v_source_bonus NUMERIC;
    v_final_score NUMERIC;
    v_band link_confidence_band_enum;
    v_rationale JSONB;
    v_evidence_by_source JSONB;
BEGIN
    -- Get evidence summary
    SELECT
        aes.evidence_count,
        aes.sec_evidence_count,
        aes.curated_evidence_count,
        aes.news_evidence_count,
        aes.is_news_only,
        aes.evidence_by_source
    INTO
        v_evidence_count,
        v_sec_count,
        v_curated_count,
        v_news_count,
        v_is_news_only,
        v_evidence_by_source
    FROM assertion_evidence_summary aes
    WHERE aes.assertion_id = p_assertion_id;

    -- Validate news-only assertion (should never happen)
    IF v_is_news_only THEN
        RAISE EXCEPTION 'Assertion % has only NEWS_METADATA evidence (violates Section 22E.1)', p_assertion_id;
    END IF;

    -- Method baseline
    CASE p_method
        WHEN 'DETERMINISTIC' THEN v_base_score := 0.95;
        WHEN 'CURATED' THEN v_base_score := 0.90;
        WHEN 'ML_SUGGESTED_APPROVED' THEN v_base_score := 0.75;
    END CASE;

    -- Evidence count bonus (+0.01 per additional evidence, capped at +0.03)
    v_evidence_bonus := LEAST(0.03, (v_evidence_count - 1) * 0.01);

    -- Source tier bonus
    v_source_bonus := 0.0;
    -- SEC evidence: up to +0.06
    IF v_sec_count > 0 THEN
        v_source_bonus := v_source_bonus + LEAST(0.06, v_sec_count * 0.02);
    END IF;
    -- Curated evidence (OpenTargets, ChEMBL): up to +0.05
    IF v_curated_count > 0 THEN
        v_source_bonus := v_source_bonus + LEAST(0.05, v_curated_count * 0.015);
    END IF;

    -- Compute final score
    v_final_score := v_base_score + v_evidence_bonus + v_source_bonus;

    -- Apply caps
    IF p_method = 'DETERMINISTIC' THEN
        v_final_score := LEAST(0.99, v_final_score);
    ELSIF p_method = 'ML_SUGGESTED_APPROVED' THEN
        v_final_score := LEAST(0.85, v_final_score);
    END IF;

    -- Get band
    v_band := get_confidence_band(v_final_score);

    -- Build rationale JSON
    v_rationale := jsonb_build_object(
        'method', p_method,
        'evidence_count', v_evidence_count,
        'evidence_by_source', COALESCE(v_evidence_by_source, '{}'::jsonb),
        'base_score', v_base_score,
        'evidence_bonus', v_evidence_bonus,
        'source_bonus', v_source_bonus,
        'agreement_bonus', 0.00,  -- TODO: implement in Python
        'recency_bonus', 0.00,     -- TODO: implement in Python
        'curator_delta', 0.00,
        'caps_applied', CASE
            WHEN p_method = 'DETERMINISTIC' AND (v_base_score + v_evidence_bonus + v_source_bonus) > 0.99
                THEN jsonb_build_array('deterministic_cap_0.99')
            WHEN p_method = 'ML_SUGGESTED_APPROVED' AND (v_base_score + v_evidence_bonus + v_source_bonus) > 0.85
                THEN jsonb_build_array('ml_suggested_cap_0.85')
            ELSE '[]'::jsonb
        END,
        'final_score', v_final_score,
        'band', v_band
    );

    -- Return results
    RETURN QUERY SELECT v_final_score, v_band, v_rationale;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 6: BACKFILL FUNCTION
-- ============================================================================

-- Backfill confidence for all assertions
-- Default method is CURATED unless otherwise specified
CREATE OR REPLACE FUNCTION backfill_assertion_confidence(
    p_default_method link_method_enum DEFAULT 'CURATED'::link_method_enum
)
RETURNS TABLE (
    assertions_processed INTEGER,
    assertions_updated INTEGER,
    assertions_skipped INTEGER
) AS $$
DECLARE
    v_processed INTEGER := 0;
    v_updated INTEGER := 0;
    v_skipped INTEGER := 0;
    v_assertion_id BIGINT;
    v_confidence RECORD;
BEGIN
    -- Loop through all active assertions without confidence
    FOR v_assertion_id IN
        SELECT assertion_id
        FROM assertion
        WHERE deleted_at IS NULL
        AND retracted_at IS NULL
        AND link_confidence_score IS NULL
    LOOP
        v_processed := v_processed + 1;

        BEGIN
            -- Compute confidence
            SELECT * INTO v_confidence
            FROM compute_link_confidence(v_assertion_id, p_default_method)
            LIMIT 1;

            -- Update assertion
            UPDATE assertion
            SET
                link_confidence_score = v_confidence.score,
                link_confidence_band = v_confidence.band,
                link_method = p_default_method,
                link_rationale_json = v_confidence.rationale,
                updated_at = NOW()
            WHERE assertion_id = v_assertion_id;

            v_updated := v_updated + 1;

        EXCEPTION
            WHEN OTHERS THEN
                -- Skip assertions with errors (e.g., news-only)
                RAISE NOTICE 'Skipping assertion % due to error: %', v_assertion_id, SQLERRM;
                v_skipped := v_skipped + 1;
        END;
    END LOOP;

    RETURN QUERY SELECT v_processed, v_updated, v_skipped;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 7: VALIDATION CONSTRAINTS (NOT NULL - commented out for now)
-- ============================================================================

-- These will be enabled in PR3 after backfill is complete
-- For now, constraints are optional to allow gradual migration

-- ALTER TABLE assertion ALTER COLUMN link_confidence_score SET NOT NULL;
-- ALTER TABLE assertion ALTER COLUMN link_confidence_band SET NOT NULL;
-- ALTER TABLE assertion ALTER COLUMN link_method SET NOT NULL;
-- ALTER TABLE assertion ALTER COLUMN link_rationale_json SET NOT NULL;

-- Instead, add a validation function that can be called explicitly
CREATE OR REPLACE FUNCTION validate_explanation_assertions()
RETURNS TABLE (
    invalid_assertion_id BIGINT,
    issue TEXT
) AS $$
BEGIN
    -- Find assertions used in explanations without confidence
    RETURN QUERY
    SELECT DISTINCT
        a.assertion_id,
        'Missing confidence fields' as issue
    FROM assertion a
    INNER JOIN (
        SELECT DISTINCT unnest(ARRAY[
            issuer_drug_assertion_id,
            drug_target_assertion_id,
            target_disease_assertion_id
        ]) as assertion_id
        FROM explanation
        WHERE deleted_at IS NULL
    ) e ON a.assertion_id = e.assertion_id
    WHERE
        a.link_confidence_score IS NULL
        OR a.link_confidence_band IS NULL
        OR a.link_method IS NULL
        OR a.link_rationale_json IS NULL;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 8: MIGRATION VALIDATION
-- ============================================================================

-- Verify enum types were created
DO $$
DECLARE
    missing_enums TEXT[];
BEGIN
    SELECT ARRAY_AGG(enum_name)
    INTO missing_enums
    FROM (
        VALUES
            ('link_method_enum'),
            ('link_confidence_band_enum'),
            ('evidence_support_type_enum')
    ) AS required(enum_name)
    WHERE NOT EXISTS (
        SELECT 1 FROM pg_type
        WHERE typname = required.enum_name
        AND typtype = 'e'
    );

    IF array_length(missing_enums, 1) > 0 THEN
        RAISE EXCEPTION 'Migration failed: Missing enum types: %', array_to_string(missing_enums, ', ');
    END IF;

    RAISE NOTICE 'Migration 003 validation passed: All enum types exist';
END $$;

-- Verify columns were added
DO $$
DECLARE
    missing_columns TEXT[];
BEGIN
    SELECT ARRAY_AGG(column_name)
    INTO missing_columns
    FROM (
        VALUES
            ('link_confidence_score'),
            ('link_confidence_band'),
            ('link_method'),
            ('link_rationale_json'),
            ('curator_delta')
    ) AS required(column_name)
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'assertion'
        AND column_name = required.column_name
    );

    IF array_length(missing_columns, 1) > 0 THEN
        RAISE EXCEPTION 'Migration failed: Missing columns in assertion table: %', array_to_string(missing_columns, ', ');
    END IF;

    RAISE NOTICE 'Migration 003 validation passed: All columns exist in assertion table';
END $$;

-- Verify functions were created
DO $$
DECLARE
    function_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO function_count
    FROM pg_proc
    WHERE proname IN ('get_confidence_band', 'compute_link_confidence', 'backfill_assertion_confidence', 'validate_explanation_assertions');

    IF function_count < 4 THEN
        RAISE WARNING 'Migration 003: Expected 4 functions, found %', function_count;
    ELSE
        RAISE NOTICE 'Migration 003 validation passed: % functions created', function_count;
    END IF;
END $$;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Migration 003 (Linkage Confidence) completed successfully';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Added:';
    RAISE NOTICE '  - 3 enum types (link_method, confidence_band, support_type)';
    RAISE NOTICE '  - 5 confidence fields to assertion table (nullable)';
    RAISE NOTICE '  - 1 support_type field to assertion_evidence';
    RAISE NOTICE '  - 4 indexes for confidence queries';
    RAISE NOTICE '  - 4 helper functions (band, compute, backfill, validate)';
    RAISE NOTICE '  - 1 evidence summary view';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '  1. Implement biograph/core/confidence.py (Python)';
    RAISE NOTICE '  2. Run backfill: SELECT * FROM backfill_assertion_confidence();';
    RAISE NOTICE '  3. Validate: SELECT * FROM validate_explanation_assertions();';
    RAISE NOTICE '  4. Enforce NOT NULL constraints (PR3)';
    RAISE NOTICE '==================================================';
END $$;
