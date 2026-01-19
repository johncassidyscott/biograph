"""
Unit tests for BioGraph lookup cache and resolvers.

Tests Section 23 of the spec: Thin Durable Core posture.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from biograph.core.lookup_cache import (
    LookupCache,
    CacheSource,
    make_cache_key,
    cached_resolve,
    cached_resolve_with_fallback
)


class TestLookupCache:
    """Test LookupCache class functionality."""

    def test_cache_set_and_get(self, db_conn):
        """Test basic cache set and get."""
        cache = LookupCache(db_conn.cursor())

        # Set cache entry
        cache.set(
            'opentargets:ENSG00000141510',
            CacheSource.OPENTARGETS,
            {'label': 'TP53', 'gene_symbol': 'TP53'}
        )

        db_conn.commit()

        # Get cache entry
        result = cache.get('opentargets:ENSG00000141510')

        assert result is not None
        assert result['label'] == 'TP53'
        assert result['gene_symbol'] == 'TP53'

    def test_cache_miss(self, db_conn):
        """Test cache miss returns None."""
        cache = LookupCache(db_conn.cursor())

        result = cache.get('nonexistent:key')

        assert result is None

    def test_cache_expiry(self, db_conn):
        """Test cache entry expiration."""
        cache = LookupCache(db_conn.cursor())

        # Set cache entry with very short TTL (use negative for testing expiry)
        # Actually, let's manually set an expired entry
        cursor = db_conn.cursor()
        cursor.execute("""
            INSERT INTO lookup_cache (
                cache_key, source, value_json, expires_at
            ) VALUES (
                %s, %s, %s, %s
            )
        """, (
            'opentargets:EXPIRED',
            'opentargets',
            '{"label": "Expired"}',
            datetime.now() - timedelta(days=1)  # Expired yesterday
        ))
        db_conn.commit()

        # Try to get expired entry
        result = cache.get('opentargets:EXPIRED')

        # Should return None (expired entries are auto-deleted)
        assert result is None

    def test_cache_hit_tracking(self, db_conn):
        """Test that cache hits are tracked."""
        cache = LookupCache(db_conn.cursor())

        # Set cache entry
        cache.set('opentargets:TEST', CacheSource.OPENTARGETS, {'label': 'Test'})
        db_conn.commit()

        # Get it multiple times
        cache.get('opentargets:TEST')
        cache.get('opentargets:TEST')
        cache.get('opentargets:TEST')
        db_conn.commit()

        # Check hit count
        cursor = db_conn.cursor()
        cursor.execute("""
            SELECT hit_count FROM lookup_cache WHERE cache_key = %s
        """, ('opentargets:TEST',))

        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 3  # 3 hits

    def test_cache_delete(self, db_conn):
        """Test cache entry deletion."""
        cache = LookupCache(db_conn.cursor())

        # Set cache entry
        cache.set('opentargets:DELETE_ME', CacheSource.OPENTARGETS, {'label': 'Delete'})
        db_conn.commit()

        # Verify it exists
        assert cache.get('opentargets:DELETE_ME') is not None

        # Delete it
        deleted = cache.delete('opentargets:DELETE_ME')
        db_conn.commit()

        assert deleted is True

        # Verify it's gone
        assert cache.get('opentargets:DELETE_ME') is None

    def test_cache_clear_source(self, db_conn):
        """Test clearing all entries for a source."""
        cache = LookupCache(db_conn.cursor())

        # Set multiple entries
        cache.set('opentargets:A', CacheSource.OPENTARGETS, {'label': 'A'})
        cache.set('opentargets:B', CacheSource.OPENTARGETS, {'label': 'B'})
        cache.set('chembl:C', CacheSource.CHEMBL, {'label': 'C'})
        db_conn.commit()

        # Clear OpenTargets entries
        count = cache.clear_source(CacheSource.OPENTARGETS)
        db_conn.commit()

        assert count == 2  # Cleared 2 OpenTargets entries

        # Verify OpenTargets entries are gone
        assert cache.get('opentargets:A') is None
        assert cache.get('opentargets:B') is None

        # Verify ChEMBL entry still exists
        assert cache.get('chembl:C') is not None

    def test_cache_cleanup_expired(self, db_conn):
        """Test cleanup of expired entries."""
        cache = LookupCache(db_conn.cursor())
        cursor = db_conn.cursor()

        # Create some expired entries
        for i in range(5):
            cursor.execute("""
                INSERT INTO lookup_cache (
                    cache_key, source, value_json, expires_at
                ) VALUES (
                    %s, %s, %s, %s
                )
            """, (
                f'opentargets:EXPIRED_{i}',
                'opentargets',
                '{"label": "Expired"}',
                datetime.now() - timedelta(days=1)
            ))

        # Create a valid entry
        cache.set('opentargets:VALID', CacheSource.OPENTARGETS, {'label': 'Valid'})
        db_conn.commit()

        # Cleanup expired
        count = cache.cleanup_expired()
        db_conn.commit()

        assert count == 5  # Cleaned up 5 expired entries

        # Verify valid entry still exists
        assert cache.get('opentargets:VALID') is not None

    def test_cache_stats(self, db_conn):
        """Test cache statistics."""
        cache = LookupCache(db_conn.cursor())

        # Create some entries
        cache.set('opentargets:STAT1', CacheSource.OPENTARGETS, {'label': 'Stat1'})
        cache.set('opentargets:STAT2', CacheSource.OPENTARGETS, {'label': 'Stat2'})
        cache.set('chembl:STAT3', CacheSource.CHEMBL, {'label': 'Stat3'})
        db_conn.commit()

        # Hit some entries
        cache.get('opentargets:STAT1')
        cache.get('opentargets:STAT1')
        cache.get('opentargets:STAT2')
        db_conn.commit()

        # Get stats
        stats = cache.stats()

        assert 'opentargets' in stats
        assert stats['opentargets']['valid_entries'] >= 2
        assert stats['opentargets']['total_hits'] >= 3


class TestCacheKeyMaking:
    """Test cache key generation."""

    def test_make_cache_key(self):
        """Test cache key format."""
        key = make_cache_key(CacheSource.OPENTARGETS, 'ENSG00000141510')
        assert key == 'opentargets:ENSG00000141510'

    def test_make_cache_key_chembl(self):
        """Test cache key for ChEMBL."""
        key = make_cache_key(CacheSource.CHEMBL, 'CHEMBL1234')
        assert key == 'chembl:CHEMBL1234'


class TestCachedResolve:
    """Test cached_resolve helper function."""

    def test_cached_resolve_hit(self, db_conn):
        """Test cached_resolve with cache hit."""
        cursor = db_conn.cursor()
        cache = LookupCache(cursor)

        # Pre-populate cache
        cache.set('opentargets:TEST', CacheSource.OPENTARGETS, {'label': 'Cached'})
        db_conn.commit()

        # Mock resolver (should NOT be called)
        mock_resolver = Mock()

        # Resolve with cache hit
        result = cached_resolve(
            cursor,
            CacheSource.OPENTARGETS,
            'TEST',
            mock_resolver,
            ttl_days=30
        )

        assert result is not None
        assert result['label'] == 'Cached'

        # Verify resolver was NOT called (cache hit)
        mock_resolver.assert_not_called()

    def test_cached_resolve_miss(self, db_conn):
        """Test cached_resolve with cache miss."""
        cursor = db_conn.cursor()

        # Mock resolver
        mock_resolver = Mock(return_value={'label': 'Live Resolved'})

        # Resolve with cache miss
        result = cached_resolve(
            cursor,
            CacheSource.OPENTARGETS,
            'MISS',
            mock_resolver,
            ttl_days=30
        )

        assert result is not None
        assert result['label'] == 'Live Resolved'

        # Verify resolver WAS called (cache miss)
        mock_resolver.assert_called_once_with('MISS')

        # Verify result was cached
        db_conn.commit()
        cache = LookupCache(cursor)
        cached = cache.get('opentargets:MISS')
        assert cached is not None
        assert cached['label'] == 'Live Resolved'


class TestCachedResolveWithFallback:
    """Test cached_resolve_with_fallback helper."""

    def test_fallback_on_resolver_failure(self, db_conn):
        """Test fallback when resolver fails."""
        cursor = db_conn.cursor()

        # Mock resolver that returns None (failure)
        mock_resolver = Mock(return_value=None)

        # Resolve with fallback
        result = cached_resolve_with_fallback(
            cursor,
            CacheSource.OPENTARGETS,
            'FAILED_ID',
            mock_resolver,
            fallback_label='FAILED_ID',
            ttl_days=30
        )

        # Should return fallback
        assert result is not None
        assert result['label'] == 'FAILED_ID'
        assert result['is_fallback'] is True

    def test_fallback_on_resolver_exception(self, db_conn):
        """Test fallback when resolver raises exception."""
        cursor = db_conn.cursor()

        # Mock resolver that raises exception
        mock_resolver = Mock(side_effect=Exception("API error"))

        # Resolve with fallback
        result = cached_resolve_with_fallback(
            cursor,
            CacheSource.OPENTARGETS,
            'ERROR_ID',
            mock_resolver,
            fallback_label='ERROR_ID',
            ttl_days=30
        )

        # Should return fallback
        assert result is not None
        assert result['label'] == 'ERROR_ID'
        assert result['is_fallback'] is True

    def test_success_no_fallback(self, db_conn):
        """Test successful resolution without fallback."""
        cursor = db_conn.cursor()

        # Mock resolver that succeeds
        mock_resolver = Mock(return_value={'label': 'Success', 'extra': 'data'})

        # Resolve
        result = cached_resolve_with_fallback(
            cursor,
            CacheSource.OPENTARGETS,
            'SUCCESS_ID',
            mock_resolver,
            fallback_label='FALLBACK',
            ttl_days=30
        )

        # Should return actual result (not fallback)
        assert result is not None
        assert result['label'] == 'Success'
        assert result['extra'] == 'data'
        assert 'is_fallback' not in result or result.get('is_fallback') is False


class TestResolverValidation:
    """Test resolver ID validation functions."""

    def test_validate_target_id(self):
        """Test OpenTargets target ID validation."""
        from biograph.integrations.opentargets import validate_target_id

        # Valid Ensembl IDs
        assert validate_target_id('ENSG00000141510') is True
        assert validate_target_id('ENSG00000000001') is True

        # Invalid IDs
        assert validate_target_id('ENSG0000014151') is False  # Too short
        assert validate_target_id('ENSG000001415100') is False  # Too long
        assert validate_target_id('ENS00000141510') is False  # Wrong prefix
        assert validate_target_id('invalid') is False

    def test_validate_disease_id(self):
        """Test OpenTargets disease ID validation."""
        from biograph.integrations.opentargets import validate_disease_id

        # Valid disease IDs
        assert validate_disease_id('EFO_0000400') is True
        assert validate_disease_id('MONDO_0007254') is True

        # Invalid IDs
        assert validate_disease_id('EFO_') is False
        assert validate_disease_id('INVALID_123') is False
        assert validate_disease_id('efo_0000400') is False  # Wrong case

    def test_validate_chembl_id(self):
        """Test ChEMBL ID validation."""
        from biograph.integrations.chembl import validate_chembl_id

        # Valid ChEMBL IDs
        assert validate_chembl_id('CHEMBL1234') is True
        assert validate_chembl_id('CHEMBL1') is True

        # Invalid IDs
        assert validate_chembl_id('CHEMBL') is False
        assert validate_chembl_id('chembl1234') is False  # Wrong case
        assert validate_chembl_id('CHEM1234') is False  # Wrong prefix

    def test_validate_geonames_id(self):
        """Test GeoNames ID validation."""
        from biograph.integrations.geonames import validate_geonames_id

        # Valid GeoNames IDs
        assert validate_geonames_id('5128581') is True
        assert validate_geonames_id('1') is True

        # Invalid IDs
        assert validate_geonames_id('') is False
        assert validate_geonames_id('abc') is False
        assert validate_geonames_id('123abc') is False


class TestResolverIntegration:
    """Test resolver integration with cache."""

    @patch('biograph.integrations.opentargets.requests.post')
    def test_opentargets_target_resolver(self, mock_post, db_conn):
        """Test OpenTargets target resolver."""
        from biograph.integrations.opentargets import get_target_label

        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': {
                'target': {
                    'id': 'ENSG00000141510',
                    'approvedSymbol': 'TP53',
                    'approvedName': 'tumor protein p53',
                    'biotype': 'protein_coding'
                }
            }
        }
        mock_post.return_value = mock_response

        cursor = db_conn.cursor()

        # First call - cache miss, should hit API
        result = get_target_label(cursor, 'ENSG00000141510')

        assert result is not None
        assert result['label'] == 'TP53'
        assert result['gene_symbol'] == 'TP53'
        assert mock_post.called

        db_conn.commit()

        # Second call - cache hit, should NOT hit API
        mock_post.reset_mock()
        result2 = get_target_label(cursor, 'ENSG00000141510')

        assert result2 is not None
        assert result2['label'] == 'TP53'
        assert not mock_post.called  # Should use cache

    @patch('biograph.integrations.chembl.requests.get')
    def test_chembl_resolver(self, mock_get, db_conn):
        """Test ChEMBL molecule resolver."""
        from biograph.integrations.chembl import get_chembl_label

        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'molecule_chembl_id': 'CHEMBL1234',
            'pref_name': 'Aspirin',
            'molecule_type': 'Small molecule',
            'max_phase': 4
        }
        mock_get.return_value = mock_response

        cursor = db_conn.cursor()

        # Resolve
        result = get_chembl_label(cursor, 'CHEMBL1234')

        assert result is not None
        assert result['label'] == 'Aspirin'
        assert result['molecule_type'] == 'Small molecule'
        assert mock_get.called

    @patch('biograph.integrations.geonames.requests.get')
    def test_geonames_resolver(self, mock_get, db_conn):
        """Test GeoNames location resolver."""
        from biograph.integrations.geonames import get_geonames_label

        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'geonameId': '5128581',
            'name': 'New York',
            'countryCode': 'US',
            'countryName': 'United States',
            'fcode': 'PPL'
        }
        mock_get.return_value = mock_response

        cursor = db_conn.cursor()

        # Resolve
        result = get_geonames_label(cursor, '5128581')

        assert result is not None
        assert result['label'] == 'New York, United States'
        assert result['name'] == 'New York'
        assert result['country_code'] == 'US'
        assert mock_get.called
