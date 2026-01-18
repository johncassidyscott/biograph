

# BioGraph MVP v8.1 — Best-in-Class Fixes

**Index-anchored intelligence graph for life sciences**

> Bloomberg-thinking applied to life sciences — now with audit-grade provenance and deterministic evidence chains.

---

## What Changed in v8.1

This version implements **8 best-in-class fixes** that transform BioGraph from good MVP to **production-grade investor intelligence**:

### ✅ Fix #1: Issuer Identity (Stable Internal Key)
**Problem**: CIKs can change (mergers, spinoffs). Using CIK as primary key breaks continuity.

**Solution**:
- Introduced `issuer` table with stable `issuer_id` (e.g., `ISS_0000059478`)
- CIK linked via `issuer_cik_history` with effective dates
- Changes are **MANUAL only** (no automated inference)
- Supports tracking M&A without data loss

```sql
issuer(issuer_id, primary_cik, created_at, notes)
issuer_cik_history(issuer_id, cik, start_date, end_date, source, observed_at)
universe_membership(issuer_id, universe_id, start_date, end_date)
```

### ✅ Fix #2: Explanation as First-Class Queryable Object
**Problem**: "No free traversal" is a product promise devs will accidentally violate.

**Solution**:
- Created `explanation` table that is **the ONLY UI query surface**
- Materialized view of fixed chain: `Issuer → DrugProgram → Target → Disease`
- Raw `assertion` table is **admin-only**
- UI cannot accidentally do graph traversal

```sql
explanation(
    explanation_id,
    issuer_id,
    drug_program_id,
    target_id,
    disease_id,
    as_of_date,              -- Fix #8: time semantics
    strength_score,
    issuer_drug_assertion_id,
    drug_target_assertion_id,
    target_disease_assertion_id
)
```

**Product Rule**: All API endpoints query `explanation` table only.

### ✅ Fix #3: DrugProgram Issuer-Scoped IDs
**Problem**: "ChEMBL or internal ID" will cause duplicates and missing coverage.

**Solution**:
- DrugProgram IDs are **always issuer-scoped**: `CIK:{cik}:PROG:{slug}`
- ChEMBL ID stored as **attribute**, not primary key
- Enforced unique constraint: `(issuer_id, slug)`
- **No cross-issuer dedupe** in MVP (avoids entity resolution hell)

```sql
drug_program(
    drug_program_id PRIMARY KEY,  -- Format: "CIK:0000059478:PROG:tirzepatide"
    issuer_id REFERENCES issuer,
    slug,                          -- Unique within issuer
    name,
    chembl_id,                     -- Attribute, not ID
    ...
    UNIQUE(issuer_id, slug)
)
```

### ✅ Fix #4: Assertion-Evidence Mediation (Audit-Grade)
**Problem**: "Evidence is first-class" isn't enforceable without constraints.

**Solution**:
- Every relationship is an `assertion` mediated by `evidence`
- **No direct edges** — all graph edges are views over assertions
- Assertion is **invalid** unless it has ≥1 `assertion_evidence` record
- Automatic confidence computation from evidence

```sql
evidence(evidence_id, source_system, source_record_id, license, observed_at, ...)
assertion(assertion_id, subject_type, subject_id, predicate, object_type, object_id, ...)
assertion_evidence(assertion_id, evidence_id, weight, notes)

-- Constraint: assertion MUST have evidence
-- Graph edges = views over assertions (issuer_drug, drug_target, target_disease)
```

**Audit Trail**: Every edge traceable to source via `assertion_evidence` → `evidence`.

### ✅ Fix #5: Open Targets Scope Lock (Prevent R&D Creep)
**Problem**: OpenTargets can explode scope with genetics, pathways, variants.

**Solution**:
- **Whitelist** of allowed OpenTargets fields:
  - Target: `id, approvedSymbol, approvedName, proteinIds, targetClass`
  - Disease: `id, name, therapeuticAreas`
  - Association: `score` (high-level only)
- **Explicitly blocked**:
  - Genetics, pathways, variant evidence
  - Network propagation scores
  - Detailed datatype scores

```python
# Scope locked in loader
ALLOWED_TARGET_FIELDS = ['id', 'approvedSymbol', 'approvedName', 'proteinIds', 'targetClass']
ALLOWED_DISEASE_FIELDS = ['id', 'name', 'therapeuticAreas']
# NO genetics, NO pathways, NO variants
```

### ✅ Fix #6: Licensing Gates (Commercial-Safe)
**Problem**: License drift kills commercial viability.

**Solution**:
- `license_allowlist` table with commercial-safe licenses only
- **Database trigger** validates every `evidence` insert
- Unknown license → **insert fails** (build-breaker)
- Attribution requirements stored for ChEMBL (CC BY-SA 3.0)

```sql
license_allowlist(license, is_commercial_safe, requires_attribution, ...)

-- Prepopulated:
'PUBLIC_DOMAIN'  -- SEC EDGAR
'CC0'            -- OpenTargets, Wikidata
'CC-BY-4.0'      -- GeoNames
'CC-BY-SA-3.0'   -- ChEMBL (requires attribution)

-- Trigger enforces: license MUST be in allowlist
```

### ✅ Fix #7: Deterministic Confidence Rubric
**Problem**: "Confidence" becomes arbitrary without formula.

**Solution**:
- **Transparent scoring formula**:
  ```
  confidence = base_source_score + log(1 + evidence_count) + recency_bonus + curator_delta
  ```
- `confidence_rubric` table stores base scores per source:
  - SEC EDGAR: 0.95 (authoritative for corporate facts)
  - OpenTargets: 0.85
  - ChEMBL: 0.80
  - Wikidata: 0.70
  - Manual: 1.00
- Confidence **auto-computed** via trigger when evidence added
- Formula is configurable, not hardcoded

```sql
CREATE FUNCTION compute_assertion_confidence(assertion_id) RETURNS NUMERIC AS $$
  -- Base score from source
  -- + logarithmic evidence count bonus
  -- + recency decay
  -- + optional curator override
  RETURN confidence [0, 1];
$$;
```

### ✅ Fix #8: As-Of Time Semantics
**Problem**: "Time-aware views" needs explicit mechanics.

**Solution**:
- Every `explanation` has `as_of_date` (snapshot date)
- Assertions are **effective-dated**: `asserted_at`, `retracted_at`
- API endpoint: `/api/explanation/{issuer}/changes?since_date=2024-Q3`
- Enables investor question: **"What changed since last quarter?"**

```sql
assertion(
    ...
    asserted_at TIMESTAMPTZ,     -- When assertion became valid
    retracted_at TIMESTAMPTZ     -- NULL = currently valid
)

explanation(
    ...
    as_of_date DATE              -- Snapshot date
)
```

---

## Architecture Overview

### Entity Model (9 Tables)

1. **Issuer** — Stable economic entity (Fix #1)
2. **Company** — SEC entity (linked via CIK)
3. **Filing** — SEC EDGAR filings
4. **InsiderTransaction** — Form 4 data
5. **Exhibit** — Exhibit metadata
6. **Location** — GeoNames canonical
7. **DrugProgram** — Issuer-scoped therapeutic asset (Fix #3)
8. **Target** — OpenTargets ID
9. **Disease** — EFO/MONDO ID

### Provenance Model (Fix #4)

- **Evidence** — First-class provenance records
- **Assertion** — Semantic relationships (subject → predicate → object)
- **AssertionEvidence** — Many-to-many link (≥1 required)

### Query Surface (Fix #2)

```
UI Queries
    ↓
Explanation Table (ONLY)
    ↓
Views over Assertions
    ↓
Assertion + Evidence
    ↓
Source Systems
```

**Rule**: UI cannot query raw assertions. Only `explanation` table.

---

## Quick Start

### 1. Initialize Database

```bash
cd backend
psql $DATABASE_URL < schema_v8_1.sql
```

### 2. Load Universe

```bash
python loaders/load_universe_v8_1.py ../data/universe.csv xbi
```

CSV format:
```csv
company_name,ticker,exchange,cik,universe_id,start_date,notes
Eli Lilly and Company,LLY,NYSE,0000059478,xbi,2024-01-01,XBI constituent
```

### 3. Run Pipeline

```bash
python build_graph_v8_1.py --phases all
```

Phases:
- Phase 0: Universe (manual CSV)
- Phase 1: CIK resolution (SEC EDGAR)
- Phase 2: Corporate spine (filings)
- Phase 3: Enrichment (Wikidata)
- Phase 4: Asset mapping (OpenTargets - **scope locked**)
- Phase 5: Materialize explanations

### 4. Check Quality Gates

```bash
python build_graph_v8_1.py --quality-gates
```

Quality checks:
- ✅ No assertions without evidence (Fix #4)
- ✅ No evidence with bad license (Fix #6)
- ✅ ≥95% issuers have drugs
- ✅ ≥90% drugs have targets

### 5. Start API

```bash
python app_v8_1.py
```

Navigate to `http://localhost:5000`

---

## API Endpoints (v8.1)

### List Issuers
```
GET /api/issuers?universe_id=xbi
```

### Issuer Dashboard
```
GET /api/issuer/{issuer_id}
```

Returns:
- Issuer info
- Pipeline (explanation chains **ONLY** — Fix #2)
- Recent filings
- Insider activity
- HQ location

### Explanation Chains
```
GET /api/explanation/{issuer_id}?as_of_date=2024-12-31
```

**CRITICAL**: This is the **ONLY** query surface for UI (Fix #2).

Returns fixed chain: `Issuer → DrugProgram → Target → Disease` with:
- Full evidence chain (audit trail)
- Computed strength score (Fix #7)
- As-of snapshot date (Fix #8)

### What Changed?
```
GET /api/explanation/{issuer_id}/changes?since_date=2024-09-30
```

Investor use case: "Show me what changed since Q3"

Returns:
- Added explanations
- Removed explanations
- Changed strength scores (Fix #8)

### Quality Metrics
```
GET /api/quality-metrics
```

Returns:
- Quality gate status (all checks)
- Assertions without evidence count (should be 0)
- Evidence with bad license count (should be 0)
- Coverage percentages

---

## Data Ingestion (Assertion-Evidence Model)

### Creating Edges with Evidence

```python
from loaders.assertion_helper import (
    create_evidence,
    create_issuer_drug_assertion
)

# Step 1: Create evidence record
evidence_id = create_evidence(
    source_system='sec_edgar',
    source_record_id='0001193125-24-123456',
    license='PUBLIC_DOMAIN',
    observed_at=datetime.now(),
    uri='https://www.sec.gov/...'
)

# Step 2: Create assertion (with evidence)
assertion_id = create_issuer_drug_assertion(
    issuer_id='ISS_0000059478',
    drug_program_id='CIK:0000059478:PROG:tirzepatide',
    relationship='develops',
    evidence_ids=[evidence_id]
)

# Confidence auto-computed via trigger (Fix #7)
```

**Rule**: Cannot create assertion without evidence (enforced).

### Materializing Explanations

```bash
python loaders/materialize_explanations.py 2024-12-31
```

This builds the `explanation` table from assertions for a given date (Fix #8).

---

## Quality Contract

### Hard Gates (Build-Breakers)

1. **No assertions without evidence** (Fix #4)
   - Trigger prevents insert
   - Query `quality_metrics.assertions_without_evidence` (should be 0)

2. **No evidence without commercial-safe license** (Fix #6)
   - Trigger validates against `license_allowlist`
   - Unknown license → insert fails

3. **Confidence is deterministic** (Fix #7)
   - Auto-computed via formula
   - Auditable, not arbitrary

4. **UI queries explanation table ONLY** (Fix #2)
   - Raw assertions are admin-only
   - Prevents accidental graph traversal

### Soft Gates (Quality Metrics)

- ≥95% issuers have ≥1 drug program
- ≥90% drug programs have target + disease
- All explanations have strength score > 0

---

## What Makes v8.1 Production-Grade

### 1. Audit-Grade Provenance
Every relationship traceable to source via:
```
Explanation → Assertion → AssertionEvidence → Evidence → Source URI
```

### 2. Deterministic Scoring
Confidence formula is transparent and configurable:
```
base_source_score + log(evidence_count) + recency_bonus
```

### 3. Commercial-Safe by Design
License validation at **database level** (not application code).

### 4. Time-Aware Intelligence
"What changed?" is a first-class query, not a hack.

### 5. Scope-Locked Sources
OpenTargets whitelist prevents R&D creep.

### 6. Issuer Continuity
M&A tracking without data loss (stable `issuer_id`).

### 7. No Accidental Graph Traversal
UI cannot query raw assertions (architectural constraint).

### 8. Issuer-Scoped Assets
No entity resolution hell (DrugProgram scoped to issuer).

---

## Deployment Checklist

- [ ] Initialize schema v8.1
- [ ] Load universe (Phase 0)
- [ ] Run CIK resolution (Phase 1)
- [ ] Load SEC filings (Phase 2)
- [ ] Enrich with Wikidata (Phase 3)
- [ ] Load OpenTargets (Phase 4 - scope locked)
- [ ] Materialize explanations (Phase 5)
- [ ] Verify quality gates (all pass)
- [ ] Start API v8.1
- [ ] Test `/api/explanation/{issuer}` (ONLY query surface)
- [ ] Test `/api/explanation/{issuer}/changes` (time-aware)
- [ ] Verify admin endpoint `/api/admin/assertions` protected

---

## Migration from v8.0

If you have v8.0 data:

1. **Issuer migration**: Create `issuer` records from existing companies
   ```sql
   INSERT INTO issuer (issuer_id, primary_cik)
   SELECT 'ISS_' || cik, cik FROM company;
   ```

2. **Assertion migration**: Convert existing edges to assertions
   ```sql
   -- company_drug → assertion
   INSERT INTO assertion (subject_type, subject_id, predicate, object_type, object_id)
   SELECT 'issuer', issuer_id, relationship, 'drug_program', drug_id
   FROM company_drug;
   ```

3. **Evidence backfill**: Create evidence records for existing edges
   (manual process, source-dependent)

4. **Materialize explanations**: Run materialization for current date

---

## License & Attribution

**Code**: MIT

**Data Sources**:
- SEC EDGAR: Public Domain (U.S. Government)
- OpenTargets: CC0 (Public Domain)
- Wikidata: CC0 (Public Domain)
- ChEMBL: CC BY-SA 3.0 (**requires attribution**)
- GeoNames: CC BY 4.0

**ChEMBL Attribution** (required by license):
> Data from ChEMBL used under CC BY-SA 3.0 license.
> ChEMBL: https://www.ebi.ac.uk/chembl/

---

## Support

For questions or issues, open a GitHub issue.

**Version**: 8.1-MVP
**Status**: Production-grade
**Audience**: Institutional investors, strategy, BD, CI

---

## What's Next

### Post-MVP Enhancements

1. **Form 4 parsing** (insider transaction details)
2. **Exhibit extraction** (contract mentions, amendments)
3. **Patent ingestion** (CPC codes, priority dates)
4. **XBRL extraction** (select financial concepts)
5. **Alert system** (filing triggers, program updates)
6. **Comparable detection** (mechanism-based peers)
7. **Export formats** (CSV, PDF evidence chains)

### Production Hardening

1. **API authentication** (JWT)
2. **Rate limiting** (per-user quotas)
3. **Caching** (Redis for explanation queries)
4. **Full-text search** (ElasticSearch for filings)
5. **Monitoring** (Prometheus metrics)
6. **Backup/recovery** (automated snapshots)

---

This is **Bloomberg-thinking applied to life sciences** with **audit-grade provenance** and **deterministic intelligence**.
