"""
BioGraph MVP v8.3 - PostgresExplanationStore

Per Section 25A of the spec, Postgres is the SOLE SOURCE OF TRUTH.

This module implements ExplanationStore using Postgres as the backend.
This is the AUTHORITATIVE implementation - all data comes from Postgres.

RESPONSIBILITIES:
- Query explanation table for fixed-chain graphs
- Fetch assertion details with evidence
- Fetch evidence records with licensing
- Support time-travel queries (as_of_date)

This implementation is ALWAYS AVAILABLE (never optional).
"""

from typing import Any, Dict, List, Optional
from datetime import date
import logging

from biograph.storage.explanation_store import (
    ExplanationStore,
    ExplanationGraph,
    AssertionDetail,
    EvidenceDetail,
    Node,
    Edge,
    ConfidenceBand,
    LinkMethod
)

logger = logging.getLogger(__name__)


class PostgresExplanationStore(ExplanationStore):
    """
    Postgres-based ExplanationStore (authoritative, always available).

    Queries:
    - explanation table for graph structure
    - assertion + assertion_evidence for details
    - evidence table for provenance

    Per Section 25A: This is the source of truth.
    """

    def __init__(self, cursor: Any):
        """
        Initialize Postgres store.

        Args:
            cursor: Database cursor (psycopg connection)
        """
        self.cursor = cursor
        logger.debug("PostgresExplanationStore initialized")

    def get_explanation(
        self,
        issuer_id: str,
        as_of_date: date
    ) -> Optional[ExplanationGraph]:
        """
        Retrieve explanation graph from Postgres.

        Queries explanation table for fixed-chain graph:
        Issuer → DrugProgram → Target → Disease

        Args:
            issuer_id: Issuer canonical ID
            as_of_date: Temporal context

        Returns:
            ExplanationGraph with nodes and edges, or None if no explanation
        """
        try:
            logger.debug(f"Fetching explanation for {issuer_id} as of {as_of_date}")

            # Query explanation table
            # Note: This assumes explanation table exists with materialized graph data
            # For MVP, we'll query assertions directly and build graph

            nodes = []
            edges = []

            # Get issuer node with company name
            self.cursor.execute("""
                SELECT i.issuer_id, c.name
                FROM issuer i
                LEFT JOIN company c ON i.primary_cik = c.cik
                WHERE i.issuer_id = %s
            """, (issuer_id,))

            issuer_row = self.cursor.fetchone()
            if not issuer_row:
                logger.warning(f"Issuer {issuer_id} not found")
                return None

            issuer_name = issuer_row[1] if issuer_row[1] else issuer_id

            nodes.append(Node(
                node_id=issuer_id,
                node_type='issuer',
                label=issuer_name,
                as_of_date=as_of_date
            ))

            # Get drug programs for issuer
            self.cursor.execute("""
                SELECT DISTINCT dp.drug_program_id, dp.name
                FROM drug_program dp
                WHERE dp.issuer_id = %s
                AND dp.deleted_at IS NULL
            """, (issuer_id,))

            drug_programs = self.cursor.fetchall()

            for dp_row in drug_programs:
                drug_program_id = dp_row[0]
                drug_program_name = dp_row[1]

                # Add DrugProgram node
                nodes.append(Node(
                    node_id=drug_program_id,
                    node_type='drug_program',
                    label=drug_program_name or drug_program_id,
                    as_of_date=as_of_date
                ))

                # Add HAS_PROGRAM edge
                edges.append(Edge(
                    edge_type='HAS_PROGRAM',
                    source_id=issuer_id,
                    target_id=drug_program_id,
                    as_of_date=as_of_date,
                    confidence_band=ConfidenceBand.HIGH,  # Deterministic
                    confidence_score=1.0,
                    link_method=LinkMethod.DETERMINISTIC,
                    evidence_count=0,  # Structural relationship
                    assertion_ids=[]
                ))

                # Get targets for drug program with target names
                self.cursor.execute("""
                    SELECT DISTINCT a.object_id, a.assertion_id,
                           a.computed_confidence, t.name
                    FROM assertion a
                    LEFT JOIN target t ON a.object_id = t.target_id
                    WHERE a.subject_id = %s
                    AND a.subject_type = 'drug_program'
                    AND a.predicate = 'targets'
                    AND a.object_type = 'target'
                    AND a.asserted_at <= %s
                    AND a.retracted_at IS NULL
                """, (drug_program_id, as_of_date))

                target_assertions = self.cursor.fetchall()

                for target_row in target_assertions:
                    target_id = target_row[0]
                    assertion_id = target_row[1]
                    computed_conf = target_row[2]
                    target_name = target_row[3] if target_row[3] else target_id

                    # Add Target node (if not already added)
                    if not any(n.node_id == target_id for n in nodes):
                        nodes.append(Node(
                            node_id=target_id,
                            node_type='target',
                            label=target_name,
                            as_of_date=as_of_date
                        ))

                    # Get evidence count
                    self.cursor.execute("""
                        SELECT COUNT(*) FROM assertion_evidence
                        WHERE assertion_id = %s
                    """, (assertion_id,))
                    evidence_count = self.cursor.fetchone()[0]

                    # Add TARGETS edge
                    edges.append(Edge(
                        edge_type='TARGETS',
                        source_id=drug_program_id,
                        target_id=target_id,
                        as_of_date=as_of_date,
                        confidence_band=ConfidenceBand.MEDIUM if computed_conf and computed_conf >= 0.5 else ConfidenceBand.LOW,
                        confidence_score=computed_conf,
                        link_method=LinkMethod.STRUCTURED_DATA,
                        evidence_count=evidence_count,
                        assertion_ids=[assertion_id]
                    ))

                    # Get diseases for target with disease names
                    self.cursor.execute("""
                        SELECT DISTINCT a.object_id, a.assertion_id,
                               a.computed_confidence, d.name
                        FROM assertion a
                        LEFT JOIN disease d ON a.object_id = d.disease_id
                        WHERE a.subject_id = %s
                        AND a.subject_type = 'target'
                        AND a.predicate = 'indicated_for'
                        AND a.object_type = 'disease'
                        AND a.asserted_at <= %s
                        AND a.retracted_at IS NULL
                    """, (target_id, as_of_date))

                    disease_assertions = self.cursor.fetchall()

                    for disease_row in disease_assertions:
                        disease_id = disease_row[0]
                        disease_assertion_id = disease_row[1]
                        disease_computed_conf = disease_row[2]
                        disease_name = disease_row[3] if disease_row[3] else disease_id

                        # Add Disease node (if not already added)
                        if not any(n.node_id == disease_id for n in nodes):
                            nodes.append(Node(
                                node_id=disease_id,
                                node_type='disease',
                                label=disease_name,
                                as_of_date=as_of_date
                            ))

                        # Get evidence count for disease assertion
                        self.cursor.execute("""
                            SELECT COUNT(*) FROM assertion_evidence
                            WHERE assertion_id = %s
                        """, (disease_assertion_id,))
                        disease_evidence_count = self.cursor.fetchone()[0]

                        # Add INDICATED_FOR edge
                        edges.append(Edge(
                            edge_type='INDICATED_FOR',
                            source_id=target_id,
                            target_id=disease_id,
                            as_of_date=as_of_date,
                            confidence_band=ConfidenceBand.MEDIUM if disease_computed_conf and disease_computed_conf >= 0.5 else ConfidenceBand.LOW,
                            confidence_score=disease_computed_conf,
                            link_method=LinkMethod.STRUCTURED_DATA,
                            evidence_count=disease_evidence_count,
                            assertion_ids=[disease_assertion_id]
                        ))

            if not nodes or len(nodes) == 1:  # Only issuer node
                logger.debug(f"No explanation found for {issuer_id}")
                return None

            logger.debug(
                f"Built explanation graph: {len(nodes)} nodes, {len(edges)} edges"
            )

            return ExplanationGraph(
                issuer_id=issuer_id,
                as_of_date=as_of_date,
                nodes=nodes,
                edges=edges,
                source='postgres'
            )

        except Exception as e:
            logger.error(f"Error fetching explanation from Postgres: {e}")
            return None

    def get_assertion_details(
        self,
        assertion_id: int
    ) -> Optional[AssertionDetail]:
        """
        Fetch assertion details from Postgres.

        ALWAYS fetched from Postgres (authoritative).

        Args:
            assertion_id: Assertion ID

        Returns:
            AssertionDetail with evidence list, or None if not found
        """
        try:
            logger.debug(f"Fetching assertion details for {assertion_id}")

            # Get assertion
            self.cursor.execute("""
                SELECT
                    assertion_id,
                    subject_id,
                    subject_type,
                    predicate,
                    object_id,
                    object_type,
                    confidence_band,
                    confidence_score,
                    link_method,
                    link_method_detail,
                    valid_from,
                    valid_until,
                    created_at,
                    created_by
                FROM assertion
                WHERE assertion_id = %s
                AND deleted_at IS NULL
            """, (assertion_id,))

            row = self.cursor.fetchone()
            if not row:
                logger.warning(f"Assertion {assertion_id} not found")
                return None

            # Get evidence
            self.cursor.execute("""
                SELECT
                    e.evidence_id,
                    e.source_system,
                    e.source_record_id,
                    e.observed_at,
                    e.license,
                    e.uri,
                    e.snippet,
                    e.created_at,
                    e.created_by
                FROM evidence e
                JOIN assertion_evidence ae ON ae.evidence_id = e.evidence_id
                WHERE ae.assertion_id = %s
                AND e.deleted_at IS NULL
                ORDER BY e.observed_at DESC
            """, (assertion_id,))

            evidence_rows = self.cursor.fetchall()

            evidence_list = [
                EvidenceDetail(
                    evidence_id=ev[0],
                    source_system=ev[1],
                    source_record_id=ev[2],
                    observed_at=ev[3],
                    license=ev[4],
                    uri=ev[5],
                    snippet=ev[6],
                    created_at=ev[7],
                    created_by=ev[8]
                )
                for ev in evidence_rows
            ]

            return AssertionDetail(
                assertion_id=row[0],
                subject_id=row[1],
                subject_type=row[2],
                predicate=row[3],
                object_id=row[4],
                object_type=row[5],
                confidence_band=ConfidenceBand(row[6]),
                confidence_score=row[7],
                link_method=LinkMethod(row[8]),
                link_method_detail=row[9],
                valid_from=row[10],
                valid_until=row[11],
                evidence=evidence_list,
                created_at=row[12],
                created_by=row[13]
            )

        except Exception as e:
            logger.error(f"Error fetching assertion details: {e}")
            return None

    def get_evidence(
        self,
        evidence_id: int
    ) -> Optional[EvidenceDetail]:
        """
        Fetch evidence record from Postgres.

        ALWAYS fetched from Postgres (authoritative).
        Per Section 25C: Evidence text, licensing NEVER in Neo4j.

        Args:
            evidence_id: Evidence ID

        Returns:
            EvidenceDetail, or None if not found
        """
        try:
            logger.debug(f"Fetching evidence {evidence_id}")

            self.cursor.execute("""
                SELECT
                    evidence_id,
                    source_system,
                    source_record_id,
                    observed_at,
                    license,
                    uri,
                    snippet,
                    created_at,
                    created_by
                FROM evidence
                WHERE evidence_id = %s
                AND deleted_at IS NULL
            """, (evidence_id,))

            row = self.cursor.fetchone()
            if not row:
                logger.warning(f"Evidence {evidence_id} not found")
                return None

            return EvidenceDetail(
                evidence_id=row[0],
                source_system=row[1],
                source_record_id=row[2],
                observed_at=row[3],
                license=row[4],
                uri=row[5],
                snippet=row[6],
                created_at=row[7],
                created_by=row[8]
            )

        except Exception as e:
            logger.error(f"Error fetching evidence: {e}")
            return None

    def get_store_name(self) -> str:
        """
        Get store implementation name.

        Returns:
            'postgres'
        """
        return 'postgres'

    def is_available(self) -> bool:
        """
        Check if Postgres is available.

        Postgres is ALWAYS required (per Section 25A).

        Returns:
            True if Postgres connection is healthy
        """
        try:
            self.cursor.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Postgres health check failed: {e}")
            return False
