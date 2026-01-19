# Branch Comparison Report

**Date**: 2026-01-19
**Comparison**: `claude/review-biograph-mvp-wqkvM` vs `claude/review-biograph-mvp-Ze3Y6`

## Commit Information

| Branch | HEAD Commit | Author | Date | Message |
|--------|-------------|--------|------|---------|
| wqkvM | `0d520f8471ff585728b0dea8436b3df42574163d` | Claude | 2026-01-19 13:34:18 | Add comprehensive summary of all fixes applied |
| Ze3Y6 | `357575bedceb3fa05a39ad671018b71dec306412` | Claude | 2026-01-19 13:58:27 | Fix all critical schema mismatches and clean up codebase |

## Diffstat Summary

### wqkvM vs MVP-build (origin/claude/biograph-mvp-build-fzPCW)
- **23 files changed**
- **1,123 insertions(+), 2,632 deletions(-)**
- Major deletions: backend loaders, legacy migrations, schema files, pycache

### Ze3Y6 vs MVP-build
- **6 files changed**
- **874 insertions(+), 429 deletions(-)**
- Focused changes: postgres_store.py, admin.py, health.py, plus architectural review doc

### Direct diff (wqkvM → Ze3Y6)
- 6 files differ
- Ze3Y6 adds `ARCHITECTURAL_REVIEW_fzPCW.md` (830 lines)
- Ze3Y6 fixes schema alignment in `postgres_store.py` and `admin.py`

---

## Criteria Evaluation

### a) Single FastAPI entrypoint (`biograph/api/main.py`)
| Branch | Status |
|--------|--------|
| wqkvM | PASS - File exists with proper structure |
| Ze3Y6 | PASS - File exists with proper structure |

### b) render.yaml points to `uvicorn biograph.api.main:app`
| Branch | Status |
|--------|--------|
| wqkvM | PASS - `startCommand: uvicorn biograph.api.main:app --host 0.0.0.0 --port $PORT --workers 2` |
| Ze3Y6 | PASS - Identical configuration |

### c) Legacy entrypoints removed or quarantined
| Branch | Status | Details |
|--------|--------|---------|
| wqkvM | PARTIAL | Removed `backend/app/schema.sql`, backend loaders, migrations - but still has `backend/app/` |
| Ze3Y6 | PARTIAL | Still has `backend/app/` with `__pycache__` files (should be gitignored) |

### d) Connection pooling implemented and used everywhere
| Branch | Status |
|--------|--------|
| wqkvM | PASS - `biograph/api/dependencies.py` implements psycopg_pool |
| Ze3Y6 | PASS - Identical implementation |

### e) API-key auth enforced on admin/curation endpoints
| Branch | Status |
|--------|--------|
| wqkvM | PASS - `verify_api_key` dependency on admin routes |
| Ze3Y6 | PASS - Identical implementation |

### f) Error middleware + structured JSON errors
| Branch | Status |
|--------|--------|
| wqkvM | PASS - Global exception handler in main.py |
| Ze3Y6 | PASS - Identical implementation |

### g) /healthz exists and checks Postgres (+ Neo4j optional)
| Branch | Status |
|--------|--------|
| wqkvM | PASS - `biograph/api/v1/health.py` with Postgres check |
| Ze3Y6 | PASS - Identical implementation |

### h) Requirements file(s) consistent and CI installs production deps only
| Branch | Status |
|--------|--------|
| wqkvM | PASS - Single `requirements.txt` with production deps |
| Ze3Y6 | PASS - Identical requirements |

### i) Contract tests green on CI and locally
| Branch | Status | Details |
|--------|--------|---------|
| wqkvM | PARTIAL | 119 passed, 33 failed, 5 errors |
| Ze3Y6 | PARTIAL | 119 passed, 33 failed, 5 errors |

---

## CRITICAL DIFFERENCE: Schema Alignment

### Database Schema (from `db/migrations/001_complete_schema.sql`)
```sql
CREATE TABLE IF NOT EXISTS assertion (
    assertion_id        BIGSERIAL PRIMARY KEY,
    subject_type        TEXT NOT NULL,
    subject_id          TEXT NOT NULL,
    predicate           TEXT NOT NULL,
    object_type         TEXT NOT NULL,
    object_id           TEXT NOT NULL,
    asserted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retracted_at        TIMESTAMPTZ,
    computed_confidence NUMERIC,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### wqkvM postgres_store.py queries (MISMATCHED)
```python
SELECT DISTINCT a.object_id, a.assertion_id,
       a.confidence_band, a.confidence_score, a.link_method
FROM assertion a
WHERE a.subject_id = %s
...
AND a.valid_from <= %s
AND (a.valid_until IS NULL OR a.valid_until >= %s)
AND a.deleted_at IS NULL
```
**Columns `confidence_band`, `confidence_score`, `link_method`, `valid_from`, `valid_until`, `deleted_at` DO NOT EXIST in the schema.**

### Ze3Y6 postgres_store.py queries (CORRECT)
```python
SELECT DISTINCT a.object_id, a.assertion_id,
       a.computed_confidence, t.name
FROM assertion a
LEFT JOIN target t ON a.object_id = t.target_id
WHERE a.subject_id = %s
...
AND a.asserted_at <= %s
AND a.retracted_at IS NULL
```
**Uses correct columns: `computed_confidence`, `asserted_at`, `retracted_at`.**

---

## Local Validation Results

### Branch: wqkvM

**Install**: SUCCESS (requirements.txt installed)

**Migrations**: SUCCESS
- 001_complete_schema.sql: PASS
- 002_schema_hardening.sql: PASS
- 003_linkage_confidence.sql: PASS
- 004_lookup_cache.sql: PASS

**Pytest Results**:
```
=================== 33 failed, 119 passed, 5 errors in 4.78s ===================
```

### Branch: Ze3Y6

**Install**: SUCCESS (requirements.txt installed)

**Migrations**: SUCCESS
- 001_complete_schema.sql: PASS
- 002_schema_hardening.sql: PASS
- 003_linkage_confidence.sql: PASS
- 004_lookup_cache.sql: PASS

**Pytest Results**:
```
=================== 33 failed, 119 passed, 5 errors in 4.57s ===================
```

---

## Selection Decision

### Winner: `claude/review-biograph-mvp-Ze3Y6`

**Reasoning**:

1. **Internal Consistency (CRITICAL)**: Ze3Y6's `postgres_store.py` and `admin.py` use columns that actually exist in the database schema (`computed_confidence`, `asserted_at`, `retracted_at`). wqkvM's code references non-existent columns (`confidence_band`, `confidence_score`, `link_method`, `valid_from`, `valid_until`, `deleted_at`) and would fail at runtime.

2. **Test Results**: Both branches have identical test results (119 passed, 33 failed, 5 errors). The test failures are identical and unrelated to the branch differences.

3. **Fewer Files Changed**: Ze3Y6 has more focused changes (6 files vs 23 files), making it easier to review and understand.

4. **Documentation**: Ze3Y6 includes `ARCHITECTURAL_REVIEW_fzPCW.md` documenting the review process.

5. **Same Requirements**: Both have identical production dependencies.

### Loser: `claude/review-biograph-mvp-wqkvM`

**Archived as**: `archive/claude-review-biograph-mvp-wqkvM`

**Reason for Archive**: Code contains schema mismatches that would cause runtime failures. The postgres_store.py queries reference columns that don't exist in the database schema.

---

## Actions Taken

1. [x] Created comparison report at `docs/BRANCH_COMPARISON.md`
2. [ ] Created annotated tag `archive/claude-review-biograph-mvp-wqkvM`
3. [ ] Pushed tag to remote
4. [ ] Merged Ze3Y6 into canonical MVP branch
5. [ ] Deleted losing branch from remote
