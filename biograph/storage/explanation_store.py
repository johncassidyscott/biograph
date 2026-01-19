"""
BioGraph MVP v8.3 - ExplanationStore Abstraction

Per Section 25G of the spec, this module defines the ExplanationStore interface
for retrieving explanation graphs from either Postgres or Neo4j.

DESIGN PRINCIPLES (LOCKED):
1. Postgres is the ONLY source of truth
2. Neo4j is an optional performance optimization
3. API must work with Postgres-only (Neo4j disabled)
4. Evidence details ALWAYS fetched from Postgres
5. No write-back from Neo4j to Postgres

ExplanationStore provides:
- get_explanation(): Retrieve explanation graph for issuer/as_of_date
- get_assertion_details(): Fetch assertion + evidence from Postgres
- get_evidence(): Fetch evidence record from Postgres
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import date
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ConfidenceBand(Enum):
    """Confidence band for assertion (user-facing)."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LinkMethod(Enum):
    """Link method for assertion (how it was created)."""
    DETERMINISTIC = "DETERMINISTIC"
    CURATED = "CURATED"
    ML_SUGGESTED_APPROVED = "ML_SUGGESTED_APPROVED"


@dataclass
class Node:
    """
    Node in explanation graph.

    Represents a canonical entity (Issuer, DrugProgram, Target, Disease).
    """
    node_id: str              # Canonical ID (issuer_id, drug_program_id, target_id, disease_id)
    node_type: str            # 'issuer', 'drug_program', 'target', 'disease'
    label: Optional[str]      # Human-readable label (resolved or ID fallback)
    as_of_date: date          # Temporal context


@dataclass
class Edge:
    """
    Edge in explanation graph.

    Represents a relationship between nodes (HAS_PROGRAM, TARGETS, INDICATED_FOR).
    """
    edge_type: str                      # 'HAS_PROGRAM', 'TARGETS', 'INDICATED_FOR'
    source_id: str                      # Source node canonical ID
    target_id: str                      # Target node canonical ID
    as_of_date: date                    # Temporal context
    confidence_band: ConfidenceBand     # HIGH, MEDIUM, LOW
    confidence_score: Optional[float]   # Optional score for sorting
    link_method: LinkMethod             # How assertion was created
    evidence_count: int                 # Count of evidence records
    assertion_ids: List[int]            # Assertion IDs for Postgres lookup


@dataclass
class ExplanationGraph:
    """
    Explanation graph for an issuer at a specific as_of_date.

    Represents the fixed-chain explanation:
    Issuer → DrugProgram → Target → Disease
    """
    issuer_id: str
    as_of_date: date
    nodes: List[Node]         # All nodes in graph
    edges: List[Edge]         # All edges in graph
    source: str               # 'postgres' or 'neo4j' (for debugging)


@dataclass
class EvidenceDetail:
    """
    Evidence record from Postgres (ALWAYS from Postgres, never Neo4j).

    Per Section 25C: Evidence text, snippets, and licensing NEVER stored in Neo4j.
    """
    evidence_id: int
    source_system: str
    source_record_id: str
    observed_at: date
    license: str
    uri: str
    snippet: Optional[str]
    created_at: Any           # timestamp
    created_by: Optional[str]


@dataclass
class AssertionDetail:
    """
    Assertion details from Postgres (ALWAYS from Postgres, never Neo4j).

    Includes full assertion metadata and linked evidence.
    """
    assertion_id: int
    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    confidence_band: ConfidenceBand
    confidence_score: Optional[float]
    link_method: LinkMethod
    link_method_detail: Optional[str]
    valid_from: date
    valid_until: Optional[date]
    evidence: List[EvidenceDetail]
    created_at: Any           # timestamp
    created_by: Optional[str]


class ExplanationStore(ABC):
    """
    Abstract interface for retrieving explanation graphs.

    Implementations:
    - PostgresExplanationStore: Authoritative source of truth
    - Neo4jExplanationStore: Read-optimized projection (optional)

    Per Section 25D: Evidence and audit details MUST be fetched from Postgres.
    """

    @abstractmethod
    def get_explanation(
        self,
        issuer_id: str,
        as_of_date: date
    ) -> Optional[ExplanationGraph]:
        """
        Retrieve explanation graph for issuer at as_of_date.

        Returns fixed-chain explanation:
        Issuer → DrugProgram → Target → Disease

        Args:
            issuer_id: Issuer canonical ID
            as_of_date: Temporal context (query as of this date)

        Returns:
            ExplanationGraph with nodes and edges, or None if no explanation
        """
        pass

    @abstractmethod
    def get_assertion_details(
        self,
        assertion_id: int
    ) -> Optional[AssertionDetail]:
        """
        Fetch assertion details from Postgres.

        ALWAYS fetched from Postgres (never Neo4j).

        Args:
            assertion_id: Assertion ID

        Returns:
            AssertionDetail with evidence list, or None if not found
        """
        pass

    @abstractmethod
    def get_evidence(
        self,
        evidence_id: int
    ) -> Optional[EvidenceDetail]:
        """
        Fetch evidence record from Postgres.

        ALWAYS fetched from Postgres (never Neo4j).

        Per Section 25C: Evidence text, snippets, licensing NEVER in Neo4j.

        Args:
            evidence_id: Evidence ID

        Returns:
            EvidenceDetail, or None if not found
        """
        pass

    @abstractmethod
    def get_store_name(self) -> str:
        """
        Get store implementation name (for logging/debugging).

        Returns:
            Store name ('postgres' or 'neo4j')
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if store is available.

        For Postgres: Always True (required)
        For Neo4j: May be False (optional, can fail)

        Returns:
            True if store is available and healthy
        """
        pass


class ExplanationStoreFactory:
    """
    Factory for creating ExplanationStore instances.

    Supports:
    - Postgres-only mode (safe default)
    - Neo4j fast-path with Postgres fallback

    Per Section 25F: GRAPH_BACKEND=postgres|neo4j
    """

    @staticmethod
    def create_store(
        cursor: Any,
        backend: str = "postgres",
        neo4j_config: Optional[Dict[str, str]] = None
    ) -> ExplanationStore:
        """
        Create ExplanationStore instance.

        Args:
            cursor: Database cursor (for Postgres)
            backend: 'postgres' or 'neo4j'
            neo4j_config: Optional Neo4j connection config (uri, user, password)

        Returns:
            ExplanationStore implementation

        Raises:
            ValueError: If backend is invalid
        """
        from biograph.storage.postgres_store import PostgresExplanationStore

        if backend == "postgres":
            logger.info("Using PostgresExplanationStore (authoritative)")
            return PostgresExplanationStore(cursor)

        elif backend == "neo4j":
            if not neo4j_config:
                logger.warning(
                    "Neo4j backend requested but no config provided, falling back to Postgres"
                )
                return PostgresExplanationStore(cursor)

            try:
                from biograph.storage.neo4j_store import Neo4jExplanationStore

                logger.info("Using Neo4jExplanationStore (fast path)")
                return Neo4jExplanationStore(
                    postgres_cursor=cursor,
                    neo4j_uri=neo4j_config['uri'],
                    neo4j_user=neo4j_config['user'],
                    neo4j_password=neo4j_config['password']
                )
            except ImportError:
                logger.warning(
                    "Neo4j store not available (module not found), falling back to Postgres"
                )
                return PostgresExplanationStore(cursor)
            except Exception as e:
                logger.error(f"Failed to create Neo4j store: {e}, falling back to Postgres")
                return PostgresExplanationStore(cursor)

        else:
            raise ValueError(f"Invalid backend: {backend}. Must be 'postgres' or 'neo4j'")


def create_explanation_store_from_env(cursor: Any) -> ExplanationStore:
    """
    Create ExplanationStore from environment variables.

    Reads:
    - GRAPH_BACKEND (default: 'postgres')
    - NEO4J_URI
    - NEO4J_USER
    - NEO4J_PASSWORD

    Args:
        cursor: Database cursor (for Postgres)

    Returns:
        ExplanationStore implementation
    """
    import os

    backend = os.getenv('GRAPH_BACKEND', 'postgres').lower()

    neo4j_config = None
    if backend == 'neo4j':
        neo4j_uri = os.getenv('NEO4J_URI')
        neo4j_user = os.getenv('NEO4J_USER')
        neo4j_password = os.getenv('NEO4J_PASSWORD')

        if neo4j_uri and neo4j_user and neo4j_password:
            neo4j_config = {
                'uri': neo4j_uri,
                'user': neo4j_user,
                'password': neo4j_password
            }
        else:
            logger.warning(
                "Neo4j backend requested but config incomplete "
                "(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD required), "
                "falling back to Postgres"
            )
            backend = 'postgres'

    return ExplanationStoreFactory.create_store(cursor, backend, neo4j_config)
