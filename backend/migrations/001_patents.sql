-- Migration 001: Patent Extensions
-- Note: patent, assignee, patent_assignee, patent_drug tables are defined in 000_core.sql
-- This migration is now a placeholder for future patent-specific extensions

-- If additional patent-related tables are needed, add them here
-- Example:
-- CREATE TABLE patent_citation (
--     patent_id INT REFERENCES patent(id) ON DELETE CASCADE,
--     cited_patent_id INT REFERENCES patent(id) ON DELETE CASCADE,
--     citation_type TEXT,
--     PRIMARY KEY (patent_id, cited_patent_id)
-- );

-- For now, this migration is intentionally empty to avoid duplicates with 000_core.sql
-- All patent tables are created in 000_core.sql

DO $$
BEGIN
    RAISE NOTICE 'Migration 001: Patent extensions (currently empty, avoiding duplicates)';
END $$;
