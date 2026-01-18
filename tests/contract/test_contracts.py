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


# Pytest configuration
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "contract: mark test as a contract test (non-negotiable invariant)"
    )
