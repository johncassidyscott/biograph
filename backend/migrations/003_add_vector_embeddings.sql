-- Migration 003: Add vector embeddings for semantic entity resolution

-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Add description and embedding columns to entity table
ALTER TABLE entity
ADD COLUMN IF NOT EXISTS description TEXT,
ADD COLUMN IF NOT EXISTS embedding vector(768);  -- 768 dimensions for BioBERT/PubMedBERT

-- Create vector similarity index for fast nearest neighbor search
-- Using HNSW (Hierarchical Navigable Small World) for better performance
CREATE INDEX IF NOT EXISTS entity_embedding_idx ON entity
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Add metadata column for flexible entity enrichment data
ALTER TABLE entity
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- Index for metadata queries
CREATE INDEX IF NOT EXISTS entity_metadata_idx ON entity USING GIN (metadata);

-- Add embedding update timestamp
ALTER TABLE entity
ADD COLUMN IF NOT EXISTS embedding_updated_at TIMESTAMPTZ;

-- Function to automatically update entity updated_at timestamp
CREATE OR REPLACE FUNCTION update_entity_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update timestamp on entity changes
DROP TRIGGER IF EXISTS entity_updated_at_trigger ON entity;
CREATE TRIGGER entity_updated_at_trigger
    BEFORE UPDATE ON entity
    FOR EACH ROW
    EXECUTE FUNCTION update_entity_updated_at();

-- Create entity_enrichment_log table to track enrichment attempts
CREATE TABLE IF NOT EXISTS entity_enrichment_log (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    enrichment_type TEXT NOT NULL,          -- 'wikidata', 'umls', 'chembl', 'pubchem', 'embedding'
    status          TEXT NOT NULL,          -- 'success', 'not_found', 'error', 'rate_limited'
    response_data   JSONB,                  -- Store API response
    error_message   TEXT,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS entity_enrichment_log_entity_idx ON entity_enrichment_log(entity_id);
CREATE INDEX IF NOT EXISTS entity_enrichment_log_type_idx ON entity_enrichment_log(enrichment_type);
CREATE INDEX IF NOT EXISTS entity_enrichment_log_status_idx ON entity_enrichment_log(status);

-- View for entities needing enrichment (no embedding or identifiers)
CREATE OR REPLACE VIEW entities_needing_enrichment AS
SELECT
    e.id,
    e.kind,
    e.canonical_id,
    e.name,
    e.description,
    e.embedding IS NULL as needs_embedding,
    e.description IS NULL as needs_description,
    NOT EXISTS (
        SELECT 1 FROM entity_identifier ei
        WHERE ei.entity_id = e.id
        AND ei.identifier_type IN ('wikidata_qid', 'lei', 'permid')
    ) as needs_identifiers,
    e.created_at,
    e.updated_at
FROM entity e
WHERE
    e.embedding IS NULL
    OR e.description IS NULL
    OR NOT EXISTS (
        SELECT 1 FROM entity_identifier ei
        WHERE ei.entity_id = e.id
        AND ei.identifier_type IN ('wikidata_qid', 'lei', 'permid')
    )
ORDER BY e.created_at DESC;

-- View for high-quality entities (fully enriched)
CREATE OR REPLACE VIEW enriched_entities AS
SELECT
    e.id,
    e.kind,
    e.canonical_id,
    e.name,
    e.description,
    e.embedding IS NOT NULL as has_embedding,
    e.description IS NOT NULL as has_description,
    COUNT(ei.identifier_type) as identifier_count,
    array_agg(DISTINCT ei.identifier_type) FILTER (WHERE ei.identifier_type IS NOT NULL) as identifier_types,
    e.metadata,
    e.created_at,
    e.updated_at,
    e.embedding_updated_at
FROM entity e
LEFT JOIN entity_identifier ei ON ei.entity_id = e.id
WHERE e.embedding IS NOT NULL
GROUP BY e.id, e.kind, e.canonical_id, e.name, e.description, e.metadata, e.created_at, e.updated_at, e.embedding_updated_at
ORDER BY identifier_count DESC, e.updated_at DESC;

-- Add comments for documentation
COMMENT ON COLUMN entity.embedding IS 'BioBERT/PubMedBERT 768-dimensional vector embedding for semantic similarity search';
COMMENT ON COLUMN entity.description IS 'Entity description from Wikidata, MeSH, ChEMBL, or other authoritative sources';
COMMENT ON COLUMN entity.metadata IS 'Flexible JSONB field for additional enrichment data (images, URLs, structured data)';
COMMENT ON TABLE entity_enrichment_log IS 'Audit log of all entity enrichment attempts for debugging and monitoring';
