-- Migration 002: Evidence-First Data Model
-- Per BioGraph MVP Spec: Evidence-first architecture with license enforcement
-- Date: 2026-01-20
-- Status: P0 Blocker Resolution

-- ============================================================================
-- LICENSE ALLOWLIST (Per Section 14)
-- ============================================================================

CREATE TABLE license_allowlist (
    license TEXT PRIMARY KEY,
    is_commercial_safe BOOLEAN NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE license_allowlist IS 'Commercial-safe license allowlist per Section 14';

-- Seed commercial-safe licenses
INSERT INTO license_allowlist (license, is_commercial_safe, notes) VALUES
    ('CC0', TRUE, 'Public domain - Wikidata, USPTO'),
    ('CC-BY-4.0', TRUE, 'Attribution required - OpenTargets, ChEMBL'),
    ('ODbL', TRUE, 'Open Database License'),
    ('OGL-UK-3.0', TRUE, 'UK Open Government License'),
    ('MIT', TRUE, 'MIT License'),
    ('Apache-2.0', TRUE, 'Apache License 2.0'),
    ('PROPRIETARY', FALSE, 'Subscription required - block'),
    ('CC-BY-NC', FALSE, 'Non-commercial only - block'),
    ('ALL_RIGHTS_RESERVED', FALSE, 'All rights reserved - block');

-- ============================================================================
-- EVIDENCE (Per Section 8)
-- ============================================================================

CREATE TABLE evidence (
    evidence_id SERIAL PRIMARY KEY,
    source_system TEXT NOT NULL,        -- e.g., 'wikidata', 'opentargets', 'sec_edgar'
    source_record_id TEXT NOT NULL,     -- e.g., 'Q312', 'ENSG00000157764', '0001318605'
    evidence_type TEXT,                 -- e.g., 'company_enrichment', 'target_association'
    license TEXT NOT NULL REFERENCES license_allowlist(license),
    url TEXT,                           -- Link to authoritative source
    snippet TEXT,                       -- Bounded text snippet if applicable (max 500 chars)
    checksum TEXT,                      -- Content hash for deduplication (SHA256)
    observed_at TIMESTAMPTZ NOT NULL,   -- When evidence was captured
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE evidence IS 'Evidence records with provenance and license tracking';
COMMENT ON COLUMN evidence.source_system IS 'System that provided the evidence (e.g., wikidata, opentargets)';
COMMENT ON COLUMN evidence.source_record_id IS 'ID of the record in the source system';
COMMENT ON COLUMN evidence.license IS 'License under which this evidence is available';
COMMENT ON COLUMN evidence.observed_at IS 'Timestamp when evidence was captured';

CREATE INDEX evidence_source_idx ON evidence(source_system, source_record_id);
CREATE INDEX evidence_license_idx ON evidence(license);
CREATE INDEX evidence_observed_idx ON evidence(observed_at DESC);
CREATE INDEX evidence_checksum_idx ON evidence(checksum) WHERE checksum IS NOT NULL;

-- ============================================================================
-- ASSERTION (Canonical Claims Derived from Evidence)
-- ============================================================================

CREATE TABLE assertion (
    assertion_id SERIAL PRIMARY KEY,
    assertion_type TEXT NOT NULL,       -- e.g., 'company_identity', 'target_disease', 'drug_target'
    subject_entity_id INT REFERENCES entity(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,            -- e.g., 'enriched_by', 'targets', 'treats'
    object_entity_id INT REFERENCES entity(id) ON DELETE CASCADE,
    confidence TEXT,                    -- 'DETERMINISTIC', 'HIGH', 'MEDIUM', 'LOW'
    effective_from DATE,                -- When assertion became true
    effective_to DATE,                  -- When assertion ceased to be true (NULL = still valid)
    metadata JSONB DEFAULT '{}'::jsonb, -- Additional assertion-specific data
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE assertion IS 'Canonical assertions derived from evidence';
COMMENT ON COLUMN assertion.confidence IS 'Linkage confidence level per biograph.core.confidence';
COMMENT ON COLUMN assertion.effective_from IS 'Temporal validity start (for time-aware queries)';
COMMENT ON COLUMN assertion.effective_to IS 'Temporal validity end (NULL = currently valid)';

CREATE INDEX assertion_subject_idx ON assertion(subject_entity_id);
CREATE INDEX assertion_object_idx ON assertion(object_entity_id);
CREATE INDEX assertion_type_idx ON assertion(assertion_type);
CREATE INDEX assertion_predicate_idx ON assertion(predicate);
CREATE INDEX assertion_effective_idx ON assertion(effective_from, effective_to);

-- ============================================================================
-- ASSERTION_EVIDENCE (Many-to-Many Join)
-- ============================================================================

CREATE TABLE assertion_evidence (
    assertion_id INT REFERENCES assertion(assertion_id) ON DELETE CASCADE,
    evidence_id INT REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    PRIMARY KEY (assertion_id, evidence_id)
);

COMMENT ON TABLE assertion_evidence IS 'Links assertions to supporting evidence (many-to-many)';

CREATE INDEX assertion_evidence_evidence_idx ON assertion_evidence(evidence_id);

-- ============================================================================
-- LOOKUP_CACHE (Thin Durable Core)
-- ============================================================================

CREATE TABLE lookup_cache (
    cache_key TEXT PRIMARY KEY,         -- e.g., 'wikidata:Q312', 'chembl:CHEMBL25'
    source TEXT NOT NULL,               -- 'wikidata', 'chembl', 'geonames', 'mesh'
    value_json JSONB NOT NULL,          -- Cached label/metadata
    expires_at TIMESTAMPTZ NOT NULL,    -- TTL (default: 30 days from creation)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE lookup_cache IS 'Disposable cache for external ontology lookups (Thin Durable Core)';
COMMENT ON COLUMN lookup_cache.cache_key IS 'Unique key: "source:entity_id" format';
COMMENT ON COLUMN lookup_cache.expires_at IS 'Cache expiry (TTL). Entries deleted on access if expired.';

CREATE INDEX lookup_cache_expires_idx ON lookup_cache(expires_at);
CREATE INDEX lookup_cache_source_idx ON lookup_cache(source);

-- ============================================================================
-- TRIGGERS: Evidence License Validation
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_evidence_license()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if license is in allowlist and is commercial-safe
    IF NOT EXISTS (
        SELECT 1 FROM license_allowlist
        WHERE license = NEW.license AND is_commercial_safe = TRUE
    ) THEN
        RAISE EXCEPTION 'License "%" is not commercial-safe or not in allowlist. See license_allowlist table.', NEW.license;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER evidence_license_check
    BEFORE INSERT OR UPDATE ON evidence
    FOR EACH ROW
    EXECUTE FUNCTION validate_evidence_license();

COMMENT ON FUNCTION validate_evidence_license() IS 'Enforces license allowlist at DB level';

-- ============================================================================
-- TRIGGERS: Cache Cleanup
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_expired_cache()
RETURNS TRIGGER AS $$
BEGIN
    -- Delete expired cache entries (lazy cleanup on insert)
    DELETE FROM lookup_cache WHERE expires_at < NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cache_cleanup_trigger
    AFTER INSERT ON lookup_cache
    EXECUTE FUNCTION cleanup_expired_cache();

COMMENT ON FUNCTION cleanup_expired_cache() IS 'Lazy cleanup of expired cache entries';

-- ============================================================================
-- INDEXES: Performance Optimization
-- ============================================================================

-- entity table: optimize search by kind + name
CREATE INDEX IF NOT EXISTS entity_kind_name_idx ON entity(kind, name);

-- edge table: optimize queries by type
CREATE INDEX IF NOT EXISTS edge_type_idx ON edge(type) WHERE type IS NOT NULL;

-- entity table: temporal queries
CREATE INDEX IF NOT EXISTS entity_updated_at_idx ON entity(updated_at DESC);

-- ============================================================================
-- VALIDATION: Verify Migration
-- ============================================================================

DO $$
BEGIN
    -- Verify tables exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'evidence') THEN
        RAISE EXCEPTION 'Migration failed: evidence table not created';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'assertion') THEN
        RAISE EXCEPTION 'Migration failed: assertion table not created';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'lookup_cache') THEN
        RAISE EXCEPTION 'Migration failed: lookup_cache table not created';
    END IF;

    -- Verify seed data
    IF (SELECT COUNT(*) FROM license_allowlist WHERE is_commercial_safe = TRUE) < 5 THEN
        RAISE EXCEPTION 'Migration failed: license_allowlist not properly seeded';
    END IF;

    RAISE NOTICE 'Migration 002: Evidence model created successfully';
END $$;
