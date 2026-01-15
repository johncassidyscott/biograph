#!/usr/bin/env python3
"""
Batch Embedding Generation - Generate semantic embeddings for all entities.

This script:
1. Finds all entities without embeddings
2. Generates embeddings in batches (efficient GPU utilization)
3. Updates database with embeddings

Usage:
    python scripts/generate_embeddings.py [--batch-size 128] [--kind drug]

Options:
    --batch-size: Number of entities to process at once (default: 128)
    --kind: Only process specific entity type (drug, disease, company, target)
    --force: Regenerate embeddings for all entities (default: only missing)
"""

import sys
import os
import argparse
from typing import List, Tuple, Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_conn
from services import get_embedding_service
import numpy as np

def get_entities_needing_embeddings(kind: Optional[str] = None, force: bool = False) -> List[Tuple[int, str, str]]:
    """
    Get entities that need embeddings.

    Args:
        kind: Filter by entity type (optional)
        force: Include entities that already have embeddings

    Returns:
        List of (id, kind, name) tuples
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if force:
                # Regenerate all
                if kind:
                    cur.execute("""
                        SELECT id, kind, name
                        FROM entity
                        WHERE kind = %s
                        ORDER BY id
                    """, (kind,))
                else:
                    cur.execute("""
                        SELECT id, kind, name
                        FROM entity
                        ORDER BY id
                    """)
            else:
                # Only missing embeddings
                if kind:
                    cur.execute("""
                        SELECT id, kind, name
                        FROM entity
                        WHERE kind = %s AND embedding IS NULL
                        ORDER BY id
                    """, (kind,))
                else:
                    cur.execute("""
                        SELECT id, kind, name
                        FROM entity
                        WHERE embedding IS NULL
                        ORDER BY id
                    """)

            return [(row['id'], row['kind'], row['name']) for row in cur.fetchall()]

def update_embeddings_batch(entity_ids: List[int], embeddings: np.ndarray) -> None:
    """
    Update embeddings for a batch of entities.

    Args:
        entity_ids: List of entity IDs
        embeddings: Array of shape (len(entity_ids), 768)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Prepare data for batch update
            for entity_id, embedding in zip(entity_ids, embeddings):
                embedding_list = embedding.tolist()
                cur.execute("""
                    UPDATE entity
                    SET embedding = %s::vector,
                        embedding_updated_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                """, (embedding_list, entity_id))

        conn.commit()

def main():
    parser = argparse.ArgumentParser(description="Generate embeddings for entities")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size for processing")
    parser.add_argument("--kind", type=str, choices=["drug", "disease", "company", "target", "person", "grant"], help="Only process specific entity type")
    parser.add_argument("--force", action="store_true", help="Regenerate embeddings for all entities")
    args = parser.parse_args()

    print("=" * 80)
    print("BIOGRAPH EMBEDDING GENERATION")
    print("=" * 80)

    # Initialize embedding service
    print("\n[1/4] Initializing embedding service...")
    embedding_service = get_embedding_service(model_name="sapbert", use_gpu=True)

    # Get entities needing embeddings
    print(f"\n[2/4] Finding entities needing embeddings...")
    entities = get_entities_needing_embeddings(kind=args.kind, force=args.force)

    if not entities:
        print("✓ No entities need embeddings!")
        return

    print(f"  Found {len(entities):,} entities needing embeddings")

    if args.kind:
        print(f"  Entity type filter: {args.kind}")

    # Generate embeddings in batches
    print(f"\n[3/4] Generating embeddings (batch size: {args.batch_size})...")

    total_batches = (len(entities) + args.batch_size - 1) // args.batch_size
    processed = 0

    for batch_num in range(total_batches):
        start_idx = batch_num * args.batch_size
        end_idx = min(start_idx + args.batch_size, len(entities))
        batch_entities = entities[start_idx:end_idx]

        # Extract names and IDs
        entity_ids = [e[0] for e in batch_entities]
        entity_names = [e[2] for e in batch_entities]

        # Generate embeddings (this is the expensive operation)
        embeddings = embedding_service.encode(
            entity_names,
            batch_size=args.batch_size,
            show_progress=False,
            normalize=True
        )

        # Update database
        update_embeddings_batch(entity_ids, embeddings)

        processed += len(batch_entities)
        progress = (processed / len(entities)) * 100

        print(f"  Batch {batch_num + 1}/{total_batches}: {processed:,}/{len(entities):,} ({progress:.1f}%)")

    # Verify results
    print(f"\n[4/4] Verifying results...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            if args.kind:
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(embedding) as with_embedding
                    FROM entity
                    WHERE kind = %s
                """, (args.kind,))
            else:
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(embedding) as with_embedding
                    FROM entity
                """)

            result = cur.fetchone()
            total = result['total']
            with_embedding = result['with_embedding']
            coverage = (with_embedding / total * 100) if total > 0 else 0

            print(f"  Total entities: {total:,}")
            print(f"  With embeddings: {with_embedding:,} ({coverage:.1f}%)")

    print("\n" + "=" * 80)
    print("✓ EMBEDDING GENERATION COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
