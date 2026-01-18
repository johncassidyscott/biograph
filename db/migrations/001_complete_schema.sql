-- BioGraph MVP v8.2 - Complete Schema
-- Implements docs/spec/BioGraph_Master_Spec_v8.2_MVP.txt
--
-- CRITICAL CONTRACTS:
-- 1. Evidence-first: No assertions without >=1 evidence
-- 2. License gates: Evidence must have allowlisted license
-- 3. Fixed chains: Issuer → DrugProgram → Target → Disease ONLY
-- 4. Query surface: Explanation table is ONLY product query interface
-- 5. ML suggests, humans decide: No auto-canonical creation
-- 6. News metadata-only: Cannot be sole source of assertions

-- ============================================================================
-- SECTION 1: Issuer Identity (Stable Internal Key)
-- ============================================================================

CREATE TABLE IF NOT EXISTS issuer (
    issuer_id           TEXT PRIMARY KEY,           -- Format: ISS_{CIK} (stable)
    primary_cik         TEXT NOT NULL,              -- Current primary CIK
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes               TEXT
);

CREATE INDEX idx_issuer_primary_cik ON issuer(primary_cik);

-- Issuer CIK History: Track CIK changes (mergers, spinoffs)
-- Changes are MANUAL only (Phase 0)
CREATE TABLE IF NOT EXISTS issuer_cik_history (
    id                  BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    cik                 TEXT NOT NULL,              -- SEC CIK (10-digit, zero-padded)
    start_date          DATE NOT NULL,
    end_date            DATE,                       -- NULL = current
    source              TEXT NOT NULL,              -- 'manual', 'sec_merger', etc.
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes               TEXT,
    UNIQUE(issuer_id, cik, start_date)
);

CREATE INDEX idx_issuer_cik_history_issuer ON issuer_cik_history(issuer_id);
CREATE INDEX idx_issuer_cik_history_cik ON issuer_cik_history(cik);
CREATE INDEX idx_issuer_cik_history_current ON issuer_cik_history(cik) WHERE end_date IS NULL;

-- Universe Membership: Index-anchored scope
CREATE TABLE IF NOT EXISTS universe_membership (
    id                  BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    universe_id         TEXT NOT NULL,              -- e.g., 'xbi', 'ibb'
    start_date          DATE NOT NULL,
    end_date            DATE,                       -- NULL = currently in universe
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(issuer_id, universe_id, start_date),
    CHECK (end_date IS NULL OR end_date > start_date)
);

CREATE INDEX idx_universe_active ON universe_membership(issuer_id, universe_id)
    WHERE end_date IS NULL;
CREATE INDEX idx_universe_id ON universe_membership(universe_id);

-- ============================================================================
-- SECTION 2: Corporate Data (SEC EDGAR)
-- ============================================================================

-- Company: SEC entity metadata (linked to issuer via CIK)
CREATE TABLE IF NOT EXISTS company (
    cik                 TEXT PRIMARY KEY,           -- SEC CIK (10 digits, zero-padded)
    sec_legal_name      TEXT NOT NULL,
    ticker              TEXT,
    exchange            TEXT,
    wikidata_qid        TEXT,
    revenue_usd         BIGINT,
    employees           INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_company_ticker ON company(ticker) WHERE ticker IS NOT NULL;
CREATE INDEX idx_company_wikidata ON company(wikidata_qid) WHERE wikidata_qid IS NOT NULL;

-- Filing: SEC EDGAR filings metadata
CREATE TABLE IF NOT EXISTS filing (
    filing_id           BIGSERIAL PRIMARY KEY,
    accession_number    TEXT UNIQUE NOT NULL,       -- EDGAR accession (e.g., 0001193125-24-123456)
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    form_type           TEXT NOT NULL,              -- 10-K, 10-Q, 8-K, etc.
    filing_date         DATE NOT NULL,
    accepted_at         TIMESTAMPTZ,
    items_8k            TEXT[],                     -- For 8-K: item codes
    xbrl_summary        JSONB,                      -- Select XBRL concepts
    edgar_url           TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_filing_company ON filing(company_cik);
CREATE INDEX idx_filing_date ON filing(filing_date DESC);
CREATE INDEX idx_filing_type ON filing(form_type);
CREATE INDEX idx_filing_accession ON filing(accession_number);

-- InsiderTransaction: Form 4 data
CREATE TABLE IF NOT EXISTS insider_transaction (
    id                  BIGSERIAL PRIMARY KEY,
    accession_number    TEXT NOT NULL,
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    insider_name        TEXT NOT NULL,
    insider_cik         TEXT,
    transaction_date    DATE NOT NULL,
    transaction_code    TEXT,                       -- P, S, A, etc.
    shares              NUMERIC,
    price_per_share     NUMERIC,
    is_derivative       BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_insider_company ON insider_transaction(company_cik);
CREATE INDEX idx_insider_date ON insider_transaction(transaction_date DESC);

-- Exhibit: EDGAR exhibit metadata + artifacts (Section 19)
-- Artifacts are first-class evidence inputs
CREATE TABLE IF NOT EXISTS exhibit (
    exhibit_id          BIGSERIAL PRIMARY KEY,
    filing_id           BIGINT NOT NULL REFERENCES filing(filing_id) ON DELETE CASCADE,
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    exhibit_type        TEXT NOT NULL,              -- EX-10, EX-21, EX-99, etc.
    description         TEXT,
    edgar_url           TEXT NOT NULL,
    text_available      BOOLEAN DEFAULT FALSE,      -- Is text publicly accessible?
    text_snippet        TEXT,                       -- Short excerpt for NER (if allowed)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_exhibit_filing ON exhibit(filing_id);
CREATE INDEX idx_exhibit_company ON exhibit(company_cik);
CREATE INDEX idx_exhibit_type ON exhibit(exhibit_type);

-- Location: GeoNames canonical
CREATE TABLE IF NOT EXISTS location (
    geonames_id         TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    country_code        TEXT,
    latitude            NUMERIC,
    longitude           NUMERIC,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- SECTION 3: Biomedical Entities
-- ============================================================================

-- DrugProgram: Issuer-scoped therapeutic asset (Section 7)
-- ID scheme: CIK:{cik}:PROG:{slug}
CREATE TABLE IF NOT EXISTS drug_program (
    drug_program_id     TEXT PRIMARY KEY,           -- Format: "CIK:0000059478:PROG:tirzepatide"
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    slug                TEXT NOT NULL,              -- Unique within issuer
    name                TEXT NOT NULL,
    drug_type           TEXT,                       -- small_molecule, biologic, gene_therapy
    development_stage   TEXT,                       -- preclinical, phase1, phase2, phase3, approved
    chembl_id           TEXT,                       -- ChEMBL ID if available (attribute, not ID)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(issuer_id, slug)
);

CREATE INDEX idx_drug_issuer ON drug_program(issuer_id);
CREATE INDEX idx_drug_chembl ON drug_program(chembl_id) WHERE chembl_id IS NOT NULL;
CREATE INDEX idx_drug_stage ON drug_program(development_stage);

-- DrugProgram Alias: For within-issuer duplicate resolution (ER output)
-- No merges, only aliases
CREATE TABLE IF NOT EXISTS drug_program_alias (
    id                  BIGSERIAL PRIMARY KEY,
    drug_program_id     TEXT NOT NULL REFERENCES drug_program(drug_program_id) ON DELETE CASCADE,
    alias_name          TEXT NOT NULL,
    source              TEXT NOT NULL,              -- 'er_dedupe', 'manual'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by          TEXT,
    UNIQUE(drug_program_id, alias_name)
);

CREATE INDEX idx_drug_alias_program ON drug_program_alias(drug_program_id);

-- Target: OpenTargets stable ID
CREATE TABLE IF NOT EXISTS target (
    target_id           TEXT PRIMARY KEY,           -- Ensembl gene ID or UniProt
    name                TEXT NOT NULL,
    gene_symbol         TEXT,
    uniprot_id          TEXT,
    target_class        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_target_symbol ON target(gene_symbol) WHERE gene_symbol IS NOT NULL;

-- Disease: OpenTargets stable ontology ID
CREATE TABLE IF NOT EXISTS disease (
    disease_id          TEXT PRIMARY KEY,           -- EFO/MONDO ID
    name                TEXT NOT NULL,
    therapeutic_area    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- SECTION 4: Evidence-First Assertion Model
-- ============================================================================

-- License Allowlist (Section 14)
CREATE TABLE IF NOT EXISTS license_allowlist (
    license             TEXT PRIMARY KEY,
    description         TEXT NOT NULL,
    is_commercial_safe  BOOLEAN NOT NULL,
    requires_attribution BOOLEAN DEFAULT FALSE,
    attribution_text    TEXT,
    url                 TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Prepopulate with MVP-safe licenses
INSERT INTO license_allowlist (license, description, is_commercial_safe, requires_attribution, attribution_text) VALUES
('PUBLIC_DOMAIN', 'U.S. Government / SEC EDGAR', TRUE, FALSE, NULL),
('CC0', 'Creative Commons Zero (Public Domain)', TRUE, FALSE, NULL),
('CC-BY-4.0', 'Creative Commons Attribution 4.0', TRUE, TRUE, 'Data from [source] used under CC BY 4.0 license.'),
('CC-BY-SA-3.0', 'Creative Commons Attribution-ShareAlike 3.0 (ChEMBL)', TRUE, TRUE, 'Data from ChEMBL used under CC BY-SA 3.0 license. ChEMBL: https://www.ebi.ac.uk/chembl/')
ON CONFLICT (license) DO NOTHING;

-- Evidence: First-class provenance records (Section 8)
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id         BIGSERIAL PRIMARY KEY,
    source_system       TEXT NOT NULL,              -- 'sec_edgar', 'sec_edgar_exhibit', 'news_metadata', 'opentargets', 'chembl'
    source_record_id    TEXT NOT NULL,              -- External ID in source system
    observed_at         TIMESTAMPTZ NOT NULL,       -- When fact was observed in source
    retrieved_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- When we fetched it
    license             TEXT NOT NULL REFERENCES license_allowlist(license),  -- ENFORCED
    uri                 TEXT,                       -- Link to source
    checksum            TEXT,                       -- Content hash for verification
    snippet             TEXT,                       -- Optional: excerpt from source
    base_confidence     NUMERIC CHECK (base_confidence >= 0 AND base_confidence <= 1),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_system, source_record_id)
);

CREATE INDEX idx_evidence_source ON evidence(source_system);
CREATE INDEX idx_evidence_observed ON evidence(observed_at DESC);
CREATE INDEX idx_evidence_license ON evidence(license);

-- Confidence Rubric (Section 13)
CREATE TABLE IF NOT EXISTS confidence_rubric (
    source_system       TEXT PRIMARY KEY,
    base_score          NUMERIC NOT NULL CHECK (base_score >= 0 AND base_score <= 1),
    recency_weight      NUMERIC DEFAULT 0.05,
    evidence_count_weight NUMERIC DEFAULT 0.1,
    notes               TEXT
);

-- Prepopulate with MVP rubric
INSERT INTO confidence_rubric (source_system, base_score, notes) VALUES
('sec_edgar', 0.95, 'SEC filings are authoritative for corporate facts'),
('sec_edgar_exhibit', 0.90, 'EDGAR exhibits are high-quality artifacts'),
('opentargets', 0.85, 'OpenTargets high-quality for target-disease'),
('chembl', 0.80, 'ChEMBL curated drug-target data'),
('wikidata', 0.70, 'Wikidata crowdsourced but validated'),
('news_metadata', 0.50, 'News is context only, cannot create assertions'),
('manual', 1.00, 'Manual curation is authoritative')
ON CONFLICT (source_system) DO NOTHING;

-- Assertion: Semantic relationship (Section 8, effective-dated per Section 12)
CREATE TABLE IF NOT EXISTS assertion (
    assertion_id        BIGSERIAL PRIMARY KEY,
    subject_type        TEXT NOT NULL,              -- 'issuer', 'drug_program', 'target'
    subject_id          TEXT NOT NULL,
    predicate           TEXT NOT NULL,              -- 'has_program', 'targets', 'treats', 'located_at'
    object_type         TEXT NOT NULL,              -- 'drug_program', 'target', 'disease', 'location'
    object_id           TEXT NOT NULL,
    asserted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- When assertion became valid
    retracted_at        TIMESTAMPTZ,                -- NULL = currently valid
    computed_confidence NUMERIC,                    -- Auto-computed from evidence
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_assertion_subject ON assertion(subject_type, subject_id);
CREATE INDEX idx_assertion_object ON assertion(object_type, object_id);
CREATE INDEX idx_assertion_predicate ON assertion(predicate);
CREATE INDEX idx_assertion_active ON assertion(subject_id, object_id) WHERE retracted_at IS NULL;

-- Assertion Evidence: Many-to-many link (Section 8)
-- CRITICAL CONTRACT: Assertion requires >=1 assertion_evidence
CREATE TABLE IF NOT EXISTS assertion_evidence (
    id                  BIGSERIAL PRIMARY KEY,
    assertion_id        BIGINT NOT NULL REFERENCES assertion(assertion_id) ON DELETE CASCADE,
    evidence_id         BIGINT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    weight              NUMERIC DEFAULT 1.0,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(assertion_id, evidence_id)
);

CREATE INDEX idx_assertion_evidence_assertion ON assertion_evidence(assertion_id);
CREATE INDEX idx_assertion_evidence_evidence ON assertion_evidence(evidence_id);

-- ============================================================================
-- SECTION 5: Query Surface (Explanation is ONLY product interface)
-- ============================================================================

-- Explanation: Materialized explanation chain (Section 4)
-- Fixed chain: Issuer → DrugProgram → Target → Disease
-- This is the ONLY query surface for product/UI
CREATE TABLE IF NOT EXISTS explanation (
    explanation_id      TEXT PRIMARY KEY,           -- Deterministic ID
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    drug_program_id     TEXT NOT NULL REFERENCES drug_program(drug_program_id) ON DELETE CASCADE,
    target_id           TEXT NOT NULL REFERENCES target(target_id) ON DELETE CASCADE,
    disease_id          TEXT NOT NULL REFERENCES disease(disease_id) ON DELETE CASCADE,
    as_of_date          DATE NOT NULL,              -- Snapshot date (Section 12)
    strength_score      NUMERIC,                    -- Overall chain strength
    -- Assertion IDs for audit trail
    issuer_drug_assertion_id    BIGINT REFERENCES assertion(assertion_id),
    drug_target_assertion_id    BIGINT REFERENCES assertion(assertion_id),
    target_disease_assertion_id BIGINT REFERENCES assertion(assertion_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(issuer_id, drug_program_id, target_id, disease_id, as_of_date)
);

CREATE INDEX idx_explanation_issuer ON explanation(issuer_id);
CREATE INDEX idx_explanation_disease ON explanation(disease_id);
CREATE INDEX idx_explanation_target ON explanation(target_id);
CREATE INDEX idx_explanation_asof ON explanation(as_of_date DESC);
CREATE INDEX idx_explanation_strength ON explanation(strength_score DESC);

-- ============================================================================
-- SECTION 6: NER/ER Infrastructure (Section 15)
-- ============================================================================

-- NLP Run: Track NER execution
CREATE TABLE IF NOT EXISTS nlp_run (
    run_id              BIGSERIAL PRIMARY KEY,
    source_type         TEXT NOT NULL,              -- 'filing', 'exhibit', 'news_headline'
    source_id           BIGINT NOT NULL,            -- filing_id, exhibit_id, news_item_id
    model_name          TEXT NOT NULL,              -- e.g., 'en_core_sci_md'
    model_version       TEXT NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running',  -- 'running', 'completed', 'failed'
    error_message       TEXT,
    mentions_extracted  INTEGER DEFAULT 0
);

CREATE INDEX idx_nlp_run_source ON nlp_run(source_type, source_id);
CREATE INDEX idx_nlp_run_status ON nlp_run(status);

-- Mention: NER-extracted spans
CREATE TABLE IF NOT EXISTS mention (
    mention_id          BIGSERIAL PRIMARY KEY,
    run_id              BIGINT NOT NULL REFERENCES nlp_run(run_id) ON DELETE CASCADE,
    entity_type         TEXT NOT NULL,              -- 'drug', 'target', 'disease'
    text                TEXT NOT NULL,
    start_char          INTEGER,
    end_char            INTEGER,
    context             TEXT,                       -- Surrounding text
    confidence          NUMERIC,                    -- NER confidence
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mention_run ON mention(run_id);
CREATE INDEX idx_mention_type ON mention(entity_type);
CREATE INDEX idx_mention_text ON mention(text);

-- Candidate: Normalized entity suggestion (queued for curation)
-- ML suggests ONLY, humans decide (Section 15)
CREATE TABLE IF NOT EXISTS candidate (
    candidate_id        BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    entity_type         TEXT NOT NULL,              -- 'drug_program', 'target', 'disease'
    normalized_name     TEXT NOT NULL,
    source_type         TEXT NOT NULL,              -- 'filing', 'exhibit', 'news_headline'
    source_id           BIGINT NOT NULL,
    mention_ids         BIGINT[],                   -- Array of mention_id
    external_id         TEXT,                       -- If resolved (target_id, disease_id)
    external_id_source  TEXT,                       -- 'opentargets_dict', 'chembl_dict'
    features_json       JSONB,                      -- Additional features for curation
    status              TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'accepted', 'rejected'
    decided_by          TEXT,
    decided_at          TIMESTAMPTZ,
    decision_notes      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_candidate_issuer ON candidate(issuer_id);
CREATE INDEX idx_candidate_type ON candidate(entity_type);
CREATE INDEX idx_candidate_status ON candidate(status);
CREATE INDEX idx_candidate_source ON candidate(source_type, source_id);

-- Duplicate Suggestion: ER-detected potential duplicates
-- Within-issuer ONLY (Section 15)
CREATE TABLE IF NOT EXISTS duplicate_suggestion (
    suggestion_id       BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id) ON DELETE CASCADE,
    entity_type         TEXT NOT NULL DEFAULT 'drug_program',
    entity_id_1         TEXT NOT NULL,              -- drug_program_id
    entity_id_2         TEXT NOT NULL,              -- drug_program_id
    similarity_score    NUMERIC NOT NULL CHECK (similarity_score >= 0 AND similarity_score <= 1),
    features_json       JSONB,                      -- Dedupe features
    status              TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'accepted_as_alias', 'rejected'
    decided_by          TEXT,
    decided_at          TIMESTAMPTZ,
    decision_notes      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (entity_id_1 < entity_id_2),              -- Enforce ordering to prevent duplicates
    UNIQUE(issuer_id, entity_id_1, entity_id_2)
);

CREATE INDEX idx_duplicate_issuer ON duplicate_suggestion(issuer_id);
CREATE INDEX idx_duplicate_status ON duplicate_suggestion(status);
CREATE INDEX idx_duplicate_score ON duplicate_suggestion(similarity_score DESC);

-- ============================================================================
-- SECTION 7: News Metadata (Section 20 - Metadata-Only)
-- ============================================================================

-- News Item: Metadata-only (NOT full article text)
-- News cannot be sole source of assertions (Section 21)
CREATE TABLE IF NOT EXISTS news_item (
    news_item_id        BIGSERIAL PRIMARY KEY,
    publisher           TEXT NOT NULL,
    headline            TEXT NOT NULL,
    url                 TEXT NOT NULL UNIQUE,
    published_at        TIMESTAMPTZ NOT NULL,
    license             TEXT REFERENCES license_allowlist(license),  -- Must be known
    snippet             TEXT,                       -- Short excerpt (ONLY if license permits)
    related_issuer_ids  TEXT[],                     -- Display correlation only (NOT identity)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_news_published ON news_item(published_at DESC);
CREATE INDEX idx_news_publisher ON news_item(publisher);

-- ============================================================================
-- SECTION 8: Ingestion Audit Trail
-- ============================================================================

CREATE TABLE IF NOT EXISTS ingestion_log (
    log_id              BIGSERIAL PRIMARY KEY,
    phase               TEXT NOT NULL,              -- 'phase_0', 'phase_1', etc.
    source_system       TEXT NOT NULL,
    records_processed   INTEGER,
    records_inserted    INTEGER,
    records_updated     INTEGER,
    records_discarded   INTEGER,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running',
    error_message       TEXT,
    metadata            JSONB
);

CREATE INDEX idx_ingestion_phase ON ingestion_log(phase);
CREATE INDEX idx_ingestion_date ON ingestion_log(started_at DESC);

-- ============================================================================
-- SECTION 9: Functions for Confidence Computation (Section 13)
-- ============================================================================

-- Compute assertion confidence using deterministic rubric
CREATE OR REPLACE FUNCTION compute_assertion_confidence(p_assertion_id BIGINT)
RETURNS NUMERIC AS $$
DECLARE
    v_base_score NUMERIC;
    v_evidence_count INTEGER;
    v_recency_bonus NUMERIC;
    v_confidence NUMERIC;
    v_source_system TEXT;
    v_oldest_observed TIMESTAMPTZ;
BEGIN
    -- Get evidence for this assertion
    SELECT COUNT(*), MIN(e.observed_at)
    INTO v_evidence_count, v_oldest_observed
    FROM assertion_evidence ae
    JOIN evidence e ON ae.evidence_id = e.evidence_id
    WHERE ae.assertion_id = p_assertion_id;

    -- Get primary source system (use highest base score)
    SELECT e.source_system INTO v_source_system
    FROM assertion_evidence ae
    JOIN evidence e ON ae.evidence_id = e.evidence_id
    JOIN confidence_rubric cr ON e.source_system = cr.source_system
    WHERE ae.assertion_id = p_assertion_id
    ORDER BY cr.base_score DESC
    LIMIT 1;

    -- Get base score for source system
    SELECT base_score INTO v_base_score
    FROM confidence_rubric
    WHERE source_system = v_source_system;

    IF v_base_score IS NULL THEN
        v_base_score := 0.5;  -- Default
    END IF;

    -- Recency bonus (decay over time)
    IF v_oldest_observed IS NOT NULL THEN
        v_recency_bonus := 0.05 * EXP(-EXTRACT(EPOCH FROM (NOW() - v_oldest_observed)) / (365.25 * 24 * 3600));
    ELSE
        v_recency_bonus := 0;
    END IF;

    -- Evidence count bonus (logarithmic)
    v_confidence := v_base_score + 0.1 * LN(1 + v_evidence_count) + v_recency_bonus;

    -- Clamp to [0, 1]
    v_confidence := GREATEST(0, LEAST(1, v_confidence));

    RETURN v_confidence;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-compute confidence when evidence is added
CREATE OR REPLACE FUNCTION update_assertion_confidence() RETURNS TRIGGER AS $$
BEGIN
    UPDATE assertion
    SET computed_confidence = compute_assertion_confidence(NEW.assertion_id),
        updated_at = NOW()
    WHERE assertion_id = NEW.assertion_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER recompute_confidence_on_evidence
    AFTER INSERT ON assertion_evidence
    FOR EACH ROW
    EXECUTE FUNCTION update_assertion_confidence();

-- ============================================================================
-- SECTION 10: Validation Functions (Contract Enforcement)
-- ============================================================================

-- Validate that evidence license is in allowlist
CREATE OR REPLACE FUNCTION validate_evidence_license() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM license_allowlist
        WHERE license = NEW.license AND is_commercial_safe = TRUE
    ) THEN
        RAISE EXCEPTION 'Evidence license "%" is not in commercial-safe allowlist', NEW.license;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER check_evidence_license
    BEFORE INSERT OR UPDATE ON evidence
    FOR EACH ROW
    EXECUTE FUNCTION validate_evidence_license();

-- ============================================================================
-- SECTION 11: Helper Views (Graph Edges = Views Over Assertions)
-- ============================================================================

-- Issuer → DrugProgram (view over assertions)
CREATE OR REPLACE VIEW issuer_drug AS
SELECT
    a.assertion_id,
    a.subject_id AS issuer_id,
    a.object_id AS drug_program_id,
    a.predicate AS relationship,
    a.computed_confidence AS confidence,
    a.asserted_at,
    a.retracted_at
FROM assertion a
WHERE a.subject_type = 'issuer'
  AND a.object_type = 'drug_program'
  AND a.retracted_at IS NULL;

-- DrugProgram → Target
CREATE OR REPLACE VIEW drug_target AS
SELECT
    a.assertion_id,
    a.subject_id AS drug_program_id,
    a.object_id AS target_id,
    a.predicate AS interaction_type,
    a.computed_confidence AS confidence,
    a.asserted_at,
    a.retracted_at
FROM assertion a
WHERE a.subject_type = 'drug_program'
  AND a.object_type = 'target'
  AND a.retracted_at IS NULL;

-- Target → Disease
CREATE OR REPLACE VIEW target_disease AS
SELECT
    a.assertion_id,
    a.subject_id AS target_id,
    a.object_id AS disease_id,
    a.computed_confidence AS association_score,
    a.asserted_at,
    a.retracted_at
FROM assertion a
WHERE a.subject_type = 'target'
  AND a.object_type = 'disease'
  AND a.retracted_at IS NULL;

-- Issuer → Location
CREATE OR REPLACE VIEW issuer_location AS
SELECT
    a.assertion_id,
    a.subject_id AS issuer_id,
    a.object_id AS location_id,
    a.predicate AS location_type,
    a.computed_confidence AS confidence,
    a.asserted_at,
    a.retracted_at
FROM assertion a
WHERE a.subject_type = 'issuer'
  AND a.object_type = 'location'
  AND a.retracted_at IS NULL;

-- ============================================================================
-- SECTION 12: Quality Metrics View
-- ============================================================================

CREATE OR REPLACE VIEW quality_metrics AS
SELECT
    (SELECT COUNT(*) FROM issuer WHERE issuer_id IN
        (SELECT issuer_id FROM universe_membership WHERE end_date IS NULL)) AS issuers_in_universe,
    (SELECT COUNT(DISTINCT issuer_id) FROM issuer_drug) AS issuers_with_drugs,
    (SELECT COUNT(*) FROM drug_program) AS total_drugs,
    (SELECT COUNT(DISTINCT drug_program_id) FROM drug_target) AS drugs_with_targets,
    (SELECT COUNT(*) FROM explanation WHERE as_of_date = CURRENT_DATE) AS current_explanations,
    (SELECT COUNT(*) FROM evidence) AS total_evidence_records,
    (SELECT COUNT(*) FROM assertion WHERE assertion_id NOT IN
        (SELECT DISTINCT assertion_id FROM assertion_evidence)) AS assertions_without_evidence,
    (SELECT COUNT(*) FROM evidence WHERE license NOT IN
        (SELECT license FROM license_allowlist WHERE is_commercial_safe = TRUE)) AS evidence_with_bad_license,
    (SELECT COUNT(*) FROM candidate WHERE status = 'pending') AS pending_candidates,
    (SELECT COUNT(*) FROM duplicate_suggestion WHERE status = 'pending') AS pending_duplicate_suggestions;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
