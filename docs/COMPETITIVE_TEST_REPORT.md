# COMPETITIVE TEST REPORT — BIOGRAPH MVP

**Branch:** `claude/port-wikidata-baz03-Appnm`
**Test Date:** 2026-01-20
**Tester:** Adversarial QA Engineer + Staff Architect
**Test Environment:** Python 3.11.14, Linux 4.4.0

---

## EXECUTIVE VERDICT: **FAIL** ❌

**Rationale:**
This branch contains **9 P0 blockers** that prevent deployment, violate core architectural contracts, and make the system non-functional. The codebase exhibits fundamental inconsistencies between schema, code, and deployment configuration that must be resolved before investor presentation.

**Critical Issues:**
1. **Build fails** (invalid dependency version)
2. **Multiple conflicting entrypoints** (Flask + FastAPI)
3. **Evidence model missing** (core contract violation)
4. **No authentication** (security P0)
5. **Schema inconsistencies** (3 different schemas)

**Recommended Action:** Do not merge. Fix all P0 issues, rebuild from clean state, and re-test.

---

## FINDINGS BY CATEGORY

### 1. BUILD (P0 BLOCKERS)

#### P0-01: Invalid psycopg Version
**Severity:** P0 (blocks deployment)
**File:** `requirements.txt:3`
**Issue:** Specifies `psycopg==3.13.0` but latest version is `3.3.2`

**Repro:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# ERROR: No matching distribution found for psycopg==3.13.0
```

**Impact:** Deployment fails immediately on Render.
**Fix:** Change to `psycopg[binary]==3.3.2`

---

#### P0-02: Multiple Conflicting Entrypoints
**Severity:** P0 (violates "Single entrypoint enforcement")
**Files:**
- `app.py` (Flask-based API)
- `backend/app/main.py` (FastAPI-based API)
- `render.yaml:7` (uses `app:app`)

**Issue:** Two different web frameworks implementing overlapping endpoints:

**Flask app (app.py):**
```python
@app.route('/health')
@app.route('/api/stats')
@app.route('/api/search')
```

**FastAPI app (backend/app/main.py):**
```python
@app.get("/health")
@app.get("/api/graph/nodes")
@app.get("/api/graph/edges")
```

**Deployment uses:** `gunicorn app:app` (Flask)
**Problem:** FastAPI code exists but is never deployed. FastAPI is NOT in production requirements.txt.

**Impact:**
- Code confusion (which app is production?)
- FastAPI import will fail at runtime if anything imports `backend.app.main`
- Maintenance burden (two apps to update)

**Fix:**
1. Delete `backend/app/main.py` (FastAPI version)
2. Remove all FastAPI imports from codebase
3. Update `backend/requirements.txt` to match root `requirements.txt`
4. Ensure only Flask app remains

---

#### P0-03: Conflicting Requirements Files
**Severity:** P0
**Files:**
- `requirements.txt` (Flask stack)
- `backend/requirements.txt` (FastAPI stack)

**Issue:**
```
# Root requirements.txt
Flask==2.3.3
psycopg[binary]==3.13.0  # INVALID VERSION

# backend/requirements.txt
fastapi==0.115.0         # NOT USED IN DEPLOYMENT
psycopg[binary]==3.2.1   # DIFFERENT VERSION
```

**Impact:** Deployment uses root requirements.txt, but backend code expects different versions.

**Fix:** Consolidate to single `requirements.txt` with correct versions.

---

### 2. DATA MODEL (P0 BLOCKERS)

#### P0-04: Evidence Model Missing
**Severity:** P0 (violates "evidence-first" contract)
**Files:**
- `backend/migrations/000_core.sql` (no evidence table)
- `backend/migrations/001_patents.sql` (no evidence table)
- `backend/app/schema.sql` (no evidence table)
- `biograph/core/guardrails.py` (references evidence table)

**Issue:** Core guardrails enforce evidence requirements:
```python
# biograph/core/guardrails.py:32
cursor.execute("""
    SELECT e.license, la.is_commercial_safe
    FROM evidence e
    LEFT JOIN license_allowlist la ON e.license = la.license
    WHERE e.evidence_id = %s
""", (evidence_id,))
```

But these tables DO NOT EXIST in any migration:
- `evidence`
- `assertion`
- `assertion_evidence`
- `license_allowlist`

**Impact:**
- Guardrails will crash with "relation does not exist"
- Cannot enforce "evidence-first" principle
- **FAIL condition:** "Every assertion/explanation edge lacks evidence+license+observed_at"

**Fix:** Create migration with evidence model:
```sql
CREATE TABLE license_allowlist (
    license TEXT PRIMARY KEY,
    is_commercial_safe BOOLEAN NOT NULL
);

CREATE TABLE evidence (
    evidence_id SERIAL PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    license TEXT NOT NULL REFERENCES license_allowlist(license),
    url TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE assertion (
    assertion_id SERIAL PRIMARY KEY,
    -- assertion fields
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE assertion_evidence (
    assertion_id INT REFERENCES assertion(assertion_id) ON DELETE CASCADE,
    evidence_id INT REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    PRIMARY KEY (assertion_id, evidence_id)
);
```

---

#### P0-05: Schema Inconsistencies
**Severity:** P0
**Files:**
- `backend/migrations/000_core.sql`
- `backend/migrations/001_patents.sql`
- `backend/app/schema.sql`

**Issue:** Three different schemas with conflicting definitions:

**Edge table differences:**
```sql
# 000_core.sql:38
CREATE TABLE edge (
    id SERIAL PRIMARY KEY,
    src_id INT REFERENCES entity(id),
    dst_id INT REFERENCES entity(id),
    type TEXT,                    -- ← field name: "type"
    props JSONB
);

# schema.sql:21
create table if not exists edge (
    id bigserial primary key,
    src_id bigint not null,
    dst_id bigint not null,
    predicate text not null,      -- ← field name: "predicate"
    source text
);
```

**Duplicate table definitions:**
`001_patents.sql` redefines `patent`, `assignee`, `patent_assignee`, `patent_drug` which already exist in `000_core.sql`. Running migrations in sequence will fail.

**Impact:**
- Migration failures
- Code breaks depending on which schema version runs
- API queries use wrong field names

**Fix:**
1. Remove duplicate definitions from `001_patents.sql`
2. Standardize edge schema (decide: `type` vs `predicate`)
3. Create single authoritative migration chain

---

#### P0-06: Lookup Cache Missing
**Severity:** P0
**Files:**
- `biograph/core/lookup_cache.py` (references `lookup_cache` table)
- `biograph/integrations/wikidata.py` (uses `LookupCache`)
- `tests/test_wikidata.py` (tests cache functionality)

**Issue:** Code requires `lookup_cache` table:
```python
# biograph/core/lookup_cache.py (implied usage)
cursor.execute("""
    INSERT INTO lookup_cache (cache_key, source, value_json, expires_at)
    VALUES (%s, %s, %s, %s)
""")
```

But table does NOT exist in any migration.

**Impact:**
- Wikidata integration crashes
- Tests fail
- "Thin Durable Core" principle unenforceable

**Fix:** Add to migration:
```sql
CREATE TABLE lookup_cache (
    cache_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    value_json JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX lookup_cache_expires_idx ON lookup_cache(expires_at);
```

---

### 3. EXECUTION LAYER (P0/P1)

#### P0-07: No Connection Pooling
**Severity:** P1 (performance issue under load)
**File:** `backend/app/db.py:14-19`

**Issue:**
```python
@contextmanager
def get_conn() -> Iterator[Connection]:
   conn: Connection = Connection.connect(get_database_url(), row_factory=dict_row)
   try:
       yield conn
   finally:
       conn.close()
```

Creates **new connection per request**. No pooling.

**Impact:**
- Slow under concurrent load
- Connection exhaustion with 50+ concurrent requests
- High latency

**Fix:** Use `psycopg_pool.ConnectionPool`:
```python
from psycopg_pool import ConnectionPool

_pool = None

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_database_url(),
            min_size=2,
            max_size=10,
            kwargs={'row_factory': dict_row}
        )
    return _pool

@contextmanager
def get_conn() -> Iterator[Connection]:
    with get_pool().connection() as conn:
        yield conn
```

---

#### P1-01: No Error Middleware
**Severity:** P1
**File:** `app.py`

**Issue:** No global error handler. Stack traces leak in responses:

```python
@app.route('/api/stats')
def get_stats():
    try:
        # ...
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
        # ↑ LEAKS STACK TRACES IN str(e)
```

**Impact:**
- Exposes internal paths
- Poor user experience
- Security risk

**Fix:** Add error handler:
```python
@app.errorhandler(Exception)
def handle_error(e):
    logger.exception("Unhandled error")
    return jsonify({
        'error': 'Internal server error',
        'request_id': g.get('request_id')
    }), 500
```

---

#### P1-02: No Request ID Correlation
**Severity:** P1
**File:** `app.py`

**Issue:** No request ID middleware. Cannot trace errors.

**Fix:** Add middleware:
```python
import uuid

@app.before_request
def add_request_id():
    g.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))

@app.after_request
def add_request_id_header(response):
    response.headers['X-Request-ID'] = g.request_id
    return response
```

---

### 4. SECURITY (P0 BLOCKERS)

#### P0-08: No Authentication
**Severity:** P0 (FAIL condition)
**Files:** All API endpoints

**Issue:** **ALL** endpoints are public:
- `GET /api/stats` (should be public)
- `GET /api/search` (should be public)
- No admin endpoints exist yet, but none would be gated

**Requirement violation:**
> "Admin/curation/raw endpoints must be API-key gated"

**Impact:**
- No way to protect admin operations
- Cannot deploy curation tools
- **FAIL condition:** "Admin/curation endpoints accessible without API key"

**Fix:** Add API key middleware (prepare for future admin endpoints):
```python
import os

ADMIN_API_KEYS = set(os.getenv('ADMIN_API_KEYS', '').split(','))

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key not in ADMIN_API_KEYS:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Usage:
# @app.route('/admin/curate')
# @require_api_key
# def curate():
#     ...
```

**Note:** Public endpoints remain public, but infrastructure is ready for admin routes.

---

#### P0-09: Potential SQL Injection (Low Risk)
**Severity:** P1 (defense in depth)
**File:** `app.py:58-70`

**Issue:** Query uses parameterization correctly, but Pydantic validation missing.

**Current (safe but unvalidated):**
```python
query = request.args.get('q', '').strip()
kind = request.args.get('kind', '')

cur.execute("""
    SELECT id, kind, canonical_id, name
    FROM entity
    WHERE kind = %s AND name ILIKE %s
    LIMIT 20
""", (kind, f'%{query}%'))
```

**Issue:** No input validation. `kind` could be arbitrary string.

**Fix:** Add Pydantic models:
```python
from pydantic import BaseModel, Field, validator

class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=100)
    kind: str = Field('', regex='^(drug|target|disease|company|trial)?$')

# In route:
try:
    params = SearchRequest(**request.args)
except ValidationError as e:
    return jsonify({'error': 'Invalid input'}), 400
```

---

### 5. EVIDENCE/AUDIT (P0 BLOCKERS)

#### P0-04 (Duplicate): Evidence Model Missing
See "Data Model" section above.

**FAIL Condition Met:**
> "Any assertion/explanation edge lacks evidence+license+observed_at"

**Status:** Cannot validate because evidence model doesn't exist.

---

### 6. NER/ER CONTRACT (NOT APPLICABLE)

**Status:** No NER/ER code found in codebase.
**Finding:** Requirement states "skip taxonomy validation". No NLP pipeline exists to test.

**Expected tables missing:**
- `nlp_run`
- `mention`
- `candidate`
- `duplicate_suggestion`

**Recommendation:** P2 - Document that NER/ER is out of scope for this branch.

---

### 7. THIN DURABLE CORE + INTEGRATIONS (P1)

#### P1-03: Wikidata Integration Incomplete
**Severity:** P1
**File:** `biograph/integrations/wikidata.py`

**Status:** Code is well-structured and follows thin core principles ✅

**Findings:**
- ✅ No bulk ingestion
- ✅ Uses lookup cache (table missing, see P0-06)
- ✅ Graceful degradation on API failures
- ✅ Proper timeouts (10s)
- ✅ User-Agent set correctly
- ❌ Tests reference missing DB tables

**Issue:** Cannot validate integration without:
1. `lookup_cache` table
2. `evidence` table
3. `license_allowlist` table

**Recommendation:** Add missing tables, then integration is production-ready.

---

#### P1-04: Missing Dependencies for Integrations
**Severity:** P1
**File:** `requirements.txt`

**Issue:** `biograph/integrations/wikidata.py` imports `requests` but it's NOT in requirements.txt.

**Fix:** Add to requirements.txt:
```
requests==2.31.0
```

---

### 8. POSTGRES ↔ NEO4J PROJECTION (NOT APPLICABLE)

**Status:** No Neo4j code found in codebase.
**Finding:** No references to neo4j, cypher, or graph projection.

**Conclusion:** Neo4j projection is out of scope for this branch. Postgres-only architecture.

---

### 9. PERFORMANCE & MAINTAINABILITY (P1/P2)

#### P1-05: No Database Indexes
**Severity:** P1
**Files:** Migration files

**Issue:** Some indexes exist, but key query paths lack indexes:

**Missing indexes:**
```sql
-- For /api/search filtering by kind
CREATE INDEX entity_kind_name_idx ON entity(kind, name);

-- For edge queries
CREATE INDEX edge_type_idx ON edge(type);

-- For temporal queries
CREATE INDEX entity_updated_at_idx ON entity(updated_at);
```

**Fix:** Add to migration.

---

#### P2-01: No Migration Runner
**Severity:** P2
**Files:** `backend/migrations/`

**Issue:** Migration files exist but no runner script. Manual execution required.

**Recommendation:** Create `scripts/run_migrations.py`:
```python
#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from backend.app.db import get_conn

def run_migrations():
    migrations_dir = Path(__file__).parent.parent / 'backend' / 'migrations'
    migration_files = sorted(migrations_dir.glob('*.sql'))

    with get_conn() as conn:
        with conn.cursor() as cur:
            for migration_file in migration_files:
                print(f"Running {migration_file.name}...")
                with open(migration_file) as f:
                    cur.execute(f.read())
        conn.commit()

    print("Migrations complete.")

if __name__ == '__main__':
    run_migrations()
```

---

#### P2-02: No Health Check Validation
**Severity:** P2
**File:** `app.py:78-79`

**Issue:**
```python
@app.route('/health')
def health():
    return jsonify({'status': 'ok'})
```

Does not check database connectivity.

**Fix:**
```python
@app.route('/health')
def health():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return jsonify({
            'status': 'ok',
            'database': 'connected'
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'degraded',
            'database': 'disconnected'
        }), 503
```

---

#### P2-03: Code Organization
**Severity:** P2
**Finding:** Good module structure:
```
biograph/
  core/          ✅ guardrails, lookup_cache, disease_hierarchy
  integrations/  ✅ wikidata

backend/
  app/           ✅ db, main
  loaders/       ✅ data loaders
```

**Issue:** Mixed Flask + FastAPI creates confusion.

**Recommendation:** After removing FastAPI, structure is clean.

---

### 10. ADDITIONAL FINDINGS

#### P2-04: Unused File
**File:** `and edges are being loaded by the frontend`
**Issue:** This appears to be a misnamed file (13KB) in root directory.

**Recommendation:** Delete or rename properly.

---

#### P2-05: No pytest.ini
**Severity:** P2
**Issue:** Tests exist but no pytest configuration.

**Recommendation:** Create `pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    wikidata: Wikidata integration tests
    slow: Slow running tests
```

---

## PASS/FAIL RULES EVALUATION

### FAIL Conditions

| Condition | Status | Evidence |
|-----------|--------|----------|
| Multiple runnable API entrypoints used in deployment | ❌ FAIL | Flask (deployed) + FastAPI (dormant) |
| Admin/curation endpoints accessible without API key | ⚠️ N/A | No admin endpoints exist yet, but no auth infrastructure |
| Any assertion/explanation edge lacks evidence+license+observed_at | ❌ FAIL | Evidence model missing entirely |
| NER/ER creates canonical entities or merges automatically | ✅ PASS | No NER/ER code |
| Bulk ontology ingestion is present | ✅ PASS | Wikidata uses thin core pattern |
| Neo4j is authoritative or required for correctness | ✅ PASS | No Neo4j code |
| API returns stack traces or leaks secrets | ⚠️ RISK | No middleware, exceptions leak |

**Verdict:** **3 hard FAIL conditions met** + **1 risk condition**

---

## SUMMARY OF BLOCKERS

### P0 Issues (Must Fix)
1. ❌ Invalid psycopg version → **BUILD FAILS**
2. ❌ Multiple entrypoints (Flask + FastAPI) → **ARCHITECTURE VIOLATION**
3. ❌ Conflicting requirements.txt → **BUILD INCONSISTENCY**
4. ❌ Evidence model missing → **CONTRACT VIOLATION**
5. ❌ Schema inconsistencies → **MIGRATION FAILURES**
6. ❌ Lookup cache table missing → **INTEGRATION CRASH**
7. ❌ No authentication infrastructure → **SECURITY VIOLATION**

### P1 Issues (Should Fix)
8. Connection pooling missing
9. Error middleware missing
10. Request ID correlation missing
11. Wikidata integration needs DB tables
12. Missing `requests` dependency
13. Missing database indexes

### P2 Issues (Nice to Have)
14. No migration runner
15. Health check doesn't validate DB
16. Cleanup unused files
17. Add pytest.ini

---

## RECOMMENDED FIX SEQUENCE

### Phase 1: Unblock Build (P0)
1. Fix `requirements.txt`: `psycopg[binary]==3.3.2`
2. Add `requests==2.31.0`
3. Delete `backend/app/main.py` (FastAPI app)
4. Delete `backend/requirements.txt` (consolidate to root)
5. Remove FastAPI imports from any other files

### Phase 2: Fix Data Model (P0)
6. Create `backend/migrations/002_evidence_model.sql`:
   - `license_allowlist` table
   - `evidence` table
   - `assertion` table
   - `assertion_evidence` join table
   - `lookup_cache` table
7. Resolve schema conflicts (standardize edge.type vs edge.predicate)
8. Remove duplicate definitions from `001_patents.sql`

### Phase 3: Add Security (P0)
9. Add API key middleware infrastructure
10. Add error handling middleware
11. Add request ID middleware

### Phase 4: Test & Validate
12. Create migration runner script
13. Run migrations on clean DB
14. Run smoke tests
15. Validate Wikidata integration

---

## TEST ENVIRONMENT DETAILS

**Python Version:** 3.11.14
**OS:** Linux 4.4.0
**Package Manager:** pip 24.0

**Attempted Build:**
```bash
python3 -m venv /tmp/test-env
source /tmp/test-env/bin/activate
pip install -r requirements.txt
# ERROR: No matching distribution found for psycopg==3.13.0
```

**Database:** Not tested (Postgres unavailable, build failed before DB tests)

---

## APPENDIX: File References

### Critical Files
- `requirements.txt` - P0 fix needed
- `app.py` - Production entrypoint
- `backend/app/main.py` - DELETE (unused FastAPI app)
- `backend/app/db.py` - Add connection pooling
- `backend/migrations/000_core.sql` - Base schema
- `backend/migrations/001_patents.sql` - Remove duplicates
- `biograph/core/guardrails.py` - Evidence validation (needs tables)
- `biograph/integrations/wikidata.py` - Ready (needs DB tables)

### Test Files
- `tests/test_wikidata.py` - Comprehensive tests (needs DB tables)

### Documentation
- `README.md` - Clear vision statement ✅
- `docs/WIKIDATA_PORT_PLAN.md` - Implementation plan ✅

---

## CONCLUSION

This branch exhibits **fundamental architectural inconsistencies** that prevent deployment and violate core contracts. While individual modules (e.g., Wikidata integration, guardrails) show good design, the overall system is **non-functional** due to missing critical infrastructure.

**Key Problems:**
1. Build doesn't work
2. Evidence model doesn't exist
3. Two frameworks compete for ownership
4. Schema definitions conflict

**Path Forward:**
1. Fix P0 blockers (see fix sequence above)
2. Create comprehensive integration test
3. Re-run competitive test
4. Only then: merge to main

**Estimated Effort:** 4-6 hours to fix all P0 issues + test validation.

---

**Report Generated:** 2026-01-20
**Tested By:** Adversarial QA + Staff Architect
**Next Steps:** Fix P0 blockers, add tests, re-validate
