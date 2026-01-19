"""
BioGraph MVP v8.3 - Storage & Projection Architecture

This module provides the abstraction layer for dual-storage architecture:
- Postgres (Neon) as System of Record (authoritative)
- Neo4j (Aura) as Read-Optimized Projection (derived)

Per Section 25 of the spec, Postgres is the ONLY source of truth.
Neo4j is an optional performance optimization that can be disabled.
"""

from biograph.storage.explanation_store import (
    ExplanationStore,
    ExplanationGraph,
    AssertionDetail,
    EvidenceDetail
)

__all__ = [
    'ExplanationStore',
    'ExplanationGraph',
    'AssertionDetail',
    'EvidenceDetail'
]
