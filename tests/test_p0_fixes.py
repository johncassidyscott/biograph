"""
Regression tests for P0 blocker fixes.

Tests that all P0 issues identified in COMPETITIVE_TEST_REPORT.md are resolved.
"""

import pytest
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestP0BuildFixes:
    """Test P0-01: Build fixes"""

    def test_requirements_psycopg_version(self):
        """Verify psycopg version is valid (P0-01)."""
        requirements_path = Path(__file__).parent.parent / 'requirements.txt'
        with open(requirements_path) as f:
            content = f.read()

        # Should NOT have invalid version 3.13.0
        assert 'psycopg[binary]==3.13.0' not in content, \
            "P0-01 NOT FIXED: Invalid psycopg version 3.13.0 still present"

        # Should have valid version
        assert 'psycopg[binary]==3.3.2' in content or 'psycopg[binary]==3.' in content, \
            "P0-01 NOT FIXED: Valid psycopg version not found"

    def test_requirements_has_psycopg_pool(self):
        """Verify psycopg-pool is in requirements (P1-07)."""
        requirements_path = Path(__file__).parent.parent / 'requirements.txt'
        with open(requirements_path) as f:
            content = f.read()

        assert 'psycopg-pool' in content, \
            "P1-07 NOT FIXED: psycopg-pool not in requirements"

    def test_requirements_has_requests(self):
        """Verify requests is in requirements (P1-04)."""
        requirements_path = Path(__file__).parent.parent / 'requirements.txt'
        with open(requirements_path) as f:
            content = f.read()

        assert 'requests==' in content, \
            "P1-04 NOT FIXED: requests not in requirements (needed for Wikidata)"


class TestP0EntrypointFixes:
    """Test P0-02: Single entrypoint enforcement"""

    def test_fastapi_entrypoint_removed(self):
        """Verify FastAPI app is removed (P0-02)."""
        fastapi_app_path = Path(__file__).parent.parent / 'backend' / 'app' / 'main.py'

        assert not fastapi_app_path.exists(), \
            "P0-02 NOT FIXED: FastAPI entrypoint (backend/app/main.py) still exists"

    def test_backend_requirements_removed(self):
        """Verify backend/requirements.txt is removed (P0-03)."""
        backend_req_path = Path(__file__).parent.parent / 'backend' / 'requirements.txt'

        assert not backend_req_path.exists(), \
            "P0-03 NOT FIXED: backend/requirements.txt still exists"

    def test_flask_app_exists(self):
        """Verify Flask app (app.py) is present."""
        app_path = Path(__file__).parent.parent / 'app.py'
        assert app_path.exists(), "Flask app (app.py) not found"


class TestP0SchemaFixes:
    """Test P0-04, P0-05, P0-06: Schema fixes"""

    def test_evidence_migration_exists(self):
        """Verify evidence model migration created (P0-04)."""
        migration_path = Path(__file__).parent.parent / 'backend' / 'migrations' / '002_evidence_model.sql'

        assert migration_path.exists(), \
            "P0-04 NOT FIXED: Evidence model migration (002_evidence_model.sql) not found"

        # Verify it contains evidence table
        with open(migration_path) as f:
            content = f.read()

        assert 'CREATE TABLE evidence' in content, \
            "P0-04 NOT FIXED: evidence table not in migration"
        assert 'CREATE TABLE assertion' in content, \
            "P0-04 NOT FIXED: assertion table not in migration"
        assert 'CREATE TABLE lookup_cache' in content, \
            "P0-06 NOT FIXED: lookup_cache table not in migration"
        assert 'CREATE TABLE license_allowlist' in content, \
            "P0-04 NOT FIXED: license_allowlist table not in migration"

    def test_patent_migration_no_duplicates(self):
        """Verify 001_patents.sql doesn't duplicate 000_core.sql (P0-05)."""
        migration_path = Path(__file__).parent.parent / 'backend' / 'migrations' / '001_patents.sql'

        with open(migration_path) as f:
            content = f.read()

        # Should NOT have duplicate CREATE TABLE statements
        # Count occurrences of "CREATE TABLE patent"
        patent_creates = content.count('CREATE TABLE patent')
        assignee_creates = content.count('CREATE TABLE assignee')

        assert patent_creates == 0, \
            f"P0-05 NOT FIXED: 001_patents.sql still has {patent_creates} CREATE TABLE patent (should be 0)"
        assert assignee_creates == 0, \
            f"P0-05 NOT FIXED: 001_patents.sql still has {assignee_creates} CREATE TABLE assignee (should be 0)"


class TestP0MiddlewareFixes:
    """Test P0-08, P1-01, P1-02: Middleware infrastructure"""

    def test_app_has_error_middleware(self):
        """Verify error middleware added (P1-01)."""
        app_path = Path(__file__).parent.parent / 'app.py'

        with open(app_path) as f:
            content = f.read()

        assert '@app.errorhandler(Exception)' in content, \
            "P1-01 NOT FIXED: Error handler middleware not found"
        assert 'def handle_error' in content, \
            "P1-01 NOT FIXED: handle_error function not found"

    def test_app_has_request_id_middleware(self):
        """Verify request ID middleware added (P1-02)."""
        app_path = Path(__file__).parent.parent / 'app.py'

        with open(app_path) as f:
            content = f.read()

        assert '@app.before_request' in content, \
            "P1-02 NOT FIXED: before_request middleware not found"
        assert 'request_id' in content.lower(), \
            "P1-02 NOT FIXED: request_id logic not found"
        assert 'X-Request-ID' in content, \
            "P1-02 NOT FIXED: X-Request-ID header handling not found"

    def test_app_has_api_key_decorator(self):
        """Verify API key infrastructure added (P0-08)."""
        app_path = Path(__file__).parent.parent / 'app.py'

        with open(app_path) as f:
            content = f.read()

        assert 'def require_api_key' in content, \
            "P0-08 NOT FIXED: require_api_key decorator not found"
        assert 'ADMIN_API_KEYS' in content, \
            "P0-08 NOT FIXED: ADMIN_API_KEYS not found"

    def test_health_check_validates_db(self):
        """Verify health check validates database (P2-02)."""
        app_path = Path(__file__).parent.parent / 'app.py'

        with open(app_path) as f:
            content = f.read()

        # Find health route
        assert '@app.route(\'/health\')' in content, \
            "Health check endpoint not found"

        # Check that it queries database
        assert 'SELECT 1' in content or 'database' in content.lower(), \
            "P2-02 NOT FIXED: Health check doesn't validate database connectivity"


class TestP0ConnectionPooling:
    """Test P1-07: Connection pooling"""

    def test_db_has_connection_pool(self):
        """Verify connection pooling added to db.py (P1-07)."""
        db_path = Path(__file__).parent.parent / 'backend' / 'app' / 'db.py'

        with open(db_path) as f:
            content = f.read()

        assert 'from psycopg_pool import ConnectionPool' in content, \
            "P1-07 NOT FIXED: ConnectionPool import not found"
        assert 'def init_pool' in content, \
            "P1-07 NOT FIXED: init_pool function not found"
        assert '_pool' in content, \
            "P1-07 NOT FIXED: _pool global variable not found"

    def test_app_initializes_pool(self):
        """Verify app.py initializes connection pool (P1-07)."""
        app_path = Path(__file__).parent.parent / 'app.py'

        with open(app_path) as f:
            content = f.read()

        assert 'init_pool' in content, \
            "P1-07 NOT FIXED: app.py doesn't call init_pool()"
        assert 'close_pool' in content, \
            "P1-07 NOT FIXED: app.py doesn't register close_pool()"


class TestP0MigrationRunner:
    """Test P2-01: Migration runner script"""

    def test_migration_runner_exists(self):
        """Verify migration runner script created (P2-01)."""
        runner_path = Path(__file__).parent.parent / 'scripts' / 'run_migrations.py'

        assert runner_path.exists(), \
            "P2-01 NOT FIXED: Migration runner (scripts/run_migrations.py) not found"

        # Verify it's executable
        assert os.access(runner_path, os.X_OK), \
            "P2-01 NOT FIXED: Migration runner not executable"


class TestP0Documentation:
    """Test deliverables created"""

    def test_competitive_test_report_exists(self):
        """Verify COMPETITIVE_TEST_REPORT.md created."""
        report_path = Path(__file__).parent.parent / 'docs' / 'COMPETITIVE_TEST_REPORT.md'

        assert report_path.exists(), \
            "DELIVERABLE MISSING: docs/COMPETITIVE_TEST_REPORT.md not found"

        with open(report_path) as f:
            content = f.read()

        assert 'EXECUTIVE VERDICT' in content, \
            "COMPETITIVE_TEST_REPORT.md missing EXECUTIVE VERDICT section"
        assert 'P0' in content, \
            "COMPETITIVE_TEST_REPORT.md missing P0 findings"

    def test_arch_review_exists(self):
        """Verify ARCH_REVIEW.md created."""
        review_path = Path(__file__).parent.parent / 'docs' / 'ARCH_REVIEW.md'

        assert review_path.exists(), \
            "DELIVERABLE MISSING: docs/ARCH_REVIEW.md not found"

        with open(review_path) as f:
            content = f.read()

        assert 'THIN DURABLE CORE' in content.upper(), \
            "ARCH_REVIEW.md missing Thin Durable Core assessment"


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
