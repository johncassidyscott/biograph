-- BioGraph MVP v8.2 - Lookup Cache (Thin Durable Core)
-- Implements Section 23: Data Retention & Resolution Posture
--
-- Purpose: Lightweight, disposable cache for live-resolved labels
-- (OpenTargets, ChEMBL, GeoNames, Wikidata)
--
-- Changes:
-- 1. Create lookup_cache table
-- 2. Add cache source enum
-- 3. Add helper functions for cache management
-- 4. Add indexes for fast lookups
-- 5. Add cleanup function for expired entries

-- ============================================================================
-- SECTION 1: ENUM TYPE FOR CACHE SOURCES
-- ============================================================================

-- Cache source enum (what external system this cache entry came from)
CREATE TYPE cache_source_enum AS ENUM (
    'opentargets',
    'chembl',
    'geonames',
    'wikidata'
);

-- ============================================================================
-- SECTION 2: LOOKUP CACHE TABLE
-- ============================================================================

-- Lookup Cache: Disposable cache for ID → label lookups
-- Per Section 23D, this cache is NOT truth; it's presentation layer only.
-- Can be dropped and rebuilt anytime without data loss.

CREATE TABLE IF NOT EXISTS lookup_cache (
    cache_key       TEXT PRIMARY KEY,               -- Format: "{source}:{id}"
    source          cache_source_enum NOT NULL,     -- Which external system
    value_json      JSONB NOT NULL,                 -- Cached data (label + metadata)
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,           -- TTL enforcement
    hit_count       INTEGER DEFAULT 0,              -- Cache hit counter
    last_hit_at     TIMESTAMPTZ,                    -- Last access time
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast lookups and cleanup
CREATE INDEX IF NOT EXISTS idx_lookup_cache_source ON lookup_cache(source);
CREATE INDEX IF NOT EXISTS idx_lookup_cache_expires ON lookup_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_lookup_cache_hits ON lookup_cache(hit_count DESC, last_hit_at DESC);

-- GIN index for JSONB queries (if needed)
CREATE INDEX IF NOT EXISTS idx_lookup_cache_value_gin ON lookup_cache USING gin(value_json jsonb_path_ops);

-- ============================================================================
-- SECTION 3: CACHE HELPER FUNCTIONS
-- ============================================================================

-- Function: Get from cache or return NULL
CREATE OR REPLACE FUNCTION cache_get(
    p_cache_key TEXT
)
RETURNS JSONB AS $$
DECLARE
    v_value JSONB;
    v_expires_at TIMESTAMPTZ;
BEGIN
    -- Try to get from cache
    SELECT value_json, expires_at
    INTO v_value, v_expires_at
    FROM lookup_cache
    WHERE cache_key = p_cache_key;

    -- If not found, return NULL
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    -- If expired, delete and return NULL
    IF v_expires_at < NOW() THEN
        DELETE FROM lookup_cache WHERE cache_key = p_cache_key;
        RETURN NULL;
    END IF;

    -- Update hit count and last hit time
    UPDATE lookup_cache
    SET hit_count = hit_count + 1,
        last_hit_at = NOW()
    WHERE cache_key = p_cache_key;

    RETURN v_value;
END;
$$ LANGUAGE plpgsql;

-- Function: Set cache entry with TTL
CREATE OR REPLACE FUNCTION cache_set(
    p_cache_key TEXT,
    p_source cache_source_enum,
    p_value_json JSONB,
    p_ttl_days INTEGER DEFAULT 30
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO lookup_cache (
        cache_key,
        source,
        value_json,
        expires_at
    ) VALUES (
        p_cache_key,
        p_source,
        p_value_json,
        NOW() + (p_ttl_days || ' days')::INTERVAL
    )
    ON CONFLICT (cache_key) DO UPDATE SET
        value_json = EXCLUDED.value_json,
        fetched_at = NOW(),
        expires_at = NOW() + (p_ttl_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql;

-- Function: Delete cache entry
CREATE OR REPLACE FUNCTION cache_delete(
    p_cache_key TEXT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_deleted BOOLEAN;
BEGIN
    DELETE FROM lookup_cache WHERE cache_key = p_cache_key;
    GET DIAGNOSTICS v_deleted = FOUND;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- Function: Clear all cache entries for a source
CREATE OR REPLACE FUNCTION cache_clear_source(
    p_source cache_source_enum
)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    DELETE FROM lookup_cache WHERE source = p_source;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Clear all expired entries
CREATE OR REPLACE FUNCTION cache_cleanup_expired()
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    DELETE FROM lookup_cache WHERE expires_at < NOW();
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Get cache statistics
CREATE OR REPLACE FUNCTION cache_stats()
RETURNS TABLE (
    source cache_source_enum,
    total_entries BIGINT,
    expired_entries BIGINT,
    valid_entries BIGINT,
    total_hits BIGINT,
    avg_hits NUMERIC,
    oldest_entry TIMESTAMPTZ,
    newest_entry TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        lc.source,
        COUNT(*) as total_entries,
        COUNT(*) FILTER (WHERE lc.expires_at < NOW()) as expired_entries,
        COUNT(*) FILTER (WHERE lc.expires_at >= NOW()) as valid_entries,
        SUM(lc.hit_count) as total_hits,
        ROUND(AVG(lc.hit_count), 2) as avg_hits,
        MIN(lc.fetched_at) as oldest_entry,
        MAX(lc.fetched_at) as newest_entry
    FROM lookup_cache lc
    GROUP BY lc.source;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 4: AUTOMATIC CLEANUP (CRON JOB HELPER)
-- ============================================================================

-- View: Cache entries needing cleanup
CREATE OR REPLACE VIEW cache_expired_entries AS
SELECT
    cache_key,
    source,
    expires_at,
    fetched_at,
    NOW() - expires_at AS expired_duration
FROM lookup_cache
WHERE expires_at < NOW()
ORDER BY expires_at ASC;

-- View: Cache performance metrics
CREATE OR REPLACE VIEW cache_performance AS
SELECT
    source,
    COUNT(*) as entry_count,
    SUM(hit_count) as total_hits,
    ROUND(AVG(hit_count), 2) as avg_hits_per_entry,
    MAX(hit_count) as max_hits,
    COUNT(*) FILTER (WHERE last_hit_at > NOW() - INTERVAL '7 days') as active_last_week,
    COUNT(*) FILTER (WHERE hit_count = 0) as never_hit,
    ROUND(100.0 * COUNT(*) FILTER (WHERE hit_count = 0) / NULLIF(COUNT(*), 0), 1) as never_hit_pct
FROM lookup_cache
GROUP BY source
ORDER BY total_hits DESC;

-- ============================================================================
-- SECTION 5: THIN CORE VALIDATION VIEWS
-- ============================================================================

-- View: Validate thin core principles (no bulk ontology tables)
-- This view should return empty results if thin core is properly enforced
CREATE OR REPLACE VIEW thin_core_violations AS
SELECT
    'target' as table_name,
    COUNT(*) as row_count,
    'Should only contain targets referenced by assertions' as issue
FROM target
WHERE target_id NOT IN (
    SELECT DISTINCT subject_id FROM assertion WHERE subject_type = 'target'
    UNION
    SELECT DISTINCT object_id FROM assertion WHERE object_type = 'target'
)
HAVING COUNT(*) > 100  -- Allow small number of unreferenced targets

UNION ALL

SELECT
    'disease' as table_name,
    COUNT(*) as row_count,
    'Should only contain diseases referenced by assertions' as issue
FROM disease
WHERE disease_id NOT IN (
    SELECT DISTINCT object_id FROM assertion WHERE object_type = 'disease'
)
HAVING COUNT(*) > 100  -- Allow small number of unreferenced diseases

UNION ALL

SELECT
    'lookup_cache' as table_name,
    COUNT(*) as row_count,
    'Cache should be small (<10K entries for MVP)' as issue
FROM lookup_cache
HAVING COUNT(*) > 10000;

-- ============================================================================
-- SECTION 6: MIGRATION VALIDATION
-- ============================================================================

-- Verify cache table was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = 'lookup_cache'
    ) THEN
        RAISE EXCEPTION 'Migration failed: lookup_cache table not created';
    END IF;

    RAISE NOTICE 'Migration 004 validation passed: lookup_cache table exists';
END $$;

-- Verify cache source enum was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type
        WHERE typname = 'cache_source_enum'
        AND typtype = 'e'
    ) THEN
        RAISE EXCEPTION 'Migration failed: cache_source_enum not created';
    END IF;

    RAISE NOTICE 'Migration 004 validation passed: cache_source_enum exists';
END $$;

-- Verify helper functions were created
DO $$
DECLARE
    function_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO function_count
    FROM pg_proc
    WHERE proname IN (
        'cache_get',
        'cache_set',
        'cache_delete',
        'cache_clear_source',
        'cache_cleanup_expired',
        'cache_stats'
    );

    IF function_count < 6 THEN
        RAISE WARNING 'Migration 004: Expected 6 cache functions, found %', function_count;
    ELSE
        RAISE NOTICE 'Migration 004 validation passed: % cache functions created', function_count;
    END IF;
END $$;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Migration 004 (Lookup Cache) completed successfully';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Added:';
    RAISE NOTICE '  - lookup_cache table (disposable cache)';
    RAISE NOTICE '  - cache_source_enum (opentargets, chembl, geonames, wikidata)';
    RAISE NOTICE '  - 6 cache helper functions (get, set, delete, clear, cleanup, stats)';
    RAISE NOTICE '  - 4 indexes for fast lookups and cleanup';
    RAISE NOTICE '  - 3 views (expired_entries, performance, thin_core_violations)';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Thin Durable Core Principles (Section 23):';
    RAISE NOTICE '  - Cache is DISPOSABLE (not truth)';
    RAISE NOTICE '  - Default TTL: 30 days';
    RAISE NOTICE '  - Live resolution on cache miss';
    RAISE NOTICE '  - Fallback to ID on live fetch failure';
    RAISE NOTICE '  - Cache does NOT affect linkage confidence';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '  1. Implement resolvers (biograph/integrations/)';
    RAISE NOTICE '  2. Wire into API (presentation layer only)';
    RAISE NOTICE '  3. Run periodic cleanup: SELECT cache_cleanup_expired();';
    RAISE NOTICE '  4. Monitor stats: SELECT * FROM cache_performance;';
    RAISE NOTICE '==================================================';
END $$;
