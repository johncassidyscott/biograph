#!/usr/bin/env python3
"""
Entity Resolution Service - Canonical entity resolution for BioGraph.

This is the SINGLE SOURCE OF TRUTH for resolving entity names to canonical IDs.
All loaders MUST use this service instead of creating entities directly.

Resolution Strategy:
1. Exact match against existing entities (canonical_id, name, aliases)
2. Normalized match (lowercase, strip punctuation, remove suffixes)
3. Fuzzy match (Levenshtein distance > 90% similarity)
4. API resolution (ChEMBL, PubChem, SEC for unknown entities)
5. Create new entity only if no match found

Confidence Levels:
- 1.0: Exact canonical ID match (CHEMBL:123, MESH:D001234)
- 0.95: Exact name match with existing entity
- 0.90: Normalized match (case/punctuation differences)
- 0.80: Fuzzy match (high string similarity)
- 0.70: API-resolved match
- 0.50: New entity created (no existing match)
"""

from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List
from difflib import SequenceMatcher
import re
from app.db import get_conn


@dataclass
class ResolvedEntity:
    """Result of entity resolution"""
    entity_id: int  # Database entity.id
    canonical_id: str  # e.g., CHEMBL:CHEMBL123
    name: str  # Canonical name
    confidence: float  # 0.0-1.0
    match_type: str  # exact_id, exact_name, normalized, fuzzy, api, created
    source: str  # Which resolver found it


class EntityResolver:
    """
    Central entity resolution service.
    Maintains in-memory lookup tables for fast resolution.
    """

    def __init__(self):
        self.drugs: Dict[str, Tuple[int, str, str]] = {}  # name_lower -> (id, canonical_id, name)
        self.diseases: Dict[str, Tuple[int, str, str]] = {}
        self.companies: Dict[str, Tuple[int, str, str]] = {}
        self.targets: Dict[str, Tuple[int, str, str]] = {}
        self.aliases: Dict[str, List[Tuple[int, str, str, str]]] = {}  # alias_lower -> [(id, canonical_id, name, kind)]
        self._loaded = False

    def load_lookup_tables(self) -> None:
        """Load all entities and aliases into memory for fast lookup"""
        if self._loaded:
            return

        print("Loading entity lookup tables...")

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Load all entities by kind
                cur.execute("""
                    SELECT id, kind, canonical_id, name
                    FROM entity
                    ORDER BY kind, name
                """)

                for row in cur.fetchall():
                    eid, kind, canonical_id, name = row
                    name_lower = name.lower()

                    if kind == "drug":
                        self.drugs[name_lower] = (eid, canonical_id, name)
                    elif kind == "disease":
                        self.diseases[name_lower] = (eid, canonical_id, name)
                    elif kind == "company":
                        self.companies[name_lower] = (eid, canonical_id, name)
                    elif kind == "target":
                        self.targets[name_lower] = (eid, canonical_id, name)

                # Load all aliases
                cur.execute("""
                    SELECT e.id, e.kind, e.canonical_id, e.name, a.alias
                    FROM entity e
                    JOIN alias a ON a.entity_id = e.id
                """)

                for row in cur.fetchall():
                    eid, kind, canonical_id, name, alias = row
                    alias_lower = alias.lower()

                    if alias_lower not in self.aliases:
                        self.aliases[alias_lower] = []
                    self.aliases[alias_lower].append((eid, canonical_id, name, kind))

        total = len(self.drugs) + len(self.diseases) + len(self.companies) + len(self.targets)
        print(f"✓ Loaded {total:,} entities, {len(self.aliases):,} aliases")
        self._loaded = True

    def normalize_name(self, name: str) -> str:
        """
        Normalize entity name for matching.
        - Lowercase
        - Remove extra whitespace
        - Remove common punctuation
        - Remove company suffixes (Inc, LLC, etc.)
        """
        # Lowercase
        normalized = name.lower()

        # Remove common company suffixes
        suffixes = [
            r'\s+inc\.?$', r'\s+llc\.?$', r'\s+ltd\.?$', r'\s+corporation$',
            r'\s+corp\.?$', r'\s+company$', r'\s+co\.?$', r'\s+a/s$',
            r'\s+ab$', r'\s+gmbh$', r'\s+s\.a\.?$', r'\s+plc$',
            r',\s+inc\.?$', r',\s+llc\.?$', r',\s+ltd\.?$'
        ]
        for suffix in suffixes:
            normalized = re.sub(suffix, '', normalized)

        # Remove "the" prefix
        normalized = re.sub(r'^the\s+', '', normalized)

        # Remove extra punctuation and whitespace
        normalized = re.sub(r'[^\w\s-]', ' ', normalized)
        normalized = ' '.join(normalized.split())

        return normalized

    def fuzzy_match(self, name: str, candidates: Dict[str, Tuple]) -> Optional[Tuple[str, float]]:
        """
        Find best fuzzy match from candidates.
        Returns (matched_name, similarity_score) or None if no good match.
        Threshold: 90% similarity
        """
        name_normalized = self.normalize_name(name)
        best_match = None
        best_score = 0.0

        for candidate_name in candidates.keys():
            candidate_normalized = self.normalize_name(candidate_name)
            similarity = SequenceMatcher(None, name_normalized, candidate_normalized).ratio()

            if similarity > best_score:
                best_score = similarity
                best_match = candidate_name

        if best_score >= 0.90:
            return (best_match, best_score)
        return None

    def resolve_drug(self, name: str, chembl_id: Optional[str] = None) -> ResolvedEntity:
        """
        Resolve drug name to canonical entity.

        Priority:
        1. If chembl_id provided, use it (confidence 1.0)
        2. Exact name match in drugs table
        3. Exact match in aliases
        4. Fuzzy match
        5. Try API resolution (PubChem, ChEMBL search)
        6. Create new entity
        """
        self.load_lookup_tables()

        # 1. Canonical ID match
        if chembl_id:
            canonical_id = f"CHEMBL:{chembl_id}" if not chembl_id.startswith("CHEMBL:") else chembl_id
            # Check if exists
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name FROM entity WHERE kind = 'drug' AND canonical_id = %s",
                        (canonical_id,)
                    )
                    result = cur.fetchone()
                    if result:
                        return ResolvedEntity(
                            entity_id=result[0],
                            canonical_id=canonical_id,
                            name=result[1],
                            confidence=1.0,
                            match_type="exact_id",
                            source="canonical"
                        )
                    # Doesn't exist yet, create it
                    return self._create_drug_entity(name, canonical_id, 1.0, "canonical")

        # 2. Exact name match
        name_lower = name.lower()
        if name_lower in self.drugs:
            eid, canonical_id, canonical_name = self.drugs[name_lower]
            return ResolvedEntity(
                entity_id=eid,
                canonical_id=canonical_id,
                name=canonical_name,
                confidence=0.95,
                match_type="exact_name",
                source="lookup"
            )

        # 3. Alias match
        if name_lower in self.aliases:
            matches = [m for m in self.aliases[name_lower] if m[3] == "drug"]
            if matches:
                eid, canonical_id, canonical_name, _ = matches[0]
                return ResolvedEntity(
                    entity_id=eid,
                    canonical_id=canonical_id,
                    name=canonical_name,
                    confidence=0.95,
                    match_type="exact_alias",
                    source="alias"
                )

        # 4. Fuzzy match
        fuzzy = self.fuzzy_match(name, self.drugs)
        if fuzzy:
            matched_name, score = fuzzy
            eid, canonical_id, canonical_name = self.drugs[matched_name]
            return ResolvedEntity(
                entity_id=eid,
                canonical_id=canonical_id,
                name=canonical_name,
                confidence=score * 0.85,  # Discount fuzzy matches
                match_type="fuzzy",
                source="fuzzy_match"
            )

        # 5. TODO: API resolution via ChEMBL/PubChem name search
        # For now, skip to avoid rate limits during build

        # 6. Create new entity with generated ID
        normalized = self.normalize_name(name)
        canonical_id = f"DRUG:{normalized.replace(' ', '_')}"
        return self._create_drug_entity(name, canonical_id, 0.50, "created")

    def _create_drug_entity(self, name: str, canonical_id: str, confidence: float, match_type: str) -> ResolvedEntity:
        """Create new drug entity in database"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO entity (kind, canonical_id, name)
                    VALUES ('drug', %s, %s)
                    ON CONFLICT (kind, canonical_id) DO UPDATE
                      SET name = EXCLUDED.name, updated_at = NOW()
                    RETURNING id
                    """,
                    (canonical_id, name)
                )
                entity_id = cur.fetchone()['id']
            conn.commit()

        # Add to lookup table
        self.drugs[name.lower()] = (entity_id, canonical_id, name)

        return ResolvedEntity(
            entity_id=entity_id,
            canonical_id=canonical_id,
            name=name,
            confidence=confidence,
            match_type=match_type,
            source="resolver"
        )

    def resolve_disease(self, name: str, mesh_id: Optional[str] = None) -> ResolvedEntity:
        """
        Resolve disease name to canonical entity.
        Similar strategy to drugs but uses MeSH as canonical source.
        """
        self.load_lookup_tables()

        # 1. Canonical MeSH ID
        if mesh_id:
            canonical_id = f"MESH:{mesh_id}" if not mesh_id.startswith("MESH:") else mesh_id
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name FROM entity WHERE kind = 'disease' AND canonical_id = %s",
                        (canonical_id,)
                    )
                    result = cur.fetchone()
                    if result:
                        return ResolvedEntity(
                            entity_id=result[0],
                            canonical_id=canonical_id,
                            name=result[1],
                            confidence=1.0,
                            match_type="exact_id",
                            source="canonical"
                        )

        # 2. Exact name match
        name_lower = name.lower()
        if name_lower in self.diseases:
            eid, canonical_id, canonical_name = self.diseases[name_lower]
            return ResolvedEntity(
                entity_id=eid,
                canonical_id=canonical_id,
                name=canonical_name,
                confidence=0.95,
                match_type="exact_name",
                source="lookup"
            )

        # 3. Alias match
        if name_lower in self.aliases:
            matches = [m for m in self.aliases[name_lower] if m[3] == "disease"]
            if matches:
                eid, canonical_id, canonical_name, _ = matches[0]
                return ResolvedEntity(
                    entity_id=eid,
                    canonical_id=canonical_id,
                    name=canonical_name,
                    confidence=0.95,
                    match_type="exact_alias",
                    source="alias"
                )

        # 4. Fuzzy match
        fuzzy = self.fuzzy_match(name, self.diseases)
        if fuzzy:
            matched_name, score = fuzzy
            eid, canonical_id, canonical_name = self.diseases[matched_name]
            return ResolvedEntity(
                entity_id=eid,
                canonical_id=canonical_id,
                name=canonical_name,
                confidence=score * 0.85,
                match_type="fuzzy",
                source="fuzzy_match"
            )

        # 5. Create new entity (low confidence - not in MeSH)
        normalized = self.normalize_name(name)
        canonical_id = f"CONDITION:{normalized.replace(' ', '_')}"
        return self._create_disease_entity(name, canonical_id, 0.40, "created")

    def _create_disease_entity(self, name: str, canonical_id: str, confidence: float, match_type: str) -> ResolvedEntity:
        """Create new disease entity in database"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO entity (kind, canonical_id, name)
                    VALUES ('disease', %s, %s)
                    ON CONFLICT (kind, canonical_id) DO UPDATE
                      SET name = EXCLUDED.name, updated_at = NOW()
                    RETURNING id
                    """,
                    (canonical_id, name)
                )
                entity_id = cur.fetchone()['id']
            conn.commit()

        self.diseases[name.lower()] = (entity_id, canonical_id, name)

        return ResolvedEntity(
            entity_id=entity_id,
            canonical_id=canonical_id,
            name=name,
            confidence=confidence,
            match_type=match_type,
            source="resolver"
        )

    def resolve_company(self, name: str, cik: Optional[str] = None) -> ResolvedEntity:
        """
        Resolve company name to canonical entity.
        Uses SEC CIK as canonical ID where available.
        """
        self.load_lookup_tables()

        # 1. Canonical CIK
        if cik:
            canonical_id = f"CIK:{cik}" if not cik.startswith("CIK:") else cik
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name FROM entity WHERE kind = 'company' AND canonical_id = %s",
                        (canonical_id,)
                    )
                    result = cur.fetchone()
                    if result:
                        return ResolvedEntity(
                            entity_id=result[0],
                            canonical_id=canonical_id,
                            name=result[1],
                            confidence=1.0,
                            match_type="exact_id",
                            source="canonical"
                        )

        # 2-4. Same pattern as drugs/diseases
        name_lower = name.lower()
        if name_lower in self.companies:
            eid, canonical_id, canonical_name = self.companies[name_lower]
            return ResolvedEntity(
                entity_id=eid,
                canonical_id=canonical_id,
                name=canonical_name,
                confidence=0.95,
                match_type="exact_name",
                source="lookup"
            )

        if name_lower in self.aliases:
            matches = [m for m in self.aliases[name_lower] if m[3] == "company"]
            if matches:
                eid, canonical_id, canonical_name, _ = matches[0]
                return ResolvedEntity(
                    entity_id=eid,
                    canonical_id=canonical_id,
                    name=canonical_name,
                    confidence=0.95,
                    match_type="exact_alias",
                    source="alias"
                )

        fuzzy = self.fuzzy_match(name, self.companies)
        if fuzzy:
            matched_name, score = fuzzy
            eid, canonical_id, canonical_name = self.companies[matched_name]
            return ResolvedEntity(
                entity_id=eid,
                canonical_id=canonical_id,
                name=canonical_name,
                confidence=score * 0.85,
                match_type="fuzzy",
                source="fuzzy_match"
            )

        # Create new entity
        normalized = self.normalize_name(name)
        canonical_id = f"COMPANY:{normalized.replace(' ', '_')}"
        return self._create_company_entity(name, canonical_id, 0.60, "created")

    def _create_company_entity(self, name: str, canonical_id: str, confidence: float, match_type: str) -> ResolvedEntity:
        """Create new company entity in database"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO entity (kind, canonical_id, name)
                    VALUES ('company', %s, %s)
                    ON CONFLICT (kind, canonical_id) DO UPDATE
                      SET name = EXCLUDED.name, updated_at = NOW()
                    RETURNING id
                    """,
                    (canonical_id, name)
                )
                entity_id = cur.fetchone()['id']
            conn.commit()

        self.companies[name.lower()] = (entity_id, canonical_id, name)

        return ResolvedEntity(
            entity_id=entity_id,
            canonical_id=canonical_id,
            name=name,
            confidence=confidence,
            match_type=match_type,
            source="resolver"
        )


# Global singleton resolver instance
_resolver: Optional[EntityResolver] = None


def get_resolver() -> EntityResolver:
    """Get the global entity resolver instance"""
    global _resolver
    if _resolver is None:
        _resolver = EntityResolver()
    return _resolver
