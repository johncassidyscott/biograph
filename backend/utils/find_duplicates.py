#!/usr/bin/env python3
"""
Find potential duplicate entities in the knowledge graph.

Strategies:
1. Same name, different canonical_id (e.g., CHEMBL vs CTG_INT)
2. High string similarity (fuzzy matching)
3. Same aliases pointing to different entities
4. Network analysis (entities with identical relationship patterns)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from typing import List, Tuple, Dict
from difflib import SequenceMatcher
from backend.app.db import get_conn


def normalize_name(name: str) -> str:
    """Normalize for comparison"""
    import re
    n = name.lower()
    n = re.sub(r'[^\w\s]', ' ', n)
    n = ' '.join(n.split())
    return n


def find_exact_name_duplicates(kind: str = None) -> List[Tuple[str, List[Tuple]]]:
    """
    Find entities with identical names but different canonical IDs.
    This is the most obvious form of duplication.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT name, kind, canonical_id, id
                FROM entity
                {}
                ORDER BY name, kind
            """.format("WHERE kind = %s" if kind else "")

            params = (kind,) if kind else ()
            cur.execute(query, params)

            # Group by normalized name
            groups: Dict[str, List[Tuple]] = {}
            for row in cur.fetchall():
                name, kind, canonical_id, entity_id = row
                normalized = normalize_name(name)
                key = f"{kind}:{normalized}"

                if key not in groups:
                    groups[key] = []
                groups[key].append((name, kind, canonical_id, entity_id))

            # Filter to only duplicates
            duplicates = [(key, entities) for key, entities in groups.items() if len(entities) > 1]

            return duplicates


def find_fuzzy_duplicates(kind: str, threshold: float = 0.90) -> List[Tuple[Tuple, Tuple, float]]:
    """
    Find entities with high string similarity that might be duplicates.
    This catches typos, slight variations, etc.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, canonical_id, name FROM entity WHERE kind = %s ORDER BY name",
                (kind,)
            )

            entities = cur.fetchall()

    # Compare all pairs (this is O(n²) - only use for small result sets)
    duplicates = []
    for i, e1 in enumerate(entities):
        for e2 in entities[i+1:]:
            id1, cid1, name1 = e1
            id2, cid2, name2 = e2

            # Skip if already same canonical ID prefix (e.g., both CHEMBL)
            prefix1 = cid1.split(':')[0]
            prefix2 = cid2.split(':')[0]
            if prefix1 == prefix2:
                continue

            # Calculate similarity
            n1 = normalize_name(name1)
            n2 = normalize_name(name2)
            similarity = SequenceMatcher(None, n1, n2).ratio()

            if similarity >= threshold:
                duplicates.append((e1, e2, similarity))

    return duplicates


def find_alias_conflicts() -> List[Tuple[str, List[Tuple]]]:
    """
    Find aliases that point to multiple different entities.
    This indicates entity resolution failures.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    a.alias,
                    e.id,
                    e.kind,
                    e.canonical_id,
                    e.name
                FROM alias a
                JOIN entity e ON e.id = a.entity_id
                ORDER BY a.alias, e.kind
            """)

            # Group by alias
            groups: Dict[str, List[Tuple]] = {}
            for row in cur.fetchall():
                alias, entity_id, kind, canonical_id, name = row
                alias_lower = alias.lower()

                if alias_lower not in groups:
                    groups[alias_lower] = []
                groups[alias_lower].append((alias, entity_id, kind, canonical_id, name))

            # Filter to conflicts (same alias, different entities, same kind)
            conflicts = []
            for alias, entities in groups.items():
                # Group by kind
                by_kind: Dict[str, List] = {}
                for e in entities:
                    kind = e[2]
                    if kind not in by_kind:
                        by_kind[kind] = []
                    by_kind[kind].append(e)

                # Check for conflicts within each kind
                for kind, kind_entities in by_kind.items():
                    if len(kind_entities) > 1:
                        conflicts.append((alias, kind_entities))

            return conflicts


def print_duplicate_report():
    """Generate and print comprehensive duplicate report"""

    print("=" * 80)
    print("BIOGRAPH ENTITY DUPLICATION REPORT")
    print("=" * 80)

    # 1. Exact name duplicates by kind
    for kind in ["drug", "disease", "company", "target"]:
        print(f"\n### {kind.upper()} - Exact Name Duplicates")
        duplicates = find_exact_name_duplicates(kind)

        if not duplicates:
            print(f"  ✓ No exact duplicates found for {kind}")
            continue

        print(f"  Found {len(duplicates)} sets of duplicates:\n")

        for key, entities in duplicates[:20]:  # Show top 20
            name = entities[0][0]
            print(f"  '{name}':")
            for _, kind, canonical_id, entity_id in entities:
                print(f"    - {canonical_id} (ID: {entity_id})")
            print()

        if len(duplicates) > 20:
            print(f"  ... and {len(duplicates) - 20} more\n")

    # 2. Fuzzy duplicates (just for drugs for now - most critical)
    print(f"\n### DRUG - Fuzzy Duplicates (90%+ similar)")
    fuzzy_dupes = find_fuzzy_duplicates("drug", threshold=0.90)

    if not fuzzy_dupes:
        print("  ✓ No fuzzy duplicates found")
    else:
        print(f"  Found {len(fuzzy_dupes)} potential duplicates:\n")

        for (id1, cid1, name1), (id2, cid2, name2), similarity in fuzzy_dupes[:10]:
            print(f"  {similarity:.0%} match:")
            print(f"    - {name1} ({cid1})")
            print(f"    - {name2} ({cid2})")
            print()

        if len(fuzzy_dupes) > 10:
            print(f"  ... and {len(fuzzy_dupes) - 10} more\n")

    # 3. Alias conflicts
    print(f"\n### Alias Conflicts")
    conflicts = find_alias_conflicts()

    if not conflicts:
        print("  ✓ No alias conflicts found")
    else:
        print(f"  Found {len(conflicts)} aliases pointing to multiple entities:\n")

        for alias, entities in conflicts[:10]:
            print(f"  '{alias}' points to:")
            for _, entity_id, kind, canonical_id, name in entities:
                print(f"    - {name} ({canonical_id}) [ID: {entity_id}]")
            print()

        if len(conflicts) > 10:
            print(f"  ... and {len(conflicts) - 10} more\n")

    # 4. Summary stats
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Count entities by canonical ID prefix
            cur.execute("""
                SELECT
                    kind,
                    SPLIT_PART(canonical_id, ':', 1) as id_prefix,
                    COUNT(*) as count
                FROM entity
                GROUP BY kind, id_prefix
                ORDER BY kind, count DESC
            """)

            print("\nEntities by ID type:")
            current_kind = None
            for row in cur.fetchall():
                kind, prefix, count = row
                if kind != current_kind:
                    print(f"\n  {kind.upper()}:")
                    current_kind = kind
                print(f"    {prefix}: {count}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    print_duplicate_report()
