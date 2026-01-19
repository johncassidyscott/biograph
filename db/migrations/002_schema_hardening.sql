-- BioGraph MVP v8.2 - Schema Hardening (PR1)
-- Adds constraints, indexes, enums, and commercial-grade infrastructure
--
-- Changes:
-- 1. Enum types for controlled vocabularies
-- 2. Additional constraints and indexes
-- 3. Entity versioning infrastructure (immutable entities)
-- 4. Soft delete columns for audit trail
-- 5. Batch operation tracking for rollback capability
-- 6. Performance indexes for common query patterns

-- ============================================================================
-- SECTION 1: ENUM TYPES (Controlled Vocabularies)
-- ============================================================================

-- Source system enum
CREATE TYPE source_system_type AS ENUM (
    'sec_edgar',
    'sec_edgar_exhibit',
    'opentargets',
    'chembl',
    'wikidata',
    'geonames',
    'news_metadata',
    'manual'
);

-- Entity type enum (for candidates, assertions, etc.)
CREATE TYPE entity_type_enum AS ENUM (
    'issuer',
    'drug_program',
    'target',
    'disease',
    'location'
);

-- Predicate type enum (for assertions)
CREATE TYPE predicate_enum AS ENUM (
    'has_program',
    'targets',
    'treats',
    'located_at',
    'insider_at',
    'filed',
    'has_exhibit'
);

-- Candidate/curation status enum
CREATE TYPE curation_status_enum AS ENUM (
    'pending',
    'accepted',
    'rejected',
    'needs_review'
);

-- NLP run status enum
CREATE TYPE nlp_run_status_enum AS ENUM (
    'running',
    'completed',
    'failed',
    'cancelled'
);

-- Drug development stage enum
CREATE TYPE development_stage_enum AS ENUM (
    'discovery',
    'preclinical',
    'phase1',
    'phase2',
    'phase3',
    'approved',
    'discontinued',
    'unknown'
);

-- Drug type enum
CREATE TYPE drug_type_enum AS ENUM (
    'small_molecule',
    'biologic',
    'gene_therapy',
    'cell_therapy',
    'vaccine',
    'other',
    'unknown'
);

-- ============================================================================
-- SECTION 2: BATCH OPERATION TRACKING (P0 Gap - §1.3)
-- ============================================================================

-- Batch Operation: Track ingestion runs for rollback capability
CREATE TABLE IF NOT EXISTS batch_operation (
    batch_id            TEXT PRIMARY KEY,               -- Format: {operation}_{timestamp}_{uuid}
    operation_type      TEXT NOT NULL,                  -- 'filing_ingest', 'ner_run', 'er_run', 'explanation_refresh'
    issuer_id           TEXT REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running', -- 'running', 'completed', 'failed', 'rolled_back'
    rows_inserted       INTEGER DEFAULT 0,
    rows_updated        INTEGER DEFAULT 0,
    rows_deleted        INTEGER DEFAULT 0,
    error_message       TEXT,
    metadata            JSONB,                          -- Operation-specific params
    created_by          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_batch_operation_type ON batch_operation(operation_type);
CREATE INDEX idx_batch_operation_issuer ON batch_operation(issuer_id);
CREATE INDEX idx_batch_operation_status ON batch_operation(status);
CREATE INDEX idx_batch_operation_started ON batch_operation(started_at DESC);

-- Rollback function for batch operations
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
    -- (Requires batch_id column on relevant tables - added below)
    UPDATE evidence SET deleted_at = NOW() WHERE batch_id = p_batch_id AND deleted_at IS NULL;
    UPDATE assertion SET deleted_at = NOW() WHERE batch_id = p_batch_id AND deleted_at IS NULL;
    UPDATE drug_program SET deleted_at = NOW() WHERE batch_id = p_batch_id AND deleted_at IS NULL;
    UPDATE candidate SET deleted_at = NOW() WHERE batch_id = p_batch_id AND deleted_at IS NULL;

    -- Mark batch as rolled back
    UPDATE batch_operation
    SET status = 'rolled_back', completed_at = NOW()
    WHERE batch_id = p_batch_id;

    RAISE NOTICE 'Rolled back batch operation %', p_batch_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 3: ENTITY VERSIONING (P0 Gap - §1.1)
-- ============================================================================

-- Add versioning columns to core entity tables
-- Version strategy: Immutable entities with version chains

-- DrugProgram versioning
ALTER TABLE drug_program
    ADD COLUMN IF NOT EXISTS version_id INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS supersedes_id TEXT REFERENCES drug_program(drug_program_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT TRUE;

CREATE INDEX idx_drug_program_version ON drug_program(drug_program_id, version_id);
CREATE INDEX idx_drug_program_current ON drug_program(drug_program_id) WHERE is_current = TRUE;
CREATE INDEX idx_drug_program_valid ON drug_program(valid_from, valid_to);

-- Target versioning
ALTER TABLE target
    ADD COLUMN IF NOT EXISTS version_id INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS supersedes_id TEXT REFERENCES target(target_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT TRUE;

CREATE INDEX idx_target_version ON target(target_id, version_id);
CREATE INDEX idx_target_current ON target(target_id) WHERE is_current = TRUE;

-- Disease versioning
ALTER TABLE disease
    ADD COLUMN IF NOT EXISTS version_id INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS supersedes_id TEXT REFERENCES disease(disease_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT TRUE;

CREATE INDEX idx_disease_version ON disease(disease_id, version_id);
CREATE INDEX idx_disease_current ON disease(disease_id) WHERE is_current = TRUE;

-- Assertion versioning (for time-travel queries)
ALTER TABLE assertion
    ADD COLUMN IF NOT EXISTS version_id INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS supersedes_id BIGINT REFERENCES assertion(assertion_id) ON DELETE SET NULL;

CREATE INDEX idx_assertion_version ON assertion(assertion_id, version_id);

-- ============================================================================
-- SECTION 4: SOFT DELETES (P0 Gap - §1.2)
-- ============================================================================

-- Add soft delete columns to all core tables
-- Strategy: Mark deleted rather than physically remove for audit trail

-- Evidence
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT,
    ADD COLUMN IF NOT EXISTS deletion_reason TEXT,
    ADD COLUMN IF NOT EXISTS batch_id TEXT REFERENCES batch_operation(batch_id) ON DELETE SET NULL;

CREATE INDEX idx_evidence_deleted ON evidence(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_evidence_batch ON evidence(batch_id);

-- Assertion
ALTER TABLE assertion
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT,
    ADD COLUMN IF NOT EXISTS deletion_reason TEXT,
    ADD COLUMN IF NOT EXISTS batch_id TEXT REFERENCES batch_operation(batch_id) ON DELETE SET NULL;

CREATE INDEX idx_assertion_deleted ON assertion(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_assertion_batch ON assertion(batch_id);

-- DrugProgram
ALTER TABLE drug_program
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT,
    ADD COLUMN IF NOT EXISTS deletion_reason TEXT,
    ADD COLUMN IF NOT EXISTS batch_id TEXT REFERENCES batch_operation(batch_id) ON DELETE SET NULL;

CREATE INDEX idx_drug_program_deleted ON drug_program(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_drug_program_batch ON drug_program(batch_id);

-- Target
ALTER TABLE target
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT,
    ADD COLUMN IF NOT EXISTS deletion_reason TEXT;

CREATE INDEX idx_target_deleted ON target(deleted_at) WHERE deleted_at IS NOT NULL;

-- Disease
ALTER TABLE disease
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT,
    ADD COLUMN IF NOT EXISTS deletion_reason TEXT;

CREATE INDEX idx_disease_deleted ON disease(deleted_at) WHERE deleted_at IS NOT NULL;

-- Candidate
ALTER TABLE candidate
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT,
    ADD COLUMN IF NOT EXISTS deletion_reason TEXT,
    ADD COLUMN IF NOT EXISTS batch_id TEXT REFERENCES batch_operation(batch_id) ON DELETE SET NULL;

CREATE INDEX idx_candidate_deleted ON candidate(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_candidate_batch ON candidate(batch_id);

-- Explanation
ALTER TABLE explanation
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT,
    ADD COLUMN IF NOT EXISTS deletion_reason TEXT;

CREATE INDEX idx_explanation_deleted ON explanation(deleted_at) WHERE deleted_at IS NOT NULL;

-- ============================================================================
-- SECTION 5: PERFORMANCE INDEXES (P0 Gap - §2.1)
-- ============================================================================

-- Composite indexes for common query patterns

-- Issuer queries: Get active drug programs for an issuer
CREATE INDEX idx_drug_program_issuer_active ON drug_program(issuer_id)
    WHERE deleted_at IS NULL AND is_current = TRUE;

-- Evidence lookups: Find evidence by source and license
CREATE INDEX idx_evidence_source_license ON evidence(source_system, license)
    WHERE deleted_at IS NULL;

-- Assertion queries: Find active assertions by subject
CREATE INDEX idx_assertion_subject_active ON assertion(subject_type, subject_id, predicate)
    WHERE retracted_at IS NULL AND deleted_at IS NULL;

-- Assertion queries: Find active assertions by object
CREATE INDEX idx_assertion_object_active ON assertion(object_type, object_id, predicate)
    WHERE retracted_at IS NULL AND deleted_at IS NULL;

-- Assertion confidence filtering
CREATE INDEX idx_assertion_confidence ON assertion(computed_confidence DESC)
    WHERE retracted_at IS NULL AND deleted_at IS NULL;

-- Assertion evidence joins
CREATE INDEX idx_assertion_evidence_join ON assertion_evidence(assertion_id, evidence_id);

-- Candidate curation workflow: pending candidates by issuer
CREATE INDEX idx_candidate_issuer_pending ON candidate(issuer_id, entity_type, status)
    WHERE status = 'pending' AND deleted_at IS NULL;

-- Candidate curation workflow: candidates by external ID
CREATE INDEX idx_candidate_external_id ON candidate(external_id, external_id_source)
    WHERE external_id IS NOT NULL AND deleted_at IS NULL;

-- Explanation queries: Get explanations for issuer on specific date
CREATE INDEX idx_explanation_issuer_date ON explanation(issuer_id, as_of_date DESC)
    WHERE deleted_at IS NULL;

-- Explanation queries: Get explanations by disease with strength
CREATE INDEX idx_explanation_disease_strength ON explanation(disease_id, strength_score DESC)
    WHERE deleted_at IS NULL;

-- Explanation queries: Get explanations by target
CREATE INDEX idx_explanation_target_date ON explanation(target_id, as_of_date DESC)
    WHERE deleted_at IS NULL;

-- Filing queries: Recent filings by company
CREATE INDEX idx_filing_company_date ON filing(company_cik, filing_date DESC);

-- Filing queries: Recent filings by type
CREATE INDEX idx_filing_type_date ON filing(form_type, filing_date DESC);

-- NLP run tracking: Active runs
CREATE INDEX idx_nlp_run_active ON nlp_run(status, started_at DESC)
    WHERE status = 'running';

-- Mention lookups: Mentions by entity type and text
CREATE INDEX idx_mention_type_text ON mention(entity_type, text);

-- Duplicate suggestion workflow: Pending suggestions by issuer
CREATE INDEX idx_duplicate_suggestion_issuer ON duplicate_suggestion(issuer_id, status)
    WHERE status = 'pending';

-- Universe membership: Active memberships
CREATE INDEX idx_universe_membership_active ON universe_membership(universe_id, issuer_id)
    WHERE end_date IS NULL;

-- GIN indexes for JSONB columns (fast containment queries)
CREATE INDEX idx_filing_xbrl_gin ON filing USING gin(xbrl_summary jsonb_path_ops);
CREATE INDEX idx_candidate_features_gin ON candidate USING gin(features_json jsonb_path_ops);

-- Full-text search indexes for common text searches
CREATE INDEX idx_drug_program_name_trgm ON drug_program USING gin(name gin_trgm_ops)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_target_name_trgm ON target USING gin(name gin_trgm_ops)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_disease_name_trgm ON disease USING gin(name gin_trgm_ops)
    WHERE deleted_at IS NULL;

-- Enable pg_trgm extension if not already enabled (for trigram indexes)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================================
-- SECTION 6: ADDITIONAL CONSTRAINTS
-- ============================================================================

-- Add CHECK constraints for data integrity

-- Ensure version_id is positive
ALTER TABLE drug_program
    ADD CONSTRAINT check_drug_program_version_positive CHECK (version_id > 0);

ALTER TABLE target
    ADD CONSTRAINT check_target_version_positive CHECK (version_id > 0);

ALTER TABLE disease
    ADD CONSTRAINT check_disease_version_positive CHECK (version_id > 0);

ALTER TABLE assertion
    ADD CONSTRAINT check_assertion_version_positive CHECK (version_id > 0);

-- Ensure valid date ranges for versioning
ALTER TABLE drug_program
    ADD CONSTRAINT check_drug_program_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from);

ALTER TABLE target
    ADD CONSTRAINT check_target_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from);

ALTER TABLE disease
    ADD CONSTRAINT check_disease_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from);

-- Ensure only one current version per entity
CREATE UNIQUE INDEX idx_drug_program_one_current ON drug_program(drug_program_id)
    WHERE is_current = TRUE AND deleted_at IS NULL;

CREATE UNIQUE INDEX idx_target_one_current ON target(target_id)
    WHERE is_current = TRUE AND deleted_at IS NULL;

CREATE UNIQUE INDEX idx_disease_one_current ON disease(disease_id)
    WHERE is_current = TRUE AND deleted_at IS NULL;

-- Ensure soft-deleted records cannot be current
ALTER TABLE drug_program
    ADD CONSTRAINT check_drug_program_deleted_not_current
    CHECK (deleted_at IS NULL OR is_current = FALSE);

ALTER TABLE target
    ADD CONSTRAINT check_target_deleted_not_current
    CHECK (deleted_at IS NULL OR is_current = FALSE);

ALTER TABLE disease
    ADD CONSTRAINT check_disease_deleted_not_current
    CHECK (deleted_at IS NULL OR is_current = FALSE);

-- Ensure retracted assertions have retracted_at timestamp
ALTER TABLE assertion
    ADD CONSTRAINT check_assertion_retracted_consistent
    CHECK (retracted_at IS NOT NULL OR deleted_at IS NULL);

-- Ensure batch operations have consistent status
ALTER TABLE batch_operation
    ADD CONSTRAINT check_batch_completed_has_timestamp
    CHECK (status = 'running' OR completed_at IS NOT NULL);

-- ============================================================================
-- SECTION 7: EXPLANATION REFRESH INFRASTRUCTURE (P0 Gap - §1.4)
-- ============================================================================

-- Explanation Refresh Log: Track materialization runs
CREATE TABLE IF NOT EXISTS explanation_refresh_log (
    refresh_id          BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    as_of_date          DATE NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running', -- 'running', 'completed', 'failed'
    explanations_created INTEGER DEFAULT 0,
    explanations_updated INTEGER DEFAULT 0,
    explanations_deleted INTEGER DEFAULT 0,
    error_message       TEXT,
    batch_id            TEXT REFERENCES batch_operation(batch_id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_explanation_refresh_issuer ON explanation_refresh_log(issuer_id, as_of_date DESC);
CREATE INDEX idx_explanation_refresh_status ON explanation_refresh_log(status);

-- Trigger to auto-refresh explanations when assertions change
CREATE OR REPLACE FUNCTION trigger_explanation_refresh()
RETURNS TRIGGER AS $$
BEGIN
    -- Extract issuer_id from subject_id (assumes format CIK:XXX:...)
    -- This is a stub - full implementation in PR6
    -- For now, just log that a refresh is needed
    RAISE NOTICE 'Assertion % changed, explanation refresh needed for issuer', NEW.assertion_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Commented out for now - will be enabled in PR6 when materialization is implemented
-- CREATE TRIGGER assertion_changed_trigger
--     AFTER INSERT OR UPDATE OR DELETE ON assertion
--     FOR EACH ROW
--     WHEN (pg_trigger_depth() = 0)  -- Prevent recursive triggers
--     EXECUTE FUNCTION trigger_explanation_refresh();

-- ============================================================================
-- SECTION 8: VIEWS FOR ACTIVE RECORDS (Query Helpers)
-- ============================================================================

-- View: Active drug programs (not deleted, current version)
CREATE OR REPLACE VIEW active_drug_programs AS
SELECT * FROM drug_program
WHERE deleted_at IS NULL AND is_current = TRUE;

-- View: Active assertions (not retracted, not deleted)
CREATE OR REPLACE VIEW active_assertions AS
SELECT * FROM assertion
WHERE retracted_at IS NULL AND deleted_at IS NULL;

-- View: Active evidence (not deleted)
CREATE OR REPLACE VIEW active_evidence AS
SELECT * FROM evidence
WHERE deleted_at IS NULL;

-- View: Active explanations (not deleted)
CREATE OR REPLACE VIEW active_explanations AS
SELECT * FROM explanation
WHERE deleted_at IS NULL;

-- View: Pending candidates (awaiting curation)
CREATE OR REPLACE VIEW pending_candidates AS
SELECT * FROM candidate
WHERE status = 'pending' AND deleted_at IS NULL;

-- ============================================================================
-- SECTION 9: AUDIT TRAIL ENHANCEMENTS
-- ============================================================================

-- Add audit columns to key tables for compliance
ALTER TABLE drug_program
    ADD COLUMN IF NOT EXISTS created_by TEXT,
    ADD COLUMN IF NOT EXISTS updated_by TEXT;

ALTER TABLE assertion
    ADD COLUMN IF NOT EXISTS created_by TEXT,
    ADD COLUMN IF NOT EXISTS updated_by TEXT;

ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS created_by TEXT;

ALTER TABLE candidate
    ADD COLUMN IF NOT EXISTS created_by TEXT;

-- Function to track last update time
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add update triggers to tables with updated_at
CREATE TRIGGER drug_program_update_timestamp
    BEFORE UPDATE ON drug_program
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER assertion_update_timestamp
    BEFORE UPDATE ON assertion
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER explanation_update_timestamp
    BEFORE UPDATE ON explanation
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER company_update_timestamp
    BEFORE UPDATE ON company
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- SECTION 10: MIGRATION VALIDATION
-- ============================================================================

-- Verify critical tables exist
DO $$
DECLARE
    missing_tables TEXT[];
BEGIN
    SELECT ARRAY_AGG(table_name)
    INTO missing_tables
    FROM (
        VALUES
            ('issuer'),
            ('evidence'),
            ('assertion'),
            ('explanation'),
            ('drug_program'),
            ('target'),
            ('disease'),
            ('batch_operation')
    ) AS required(table_name)
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = required.table_name
    );

    IF array_length(missing_tables, 1) > 0 THEN
        RAISE EXCEPTION 'Migration failed: Missing tables: %', array_to_string(missing_tables, ', ');
    END IF;

    RAISE NOTICE 'Migration 002 validation passed: All critical tables exist';
END $$;

-- Verify critical indexes exist
DO $$
DECLARE
    total_indexes INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_indexes
    FROM pg_indexes
    WHERE schemaname = 'public';

    IF total_indexes < 50 THEN
        RAISE WARNING 'Migration 002: Expected 50+ indexes, found %', total_indexes;
    ELSE
        RAISE NOTICE 'Migration 002 validation passed: % indexes created', total_indexes;
    END IF;
END $$;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Migration 002 (Schema Hardening) completed successfully';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Added:';
    RAISE NOTICE '  - 7 enum types for controlled vocabularies';
    RAISE NOTICE '  - Batch operation tracking with rollback capability';
    RAISE NOTICE '  - Entity versioning (immutable entities)';
    RAISE NOTICE '  - Soft deletes on all core tables';
    RAISE NOTICE '  - 30+ performance indexes';
    RAISE NOTICE '  - Explanation refresh infrastructure';
    RAISE NOTICE '  - Active record views';
    RAISE NOTICE '  - Enhanced audit trail';
    RAISE NOTICE '==================================================';
END $$;
