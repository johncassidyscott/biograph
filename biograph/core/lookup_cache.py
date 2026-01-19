"""
BioGraph MVP v8.2 - Lookup Cache

Per Section 23 of the spec, this module provides a lightweight, disposable cache
for live-resolved labels from external APIs (OpenTargets, ChEMBL, GeoNames, Wikidata).

The cache is NOT truth; it's presentation layer only. Can be dropped and rebuilt
anytime without data loss.

Key Principles:
- Cache is disposable
- Default TTL: 30 days
- Live resolution on cache miss
- Fallback to ID on live fetch failure
- Cache does NOT affect linkage confidence
"""

from typing import Any, Dict, Optional
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class CacheSource(str, Enum):
    """Cache source enum (matches database enum)."""
    OPENTARGETS = "opentargets"
    CHEMBL = "chembl"
    GEONAMES = "geonames"
    WIKIDATA = "wikidata"


class LookupCache:
    """
    Lightweight cache for ID → label lookups.

    Per Section 23D, cache entries have:
    - cache_key: "{source}:{id}"
    - source: which external system
    - value_json: cached data (label + metadata)
    - TTL: 30 days default

    Usage:
        cache = LookupCache(cursor)

        # Try to get from cache
        data = cache.get('opentargets:ENSG00000141510')

        # Set cache entry
        cache.set('opentargets:ENSG00000141510', CacheSource.OPENTARGETS, {
            'label': 'TP53',
            'gene_symbol': 'TP53',
            'name': 'tumor protein p53'
        })
    """

    def __init__(self, cursor: Any):
        """
        Initialize cache with database cursor.

        Args:
            cursor: psycopg database cursor
        """
        self.cursor = cursor

    def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Get value from cache.

        Handles expiry automatically: expired entries are deleted and return None.
        Updates hit count and last_hit_at on successful hit.

        Args:
            cache_key: Cache key (format: "{source}:{id}")

        Returns:
            Cached value as dict, or None if not found/expired
        """
        try:
            self.cursor.execute("SELECT cache_get(%s)", (cache_key,))
            row = self.cursor.fetchone()

            if row and row[0]:
                logger.debug(f"Cache HIT: {cache_key}")
                return row[0]  # JSONB is returned as dict

            logger.debug(f"Cache MISS: {cache_key}")
            return None

        except Exception as e:
            logger.warning(f"Cache get error for {cache_key}: {e}")
            return None

    def set(
        self,
        cache_key: str,
        source: CacheSource,
        value: Dict[str, Any],
        ttl_days: int = 30
    ) -> None:
        """
        Set cache entry with TTL.

        Args:
            cache_key: Cache key (format: "{source}:{id}")
            source: Cache source enum
            value: Value to cache (will be stored as JSONB)
            ttl_days: Time to live in days (default: 30)
        """
        try:
            self.cursor.execute(
                "SELECT cache_set(%s, %s, %s, %s)",
                (cache_key, source.value, json.dumps(value), ttl_days)
            )
            logger.debug(f"Cache SET: {cache_key} (TTL: {ttl_days} days)")

        except Exception as e:
            logger.warning(f"Cache set error for {cache_key}: {e}")
            # Don't raise - cache failures should not break functionality

    def delete(self, cache_key: str) -> bool:
        """
        Delete cache entry.

        Args:
            cache_key: Cache key to delete

        Returns:
            True if entry was deleted, False if not found
        """
        try:
            self.cursor.execute("SELECT cache_delete(%s)", (cache_key,))
            row = self.cursor.fetchone()
            deleted = row[0] if row else False

            if deleted:
                logger.debug(f"Cache DELETE: {cache_key}")

            return deleted

        except Exception as e:
            logger.warning(f"Cache delete error for {cache_key}: {e}")
            return False

    def clear_source(self, source: CacheSource) -> int:
        """
        Clear all cache entries for a source.

        Args:
            source: Cache source to clear

        Returns:
            Number of entries deleted
        """
        try:
            self.cursor.execute("SELECT cache_clear_source(%s)", (source.value,))
            row = self.cursor.fetchone()
            count = row[0] if row else 0

            logger.info(f"Cache CLEAR: {source.value} ({count} entries deleted)")
            return count

        except Exception as e:
            logger.warning(f"Cache clear error for {source.value}: {e}")
            return 0

    def cleanup_expired(self) -> int:
        """
        Clean up expired cache entries.

        Should be run periodically (e.g., daily cron job).

        Returns:
            Number of expired entries deleted
        """
        try:
            self.cursor.execute("SELECT cache_cleanup_expired()")
            row = self.cursor.fetchone()
            count = row[0] if row else 0

            logger.info(f"Cache CLEANUP: {count} expired entries deleted")
            return count

        except Exception as e:
            logger.warning(f"Cache cleanup error: {e}")
            return 0

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with stats per source:
            {
                'opentargets': {
                    'total_entries': 150,
                    'expired_entries': 5,
                    'valid_entries': 145,
                    'total_hits': 1234,
                    'avg_hits': 8.23,
                    'oldest_entry': '2024-01-15T10:30:00Z',
                    'newest_entry': '2024-02-10T14:20:00Z'
                },
                ...
            }
        """
        try:
            self.cursor.execute("SELECT * FROM cache_stats()")
            rows = self.cursor.fetchall()

            stats = {}
            for row in rows:
                source, total, expired, valid, total_hits, avg_hits, oldest, newest = row
                stats[source] = {
                    'total_entries': total,
                    'expired_entries': expired,
                    'valid_entries': valid,
                    'total_hits': total_hits,
                    'avg_hits': float(avg_hits) if avg_hits else 0.0,
                    'oldest_entry': oldest.isoformat() if oldest else None,
                    'newest_entry': newest.isoformat() if newest else None,
                }

            return stats

        except Exception as e:
            logger.warning(f"Cache stats error: {e}")
            return {}


def make_cache_key(source: CacheSource, entity_id: str) -> str:
    """
    Make cache key from source and entity ID.

    Args:
        source: Cache source enum
        entity_id: Entity ID (e.g., 'ENSG00000141510')

    Returns:
        Cache key (e.g., 'opentargets:ENSG00000141510')
    """
    return f"{source.value}:{entity_id}"


# Convenience functions for common patterns

def cached_resolve(
    cursor: Any,
    source: CacheSource,
    entity_id: str,
    resolver_fn: callable,
    ttl_days: int = 30
) -> Optional[Dict[str, Any]]:
    """
    Resolve entity with caching.

    Pattern:
    1. Check cache
    2. If hit: return cached value
    3. If miss: call resolver_fn, cache result, return

    Args:
        cursor: Database cursor
        source: Cache source
        entity_id: Entity ID to resolve
        resolver_fn: Function that fetches live data (takes entity_id, returns dict)
        ttl_days: Cache TTL in days

    Returns:
        Resolved data dict, or None if resolution failed
    """
    cache = LookupCache(cursor)
    cache_key = make_cache_key(source, entity_id)

    # Try cache first
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Cache miss - resolve live
    try:
        logger.debug(f"Live resolve: {cache_key}")
        resolved = resolver_fn(entity_id)

        if resolved:
            # Cache the result
            cache.set(cache_key, source, resolved, ttl_days)
            return resolved
        else:
            logger.warning(f"Live resolve failed for {cache_key}")
            return None

    except Exception as e:
        logger.error(f"Live resolve error for {cache_key}: {e}")
        return None


def cached_resolve_with_fallback(
    cursor: Any,
    source: CacheSource,
    entity_id: str,
    resolver_fn: callable,
    fallback_label: Optional[str] = None,
    ttl_days: int = 30
) -> Dict[str, Any]:
    """
    Resolve entity with caching and fallback.

    Per Section 23H.3: "If live fetch fails, return ID as label (fallback)"

    Args:
        cursor: Database cursor
        source: Cache source
        entity_id: Entity ID to resolve
        resolver_fn: Function that fetches live data
        fallback_label: Fallback label (default: entity_id)
        ttl_days: Cache TTL in days

    Returns:
        Resolved data dict (always succeeds, falls back to ID if needed)
    """
    resolved = cached_resolve(cursor, source, entity_id, resolver_fn, ttl_days)

    if resolved:
        return resolved

    # Fallback to ID as label
    fallback = fallback_label or entity_id
    logger.warning(f"Using fallback label for {entity_id}: {fallback}")

    return {
        'id': entity_id,
        'label': fallback,
        'source': source.value,
        'is_fallback': True
    }
