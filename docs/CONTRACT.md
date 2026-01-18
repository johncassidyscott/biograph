# BioGraph MVP v8.2 — Contract Invariants

**Last Updated**: 2026-01-18
**Spec**: `docs/spec/BioGraph_Master_Spec_v8.2_MVP.txt`

---

## What Are Contract Invariants?

Contract invariants are **non-negotiable rules** that the system MUST enforce at all times. These are not "best practices" or "guidelines" — they are **hard requirements** from the spec that, if violated, compromise the commercial viability and trustworthiness of BioGraph.

**Purpose**:
- Prevent spec drift
- Ensure investor-grade quality
- Maintain audit trail integrity
- Protect commercial licensing posture

**Enforcement**:
- Database triggers (where possible)
- Application-level guardrails (in code)
- Contract tests (in CI)

If any contract test fails, **the build must fail**. No exceptions.

---

## The 6 Critical Contracts

### Contract A: Evidence License Required (Section 14)

**Rule**: Every evidence record MUST have a commercial-safe license from the allowlist.

**Why**: License drift kills commercial viability. We cannot redistribute or build on data with unknown or incompatible licenses.

**Enforcement**:
- DB constraint: `evidence.license` is `NOT NULL`
- DB trigger: `validate_evidence_license()` checks allowlist on INSERT/UPDATE
- Application guardrail: `biograph.core.guardrails.require_license()`

**Allowlist** (prepopulated in `license_allowlist`):
- `PUBLIC_DOMAIN` — U.S. Government / SEC EDGAR
- `CC0` — Creative Commons Zero (Public Domain)
- `CC-BY-4.0` — Creative Commons Attribution 4.0
- `CC-BY-SA-3.0` — Creative Commons Attribution-ShareAlike 3.0 (ChEMBL)

**Contract Test**:
```python
def test_cannot_insert_evidence_with_unknown_license(db_conn):
    """Evidence with unknown license should fail (trigger enforced)."""
    with pytest.raises(psycopg.errors.RaiseException):
        cursor.execute("""
            INSERT INTO evidence (source_system, source_record_id, observed_at, license, uri)
            VALUES ('test', 'test_002', NOW(), 'UNKNOWN_LICENSE', 'http://test.com')
        """)
```

**Impact if violated**: Legal risk, cannot commercialize.

---

### Contract B: Assertion Requires Evidence (Section 8)

**Rule**: An assertion is INVALID unless it has ≥1 `assertion_evidence` record.

**Why**: Evidence-first is the core architectural principle. No relationship can exist without provenance. This is what makes BioGraph auditable.

**Enforcement**:
- Application guardrail: `biograph.core.guardrails.require_assertion_has_evidence()`
- Call before commit in all assertion creation paths
- Contract test validates application logic

**Why not a DB constraint**: Foreign key + CHECK constraint would prevent transactional creation pattern (create assertion, then link evidence). We enforce at application level instead.

**Contract Test**:
```python
def test_assertion_without_evidence_is_invalid(db_conn):
    """Assertion created without evidence should fail validation."""
    # Create assertion
    cursor.execute("INSERT INTO assertion ... RETURNING assertion_id")
    assertion_id = cursor.fetchone()[0]

    # Guardrail should fail (no evidence linked)
    with pytest.raises(ValueError, match="has no evidence"):
        require_assertion_has_evidence(cursor, assertion_id)
```

**Impact if violated**: Loss of audit trail, cannot answer "why do we believe this?"

---

### Contract C: News Cannot Create Assertion (Section 21)

**Rule**: Assertions may ONLY be created from:
1. SEC filings and EDGAR exhibits
2. Open Targets
3. ChEMBL

News metadata may NEVER be the sole source of an assertion. News can only reinforce or contextualize existing assertions.

**Why**: News is metadata-only in MVP (Section 20). News alone is not authoritative enough to create canonical relationships. It's correlation signal, not causal evidence.

**Enforcement**:
- Application guardrail: `biograph.core.guardrails.forbid_news_only_assertions()`
- Checks that assertion has at least one non-news evidence source
- Contract test validates logic

**Contract Test**:
```python
def test_assertion_with_only_news_evidence_is_forbidden(db_conn):
    """Assertion with only news evidence should fail."""
    # Create assertion with only news_metadata evidence
    # ...

    # Guardrail should fail
    with pytest.raises(ValueError, match="cannot have only news_metadata evidence"):
        forbid_news_only_assertions(cursor, assertion_id)
```

**Impact if violated**: Quality degradation, speculative joins creep in.

---

### Contract D: API Reads Explanations Only (Section 4)

**Rule**: The `explanation` table is the ONLY query surface for product/UI.

Public API endpoints must query `explanation` table, NOT raw `assertion` table.

**Why**: Prevents accidental free graph traversal. The spec explicitly forbids this (Section 3). We enforce a fixed chain: Issuer → DrugProgram → Target → Disease.

Raw `assertion` queries are admin/debug-only.

**Enforcement**:
- API layer architecture: All endpoints in `biograph.api.query` use `explanation` table
- Contract test mocks API calls and validates query patterns

**Contract Test**:
```python
def test_api_endpoint_queries_explanation_table():
    """API endpoints should query explanation table, not assertions."""
    tracker = QueryTracker()  # Mock cursor
    get_explanations_for_issuer(tracker, 'ISS_TEST', date.today())

    # Verify queries
    assert any('from explanation' in q for q in tracker.queries)
    assert not any('from assertion' in q for q in tracker.queries)
```

**Impact if violated**: Scope creep, graph soup queries, performance issues.

---

### Contract E: No Canonical Creation from NER (Section 15)

**Rule**: NER pipeline must create `candidate` records, NOT canonical entities.

ML suggests ONLY. Humans decide.

**Forbidden**: NER creating `drug_program`, `target`, `disease`, or `assertion` directly.

**Allowed**: NER creating `nlp_run`, `mention`, `candidate`, `evidence`.

**Why**: Section 15 explicitly states "No automatic canonical entity creation; everything goes to curation queue." This prevents pollution of the canonical registry with low-confidence NER outputs.

**Enforcement**:
- Application architecture: NER runner only writes to candidate/mention/evidence tables
- Contract test runs NER and validates no canonical entities created

**Contract Test**:
```python
def test_ner_pipeline_creates_only_candidates(db_conn):
    """NER pipeline should create candidates, not canonical entities."""
    # Count entities before NER
    drug_count_before = cursor.execute("SELECT COUNT(*) FROM drug_program").fetchone()[0]

    # Run NER
    run_ner_on_text(cursor, 'filing', filing_id, text, issuer_id)

    # Count entities after NER
    drug_count_after = cursor.execute("SELECT COUNT(*) FROM drug_program").fetchone()[0]

    # Verify NO canonical entities created
    assert drug_count_after == drug_count_before
```

**Impact if violated**: Registry pollution, loss of human oversight, quality degradation.

---

### Contract F: ER Within Issuer Only (Section 15)

**Rule**: ER (Dedupe) must NEVER compare records across issuers.

All `duplicate_suggestion` rows must:
- Have valid `issuer_id` FK
- Compare only entities within that issuer

**Why**: Cross-issuer program deduplication is explicitly OUT OF SCOPE for MVP (Section 7). It opens entity resolution hell. Within-issuer dedupe creates aliases only, no merges.

**Enforcement**:
- DB constraint: `duplicate_suggestion.issuer_id` is FK to `issuer`
- Application logic: ER runner filters by `issuer_id`
- Contract test validates query filters

**Contract Test**:
```python
def test_er_never_compares_across_issuers(db_conn):
    """ER should only compare programs within same issuer."""
    # Create two issuers with similar programs
    # ...

    # Run ER for issuer 1
    find_duplicates_for_issuer(cursor, 'ISS_TEST006')

    # Check that NO duplicate_suggestion crosses issuer boundary
    cursor.execute("""
        SELECT COUNT(*) FROM duplicate_suggestion
        WHERE issuer_id = 'ISS_TEST006'
          AND (entity_id_1 LIKE 'CIK:0000000007:%' OR entity_id_2 LIKE 'CIK:0000000007:%')
    """)

    assert cursor.fetchone()[0] == 0, "ER must not compare across issuers"
```

**Impact if violated**: Scope creep, incorrect deduplication across companies.

---

## How to Run Contract Tests

### Locally

```bash
# Run contract tests only
pytest -v -m contract tests/contract/

# Run all tests
pytest -v tests/
```

### In CI

Contract tests run automatically on every push/PR via GitHub Actions (`.github/workflows/ci.yml`).

**CI Jobs**:
1. `contract-tests` — Runs contract tests, fails build if any fail
2. `full-tests` — Runs all tests
3. `migration-validation` — Validates migrations on fresh Postgres

**See results**: Check GitHub Actions tab in repository.

---

## Guardrails API

Application-level enforcement functions in `biograph/core/guardrails.py`:

```python
from biograph.core.guardrails import (
    require_license,
    require_assertion_has_evidence,
    forbid_news_only_assertions,
    validate_assertion_before_commit,
)

# Example: Creating an assertion with evidence
with conn.cursor() as cur:
    # Create evidence
    cur.execute("INSERT INTO evidence ... RETURNING evidence_id")
    evidence_id = cur.fetchone()[0]

    # Create assertion
    cur.execute("INSERT INTO assertion ... RETURNING assertion_id")
    assertion_id = cur.fetchone()[0]

    # Link evidence
    cur.execute("INSERT INTO assertion_evidence (assertion_id, evidence_id) VALUES (%s, %s)",
                (assertion_id, evidence_id))

    # Validate before commit (REQUIRED)
    validate_assertion_before_commit(cur, assertion_id)

    conn.commit()
```

**Rule**: Every write path that creates/modifies assertions MUST call `validate_assertion_before_commit()` before commit.

---

## Adding New Contracts

If the spec introduces new non-negotiable rules:

1. **Add to this document** with:
   - Rule statement
   - Why it matters
   - Enforcement strategy
   - Impact if violated

2. **Implement enforcement**:
   - DB trigger (if possible)
   - Application guardrail function
   - Contract test

3. **Update CI** to run new test

4. **Document in README** and spec

**Never** add contracts that are not in the spec. Contracts come from spec only.

---

## FAQ

**Q: What's the difference between a contract test and a regular test?**

A: Contract tests enforce spec invariants. They test that the system **cannot** violate the spec, even if code tries to. Regular tests verify that features work correctly.

**Q: Can contract tests be skipped or xfailed?**

A: **No**. Contract tests must always pass. If a contract test fails, the spec is being violated. Fix the code, not the test.

**Q: What if a contract prevents a feature I need?**

A: Contracts come from the spec. If you need to violate a contract, you need to:
1. Propose a spec change
2. Get it approved
3. Update contract tests
4. Implement

**Q: Can I disable a contract in development?**

A: **No**. Contracts are enforced in all environments (dev, test, CI, prod). This is by design.

---

## Related Documents

- **Spec**: `docs/spec/BioGraph_Master_Spec_v8.2_MVP.txt`
- **Schema**: `db/migrations/001_complete_schema.sql`
- **Guardrails**: `biograph/core/guardrails.py`
- **Tests**: `tests/contract/test_contracts.py`
- **CI**: `.github/workflows/ci.yml`

---

## Summary

| Contract | Enforcement | Test |
|----------|-------------|------|
| A: Evidence license required | DB trigger + guardrail | ✅ Automated |
| B: Assertion requires evidence | Application guardrail | ✅ Automated |
| C: News cannot create assertion | Application guardrail | ✅ Automated |
| D: API reads explanations only | Architecture + test | ✅ Automated |
| E: No canonical from NER | Architecture + test | ✅ Automated |
| F: ER within issuer only | DB FK + query filter | ✅ Automated |

**Status**: All contracts enforced and tested.

**CI**: Runs on every push/PR.

**Failures**: Block merge.

This is **non-negotiable**.
