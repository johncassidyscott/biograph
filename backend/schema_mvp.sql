-- BioGraph MVP Schema v8.0
-- Investor-grade, evidence-first, index-anchored knowledge graph
-- Spec: Fixed explanation chains (Company → DrugProgram → Target → Disease)

-- ============================================================================
-- CORE PRINCIPLE: Evidence-first
-- Every relationship MUST store: source_system, source_record_id,
-- observed_at, confidence, license
-- ============================================================================

-- ============================================================================
-- SECTION 1: Universe Definition (Index-anchored scope gating)
-- ============================================================================

-- Universe membership: Which companies are in scope
-- One row = one economic issuer at a point in time
CREATE TABLE IF NOT EXISTS universe_membership (
    id              BIGSERIAL PRIMARY KEY,
    company_cik     TEXT NOT NULL,              -- SEC CIK (canonical company ID)
    universe_id     TEXT NOT NULL,              -- e.g., 'xbi', 'ibb', 'sp500_pharma'
    start_date      DATE NOT NULL,
    end_date        DATE,                       -- NULL = currently in universe
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_cik, universe_id, start_date)
);

CREATE INDEX idx_universe_active ON universe_membership(company_cik, universe_id)
    WHERE end_date IS NULL;

-- ============================================================================
-- SECTION 2: Entity Tables (9 total — hard capped per spec)
-- ============================================================================

-- 2.1 Company (canonical ID: SEC CIK)
CREATE TABLE IF NOT EXISTS company (
    cik                 TEXT PRIMARY KEY,       -- SEC CIK (10 digits, zero-padded)
    sec_legal_name      TEXT NOT NULL,
    ticker              TEXT,
    exchange            TEXT,
    wikidata_qid        TEXT,                   -- For enrichment joins
    revenue_usd         BIGINT,                 -- From Wikidata/XBRL
    employees           INTEGER,                -- From Wikidata/XBRL
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_company_ticker ON company(ticker) WHERE ticker IS NOT NULL;
CREATE INDEX idx_company_wikidata ON company(wikidata_qid) WHERE wikidata_qid IS NOT NULL;

-- 2.2 Filing (SEC EDGAR filings metadata)
CREATE TABLE IF NOT EXISTS filing (
    accession_number    TEXT PRIMARY KEY,       -- EDGAR accession (e.g., 0001193125-24-123456)
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    form_type           TEXT NOT NULL,          -- 10-K, 10-Q, 8-K, etc.
    filing_date         DATE NOT NULL,
    accepted_at         TIMESTAMPTZ,
    items_8k            TEXT[],                 -- For 8-K: item codes (e.g., ['1.01', '9.01'])
    xbrl_summary        JSONB,                  -- Select XBRL concepts (≤30)
    edgar_url           TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_filing_company ON filing(company_cik);
CREATE INDEX idx_filing_date ON filing(filing_date DESC);
CREATE INDEX idx_filing_type ON filing(form_type);

-- 2.3 InsiderTransaction (Form 4 data)
CREATE TABLE IF NOT EXISTS insider_transaction (
    id                  BIGSERIAL PRIMARY KEY,
    accession_number    TEXT NOT NULL,          -- Form 4 accession
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    insider_name        TEXT NOT NULL,
    insider_cik         TEXT,
    transaction_date    DATE NOT NULL,
    transaction_code    TEXT,                   -- P, S, A, etc.
    shares              NUMERIC,
    price_per_share     NUMERIC,
    is_derivative       BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_insider_company ON insider_transaction(company_cik);
CREATE INDEX idx_insider_date ON insider_transaction(transaction_date DESC);

-- 2.4 Exhibit (EDGAR exhibit metadata only — no full text)
CREATE TABLE IF NOT EXISTS exhibit (
    id                  BIGSERIAL PRIMARY KEY,
    accession_number    TEXT NOT NULL REFERENCES filing(accession_number),
    company_cik         TEXT NOT NULL REFERENCES company(cik),
    exhibit_type        TEXT NOT NULL,          -- EX-10, EX-21, EX-99, etc.
    description         TEXT,
    edgar_url           TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_exhibit_filing ON exhibit(accession_number);
CREATE INDEX idx_exhibit_type ON exhibit(exhibit_type);

-- 2.5 Location (canonical ID: GeoNames ID)
CREATE TABLE IF NOT EXISTS location (
    geonames_id         TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    country_code        TEXT,
    latitude            NUMERIC,
    longitude           NUMERIC,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.6 DrugProgram (canonical ID: ChEMBL ID or internal candidate ID)
CREATE TABLE IF NOT EXISTS drug_program (
    id                  TEXT PRIMARY KEY,       -- ChEMBL ID (e.g., CHEMBL123) or internal (e.g., CAND_XXX_001)
    name                TEXT NOT NULL,
    drug_type           TEXT,                   -- small_molecule, biologic, gene_therapy, etc.
    development_stage   TEXT,                   -- preclinical, phase1, phase2, phase3, approved
    chembl_id           TEXT,                   -- If ChEMBL molecule
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_drug_chembl ON drug_program(chembl_id) WHERE chembl_id IS NOT NULL;
CREATE INDEX idx_drug_stage ON drug_program(development_stage);

-- 2.7 Target (canonical ID: stable external ID via Open Targets)
CREATE TABLE IF NOT EXISTS target (
    id                  TEXT PRIMARY KEY,       -- Ensembl gene ID or UniProt (from OpenTargets)
    name                TEXT NOT NULL,
    gene_symbol         TEXT,
    uniprot_id          TEXT,
    target_class        TEXT,                   -- e.g., enzyme, receptor, transporter
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_target_symbol ON target(gene_symbol) WHERE gene_symbol IS NOT NULL;

-- 2.8 Disease (canonical ID: stable ontology ID via Open Targets)
CREATE TABLE IF NOT EXISTS disease (
    id                  TEXT PRIMARY KEY,       -- EFO/MONDO ID (from OpenTargets)
    name                TEXT NOT NULL,
    therapeutic_area    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.9 Evidence (first-class entity, not just attributes)
CREATE TABLE IF NOT EXISTS evidence (
    id                  BIGSERIAL PRIMARY KEY,
    source_system       TEXT NOT NULL,          -- e.g., 'opentargets', 'chembl', 'sec_edgar', 'manual'
    source_record_id    TEXT NOT NULL,          -- External ID in source system
    evidence_type       TEXT NOT NULL,          -- e.g., 'genetic_association', 'clinical_trial', 'filing_mention'
    confidence          NUMERIC CHECK (confidence >= 0 AND confidence <= 1),
    license             TEXT NOT NULL,          -- e.g., 'CC0', 'CC BY-SA 3.0'
    url                 TEXT,                   -- Link to source
    observed_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_system, source_record_id)
);

CREATE INDEX idx_evidence_source ON evidence(source_system);
CREATE INDEX idx_evidence_date ON evidence(observed_at DESC);

-- ============================================================================
-- SECTION 3: Relationship Tables (Evidence-first model)
-- ============================================================================

-- All relationship tables MUST reference evidence
-- This is the core contract: no edge without provenance

-- 3.1 Company → Location
CREATE TABLE IF NOT EXISTS company_location (
    id              BIGSERIAL PRIMARY KEY,
    company_cik     TEXT NOT NULL REFERENCES company(cik),
    location_id     TEXT NOT NULL REFERENCES location(geonames_id),
    location_type   TEXT NOT NULL,              -- 'hq_operational' or 'legal_process'
    evidence_id     BIGINT NOT NULL REFERENCES evidence(id),
    valid_from      DATE NOT NULL,
    valid_to        DATE,
    UNIQUE(company_cik, location_id, location_type, valid_from)
);

CREATE INDEX idx_company_location_company ON company_location(company_cik);

-- 3.2 Company → DrugProgram (develops/owns)
CREATE TABLE IF NOT EXISTS company_drug (
    id              BIGSERIAL PRIMARY KEY,
    company_cik     TEXT NOT NULL REFERENCES company(cik),
    drug_id         TEXT NOT NULL REFERENCES drug_program(id),
    relationship    TEXT NOT NULL,              -- 'develops', 'licensed_in', 'acquired', 'partnered'
    evidence_id     BIGINT NOT NULL REFERENCES evidence(id),
    valid_from      DATE NOT NULL,
    valid_to        DATE,
    UNIQUE(company_cik, drug_id, relationship, valid_from)
);

CREATE INDEX idx_company_drug_company ON company_drug(company_cik);
CREATE INDEX idx_company_drug_drug ON company_drug(drug_id);

-- 3.3 DrugProgram → Target
CREATE TABLE IF NOT EXISTS drug_target (
    id              BIGSERIAL PRIMARY KEY,
    drug_id         TEXT NOT NULL REFERENCES drug_program(id),
    target_id       TEXT NOT NULL REFERENCES target(id),
    interaction_type TEXT,                      -- 'inhibitor', 'agonist', 'antagonist', etc.
    evidence_id     BIGINT NOT NULL REFERENCES evidence(id),
    UNIQUE(drug_id, target_id, evidence_id)
);

CREATE INDEX idx_drug_target_drug ON drug_target(drug_id);
CREATE INDEX idx_drug_target_target ON drug_target(target_id);

-- 3.4 Target → Disease (from OpenTargets)
CREATE TABLE IF NOT EXISTS target_disease (
    id                  BIGSERIAL PRIMARY KEY,
    target_id           TEXT NOT NULL REFERENCES target(id),
    disease_id          TEXT NOT NULL REFERENCES disease(id),
    association_score   NUMERIC,                -- OpenTargets overall score
    evidence_id         BIGINT NOT NULL REFERENCES evidence(id),
    UNIQUE(target_id, disease_id, evidence_id)
);

CREATE INDEX idx_target_disease_target ON target_disease(target_id);
CREATE INDEX idx_target_disease_disease ON target_disease(disease_id);

-- 3.5 DrugProgram → Disease (direct indications)
CREATE TABLE IF NOT EXISTS drug_disease (
    id              BIGSERIAL PRIMARY KEY,
    drug_id         TEXT NOT NULL REFERENCES drug_program(id),
    disease_id      TEXT NOT NULL REFERENCES disease(id),
    indication_type TEXT,                       -- 'approved', 'phase3', 'phase2', etc.
    evidence_id     BIGINT NOT NULL REFERENCES evidence(id),
    UNIQUE(drug_id, disease_id, evidence_id)
);

CREATE INDEX idx_drug_disease_drug ON drug_disease(drug_id);
CREATE INDEX idx_drug_disease_disease ON drug_disease(disease_id);

-- ============================================================================
-- SECTION 4: Materialized Views for Fixed Explanation Chains
-- ============================================================================

-- The MVP has NO free graph traversal
-- All queries must use the fixed template: Company → Drug → Target → Disease

CREATE MATERIALIZED VIEW IF NOT EXISTS explanation_chain AS
SELECT
    c.cik,
    c.sec_legal_name AS company_name,
    c.ticker,
    cd.drug_id,
    dp.name AS drug_name,
    dp.development_stage,
    dt.target_id,
    t.name AS target_name,
    t.gene_symbol,
    td.disease_id,
    d.name AS disease_name,
    d.therapeutic_area,
    td.association_score,
    -- Evidence chain
    cd.evidence_id AS company_drug_evidence_id,
    dt.evidence_id AS drug_target_evidence_id,
    td.evidence_id AS target_disease_evidence_id
FROM company c
INNER JOIN company_drug cd ON c.cik = cd.company_cik AND cd.valid_to IS NULL
INNER JOIN drug_program dp ON cd.drug_id = dp.id
INNER JOIN drug_target dt ON dp.id = dt.drug_id
INNER JOIN target t ON dt.target_id = t.id
INNER JOIN target_disease td ON t.id = td.target_id
INNER JOIN disease d ON td.disease_id = d.id;

CREATE UNIQUE INDEX idx_explanation_chain_pk ON explanation_chain(cik, drug_id, target_id, disease_id);
CREATE INDEX idx_explanation_chain_company ON explanation_chain(cik);
CREATE INDEX idx_explanation_chain_disease ON explanation_chain(disease_id);
CREATE INDEX idx_explanation_chain_target ON explanation_chain(target_id);

-- Refresh function
CREATE OR REPLACE FUNCTION refresh_explanation_chain() RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY explanation_chain;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 5: Quality Gates (Metrics for trust)
-- ============================================================================

CREATE OR REPLACE VIEW quality_metrics AS
SELECT
    (SELECT COUNT(*) FROM company WHERE cik IN (SELECT company_cik FROM universe_membership WHERE end_date IS NULL)) AS companies_in_universe,
    (SELECT COUNT(DISTINCT company_cik) FROM company_drug WHERE valid_to IS NULL) AS companies_with_drugs,
    (SELECT COUNT(*) FROM drug_program) AS total_drugs,
    (SELECT COUNT(DISTINCT drug_id) FROM drug_target) AS drugs_with_targets,
    (SELECT COUNT(DISTINCT drug_id) FROM drug_disease) AS drugs_with_diseases,
    (SELECT COUNT(*) FROM evidence) AS total_evidence_records,
    (SELECT COUNT(*) FROM company_drug WHERE evidence_id IS NULL) AS edges_without_evidence;

-- ============================================================================
-- SECTION 6: Audit Trail
-- ============================================================================

CREATE TABLE IF NOT EXISTS ingestion_log (
    id              BIGSERIAL PRIMARY KEY,
    phase           TEXT NOT NULL,              -- 'universe', 'cik_lock', 'corporate_spine', 'enrichment', 'asset_mapping'
    source_system   TEXT NOT NULL,
    records_processed INTEGER,
    records_inserted  INTEGER,
    records_updated   INTEGER,
    records_discarded INTEGER,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL,              -- 'running', 'completed', 'failed'
    error_message   TEXT,
    metadata        JSONB
);

CREATE INDEX idx_ingestion_log_phase ON ingestion_log(phase);
CREATE INDEX idx_ingestion_log_date ON ingestion_log(started_at DESC);
