#!/usr/bin/env python3
"""
Merge duplicate entities - canonicalize the knowledge graph.

This script merges duplicate entities by:
1. Identifying the "winner" (entity with best canonical ID)
2. Transferring all edges from duplicates to winner
3. Transferring all aliases from duplicates to winner
4. Deleting duplicate entities

Canonical ID priority:
- CHEMBL > DRUG
- MESH > CONDITION
- CIK > COMPANY > DISCOVERED > CTG_SPONSOR
- UNIPROT > CHEMBL_TARGET
- NCT (always unique)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from typing import List, Tuple
from app.db import get_conn


CANONICAL_PRIORITY = {
    # Drugs
    "CHEMBL": 100,
    "DRUG": 10,
    "CTG_INT": 5,

    # Diseases
    "MESH": 100,
    "CONDITION": 10,

    # Companies
    "CIK": 100,
    "COMPANY": 50,
    "DISCOVERED": 30,
    "CTG_SPONSOR": 10,

    # Targets
    "UNIPROT": 100,
    "CHEMBL_TARGET": 50,

    # Trials (always unique)
    "NCT": 100,

    # Publications
    "DOI": 100,
    "PMID": 90,
    "ARXIV": 50,

    # Patents
    "USPTO": 100,
}


def get_canonical_priority(canonical_id: str) -> int:
    """Get priority score for a canonical ID (higher = better)"""
    prefix = canonical_id.split(':')[0]
    return CANONICAL_PRIORITY.get(prefix, 0)


def merge_entities(entity_ids: List[int], dry_run: bool = True) -> None:
    """
    Merge multiple entities into one canonical entity.

    Process:
    1. Choose winner (highest canonical ID priority)
    2. Move all edges to winner
    3. Move all aliases to winner
    4. Delete losers

    Args:
        entity_ids: List of entity IDs to merge
        dry_run: If True, only print what would be done (don't modify DB)
    """

    if len(entity_ids) < 2:
        print("❌ Need at least 2 entities to merge")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get entity details
            placeholders = ','.join(['%s'] * len(entity_ids))
            cur.execute(
                f"""
                SELECT id, kind, canonical_id, name
                FROM entity
                WHERE id IN ({placeholders})
                """,
                tuple(entity_ids)
            )

            entities = cur.fetchall()

            if len(entities) != len(entity_ids):
                print(f"❌ Only found {len(entities)} entities out of {len(entity_ids)} requested")
                return

            # Verify all same kind
            kinds = set(e[1] for e in entities)
            if len(kinds) > 1:
                print(f"❌ Cannot merge entities of different kinds: {kinds}")
                return

            # Choose winner (highest priority canonical ID)
            entities_sorted = sorted(entities, key=lambda e: get_canonical_priority(e[2]), reverse=True)
            winner = entities_sorted[0]
            losers = entities_sorted[1:]

            winner_id, winner_kind, winner_cid, winner_name = winner

            print(f"\n{'=' * 80}")
            print(f"MERGING {len(losers)} ENTITIES INTO CANONICAL ENTITY")
            print(f"{'=' * 80}\n")

            print(f"WINNER (will keep):")
            print(f"  ID: {winner_id}")
            print(f"  Canonical ID: {winner_cid} (priority: {get_canonical_priority(winner_cid)})")
            print(f"  Name: {winner_name}")

            print(f"\nLOSERS (will merge into winner):")
            for loser_id, loser_kind, loser_cid, loser_name in losers:
                print(f"  ID: {loser_id}")
                print(f"  Canonical ID: {loser_cid} (priority: {get_canonical_priority(loser_cid)})")
                print(f"  Name: {loser_name}")

            if dry_run:
                print(f"\n⚠️  DRY RUN MODE - No changes will be made\n")
            else:
                print(f"\n🔥 LIVE MODE - Changes will be committed!\n")

            # Count what will be transferred
            for loser_id, _, loser_cid, loser_name in losers:
                # Count edges
                cur.execute("""
                    SELECT COUNT(*) FROM edge WHERE src_id = %s OR dst_id = %s
                """, (loser_id, loser_id))
                edge_count = cur.fetchone()[0]

                # Count aliases
                cur.execute("SELECT COUNT(*) FROM alias WHERE entity_id = %s", (loser_id,))
                alias_count = cur.fetchone()[0]

                print(f"  {loser_name} ({loser_cid}):")
                print(f"    - {edge_count} edges to transfer")
                print(f"    - {alias_count} aliases to transfer")

            if dry_run:
                print(f"\n✓ Dry run complete - no changes made")
                return

            # Actually perform the merge
            print(f"\n🔄 Performing merge...")

            for loser_id, _, loser_cid, loser_name in losers:
                print(f"\n  Merging {loser_name} ({loser_cid})...")

                # Transfer edges where loser is source
                cur.execute("""
                    UPDATE edge
                    SET src_id = %s
                    WHERE src_id = %s
                    ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                """, (winner_id, loser_id))
                print(f"    ✓ Transferred {cur.rowcount} outgoing edges")

                # Transfer edges where loser is destination
                cur.execute("""
                    UPDATE edge
                    SET dst_id = %s
                    WHERE dst_id = %s
                    ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                """, (winner_id, loser_id))
                print(f"    ✓ Transferred {cur.rowcount} incoming edges")

                # Transfer aliases
                cur.execute("""
                    UPDATE alias
                    SET entity_id = %s
                    WHERE entity_id = %s
                """, (winner_id, loser_id))
                print(f"    ✓ Transferred {cur.rowcount} aliases")

                # Add loser's name as an alias to winner (if different)
                if loser_name.lower() != winner_name.lower():
                    cur.execute("""
                        INSERT INTO alias (entity_id, alias, source)
                        VALUES (%s, %s, 'merged')
                        ON CONFLICT DO NOTHING
                    """, (winner_id, loser_name))
                    print(f"    ✓ Added '{loser_name}' as alias to winner")

                # Delete the loser entity (cascades will clean up remaining edges)
                cur.execute("DELETE FROM entity WHERE id = %s", (loser_id,))
                print(f"    ✓ Deleted entity {loser_id}")

            conn.commit()
            print(f"\n✅ Merge complete! All entities consolidated into ID {winner_id}")


def merge_by_name(kind: str, name: str, dry_run: bool = True) -> None:
    """
    Find and merge all entities of a given kind with the same name.
    Convenience wrapper around merge_entities.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, canonical_id, name
                FROM entity
                WHERE kind = %s AND LOWER(name) = LOWER(%s)
                ORDER BY name
            """, (kind, name))

            entities = cur.fetchall()

            if len(entities) < 2:
                print(f"No duplicates found for {kind} '{name}'")
                return

            print(f"Found {len(entities)} entities with name '{name}':")
            for entity_id, canonical_id, entity_name in entities:
                print(f"  - {entity_name} ({canonical_id}) [ID: {entity_id}]")

            entity_ids = [e[0] for e in entities]
            merge_entities(entity_ids, dry_run=dry_run)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Merge duplicate entities")
    parser.add_argument("--ids", type=int, nargs="+", help="Entity IDs to merge")
    parser.add_argument("--name", type=str, help="Merge all entities with this name")
    parser.add_argument("--kind", type=str, help="Entity kind (required with --name)")
    parser.add_argument("--live", action="store_true", help="Actually perform merge (default is dry run)")

    args = parser.parse_args()

    dry_run = not args.live

    if args.ids:
        merge_entities(args.ids, dry_run=dry_run)
    elif args.name and args.kind:
        merge_by_name(args.kind, args.name, dry_run=dry_run)
    else:
        print("Usage:")
        print("  # Merge specific entity IDs (dry run)")
        print("  python merge_entities.py --ids 123 456 789")
        print()
        print("  # Merge all drugs named 'Semaglutide' (dry run)")
        print("  python merge_entities.py --kind drug --name Semaglutide")
        print()
        print("  # Actually perform merge (LIVE)")
        print("  python merge_entities.py --kind drug --name Semaglutide --live")
