# Entity Resolution Strategy

**Goal:** Make BioGraph "accurate AF" by ensuring entities are correctly identified and relationships are validated.

## The Problem

When ingesting data from multiple sources (ChEMBL, ClinicalTrials.gov, PubMed, FDA, etc.), the same real-world entity appears with different names and identifiers:

**Example: Eli Lilly (the company)**
- CT.gov: "Eli Lilly and Company"
- CT.gov: "Lilly"
- SEC: "ELI LILLY & Co" (CIK: 0000059478)
- Patents: "Eli Lilly And Company"

**Example: Semaglutide (the drug)**
- ChEMBL: CHEMBL2109743
- CT.gov intervention: "semaglutide"
- CT.gov intervention: "Semaglutide (Ozempic)"
- PubMed: "GLP-1 receptor agonist semaglutide"

Without entity resolution, these become **separate entities with separate graphs**, fragmenting the knowledge.

## The Solution

### 1. Canonical ID Hierarchy

Always prefer authoritative identifiers over generated ones:

**Drugs:**
1. `CHEMBL:CHEMBL123` (preferred - from ChEMBL API)
2. `DRUG:semaglutide` (fallback - normalized name)
3. ❌ `CTG_INT:semaglutide` (deprecated - old loader)

**Diseases:**
1. `MESH:D009765` (preferred - from MeSH)
2. `CONDITION:obesity` (fallback - normalized condition)

**Companies:**
1. `CIK:0000059478` (preferred - from SEC EDGAR)
2. `COMPANY:eli_lilly` (fallback - normalized name)
3. ❌ `DISCOVERED:eli_lilly` (deprecated)
4. ❌ `CTG_SPONSOR:eli_lilly_and_company` (deprecated)

**Targets:**
1. `UNIPROT:P09874` (preferred - from UniProt)
2. `CHEMBL_TARGET:CHEMBL123` (fallback - from ChEMBL)

**Trials:**
- `NCT:NCT01234567` (always unique, no resolution needed)

**Publications:**
1. `DOI:10.1234/xyz` (preferred)
2. `PMID:12345678` (acceptable)
3. `ARXIV:2401.12345` (for preprints)

### 2. EntityResolver Service

**All loaders must use the entity resolver** instead of creating entities directly.

```python
from backend.entity_resolver import get_resolver

resolver = get_resolver()
resolver.load_lookup_tables()  # Load once at start

# Resolve drug
drug = resolver.resolve_drug("Semaglutide", chembl_id="CHEMBL2109743")
# Returns: ResolvedEntity(entity_id=123, canonical_id="CHEMBL:CHEMBL2109743",
#                          name="Semaglutide", confidence=1.0, match_type="exact_id")

# Resolve without canonical ID (fuzzy matching)
drug = resolver.resolve_drug("semaglutide injection")
# Returns: ResolvedEntity(entity_id=123, canonical_id="CHEMBL:CHEMBL2109743",
#                          name="Semaglutide", confidence=0.82, match_type="fuzzy")
```

### 3. Resolution Strategy

The resolver tries multiple strategies in order:

**Priority 1: Canonical ID match (confidence 1.0)**
- If ChEMBL ID / MeSH ID / CIK provided, use it
- Check if entity already exists with that ID
- If yes: return existing entity
- If no: create new entity with canonical ID

**Priority 2: Exact name match (confidence 0.95)**
- Lowercase exact match against existing entity names
- Very high confidence - same spelling

**Priority 3: Alias match (confidence 0.95)**
- Match against stored aliases from ChEMBL, MeSH, SEC
- High confidence - official synonym

**Priority 4: Normalized match (confidence 0.90)**
- Strip punctuation, remove company suffixes (Inc, LLC, etc.)
- Remove "The" prefix, normalize whitespace
- Good confidence - minor formatting differences

**Priority 5: Fuzzy match (confidence 0.80-0.90)**
- String similarity using SequenceMatcher
- Threshold: 90%+ similarity required
- Catches typos, slight variations
- Confidence = similarity * 0.85

**Priority 6: API resolution (confidence 0.70)**
- Call external APIs to resolve unknown names
- ChEMBL name search for drugs
- MeSH API for diseases
- SEC company search
- (Not implemented yet to avoid rate limits)

**Priority 7: Create new entity (confidence 0.50)**
- If no match found, create new entity
- Low confidence - might be duplicate or data quality issue
- Flag for manual review

### 4. Confidence Scores

Every edge has a confidence score (0.0-1.0) tracking relationship certainty:

```sql
CREATE TABLE edge (
  ...
  confidence REAL DEFAULT 1.0  -- 0.0-1.0 relationship confidence
);
```

**Confidence levels:**
- **1.0:** Canonical source (ChEMBL mechanism, MeSH hierarchy)
- **0.95:** High confidence (exact ID/name match)
- **0.90:** Good confidence (normalized match)
- **0.85:** Medium-high (fuzzy match, CT.gov relationships)
- **0.70:** Medium (inferred relationships, API-resolved)
- **0.50:** Low (newly created entity, string-based match)
- **<0.50:** Very low (questionable, needs review)

**Usage:**
```sql
-- Get high-confidence drug-disease relationships
SELECT * FROM edge
WHERE predicate = 'treats'
  AND confidence >= 0.90;

-- Find low-confidence relationships needing review
SELECT * FROM edge
WHERE confidence < 0.70
ORDER BY confidence;
```

### 5. Deduplication Tools

**Find duplicates:**
```bash
cd backend
python utils/find_duplicates.py
```

Shows:
- Exact name duplicates (different IDs, same name)
- Fuzzy duplicates (90%+ similar names)
- Alias conflicts (same alias pointing to multiple entities)
- Entity distribution by ID prefix

**Merge duplicates:**
```bash
# Dry run (safe - shows what would happen)
python utils/merge_entities.py --kind drug --name "Semaglutide"

# Live merge (actually performs merge)
python utils/merge_entities.py --kind drug --name "Semaglutide" --live

# Merge specific entity IDs
python utils/merge_entities.py --ids 123 456 789 --live
```

Merge process:
1. Identifies "winner" (entity with highest canonical ID priority)
2. Transfers all edges from losers to winner
3. Transfers all aliases from losers to winner
4. Adds loser names as aliases to winner
5. Deletes loser entities

## Migration Plan

### Phase 1: Add Infrastructure ✅
- [x] Create EntityResolver service
- [x] Add confidence column to edge table
- [x] Create deduplication utilities
- [x] Document strategy

### Phase 2: Refactor Loaders (Next)
- [ ] Refactor load_ctgov.py to use resolver
- [ ] Refactor load_chembl.py (already good, add confidence)
- [ ] Refactor discover_companies.py to use resolver
- [ ] Refactor load_pubmed.py to use resolver
- [ ] Update build_graph.py to load entities in correct order

### Phase 3: Clean Existing Data
- [ ] Run migration to add confidence to existing edges
- [ ] Run find_duplicates.py to identify issues
- [ ] Merge obvious duplicates (same name, different IDs)
- [ ] Review low-confidence relationships (<0.70)
- [ ] Add missing aliases for common variations

### Phase 4: Production Hardening
- [ ] Add API resolution for unknown entities
- [ ] Implement entity change tracking (audit log)
- [ ] Build curation UI for reviewing low-confidence matches
- [ ] Add validation rules (e.g., drug must have CHEMBL or pass PubChem lookup)
- [ ] Set up monitoring for entity resolution quality metrics

## Loader Refactoring Example

**Old way (creates duplicates):**
```python
drug_cid = f"CTG_INT:{name.lower().replace(' ', '_')}"
cur.execute(
    "INSERT INTO entity (kind, canonical_id, name) VALUES ('drug', %s, %s) ...",
    (drug_cid, name)
)
```

**New way (uses resolver):**
```python
from backend.entity_resolver import get_resolver

resolver = get_resolver()
drug = resolver.resolve_drug(name)  # Returns existing or creates new

cur.execute(
    "INSERT INTO edge (src_id, predicate, dst_id, source, confidence) ...",
    (trial_id, drug.entity_id, drug.confidence)
)
```

See `loaders/load_ctgov_v2.py` for complete reference implementation.

## Quality Metrics

Track these metrics to measure resolution quality:

```sql
-- Entity distribution by ID prefix (should favor canonical IDs)
SELECT
    kind,
    SPLIT_PART(canonical_id, ':', 1) as id_type,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY kind), 1) as pct
FROM entity
GROUP BY kind, id_type
ORDER BY kind, count DESC;

-- Relationship confidence distribution
SELECT
    CASE
        WHEN confidence >= 0.95 THEN 'High (0.95-1.0)'
        WHEN confidence >= 0.85 THEN 'Good (0.85-0.95)'
        WHEN confidence >= 0.70 THEN 'Medium (0.70-0.85)'
        ELSE 'Low (<0.70)'
    END as confidence_bucket,
    COUNT(*) as edge_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM edge
GROUP BY confidence_bucket
ORDER BY MIN(confidence) DESC;

-- Entities needing review (low confidence or non-canonical IDs)
SELECT kind, canonical_id, name, id
FROM entity
WHERE (
    (kind = 'drug' AND canonical_id NOT LIKE 'CHEMBL:%')
    OR (kind = 'disease' AND canonical_id NOT LIKE 'MESH:%')
    OR (kind = 'company' AND canonical_id NOT LIKE 'CIK:%')
    OR (kind = 'target' AND canonical_id NOT LIKE 'UNIPROT:%')
)
ORDER BY kind, name
LIMIT 100;
```

**Target quality metrics:**
- **95%+ of drugs** should have CHEMBL IDs
- **98%+ of diseases** should have MESH IDs (or CONDITION: for rare diseases)
- **70%+ of companies** should have CIK IDs (rest are private/foreign)
- **95%+ of targets** should have UNIPROT IDs
- **85%+ of edges** should have confidence >= 0.85

## Next Steps

1. **Run the build** with existing loaders to see current state
2. **Run find_duplicates.py** to quantify the duplication problem
3. **Refactor loaders** one by one to use EntityResolver
4. **Run migration** to add confidence scores to existing edges
5. **Merge obvious duplicates** using merge_entities.py
6. **Review low-confidence relationships** and improve matching logic
7. **Add API resolution** for remaining unmatched entities
8. **Build curation UI** for manual review of edge cases

With this system in place, BioGraph will have production-grade entity resolution and data quality tracking.
