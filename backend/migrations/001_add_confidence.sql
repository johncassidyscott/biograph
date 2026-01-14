-- Migration: Add confidence scores to edges
-- Date: 2026-01-14
-- Description: Add confidence field to track relationship certainty

-- Add confidence column if it doesn't exist
ALTER TABLE edge
ADD COLUMN IF NOT EXISTS confidence REAL DEFAULT 1.0;

-- Add comment explaining the field
COMMENT ON COLUMN edge.confidence IS 'Relationship confidence score 0.0-1.0. 1.0=canonical source, 0.9+=high confidence, 0.7-0.9=medium, <0.7=low confidence';

-- Update existing edges to have explicit confidence based on source
-- Canonical sources get 1.0
UPDATE edge SET confidence = 1.0
WHERE source IN ('chembl', 'mesh', 'opentargets')
  AND confidence IS NULL;

-- Clinical trials get 0.85 (good but not perfect matching)
UPDATE edge SET confidence = 0.85
WHERE source = 'ctgov'
  AND confidence IS NULL;

-- Discovered/inferred relationships get lower confidence
UPDATE edge SET confidence = 0.70
WHERE source IN ('discovered', 'inferred')
  AND confidence IS NULL;

-- Add index for filtering by confidence
CREATE INDEX IF NOT EXISTS edge_confidence_idx ON edge(confidence);

-- Show summary
SELECT
    source,
    CASE
        WHEN confidence >= 0.95 THEN 'High (0.95-1.0)'
        WHEN confidence >= 0.85 THEN 'Good (0.85-0.95)'
        WHEN confidence >= 0.70 THEN 'Medium (0.70-0.85)'
        ELSE 'Low (<0.70)'
    END as confidence_bucket,
    COUNT(*) as edge_count
FROM edge
GROUP BY source, confidence_bucket
ORDER BY source, MIN(confidence) DESC;
