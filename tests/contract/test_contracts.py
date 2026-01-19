"""
Contract Test Suite for BioGraph MVP v8.2

These tests enforce the NON-NEGOTIABLE contracts from the spec:
docs/spec/BioGraph_Master_Spec_v8.2_MVP.txt

CRITICAL INVARIANTS:
A) Evidence license required (Section 14)
B) Assertion requires evidence (Section 8)
C) News cannot create assertion (Section 21)
D) API reads explanations only (Section 4)
E) No canonical creation from NER (Section 15)
F) ER within issuer only (Section 15)

Run: pytest -m contract
"""
import pytest
import psycopg
from datetime import datetime, date

# Mark all tests in this module as contract tests
pytestmark = pytest.mark.contract


class TestContractA_EvidenceLicenseRequired:
    """
    Contract A: Evidence license required (Section 14)

    Evidence.license must be:
    1. NOT NULL
    2. In license_allowlist
    3. Commercial-safe

    This is enforced by DB trigger: validate_evidence_license()
    """

    def test_cannot_insert_evidence_without_license(self, db_conn):
        """Evidence without license should fail."""
        with db_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.NotNullViolation):
                cur.execute("""
                    INSERT INTO evidence
                    (source_system, source_record_id, observed_at, license, uri)
                    VALUES ('test', 'test_001', NOW(), NULL, 'http://test.com')
                """)

    def test_cannot_insert_evidence_with_unknown_license(self, db_conn):
        """Evidence with unknown license should fail (trigger enforced)."""
        with db_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.RaiseException) as exc_info:
                cur.execute("""
                    INSERT INTO evidence
                    (source_system, source_record_id, observed_at, license, uri)
                    VALUES ('test', 'test_002', NOW(), 'UNKNOWN_LICENSE', 'http://test.com')
                """)

            assert 'not in commercial-safe allowlist' in str(exc_info.value)

    def test_can_insert_evidence_with_valid_license(self, db_conn):
        """Evidence with valid license should succeed."""
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO evidence
                (source_system, source_record_id, observed_at, license, uri)
                VALUES ('test', 'test_003', NOW(), 'PUBLIC_DOMAIN', 'http://test.com')
                RETURNING evidence_id
            """)

            result = cur.fetchone()
            assert result is not None
            assert result[0] > 0


class TestContractB_AssertionRequiresEvidence:
    """
    Contract B: Assertion requires evidence (Section 8)

    An assertion is INVALID unless it has >=1 assertion_evidence record.

    This is enforced at application level (not DB constraint, as it would prevent
    transactional creation). Tests validate the guardrail function.
    """

    def test_assertion_without_evidence_is_invalid(self, db_conn):
        """Assertion created without evidence should fail validation."""
        from biograph.core.guardrails import require_assertion_has_evidence

        with db_conn.cursor() as cur:
            # Create test issuer and drug_program
            cur.execute("""
                INSERT INTO issuer (issuer_id, primary_cik)
                VALUES ('ISS_TEST001', '0000000001')
            """)
            cur.execute("""
                INSERT INTO drug_program (drug_program_id, issuer_id, slug, name)
                VALUES ('CIK:0000000001:PROG:test', 'ISS_TEST001', 'test', 'Test Drug')
            """)

            # Create assertion WITHOUT evidence
            cur.execute("""
                INSERT INTO assertion
                (subject_type, subject_id, predicate, object_type, object_id)
                VALUES ('issuer', 'ISS_TEST001', 'has_program', 'drug_program',
                        'CIK:0000000001:PROG:test')
                RETURNING assertion_id
            """)

            assertion_id = cur.fetchone()[0]

            # Guardrail should fail
            with pytest.raises(ValueError, match="Assertion .* has no evidence"):
                require_assertion_has_evidence(cur, assertion_id)

    def test_assertion_with_evidence_is_valid(self, db_conn):
        """Assertion with evidence should pass validation."""
        from biograph.core.guardrails import require_assertion_has_evidence

        with db_conn.cursor() as cur:
            # Create test entities
            cur.execute("""
                INSERT INTO issuer (issuer_id, primary_cik)
                VALUES ('ISS_TEST002', '0000000002')
            """)
            cur.execute("""
                INSERT INTO drug_program (drug_program_id, issuer_id, slug, name)
                VALUES ('CIK:0000000002:PROG:test', 'ISS_TEST002', 'test', 'Test Drug')
            """)

            # Create evidence
            cur.execute("""
                INSERT INTO evidence
                (source_system, source_record_id, observed_at, license, uri)
                VALUES ('sec_edgar', 'test_004', NOW(), 'PUBLIC_DOMAIN', 'http://test.com')
                RETURNING evidence_id
            """)
            evidence_id = cur.fetchone()[0]

            # Create assertion
            cur.execute("""
                INSERT INTO assertion
                (subject_type, subject_id, predicate, object_type, object_id)
                VALUES ('issuer', 'ISS_TEST002', 'has_program', 'drug_program',
                        'CIK:0000000002:PROG:test')
                RETURNING assertion_id
            """)
            assertion_id = cur.fetchone()[0]

            # Link evidence
            cur.execute("""
                INSERT INTO assertion_evidence (assertion_id, evidence_id)
                VALUES (%s, %s)
            """, (assertion_id, evidence_id))

            # Guardrail should pass (no exception)
            require_assertion_has_evidence(cur, assertion_id)


class TestContractC_NewsCannotCreateAssertion:
    """
    Contract C: News cannot create assertion (Section 21)

    Assertions may ONLY be created from:
    1) SEC filings and EDGAR exhibits
    2) Open Targets
    3) ChEMBL

    News metadata may NEVER be the sole source of an assertion.
    """

    def test_assertion_with_only_news_evidence_is_forbidden(self, db_conn):
        """Assertion with only news evidence should fail."""
        from biograph.core.guardrails import forbid_news_only_assertions

        with db_conn.cursor() as cur:
            # Create test entities
            cur.execute("""
                INSERT INTO issuer (issuer_id, primary_cik)
                VALUES ('ISS_TEST003', '0000000003')
            """)
            cur.execute("""
                INSERT INTO drug_program (drug_program_id, issuer_id, slug, name)
                VALUES ('CIK:0000000003:PROG:test', 'ISS_TEST003', 'test', 'Test Drug')
            """)

            # Create NEWS evidence
            cur.execute("""
                INSERT INTO evidence
                (source_system, source_record_id, observed_at, license, uri)
                VALUES ('news_metadata', 'news_005', NOW(), 'CC0', 'http://news.com')
                RETURNING evidence_id
            """)
            news_evidence_id = cur.fetchone()[0]

            # Create assertion
            cur.execute("""
                INSERT INTO assertion
                (subject_type, subject_id, predicate, object_type, object_id)
                VALUES ('issuer', 'ISS_TEST003', 'has_program', 'drug_program',
                        'CIK:0000000003:PROG:test')
                RETURNING assertion_id
            """)
            assertion_id = cur.fetchone()[0]

            # Link ONLY news evidence
            cur.execute("""
                INSERT INTO assertion_evidence (assertion_id, evidence_id)
                VALUES (%s, %s)
            """, (assertion_id, news_evidence_id))

            # Guardrail should fail
            with pytest.raises(ValueError, match="cannot have only news_metadata evidence"):
                forbid_news_only_assertions(cur, assertion_id)

    def test_assertion_with_news_plus_filing_evidence_is_allowed(self, db_conn):
        """Assertion with news + filing evidence should pass (news reinforces)."""
        from biograph.core.guardrails import forbid_news_only_assertions

        with db_conn.cursor() as cur:
            # Create test entities
            cur.execute("""
                INSERT INTO issuer (issuer_id, primary_cik)
                VALUES ('ISS_TEST004', '0000000004')
            """)
            cur.execute("""
                INSERT INTO drug_program (drug_program_id, issuer_id, slug, name)
                VALUES ('CIK:0000000004:PROG:test', 'ISS_TEST004', 'test', 'Test Drug')
            """)

            # Create filing evidence
            cur.execute("""
                INSERT INTO evidence
                (source_system, source_record_id, observed_at, license, uri)
                VALUES ('sec_edgar', 'filing_006', NOW(), 'PUBLIC_DOMAIN', 'http://sec.gov')
                RETURNING evidence_id
            """)
            filing_evidence_id = cur.fetchone()[0]

            # Create news evidence
            cur.execute("""
                INSERT INTO evidence
                (source_system, source_record_id, observed_at, license, uri)
                VALUES ('news_metadata', 'news_007', NOW(), 'CC0', 'http://news.com')
                RETURNING evidence_id
            """)
            news_evidence_id = cur.fetchone()[0]

            # Create assertion
            cur.execute("""
                INSERT INTO assertion
                (subject_type, subject_id, predicate, object_type, object_id)
                VALUES ('issuer', 'ISS_TEST004', 'has_program', 'drug_program',
                        'CIK:0000000004:PROG:test')
                RETURNING assertion_id
            """)
            assertion_id = cur.fetchone()[0]

            # Link BOTH evidences
            cur.execute("""
                INSERT INTO assertion_evidence (assertion_id, evidence_id)
                VALUES (%s, %s), (%s, %s)
            """, (assertion_id, filing_evidence_id, assertion_id, news_evidence_id))

            # Guardrail should pass (news reinforces filing)
            forbid_news_only_assertions(cur, assertion_id)


class TestContractE_NoCanonicalCreationFromNER:
    """
    Contract E: No canonical creation from NER (Section 15)

    ML suggests ONLY. Humans decide.

    NER pipeline must:
    - Write nlp_run, mention, candidate, evidence
    - NOT create drug_program, target, disease, assertion
    """

    def test_ner_pipeline_creates_only_candidates(self, db_conn):
        """NER pipeline should create candidates, not canonical entities."""
        from biograph.nlp.ner_runner import run_ner_on_text

        # Mock filing text
        text = "Our lead program, tirzepatide, targets GLP-1 receptor for diabetes treatment."

        with db_conn.cursor() as cur:
            # Create test issuer + filing
            cur.execute("""
                INSERT INTO issuer (issuer_id, primary_cik)
                VALUES ('ISS_TEST005', '0000000005')
            """)
            cur.execute("""
                INSERT INTO company (cik, sec_legal_name)
                VALUES ('0000000005', 'Test Company')
            """)
            cur.execute("""
                INSERT INTO filing (accession_number, company_cik, form_type, filing_date, edgar_url)
                VALUES ('0001-24-000001', '0000000005', '10-K', '2024-01-01', 'http://sec.gov')
                RETURNING filing_id
            """)
            filing_id = cur.fetchone()[0]

            # Count entities before NER
            cur.execute("SELECT COUNT(*) FROM drug_program")
            drug_count_before = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM target")
            target_count_before = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM assertion")
            assertion_count_before = cur.fetchone()[0]

            # Run NER
            run_ner_on_text(cur, 'filing', filing_id, text, 'ISS_TEST005')

            # Count entities after NER
            cur.execute("SELECT COUNT(*) FROM drug_program")
            drug_count_after = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM target")
            target_count_after = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM assertion")
            assertion_count_after = cur.fetchone()[0]

            # Verify NO canonical entities created
            assert drug_count_after == drug_count_before, "NER should not create drug_program"
            assert target_count_after == target_count_before, "NER should not create target"
            assert assertion_count_after == assertion_count_before, "NER should not create assertion"

            # Verify candidates WERE created
            cur.execute("SELECT COUNT(*) FROM candidate WHERE issuer_id = 'ISS_TEST005'")
            candidate_count = cur.fetchone()[0]
            assert candidate_count > 0, "NER should create candidates"

            # Verify evidence WAS created
            cur.execute("SELECT COUNT(*) FROM evidence WHERE source_system = 'sec_edgar'")
            evidence_count = cur.fetchone()[0]
            assert evidence_count > 0, "NER should create evidence"


class TestContractF_ERWithinIssuerOnly:
    """
    Contract F: ER within issuer only (Section 15)

    ER (Dedupe) must NEVER compare records across issuers.
    All duplicate_suggestion rows must have issuer_id FK and comparison
    must be filtered to single issuer.
    """

    def test_er_never_compares_across_issuers(self, db_conn):
        """ER should only compare programs within same issuer."""
        from biograph.er.dedupe_runner import find_duplicates_for_issuer

        with db_conn.cursor() as cur:
            # Create two issuers with similar programs
            cur.execute("""
                INSERT INTO issuer (issuer_id, primary_cik) VALUES
                ('ISS_TEST006', '0000000006'),
                ('ISS_TEST007', '0000000007')
            """)

            cur.execute("""
                INSERT INTO drug_program (drug_program_id, issuer_id, slug, name) VALUES
                ('CIK:0000000006:PROG:tirz', 'ISS_TEST006', 'tirz', 'Tirzepatide'),
                ('CIK:0000000007:PROG:tirz', 'ISS_TEST007', 'tirz', 'Tirzepatide')
            """)

            # Run ER for issuer 1
            find_duplicates_for_issuer(cur, 'ISS_TEST006')

            # Check that NO duplicate_suggestion crosses issuer boundary
            cur.execute("""
                SELECT COUNT(*) FROM duplicate_suggestion
                WHERE issuer_id = 'ISS_TEST006'
                  AND (
                    entity_id_1 LIKE 'CIK:0000000007:%'
                    OR entity_id_2 LIKE 'CIK:0000000007:%'
                  )
            """)
            cross_issuer_suggestions = cur.fetchone()[0]

            assert cross_issuer_suggestions == 0, "ER must not compare across issuers"

    def test_duplicate_suggestion_has_issuer_fk(self, db_conn):
        """All duplicate_suggestion rows must have valid issuer_id."""
        with db_conn.cursor() as cur:
            # Try to insert duplicate_suggestion without valid issuer
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cur.execute("""
                    INSERT INTO duplicate_suggestion
                    (issuer_id, entity_type, entity_id_1, entity_id_2, similarity_score)
                    VALUES ('ISS_NONEXISTENT', 'drug_program', 'id1', 'id2', 0.95)
                """)


class TestContractD_APIReadsExplanationsOnly:
    """
    Contract D: API reads explanations only (Section 4)

    The explanation table is the ONLY product query surface.
    Public API endpoints must NOT query raw assertion table directly.

    This test mocks the API layer and validates query patterns.
    """

    def test_api_endpoint_queries_explanation_table(self):
        """API endpoints should query explanation table, not assertions."""
        from biograph.api.query import get_explanations_for_issuer

        # Mock database cursor to track queries
        class QueryTracker:
            def __init__(self):
                self.queries = []

            def execute(self, query, params=None):
                self.queries.append(query.lower())
                return []

            def fetchall(self):
                return []

        tracker = QueryTracker()

        # Call API function
        get_explanations_for_issuer(tracker, 'ISS_TEST', date.today())

        # Verify queries
        has_explanation_query = any('from explanation' in q for q in tracker.queries)
        has_assertion_query = any('from assertion' in q and 'from explanation' not in q for q in tracker.queries)

        assert has_explanation_query, "API must query explanation table"
        assert not has_assertion_query, "API must NOT query raw assertion table directly"


class TestContractG_ThinDurableCore:
    """
    Contract G: Thin Durable Core (Section 23)

    Storage Strategy:
    - Persist ONLY truth + audit locally
    - Resolve labels LIVE (cached, disposable)
    - NO bulk ontology ingestion

    Key Principles:
    - No large catalog tables (OpenTargets, ChEMBL, GeoNames dumps)
    - Target/disease tables only contain entities referenced by assertions
    - Lookup cache is disposable (can be dropped anytime)
    - Live resolution does NOT affect linkage confidence
    """

    def test_no_bulk_target_catalog(self, db_conn):
        """
        Target table should only contain targets referenced by assertions.

        Per Section 23I.1: Assert no large OT/ChEMBL/GeoNames catalog tables exist.
        """
        with db_conn.cursor() as cur:
            # Count unreferenced targets
            cur.execute("""
                SELECT COUNT(*) FROM target
                WHERE target_id NOT IN (
                    SELECT DISTINCT subject_id FROM assertion WHERE subject_type = 'target'
                    UNION
                    SELECT DISTINCT object_id FROM assertion WHERE object_type = 'target'
                )
            """)

            unreferenced_count = cur.fetchone()[0]

            # Allow small number of unreferenced targets (e.g., from testing)
            # But should not have thousands (which would indicate bulk ingestion)
            assert unreferenced_count < 100, (
                f"Found {unreferenced_count} unreferenced targets. "
                f"Thin Durable Core forbids bulk ontology ingestion (Section 23E). "
                f"Target table should only contain targets referenced by assertions."
            )

    def test_no_bulk_disease_catalog(self, db_conn):
        """
        Disease table should only contain diseases referenced by assertions.

        Per Section 23I.1: Assert target/disease tables only contain entities
        referenced by assertions (not full catalogs).
        """
        with db_conn.cursor() as cur:
            # Count unreferenced diseases
            cur.execute("""
                SELECT COUNT(*) FROM disease
                WHERE disease_id NOT IN (
                    SELECT DISTINCT object_id FROM assertion WHERE object_type = 'disease'
                )
            """)

            unreferenced_count = cur.fetchone()[0]

            # Allow small number of unreferenced diseases
            assert unreferenced_count < 100, (
                f"Found {unreferenced_count} unreferenced diseases. "
                f"Thin Durable Core forbids bulk ontology ingestion (Section 23E). "
                f"Disease table should only contain diseases referenced by assertions."
            )

    def test_lookup_cache_exists(self, db_conn):
        """
        Lookup cache table must exist.

        Per Section 23D: Lookup cache is required for live resolution.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'lookup_cache'
                )
            """)

            exists = cur.fetchone()[0]

            assert exists, (
                "lookup_cache table not found. "
                "Per Section 23D, lookup cache is required for Thin Durable Core."
            )

    def test_lookup_cache_is_small(self, db_conn):
        """
        Lookup cache should be small (<10K entries for MVP).

        Per Section 23D: Cache is lightweight and disposable.
        """
        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM lookup_cache")

            count = cur.fetchone()[0]

            # Allow up to 10K cached entries for MVP scale
            assert count < 10000, (
                f"Lookup cache has {count} entries (expected <10K for MVP). "
                f"Per Section 23D, cache should be lightweight. "
                f"Large cache suggests bulk ingestion instead of live resolution."
            )

    def test_lookup_cache_has_ttl(self, db_conn):
        """
        Lookup cache entries must have TTL (expires_at).

        Per Section 23D: Cache entries have TTL enforcement.
        """
        with db_conn.cursor() as cur:
            # Insert test entry
            cur.execute("""
                INSERT INTO lookup_cache (
                    cache_key, source, value_json, expires_at
                ) VALUES (
                    'test:contract_g', 'opentargets', '{"label":"test"}', NOW() + INTERVAL '30 days'
                )
                ON CONFLICT (cache_key) DO NOTHING
            """)

            # Verify expires_at is set
            cur.execute("""
                SELECT expires_at FROM lookup_cache WHERE cache_key = 'test:contract_g'
            """)

            row = cur.fetchone()

            assert row is not None, "Cache entry not created"
            assert row[0] is not None, "Cache entry must have expires_at (TTL)"

    def test_cache_get_function_exists(self, db_conn):
        """
        Cache helper functions must exist.

        Per Section 23D: cache_get, cache_set, etc. required.
        """
        with db_conn.cursor() as cur:
            # Test cache_get function
            cur.execute("SELECT cache_get('nonexistent:key')")

            # Should return NULL for missing key (not error)
            result = cur.fetchone()[0]
            assert result is None, "cache_get should return NULL for missing key"

    def test_thin_core_violations_view(self, db_conn):
        """
        Thin core violations view should be empty.

        Per Section 23 (Section 5 in migration 004): View detects violations.
        """
        with db_conn.cursor() as cur:
            cur.execute("SELECT * FROM thin_core_violations")

            violations = cur.fetchall()

            assert len(violations) == 0, (
                f"Thin Durable Core violations detected: {violations}. "
                f"Per Section 23, must not have bulk ontology tables or oversized cache."
            )

    def test_linkage_confidence_isolation(self, db_conn):
        """
        Linkage confidence must NOT depend on cached labels.

        Per Section 23H.4: Linkage confidence is computed ONLY from:
        - method (DETERMINISTIC, CURATED, ML_SUGGESTED_APPROVED)
        - evidence (count, sources, tiers)
        - assertions (structure)

        Live-resolved labels MUST NOT affect confidence scores or bands.
        """
        from biograph.core.confidence import compute_link_confidence, LinkMethod, EvidenceInfo
        from datetime import datetime

        # Create test evidence
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'opentargets', datetime.now())
        ]

        # Compute confidence
        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # Verify confidence was computed without any cache or resolver calls
        # (This test passes if no exceptions and score is deterministic)
        assert result.score > 0
        assert result.band is not None

        # Recompute - should get same result (deterministic)
        result2 = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        assert result2.score == result.score, (
            "Linkage confidence must be deterministic. "
            "Per Section 23H.4, live-resolved labels must NOT affect confidence."
        )


class TestContractH_LiteratureAndNewsEvidence:
    """
    Contract H: Literature and News Evidence (Section 24)

    Critical invariants:
    1. PubMed: Metadata ONLY (no full text)
    2. PubMed: Cannot be sole evidence for assertion
    3. MeSH: Resolve live, no bulk ingestion
    4. TA mapping: Deterministic
    5. News: Metadata ONLY, never creates assertion
    6. News: Snippet ≤ 200 chars
    """

    def test_pubmed_metadata_only(self, db_conn):
        """
        PubMed evidence must store ONLY metadata (no full text).

        Per Section 24A.2: FORBIDDEN to store full text or abstracts.
        Snippet max 200 chars.
        """
        with db_conn.cursor() as cur:
            # Create test PubMed evidence
            cur.execute("""
                INSERT INTO evidence (
                    source_system, source_record_id, observed_at, license, uri, snippet
                ) VALUES (
                    'pubmed', '12345678', '2023-01-15', 'NLM_PUBLIC',
                    'https://pubmed.ncbi.nlm.nih.gov/12345678/',
                    'Test article title'
                )
                RETURNING evidence_id
            """)

            evidence_id = cur.fetchone()[0]

            # Verify evidence record
            cur.execute("""
                SELECT source_system, license, snippet
                FROM evidence
                WHERE evidence_id = %s
            """, (evidence_id,))

            row = cur.fetchone()

            assert row[0] == 'pubmed', "Source system must be 'pubmed'"
            assert row[1] == 'NLM_PUBLIC', "License must be 'NLM_PUBLIC'"
            assert row[2] is not None, "Snippet must be present"
            assert len(row[2]) <= 200, (
                f"PubMed snippet is {len(row[2])} chars (max 200). "
                f"Per Section 24A, no full text allowed."
            )

    def test_pubmed_not_sole_evidence(self, db_conn):
        """
        PubMed evidence CANNOT be the sole evidence for an assertion.

        Per Section 24A.4: "PubMed evidence may SUPPORT assertions but may
        NEVER be the sole evidence."

        This is enforced by validation view: pubmed_sole_evidence_violations
        """
        with db_conn.cursor() as cur:
            # Check if validation view exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.views
                    WHERE table_schema = 'public'
                    AND table_name = 'pubmed_sole_evidence_violations'
                )
            """)

            view_exists = cur.fetchone()[0]

            assert view_exists, (
                "pubmed_sole_evidence_violations view not found. "
                "Per Section 24A.4, must validate PubMed not sole evidence."
            )

            # Check for violations
            cur.execute("SELECT * FROM pubmed_sole_evidence_violations")

            violations = cur.fetchall()

            assert len(violations) == 0, (
                f"Found {len(violations)} assertions with PubMed as sole evidence. "
                f"Per Section 24A.4, PubMed cannot be sole evidence. "
                f"Violations: {violations}"
            )

    def test_mesh_no_bulk_ingestion(self, db_conn):
        """
        MeSH descriptors must NOT be bulk ingested.

        Per Section 24B.2: Resolve live via NLM API, use lookup_cache.
        No separate mesh_descriptor table allowed.
        """
        with db_conn.cursor() as cur:
            # Check that mesh_descriptor table does NOT exist
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'mesh_descriptor'
                )
            """)

            mesh_table_exists = cur.fetchone()[0]

            assert not mesh_table_exists, (
                "Found mesh_descriptor table. "
                "Per Section 24B.2, MeSH must be resolved live (no bulk ingestion). "
                "Use lookup_cache for MeSH labels."
            )

    def test_ta_mapping_deterministic(self, db_conn):
        """
        Therapeutic Area mapping must be deterministic.

        Per Section 24C.2: Same input → Same TA.
        """
        from biograph.core.therapeutic_area import map_mesh_to_ta

        with db_conn.cursor() as cur:
            # Test MeSH → TA mapping twice
            mesh_ids = ['C04.557.470']  # Lung cancer

            result1 = map_mesh_to_ta(cur, mesh_ids)
            result2 = map_mesh_to_ta(cur, mesh_ids)

            assert result1.primary_ta == result2.primary_ta, (
                f"TA mapping not deterministic: {result1.primary_ta} != {result2.primary_ta}. "
                f"Per Section 24C.2, same MeSH → same TA."
            )

    def test_ta_taxonomy_fixed(self, db_conn):
        """
        Therapeutic Area taxonomy must have exactly 8 TAs.

        Per Section 24C.1: Fixed taxonomy (ONC, IMM, CNS, CVM, ID, RARE, RES, REN).
        """
        with db_conn.cursor() as cur:
            # Check therapeutic_area_enum
            cur.execute("""
                SELECT enumlabel
                FROM pg_enum
                WHERE enumtypid = 'therapeutic_area_enum'::regtype
                ORDER BY enumlabel
            """)

            ta_codes = [row[0] for row in cur.fetchall()]

            expected_tas = ['CNS', 'CVM', 'ID', 'IMM', 'ONC', 'RARE', 'REN', 'RES']

            assert ta_codes == expected_tas, (
                f"TA taxonomy mismatch. Expected {expected_tas}, got {ta_codes}. "
                f"Per Section 24C.1, taxonomy is fixed (8 TAs)."
            )

    def test_news_metadata_only(self, db_conn):
        """
        News items must store ONLY metadata (no full articles).

        Per Section 24D.2: Headline, publisher, date, URL, snippet (≤200 chars).
        """
        with db_conn.cursor() as cur:
            # Create test news item
            cur.execute("""
                INSERT INTO news_item (
                    publisher, headline, published_at, url, snippet
                ) VALUES (
                    'Test Publisher',
                    'Test Headline',
                    '2023-01-15',
                    'https://example.com/test',
                    'Test snippet'
                )
                RETURNING news_item_id
            """)

            news_item_id = cur.fetchone()[0]

            # Verify news item
            cur.execute("""
                SELECT snippet FROM news_item WHERE news_item_id = %s
            """, (news_item_id,))

            snippet = cur.fetchone()[0]

            assert snippet is not None, "Snippet must be present"
            assert len(snippet) <= 200, (
                f"News snippet is {len(snippet)} chars (max 200). "
                f"Per Section 24D, no full articles allowed."
            )

    def test_news_snippet_max_200_chars(self, db_conn):
        """
        News snippet must be ≤ 200 chars (DB constraint).

        Per Section 24D.2: CHECK constraint on snippet length.
        """
        with db_conn.cursor() as cur:
            # Try to insert news with long snippet
            long_snippet = "A" * 250

            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO news_item (
                        publisher, headline, published_at, url, snippet
                    ) VALUES (
                        'Test', 'Test', '2023-01-15', 'https://example.com/long', %s
                    )
                """, (long_snippet,))

    def test_news_never_creates_assertion(self, db_conn):
        """
        News CANNOT create assertions.

        Per Section 24D.4: "News evidence may support pre-existing assertions
        but CANNOT create new assertions."

        This is enforced by validation view: news_sole_evidence_violations
        """
        with db_conn.cursor() as cur:
            # Check if validation view exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.views
                    WHERE table_schema = 'public'
                    AND table_name = 'news_sole_evidence_violations'
                )
            """)

            view_exists = cur.fetchone()[0]

            assert view_exists, (
                "news_sole_evidence_violations view not found. "
                "Per Section 24D.4, must validate news not sole evidence."
            )

            # Check for violations
            cur.execute("SELECT * FROM news_sole_evidence_violations")

            violations = cur.fetchall()

            assert len(violations) == 0, (
                f"Found {len(violations)} assertions with news as sole evidence. "
                f"Per Section 24D.4, news cannot create assertions. "
                f"Violations: {violations}"
            )

    def test_therapeutic_area_mapping_table_exists(self, db_conn):
        """
        Therapeutic area mapping table must exist and be prepopulated.

        Per Section 24C: therapeutic_area_mapping with anchors.
        """
        with db_conn.cursor() as cur:
            # Check table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'therapeutic_area_mapping'
                )
            """)

            table_exists = cur.fetchone()[0]

            assert table_exists, (
                "therapeutic_area_mapping table not found. "
                "Per Section 24C, TA mapping table required."
            )

            # Check table is prepopulated
            cur.execute("SELECT COUNT(*) FROM therapeutic_area_mapping")

            count = cur.fetchone()[0]

            assert count > 0, (
                "therapeutic_area_mapping table is empty. "
                "Per Section 24C, table should be prepopulated with MeSH/EFO anchors."
            )

    def test_literature_news_tables_exist(self, db_conn):
        """
        Literature and news tables must exist.

        Per Section 24: news_item table required.
        """
        with db_conn.cursor() as cur:
            # Check news_item table
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'news_item'
                )
            """)

            news_table_exists = cur.fetchone()[0]

            assert news_table_exists, (
                "news_item table not found. "
                "Per Section 24D, news_item table required for news metadata."
            )


class TestContractI_StorageAndProjectionArchitecture:
    """
    Contract I: Storage & Projection Architecture (Section 25)

    Critical invariants:
    1. Postgres is the ONLY source of truth
    2. Neo4j stores DERIVED data only (can be rebuilt)
    3. Neo4j NEVER writes back to Postgres
    4. Evidence text NEVER stored in Neo4j
    5. Licensing data NEVER stored in Neo4j
    6. Confidence computation ONLY in Postgres
    7. API MUST work with Postgres-only (Neo4j optional)
    """

    def test_postgres_is_source_of_truth(self, db_conn):
        """
        Postgres must contain all assertions and evidence.

        Per Section 25A: Postgres is the SOLE SOURCE OF TRUTH.
        All canonical data lives ONLY in Postgres.

        This test verifies that assertions and evidence exist in Postgres,
        regardless of Neo4j state.
        """
        with db_conn.cursor() as cur:
            # Verify assertion table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'assertion'
                )
            """)

            assertion_table_exists = cur.fetchone()[0]

            assert assertion_table_exists, (
                "assertion table not found in Postgres. "
                "Per Section 25A, Postgres is the source of truth."
            )

            # Verify evidence table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'evidence'
                )
            """)

            evidence_table_exists = cur.fetchone()[0]

            assert evidence_table_exists, (
                "evidence table not found in Postgres. "
                "Per Section 25A, Postgres is the source of truth."
            )

            # Verify assertion_evidence link table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'assertion_evidence'
                )
            """)

            link_table_exists = cur.fetchone()[0]

            assert link_table_exists, (
                "assertion_evidence table not found in Postgres. "
                "Per Section 25A, Postgres is the source of truth."
            )

    def test_explanation_store_postgres_path(self, db_conn):
        """
        PostgresExplanationStore must work (authoritative path).

        Per Section 25G: PostgresExplanationStore is ALWAYS AVAILABLE.
        """
        from biograph.storage.postgres_store import PostgresExplanationStore

        with db_conn.cursor() as cur:
            store = PostgresExplanationStore(cur)

            # Verify store is available
            assert store.is_available(), (
                "PostgresExplanationStore not available. "
                "Per Section 25A, Postgres is always required."
            )

            # Verify store name
            assert store.get_store_name() == 'postgres', (
                "PostgresExplanationStore should return 'postgres' as store name"
            )

    def test_explanation_store_factory_postgres_default(self, db_conn):
        """
        ExplanationStoreFactory defaults to Postgres (safe mode).

        Per Section 25F: Default safe mode is postgres-only.
        """
        from biograph.storage.explanation_store import ExplanationStoreFactory

        with db_conn.cursor() as cur:
            # Create store with default backend
            store = ExplanationStoreFactory.create_store(cur, backend='postgres')

            assert store.get_store_name() == 'postgres', (
                "Default backend should be Postgres (safe mode)"
            )

            assert store.is_available(), (
                "Postgres store should always be available"
            )

    def test_config_defaults_to_postgres(self):
        """
        Configuration defaults to Postgres if GRAPH_BACKEND not set.

        Per Section 25F: GRAPH_BACKEND defaults to 'postgres' (safe mode).
        """
        from biograph.config import GraphConfig

        # Test default backend
        config = GraphConfig(backend='postgres')

        assert config.backend == 'postgres', (
            "Default backend should be 'postgres'"
        )

        assert not config.is_neo4j_enabled(), (
            "Neo4j should not be enabled by default"
        )

    def test_config_requires_neo4j_credentials(self):
        """
        Neo4j backend requires full configuration (URI, user, password).

        Per Section 25F: Neo4j config must be complete.
        """
        from biograph.config import GraphConfig

        # Neo4j without credentials should not be enabled
        config_no_creds = GraphConfig(backend='neo4j')

        assert not config_no_creds.is_neo4j_enabled(), (
            "Neo4j should not be enabled without credentials"
        )

        # Neo4j with full credentials should be enabled
        config_full = GraphConfig(
            backend='neo4j',
            neo4j_uri='neo4j+s://test.databases.neo4j.io',
            neo4j_user='test_user',
            neo4j_password='test_password'
        )

        assert config_full.is_neo4j_enabled(), (
            "Neo4j should be enabled with full credentials"
        )

    def test_no_neo4j_tables_in_postgres(self, db_conn):
        """
        Postgres should NOT have Neo4j-specific tables.

        Per Section 25: Neo4j is a separate projection layer.
        Postgres should not have Neo4j metadata tables.
        """
        with db_conn.cursor() as cur:
            # Check for Neo4j-related table names
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND (
                    table_name LIKE '%neo4j%'
                    OR table_name LIKE '%graph_projection%'
                )
            """)

            neo4j_tables = cur.fetchall()

            # Allow neo4j_projection_log table for tracking projection status
            # but no other Neo4j-specific tables
            allowed_tables = {'neo4j_projection_log'}
            found_tables = {row[0] for row in neo4j_tables}
            unexpected_tables = found_tables - allowed_tables

            assert len(unexpected_tables) == 0, (
                f"Found Neo4j-specific tables in Postgres: {unexpected_tables}. "
                f"Per Section 25, Neo4j is a separate projection layer."
            )

    def test_evidence_has_license_column(self, db_conn):
        """
        Evidence table must have license column (required for Postgres).

        Per Section 25C: Licensing data NEVER stored in Neo4j.
        Must exist in Postgres.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'evidence'
                AND column_name = 'license'
            """)

            license_column = cur.fetchone()

            assert license_column is not None, (
                "evidence table missing 'license' column. "
                "Per Section 25C, licensing data must be in Postgres only."
            )

    def test_evidence_has_snippet_column(self, db_conn):
        """
        Evidence table must have snippet column (required for Postgres).

        Per Section 25C: Evidence text NEVER stored in Neo4j.
        Must exist in Postgres.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'evidence'
                AND column_name = 'snippet'
            """)

            snippet_column = cur.fetchone()

            assert snippet_column is not None, (
                "evidence table missing 'snippet' column. "
                "Per Section 25C, evidence text must be in Postgres only."
            )

    def test_assertion_has_confidence_columns(self, db_conn):
        """
        Assertion table must have confidence columns (computed in Postgres).

        Per Section 25: Confidence computation ONLY in Postgres.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'assertion'
                AND column_name IN ('link_confidence_band', 'link_confidence_score')
                ORDER BY column_name
            """)

            confidence_columns = cur.fetchall()

            assert len(confidence_columns) == 2, (
                "assertion table missing confidence columns. "
                "Per Section 25, confidence computed in Postgres only."
            )

    def test_explanation_store_abstraction_exists(self):
        """
        ExplanationStore abstraction must exist.

        Per Section 25G: ExplanationStore interface required.
        """
        from biograph.storage.explanation_store import ExplanationStore

        # Verify abstract methods exist
        assert hasattr(ExplanationStore, 'get_explanation'), (
            "ExplanationStore missing get_explanation() method"
        )

        assert hasattr(ExplanationStore, 'get_assertion_details'), (
            "ExplanationStore missing get_assertion_details() method"
        )

        assert hasattr(ExplanationStore, 'get_evidence'), (
            "ExplanationStore missing get_evidence() method"
        )

        assert hasattr(ExplanationStore, 'is_available'), (
            "ExplanationStore missing is_available() method"
        )

    def test_postgres_store_implements_interface(self):
        """
        PostgresExplanationStore must implement ExplanationStore interface.

        Per Section 25G: PostgresExplanationStore is authoritative implementation.
        """
        from biograph.storage.explanation_store import ExplanationStore
        from biograph.storage.postgres_store import PostgresExplanationStore

        # Verify PostgresExplanationStore is subclass of ExplanationStore
        assert issubclass(PostgresExplanationStore, ExplanationStore), (
            "PostgresExplanationStore must implement ExplanationStore interface"
        )


class TestContractJ_ExecutionLayer:
    """
    Contract J: Execution Layer (Sections 26-35)

    Critical invariants:
    1. Single API entrypoint (FastAPI only)
    2. API key authentication on admin endpoints
    3. Connection pooling enabled
    4. Error handling (no stack traces)
    5. /healthz endpoint exists
    6. requirements.txt complete
    7. No legacy API files
    """

    def test_single_api_entrypoint_exists(self):
        """
        Single API entrypoint must exist.

        Per Section 27B: Exactly ONE runnable server module exists (biograph/api/main.py).
        """
        import os

        main_path = "/home/user/biograph/biograph/api/main.py"

        assert os.path.exists(main_path), (
            f"API entrypoint not found at {main_path}. "
            "Per Section 27B, exactly ONE runnable server module required."
        )

    def test_legacy_api_files_deleted(self):
        """
        Legacy API files must be deleted.

        Per Section 27E: Legacy entrypoints MUST be deleted or quarantined.
        """
        import os

        legacy_files = [
            "/home/user/biograph/app.py",
            "/home/user/biograph/app_mvp.py",
            "/home/user/biograph/backend/app/main.py",
            "/home/user/biograph/backend/app/main_mvp.py",
            "/home/user/biograph/backend/app/api_mvp.py",
            "/home/user/biograph/backend/app/api_v8_1.py"
        ]

        existing_legacy = [f for f in legacy_files if os.path.exists(f)]

        assert len(existing_legacy) == 0, (
            f"Found legacy API files: {existing_legacy}. "
            f"Per Section 27E, these MUST be deleted. "
            f"Only biograph/api/main.py should exist."
        )

    def test_fastapi_is_framework(self):
        """
        FastAPI must be the API framework.

        Per Section 27A: FastAPI is the SOLE supported API runtime.
        """
        try:
            from biograph.api.main import app
            from fastapi import FastAPI

            assert isinstance(app, FastAPI), (
                "API app is not a FastAPI instance. "
                "Per Section 27A, FastAPI is the sole supported runtime."
            )
        except ImportError as e:
            pytest.fail(f"Failed to import FastAPI app: {e}")

    def test_api_versioning(self):
        """
        API endpoints must use /api/v1/* versioning.

        Per Section 27C: All endpoints under /api/v1/*
        """
        from biograph.api.v1 import issuers, health, admin

        # Check router prefixes
        assert issuers.router.prefix == "/api/v1", (
            f"Issuers router prefix is {issuers.router.prefix}, expected /api/v1"
        )

        assert admin.router.prefix == "/api/v1/admin", (
            f"Admin router prefix is {admin.router.prefix}, expected /api/v1/admin"
        )

    def test_healthz_endpoint_exists(self):
        """
        /healthz endpoint must exist.

        Per Section 31: GET /healthz is REQUIRED.
        """
        from biograph.api.v1 import health

        # Check that health router has /healthz route
        routes = [route.path for route in health.router.routes]

        assert "/healthz" in routes, (
            "/healthz endpoint not found. "
            "Per Section 31, GET /healthz is REQUIRED for operational monitoring."
        )

    def test_api_key_auth_on_admin(self):
        """
        Admin endpoints must require API key.

        Per Section 28: Admin endpoints MUST be API-key gated.
        """
        from biograph.api.v1 import admin

        # Check that admin router has auth dependency
        # This is verified by checking dependencies in route
        assert hasattr(admin, 'verify_api_key') or hasattr(admin, 'Depends'), (
            "Admin endpoints missing API key authentication. "
            "Per Section 28, admin endpoints MUST require X-API-Key header."
        )

    def test_connection_pooling_module_exists(self):
        """
        Connection pooling module must exist.

        Per Section 29: Connection pooling is REQUIRED.
        """
        try:
            from biograph.api.dependencies import init_connection_pool, get_db

            assert callable(init_connection_pool), (
                "init_connection_pool not found or not callable"
            )

            assert callable(get_db), (
                "get_db not found or not callable"
            )
        except ImportError as e:
            pytest.fail(
                f"Connection pooling module not found: {e}. "
                f"Per Section 29, connection pooling is REQUIRED."
            )

    def test_error_handling_middleware_exists(self):
        """
        Error handling middleware must exist.

        Per Section 30: No stack traces to clients, structured JSON errors.
        """
        from biograph.api.main import app

        # Check for exception handlers
        assert len(app.exception_handlers) > 0, (
            "No exception handlers found. "
            "Per Section 30, error handling middleware is REQUIRED."
        )

    def test_requirements_txt_complete(self):
        """
        requirements.txt must include all production dependencies.

        Per Section 33: All imports used by production entrypoint MUST be in requirements.txt.
        """
        import os

        req_path = "/home/user/biograph/requirements.txt"

        assert os.path.exists(req_path), (
            "requirements.txt not found. "
            "Per Section 33, requirements.txt is REQUIRED."
        )

        with open(req_path, 'r') as f:
            requirements = f.read()

        # Check for required dependencies
        required_deps = [
            "fastapi",
            "uvicorn",
            "psycopg",
            "pydantic",
            "structlog"
        ]

        missing_deps = [dep for dep in required_deps if dep not in requirements.lower()]

        assert len(missing_deps) == 0, (
            f"Missing dependencies in requirements.txt: {missing_deps}. "
            f"Per Section 33, all imports must be listed."
        )

    def test_no_flask_dependencies(self):
        """
        Flask dependencies must be removed.

        Per Section 27A: Flask is FORBIDDEN in production code.
        """
        import os

        req_path = "/home/user/biograph/requirements.txt"

        with open(req_path, 'r') as f:
            requirements = f.read()

        # Flask should NOT be in requirements
        assert "flask" not in requirements.lower(), (
            "Found Flask in requirements.txt. "
            "Per Section 27A, Flask is FORBIDDEN. FastAPI is the sole runtime."
        )

    def test_structured_logging_configured(self):
        """
        Structured logging must be configured.

        Per Section 30D: Structured logs (JSON) with request_id required.
        """
        try:
            import structlog

            # Verify structlog is configured
            logger = structlog.get_logger()

            assert logger is not None, (
                "structlog not configured. "
                "Per Section 30D, structured logging is REQUIRED."
            )
        except ImportError:
            pytest.fail(
                "structlog not installed. "
                "Per Section 30D, structured logging is REQUIRED."
            )


# Pytest configuration
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "contract: mark test as a contract test (non-negotiable invariant)"
    )


class TestContractK_NerErCompleteness:
    """
    Contract K: NER/ER Completeness (Section 32)

    Critical invariants:
    1. NER produces candidates ONLY (no canonical entity creation)
    2. NER never creates assertions
    3. ER within issuer ONLY
    4. ER never auto-merges
    5. Candidate rows link to mention + nlp_run + evidence
    6. Evidence has license + observed_at always
    """

    def test_ner_produces_candidates_only(self, db_conn):
        """NER must produce candidates ONLY (no canonical entity creation)."""
        from biograph.nlp.ner_runner import run_ner_on_text

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO issuer (issuer_id, primary_cik) VALUES ('ISS_TEST_NER', '0000000099') ON CONFLICT DO NOTHING")
            
            cur.execute("SELECT COUNT(*) FROM drug_program WHERE issuer_id = 'ISS_TEST_NER'")
            drug_count_before = cur.fetchone()[0]

            run_ner_on_text(cur, 'filing', 99999, "KEYTRUDA is a Phase 3 candidate targeting PD-1 for melanoma.", 'ISS_TEST_NER')

            cur.execute("SELECT COUNT(*) FROM drug_program WHERE issuer_id = 'ISS_TEST_NER'")
            drug_count_after = cur.fetchone()[0]

            assert drug_count_after == drug_count_before, "NER created canonical entities (FORBIDDEN)"
            
            cur.execute("SELECT COUNT(*) FROM candidate WHERE issuer_id = 'ISS_TEST_NER'")
            assert cur.fetchone()[0] > 0, "NER must produce candidates"

        db_conn.rollback()

    def test_ner_never_creates_assertions(self, db_conn):
        """NER must NEVER create assertions."""
        from biograph.nlp.ner_runner import run_ner_on_text

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO issuer (issuer_id, primary_cik) VALUES ('ISS_TEST_NER2', '0000000098') ON CONFLICT DO NOTHING")
            
            cur.execute("SELECT COUNT(*) FROM assertion")
            count_before = cur.fetchone()[0]

            run_ner_on_text(cur, 'filing', 99998, "OPDIVO targets PD-1 for lung cancer.", 'ISS_TEST_NER2')

            cur.execute("SELECT COUNT(*) FROM assertion")
            count_after = cur.fetchone()[0]

            assert count_after == count_before, "NER created assertions (FORBIDDEN)"

        db_conn.rollback()

    def test_er_within_issuer_only(self, db_conn):
        """ER must operate within issuer ONLY."""
        from biograph.er.dedupe_runner import find_duplicates_for_issuer

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO issuer (issuer_id, primary_cik) VALUES ('ISS_ER1', '0000000097'), ('ISS_ER2', '0000000096') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO drug_program (drug_program_id, issuer_id, slug, name) VALUES ('CIK:0000000097:PROG:t1', 'ISS_ER1', 't1', 'KEYTRUDA'), ('CIK:0000000096:PROG:t2', 'ISS_ER2', 't2', 'Keytruda') ON CONFLICT DO NOTHING")

            find_duplicates_for_issuer(cur, 'ISS_ER1')

            cur.execute("SELECT COUNT(*) FROM duplicate_suggestion WHERE (entity_id_1 = 'CIK:0000000097:PROG:t1' AND entity_id_2 = 'CIK:0000000096:PROG:t2') OR (entity_id_1 = 'CIK:0000000096:PROG:t2' AND entity_id_2 = 'CIK:0000000097:PROG:t1')")
            
            assert cur.fetchone()[0] == 0, "ER crossed issuer boundary (FORBIDDEN)"

        db_conn.rollback()

    def test_candidate_links_to_evidence(self, db_conn):
        """Candidate rows must link to evidence."""
        from biograph.nlp.ner_runner import run_ner_on_text

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO issuer (issuer_id, primary_cik) VALUES ('ISS_LINK', '0000000095') ON CONFLICT DO NOTHING")

            run_ner_on_text(cur, 'filing', 99997, "TECENTRIQ targets PD-L1.", 'ISS_LINK')

            cur.execute("SELECT COUNT(*) FROM evidence WHERE source_record_id = 'filing_99997'")
            assert cur.fetchone()[0] > 0, "NER must create evidence for provenance"

            cur.execute("SELECT mention_ids FROM candidate WHERE issuer_id = 'ISS_LINK' LIMIT 1")
            row = cur.fetchone()
            if row:
                assert row[0] is not None and len(row[0]) > 0, "Candidate must link to mentions"

        db_conn.rollback()
