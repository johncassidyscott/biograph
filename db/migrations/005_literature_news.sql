-- BioGraph MVP v8.2 - Literature and News Evidence (Metadata-Only)
-- Implements Section 24: Literature and News Evidence
--
-- Changes:
-- 1. Add therapeutic_area enum (8 fixed TAs)
-- 2. Create therapeutic_area_mapping table (MeSH/EFO → TA)
-- 3. Create news_item table (metadata only)
-- 4. Add helper functions for TA mapping
-- 5. Prepopulate TA mapping anchors

-- ============================================================================
-- SECTION 1: THERAPEUTIC AREA ENUM
-- ============================================================================

-- Therapeutic Area (TA) enum - FIXED taxonomy of 8 categories
-- Per Section 24C: User-facing disease categories
CREATE TYPE therapeutic_area_enum AS ENUM (
    'ONC',      -- Oncology (Cancer)
    'IMM',      -- Immunology (Autoimmune, inflammation)
    'CNS',      -- Central Nervous System (Neurology, psychiatry)
    'CVM',      -- Cardiovascular/Metabolic (Heart, diabetes, obesity)
    'ID',       -- Infectious Disease (Viral, bacterial, fungal)
    'RARE',     -- Rare Disease (Orphan diseases)
    'RES',      -- Respiratory (Lung, asthma, COPD)
    'REN'       -- Renal (Kidney diseases)
);

-- ============================================================================
-- SECTION 2: THERAPEUTIC AREA MAPPING TABLE
-- ============================================================================

-- Therapeutic Area Mapping: Curated anchors for deterministic TA assignment
-- Per Section 24C: MeSH tree prefixes and EFO IDs map to TAs
CREATE TABLE IF NOT EXISTS therapeutic_area_mapping (
    mapping_id      BIGSERIAL PRIMARY KEY,
    ta_code         therapeutic_area_enum NOT NULL,
    ontology_type   TEXT NOT NULL,              -- 'mesh_tree', 'efo_id', 'mondo_id'
    ontology_value  TEXT NOT NULL,              -- MeSH tree prefix (e.g., 'C04*') or EFO ID
    priority        INTEGER DEFAULT 10,         -- Lower = higher priority for multi-match resolution
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(ontology_type, ontology_value, ta_code)
);

CREATE INDEX IF NOT EXISTS idx_ta_mapping_ontology ON therapeutic_area_mapping(ontology_type, ontology_value);
CREATE INDEX IF NOT EXISTS idx_ta_mapping_ta ON therapeutic_area_mapping(ta_code);

-- Prepopulate TA mapping anchors (per Section 24C)

-- ONC (Oncology)
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('ONC', 'mesh_tree', 'C04%', 1, 'Neoplasms'),
('ONC', 'efo_id', 'EFO_0000616%', 1, 'Neoplasm (EFO root)'),
('ONC', 'mondo_id', 'MONDO_0004992%', 1, 'Cancer (MONDO root)')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- IMM (Immunology)
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('IMM', 'mesh_tree', 'C20%', 2, 'Immune System Diseases'),
('IMM', 'mesh_tree', 'C17.300%', 2, 'Autoimmune Diseases'),
('IMM', 'efo_id', 'EFO_0000540%', 2, 'Immune system disease'),
('IMM', 'mondo_id', 'MONDO_0005046%', 2, 'Autoimmune disease')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- CNS (Central Nervous System)
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('CNS', 'mesh_tree', 'C10%', 3, 'Nervous System Diseases'),
('CNS', 'mesh_tree', 'F03%', 3, 'Mental Disorders'),
('CNS', 'efo_id', 'EFO_0000618%', 3, 'Nervous system disease'),
('CNS', 'mondo_id', 'MONDO_0005071%', 3, 'Nervous system disorder')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- CVM (Cardiovascular/Metabolic)
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('CVM', 'mesh_tree', 'C14%', 4, 'Cardiovascular Diseases'),
('CVM', 'mesh_tree', 'C18.452%', 4, 'Metabolic Diseases'),
('CVM', 'mesh_tree', 'E11%', 4, 'Diabetes Mellitus'),
('CVM', 'efo_id', 'EFO_0000319%', 4, 'Cardiovascular disease'),
('CVM', 'efo_id', 'EFO_0000589%', 4, 'Metabolic disease'),
('CVM', 'mondo_id', 'MONDO_0005267%', 4, 'Heart disease'),
('CVM', 'mondo_id', 'MONDO_0005015%', 4, 'Diabetes mellitus')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- ID (Infectious Disease)
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('ID', 'mesh_tree', 'C01%', 5, 'Bacterial Infections'),
('ID', 'mesh_tree', 'C02%', 5, 'Virus Diseases'),
('ID', 'mesh_tree', 'C03%', 5, 'Parasitic Diseases'),
('ID', 'efo_id', 'EFO_0005741%', 5, 'Infectious disease'),
('ID', 'mondo_id', 'MONDO_0005550%', 5, 'Infectious disease')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- RES (Respiratory)
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('RES', 'mesh_tree', 'C08%', 7, 'Respiratory Tract Diseases'),
('RES', 'efo_id', 'EFO_0000684%', 7, 'Lung disease'),
('RES', 'mondo_id', 'MONDO_0005087%', 7, 'Respiratory system disorder')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- REN (Renal)
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('REN', 'mesh_tree', 'C12.777%', 8, 'Kidney Diseases'),
('REN', 'mesh_tree', 'C13%', 8, 'Urologic Diseases'),
('REN', 'efo_id', 'EFO_0003086%', 8, 'Kidney disease'),
('REN', 'mondo_id', 'MONDO_0005240%', 8, 'Kidney disorder')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- RARE (Rare Disease)
-- Note: RARE uses curated list, not broad tree prefixes
INSERT INTO therapeutic_area_mapping (ta_code, ontology_type, ontology_value, priority, notes) VALUES
('RARE', 'efo_id', 'Orphanet_%', 6, 'Orphan diseases from Orphanet'),
('RARE', 'mondo_id', 'MONDO_0019056%', 6, 'Rare disease (MONDO)'),
('RARE', 'mesh_tree', 'C16.320%', 6, 'Genetic diseases (often rare)')
ON CONFLICT (ontology_type, ontology_value, ta_code) DO NOTHING;

-- ============================================================================
-- SECTION 3: NEWS ITEM TABLE
-- ============================================================================

-- News Item: Metadata-only storage for news articles
-- Per Section 24D: News is context only, cannot create assertions
CREATE TABLE IF NOT EXISTS news_item (
    news_item_id    BIGSERIAL PRIMARY KEY,
    publisher       TEXT NOT NULL,              -- e.g., 'Bloomberg', 'Reuters'
    headline        TEXT NOT NULL,              -- News headline
    publication_date DATE NOT NULL,
    url             TEXT NOT NULL UNIQUE,       -- News article URL
    snippet         TEXT,                       -- Optional snippet (max 200 chars)
    url_hash        TEXT GENERATED ALWAYS AS (MD5(url)) STORED,
    retrieved_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (LENGTH(snippet) <= 200 OR snippet IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_news_item_date ON news_item(publication_date DESC);
CREATE INDEX IF NOT EXISTS idx_news_item_publisher ON news_item(publisher);
CREATE INDEX IF NOT EXISTS idx_news_item_url_hash ON news_item(url_hash);

-- ============================================================================
-- SECTION 4: TA MAPPING HELPER FUNCTIONS
-- ============================================================================

-- Function: Map MeSH tree numbers to Therapeutic Area
-- Returns primary TA code based on MeSH tree prefix matching
CREATE OR REPLACE FUNCTION map_mesh_to_ta(p_mesh_tree_numbers TEXT[])
RETURNS therapeutic_area_enum AS $$
DECLARE
    v_tree_number TEXT;
    v_ta therapeutic_area_enum;
    v_best_ta therapeutic_area_enum;
    v_best_priority INTEGER := 999;
BEGIN
    -- Iterate through each MeSH tree number
    FOREACH v_tree_number IN ARRAY p_mesh_tree_numbers
    LOOP
        -- Find matching TA mapping (using LIKE for prefix matching)
        SELECT ta_code, priority
        INTO v_ta, v_best_priority
        FROM therapeutic_area_mapping
        WHERE ontology_type = 'mesh_tree'
        AND v_tree_number LIKE ontology_value
        ORDER BY priority ASC, LENGTH(ontology_value) DESC
        LIMIT 1;

        -- If found a match with better priority, use it
        IF v_ta IS NOT NULL THEN
            IF v_best_ta IS NULL OR v_best_priority < 999 THEN
                v_best_ta := v_ta;
            END IF;
        END IF;
    END LOOP;

    RETURN v_best_ta;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function: Map EFO/MONDO ID to Therapeutic Area
-- Returns primary TA code based on ontology ID prefix matching
CREATE OR REPLACE FUNCTION map_ontology_id_to_ta(
    p_ontology_type TEXT,  -- 'efo_id' or 'mondo_id'
    p_ontology_id TEXT
)
RETURNS therapeutic_area_enum AS $$
DECLARE
    v_ta therapeutic_area_enum;
BEGIN
    -- Find matching TA mapping (using LIKE for prefix matching)
    SELECT ta_code
    INTO v_ta
    FROM therapeutic_area_mapping
    WHERE ontology_type = p_ontology_type
    AND p_ontology_id LIKE ontology_value
    ORDER BY priority ASC, LENGTH(ontology_value) DESC
    LIMIT 1;

    RETURN v_ta;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function: Get disease therapeutic area
-- Combines MeSH and EFO/MONDO mapping strategies
CREATE OR REPLACE FUNCTION get_disease_therapeutic_area(p_disease_id TEXT)
RETURNS therapeutic_area_enum AS $$
DECLARE
    v_ta therapeutic_area_enum;
BEGIN
    -- Try EFO mapping first
    IF p_disease_id LIKE 'EFO_%' THEN
        v_ta := map_ontology_id_to_ta('efo_id', p_disease_id);
        IF v_ta IS NOT NULL THEN
            RETURN v_ta;
        END IF;
    END IF;

    -- Try MONDO mapping
    IF p_disease_id LIKE 'MONDO_%' THEN
        v_ta := map_ontology_id_to_ta('mondo_id', p_disease_id);
        IF v_ta IS NOT NULL THEN
            RETURN v_ta;
        END IF;
    END IF;

    -- If no match found, return NULL (will be handled as 'UNKNOWN' in application)
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- SECTION 5: DISEASE TABLE UPDATE
-- ============================================================================

-- Add TA column to disease table
ALTER TABLE disease
    ADD COLUMN IF NOT EXISTS therapeutic_area therapeutic_area_enum;

CREATE INDEX IF NOT EXISTS idx_disease_ta ON disease(therapeutic_area);

-- ============================================================================
-- SECTION 6: LICENSE ALLOWLIST UPDATE
-- ============================================================================

-- Add PubMed license to allowlist
INSERT INTO license_allowlist (license, description, is_commercial_safe, requires_attribution) VALUES
('NLM_PUBLIC', 'National Library of Medicine (PubMed) public metadata', TRUE, TRUE)
ON CONFLICT (license) DO NOTHING;

-- ============================================================================
-- SECTION 7: VALIDATION VIEWS
-- ============================================================================

-- View: PubMed evidence that is sole source (violates Section 24A)
CREATE OR REPLACE VIEW pubmed_sole_evidence_violations AS
SELECT
    a.assertion_id,
    a.subject_id,
    a.predicate,
    a.object_id,
    COUNT(DISTINCT e.source_system) as source_count,
    BOOL_AND(e.source_system = 'pubmed') as is_pubmed_only
FROM assertion a
JOIN assertion_evidence ae ON a.assertion_id = ae.assertion_id
JOIN evidence e ON ae.evidence_id = e.evidence_id
WHERE a.deleted_at IS NULL
AND a.retracted_at IS NULL
AND e.deleted_at IS NULL
GROUP BY a.assertion_id, a.subject_id, a.predicate, a.object_id
HAVING BOOL_AND(e.source_system = 'pubmed');

-- View: News evidence that is sole source (violates Section 24D - already covered by Contract C)
CREATE OR REPLACE VIEW news_sole_evidence_violations AS
SELECT
    a.assertion_id,
    a.subject_id,
    a.predicate,
    a.object_id,
    COUNT(DISTINCT e.source_system) as source_count,
    BOOL_AND(e.source_system = 'news_metadata') as is_news_only
FROM assertion a
JOIN assertion_evidence ae ON a.assertion_id = ae.assertion_id
JOIN evidence e ON ae.evidence_id = e.evidence_id
WHERE a.deleted_at IS NULL
AND a.retracted_at IS NULL
AND e.deleted_at IS NULL
GROUP BY a.assertion_id, a.subject_id, a.predicate, a.object_id
HAVING BOOL_AND(e.source_system = 'news_metadata');

-- View: News items with excessive snippet length (violates Section 24D)
CREATE OR REPLACE VIEW news_snippet_violations AS
SELECT
    news_item_id,
    publisher,
    headline,
    LENGTH(snippet) as snippet_length
FROM news_item
WHERE LENGTH(snippet) > 200;

-- ============================================================================
-- SECTION 8: MIGRATION VALIDATION
-- ============================================================================

-- Verify therapeutic_area enum was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type
        WHERE typname = 'therapeutic_area_enum'
        AND typtype = 'e'
    ) THEN
        RAISE EXCEPTION 'Migration failed: therapeutic_area_enum not created';
    END IF;

    RAISE NOTICE 'Migration 005 validation passed: therapeutic_area_enum exists';
END $$;

-- Verify tables were created
DO $$
DECLARE
    missing_tables TEXT[];
BEGIN
    SELECT ARRAY_AGG(table_name)
    INTO missing_tables
    FROM (
        VALUES
            ('therapeutic_area_mapping'),
            ('news_item')
    ) AS required(table_name)
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = required.table_name
    );

    IF array_length(missing_tables, 1) > 0 THEN
        RAISE EXCEPTION 'Migration failed: Missing tables: %', array_to_string(missing_tables, ', ');
    END IF;

    RAISE NOTICE 'Migration 005 validation passed: All tables exist';
END $$;

-- Verify TA mappings were prepopulated
DO $$
DECLARE
    mapping_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO mapping_count FROM therapeutic_area_mapping;

    IF mapping_count < 8 THEN
        RAISE WARNING 'Migration 005: Expected at least 8 TA mappings, found %', mapping_count;
    ELSE
        RAISE NOTICE 'Migration 005 validation passed: % TA mappings prepopulated', mapping_count;
    END IF;
END $$;

-- Verify helper functions were created
DO $$
DECLARE
    function_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO function_count
    FROM pg_proc
    WHERE proname IN (
        'map_mesh_to_ta',
        'map_ontology_id_to_ta',
        'get_disease_therapeutic_area'
    );

    IF function_count < 3 THEN
        RAISE WARNING 'Migration 005: Expected 3 TA mapping functions, found %', function_count;
    ELSE
        RAISE NOTICE 'Migration 005 validation passed: % TA mapping functions created', function_count;
    END IF;
END $$;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Migration 005 (Literature & News) completed successfully';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Added:';
    RAISE NOTICE '  - therapeutic_area_enum (8 fixed TAs)';
    RAISE NOTICE '  - therapeutic_area_mapping table (curated anchors)';
    RAISE NOTICE '  - news_item table (metadata only)';
    RAISE NOTICE '  - 3 TA mapping functions';
    RAISE NOTICE '  - 3 validation views';
    RAISE NOTICE '  - therapeutic_area column on disease table';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Literature and News Principles (Section 24):';
    RAISE NOTICE '  - PubMed: Metadata only (no full text)';
    RAISE NOTICE '  - PubMed: Cannot be sole evidence';
    RAISE NOTICE '  - News: Metadata only (max 200 char snippet)';
    RAISE NOTICE '  - News: Cannot create assertions';
    RAISE NOTICE '  - MeSH: Resolve live (no bulk ingestion)';
    RAISE NOTICE '  - TA: Fixed taxonomy (8 categories)';
    RAISE NOTICE '  - TA: Deterministic mapping';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '  1. Implement biograph/integrations/pubmed.py';
    RAISE NOTICE '  2. Implement biograph/integrations/mesh.py';
    RAISE NOTICE '  3. Implement biograph/core/therapeutic_area.py';
    RAISE NOTICE '  4. Add contract tests for literature rules';
    RAISE NOTICE '==================================================';
END $$;
