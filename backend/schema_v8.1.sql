-- BioGraph MVP Schema v8.1 (Best-in-Class Fixes)
-- Investor-grade, evidence-first, assertion-mediated knowledge graph
--
-- Key improvements from v8.0:
-- 1. Issuer identity (stable internal key, CIK can change)
-- 2. Explanation as first-class queryable object
-- 3. DrugProgram issuer-scoped IDs (no cross-issuer dedupe)
-- 4. Assertion-evidence mediation (audit-grade)
-- 5. Open Targets scope lock (whitelist only)
-- 6. Licensing gates (commercial-safe)
-- 7. Deterministic confidence rubric
-- 8. As-of time semantics (effective dating)

-- ============================================================================
-- SECTION 1: Issuer Identity (Fix #1)
-- ============================================================================

-- Issuer: Stable internal key representing an economic entity
-- Decoupled from CIK to handle mergers, spinoffs, ticker changes
CREATE TABLE IF NOT EXISTS issuer (
    issuer_id           TEXT PRIMARY KEY,           -- Internal stable ID (e.g., ISS_00001)
    primary_cik         TEXT NOT NULL,              -- Current primary CIK
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes               TEXT
);

CREATE INDEX idx_issuer_primary_cik ON issuer(primary_cik);

-- Issuer CIK History: Track CIK changes over time (deterministic only)
-- Changes are MANUAL (Phase 0), never automated
CREATE TABLE IF NOT EXISTS issuer_cik_history (
    id                  BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id),
    cik                 TEXT NOT NULL,              -- SEC CIK (10-digit, zero-padded)
    start_date          DATE NOT NULL,
    end_date            DATE,                       -- NULL = current
    source              TEXT NOT NULL,              -- 'manual', 'sec_merger', etc.
    observed_at         TIMESTAMPTZ NOT NULL,
    notes               TEXT,
    UNIQUE(issuer_id, cik, start_date)
);

CREATE INDEX idx_issuer_cik_history_issuer ON issuer_cik_history(issuer_id);
CREATE INDEX idx_issuer_cik_history_cik ON issuer_cik_history(cik);
CREATE INDEX idx_issuer_cik_history_current ON issuer_cik_history(cik) WHERE end_date IS NULL;

-- Universe membership: Use issuer_id instead of CIK
CREATE TABLE IF NOT EXISTS universe_membership (
    id                  BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id),
    universe_id         TEXT NOT NULL,              -- e.g., 'xbi', 'ibb', 'sp500_pharma'
    start_date          DATE NOT NULL,
    end_date            DATE,                       -- NULL = currently in universe
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(issuer_id, universe_id, start_date)
);

CREATE INDEX idx_universe_active ON universe_membership(issuer_id, universe_id)
    WHERE end_date IS NULL;

-- ============================================================================
-- SECTION 2: Entity Tables
-- ============================================================================

-- Company: SEC entity (linked to issuer via CIK history)
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
    accession_number    TEXT PRIMARY KEY,
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    form_type           TEXT NOT NULL,
    filing_date         DATE NOT NULL,
    accepted_at         TIMESTAMPTZ,
    items_8k            TEXT[],
    xbrl_summary        JSONB,
    edgar_url           TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_filing_company ON filing(company_cik);
CREATE INDEX idx_filing_date ON filing(filing_date DESC);
CREATE INDEX idx_filing_type ON filing(form_type);

-- InsiderTransaction: Form 4 data
CREATE TABLE IF NOT EXISTS insider_transaction (
    id                  BIGSERIAL PRIMARY KEY,
    accession_number    TEXT NOT NULL,
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    insider_name        TEXT NOT NULL,
    insider_cik         TEXT,
    transaction_date    DATE NOT NULL,
    transaction_code    TEXT,
    shares              NUMERIC,
    price_per_share     NUMERIC,
    is_derivative       BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_insider_company ON insider_transaction(company_cik);
CREATE INDEX idx_insider_date ON insider_transaction(transaction_date DESC);

-- Exhibit: EDGAR exhibit metadata only
CREATE TABLE IF NOT EXISTS exhibit (
    id                  BIGSERIAL PRIMARY KEY,
    accession_number    TEXT NOT NULL REFERENCES filing(accession_number),
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    exhibit_type        TEXT NOT NULL,
    description         TEXT,
    edgar_url           TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_exhibit_filing ON exhibit(accession_number);
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

-- DrugProgram: Issuer-scoped therapeutic asset (Fix #3)
-- ID scheme: Always issuer-scoped, stores chembl_id as attribute
CREATE TABLE IF NOT EXISTS drug_program (
    drug_program_id     TEXT PRIMARY KEY,           -- Format: "CIK:{cik}:PROG:{slug}"
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id),
    slug                TEXT NOT NULL,              -- Unique within issuer (e.g., "lilly-diabetes-01")
    name                TEXT NOT NULL,
    drug_type           TEXT,                       -- small_molecule, biologic, gene_therapy, etc.
    development_stage   TEXT,                       -- preclinical, phase1, phase2, phase3, approved
    chembl_id           TEXT,                       -- ChEMBL ID if available (attribute, not ID)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(issuer_id, slug)
);

CREATE INDEX idx_drug_issuer ON drug_program(issuer_id);
CREATE INDEX idx_drug_chembl ON drug_program(chembl_id) WHERE chembl_id IS NOT NULL;
CREATE INDEX idx_drug_stage ON drug_program(development_stage);

-- Target: OpenTargets stable ID
CREATE TABLE IF NOT EXISTS target (
    target_id           TEXT PRIMARY KEY,           -- Ensembl gene ID or UniProt (from OpenTargets)
    name                TEXT NOT NULL,
    gene_symbol         TEXT,
    uniprot_id          TEXT,
    target_class        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_target_symbol ON target(gene_symbol) WHERE gene_symbol IS NOT NULL;

-- Disease: OpenTargets stable ontology ID
CREATE TABLE IF NOT EXISTS disease (
    disease_id          TEXT PRIMARY KEY,           -- EFO/MONDO ID (from OpenTargets)
    name                TEXT NOT NULL,
    therapeutic_area    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- SECTION 3: Evidence-First Assertion Mediation (Fix #4)
-- ============================================================================

-- Evidence: First-class provenance records (Fix #6: licensing gates)
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id         BIGSERIAL PRIMARY KEY,
    source_system       TEXT NOT NULL,              -- e.g., 'sec_edgar', 'opentargets', 'chembl'
    source_record_id    TEXT NOT NULL,              -- External ID in source system
    observed_at         TIMESTAMPTZ NOT NULL,       -- When fact was observed in source
    retrieved_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- When we fetched it
    license             TEXT NOT NULL,              -- MUST be in allowlist (gate enforced)
    uri                 TEXT,                       -- Link to source
    checksum            TEXT,                       -- Content hash for verification
    snippet             TEXT,                       -- Optional: excerpt from source
    base_confidence     NUMERIC CHECK (base_confidence >= 0 AND base_confidence <= 1),  -- Source-specific score
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_system, source_record_id)
);

CREATE INDEX idx_evidence_source ON evidence(source_system);
CREATE INDEX idx_evidence_observed ON evidence(observed_at DESC);
CREATE INDEX idx_evidence_license ON evidence(license);

-- License allowlist (Fix #6: commercial-safe)
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
INSERT INTO license_allowlist (license, description, is_commercial_safe, requires_attribution) VALUES
('PUBLIC_DOMAIN', 'U.S. Government / SEC EDGAR', TRUE, FALSE),
('CC0', 'Creative Commons Zero (Public Domain)', TRUE, FALSE),
('CC-BY-4.0', 'Creative Commons Attribution 4.0', TRUE, TRUE),
('CC-BY-SA-3.0', 'Creative Commons Attribution-ShareAlike 3.0 (ChEMBL)', TRUE, TRUE)
ON CONFLICT (license) DO NOTHING;

-- Assertion: Semantic relationship (effective-dated for Fix #8)
CREATE TABLE IF NOT EXISTS assertion (
    assertion_id        BIGSERIAL PRIMARY KEY,
    subject_type        TEXT NOT NULL,              -- 'issuer', 'drug_program', 'target', etc.
    subject_id          TEXT NOT NULL,
    predicate           TEXT NOT NULL,              -- 'develops', 'targets', 'treats', etc.
    object_type         TEXT NOT NULL,
    object_id           TEXT NOT NULL,
    asserted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- When assertion became valid
    retracted_at        TIMESTAMPTZ,                -- NULL = currently valid (Fix #8)
    computed_confidence NUMERIC,                    -- Computed from evidence + rubric (Fix #7)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_assertion_subject ON assertion(subject_type, subject_id);
CREATE INDEX idx_assertion_object ON assertion(object_type, object_id);
CREATE INDEX idx_assertion_predicate ON assertion(predicate);
CREATE INDEX idx_assertion_active ON assertion(subject_id, object_id) WHERE retracted_at IS NULL;

-- Assertion Evidence: Many-to-many link (Fix #4)
-- Rule: An assertion is INVALID unless it has >=1 assertion_evidence
CREATE TABLE IF NOT EXISTS assertion_evidence (
    id                  BIGSERIAL PRIMARY KEY,
    assertion_id        BIGINT NOT NULL REFERENCES assertion(assertion_id),
    evidence_id         BIGINT NOT NULL REFERENCES evidence(evidence_id),
    weight              NUMERIC DEFAULT 1.0,        -- Contribution to confidence
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(assertion_id, evidence_id)
);

CREATE INDEX idx_assertion_evidence_assertion ON assertion_evidence(assertion_id);
CREATE INDEX idx_assertion_evidence_evidence ON assertion_evidence(evidence_id);

-- Confidence scoring configuration (Fix #7)
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
('opentargets', 0.85, 'OpenTargets high-quality for target-disease'),
('chembl', 0.80, 'ChEMBL curated drug-target data'),
('wikidata', 0.70, 'Wikidata crowdsourced but validated'),
('manual', 1.00, 'Manual curation is authoritative')
ON CONFLICT (source_system) DO NOTHING;

-- ============================================================================
-- SECTION 4: Explanation Chain (Fix #2 - First-Class Queryable Object)
-- ============================================================================

-- Explanation: Materialized explanation chain (ONLY query surface for UI)
-- This is the fixed path: Issuer → DrugProgram → Target → Disease
CREATE TABLE IF NOT EXISTS explanation (
    explanation_id      TEXT PRIMARY KEY,           -- Deterministic ID
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id),
    drug_program_id     TEXT NOT NULL REFERENCES drug_program(drug_program_id),
    target_id           TEXT NOT NULL REFERENCES target(target_id),
    disease_id          TEXT NOT NULL REFERENCES disease(disease_id),
    as_of_date          DATE NOT NULL,              -- Snapshot date (Fix #8)
    strength_score      NUMERIC,                    -- Overall chain strength
    -- Assertion IDs for audit trail
    issuer_drug_assertion_id    BIGINT REFERENCES assertion(assertion_id),
    drug_target_assertion_id    BIGINT REFERENCES assertion(assertion_id),
    target_disease_assertion_id BIGINT REFERENCES assertion(assertion_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_explanation_issuer ON explanation(issuer_id);
CREATE INDEX idx_explanation_disease ON explanation(disease_id);
CREATE INDEX idx_explanation_target ON explanation(target_id);
CREATE INDEX idx_explanation_asof ON explanation(as_of_date DESC);
CREATE UNIQUE INDEX idx_explanation_unique ON explanation(issuer_id, drug_program_id, target_id, disease_id, as_of_date);

-- ============================================================================
-- SECTION 5: Helper Views (Graph Edges = Views Over Assertions)
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
-- SECTION 6: Quality Gates & Validation
-- ============================================================================

-- Quality metrics (updated for issuer model)
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
        (SELECT license FROM license_allowlist WHERE is_commercial_safe = TRUE)) AS evidence_with_bad_license;

-- Validation function: Check assertion has evidence
CREATE OR REPLACE FUNCTION validate_assertion_has_evidence() RETURNS TRIGGER AS $$
BEGIN
    -- Check if assertion has at least one evidence record
    IF NOT EXISTS (
        SELECT 1 FROM assertion_evidence WHERE assertion_id = NEW.assertion_id
    ) THEN
        RAISE EXCEPTION 'Assertion % cannot be created without evidence', NEW.assertion_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Validation function: Check license is in allowlist
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

-- Triggers
CREATE TRIGGER check_evidence_license
    BEFORE INSERT OR UPDATE ON evidence
    FOR EACH ROW
    EXECUTE FUNCTION validate_evidence_license();

-- ============================================================================
-- SECTION 7: Confidence Computation (Fix #7)
-- ============================================================================

CREATE OR REPLACE FUNCTION compute_assertion_confidence(p_assertion_id BIGINT)
RETURNS NUMERIC AS $$
DECLARE
    v_base_score NUMERIC;
    v_evidence_count INTEGER;
    v_recency_bonus NUMERIC;
    v_curator_delta NUMERIC := 0;
    v_confidence NUMERIC;
    v_source_system TEXT;
    v_oldest_observed TIMESTAMPTZ;
BEGIN
    -- Get evidence for this assertion
    SELECT COUNT(*), MIN(e.observed_at), e.source_system
    INTO v_evidence_count, v_oldest_observed, v_source_system
    FROM assertion_evidence ae
    JOIN evidence e ON ae.evidence_id = e.evidence_id
    WHERE ae.assertion_id = p_assertion_id
    GROUP BY e.source_system
    LIMIT 1;

    -- Get base score for source system
    SELECT base_score INTO v_base_score
    FROM confidence_rubric
    WHERE source_system = v_source_system;

    IF v_base_score IS NULL THEN
        v_base_score := 0.5;  -- Default
    END IF;

    -- Recency bonus (decay over time)
    v_recency_bonus := 0.05 * EXP(-EXTRACT(EPOCH FROM (NOW() - v_oldest_observed)) / (365.25 * 24 * 3600));

    -- Evidence count bonus (logarithmic)
    v_confidence := v_base_score + 0.1 * LN(1 + v_evidence_count) + v_recency_bonus + v_curator_delta;

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
-- SECTION 8: Audit Trail
-- ============================================================================

CREATE TABLE IF NOT EXISTS ingestion_log (
    id                  BIGSERIAL PRIMARY KEY,
    phase               TEXT NOT NULL,
    source_system       TEXT NOT NULL,
    records_processed   INTEGER,
    records_inserted    INTEGER,
    records_updated     INTEGER,
    records_discarded   INTEGER,
    started_at          TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL,
    error_message       TEXT,
    metadata            JSONB
);

CREATE INDEX idx_ingestion_log_phase ON ingestion_log(phase);
CREATE INDEX idx_ingestion_log_date ON ingestion_log(started_at DESC);
