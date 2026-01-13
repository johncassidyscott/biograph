#!/usr/bin/env python3
"""
Infer drug-disease relationships from clinical trial data.

Logic:
- If a trial studies drug X for disease Y, and the trial is Phase 2+,
  create an edge: drug --treats--> disease

This enriches the graph by connecting drugs to diseases based on real clinical evidence.
"""
from backend.app.db import get_conn

def infer_drug_disease_relationships(min_phase: int = 2) -> None:
    """
    Infer drug-disease relationships from trials.

    Creates 'treats' edges when:
    - Trial has drug intervention (from CTG_INT:*)
    - Trial has disease condition (linked via for_condition edge)
    - Trial is Phase min_phase or higher

    Args:
        min_phase: Minimum trial phase to consider (default 2)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            print("Analyzing trials to infer drug-disease relationships...")

            # Find trials with drugs and diseases
            query = """
            SELECT DISTINCT
                drug.id as drug_id,
                drug.name as drug_name,
                disease.id as disease_id,
                disease.name as disease_name,
                t.phase_min,
                t.nct_id
            FROM trial t
            -- Join to trial entity
            JOIN entity trial_entity ON trial_entity.canonical_id = 'NCT:' || t.nct_id
            -- Find drug interventions
            JOIN edge drug_edge ON drug_edge.src_id = trial_entity.id
                AND drug_edge.predicate = 'studies'
            JOIN entity drug ON drug.id = drug_edge.dst_id
                AND drug.kind = 'drug'
            -- Find disease conditions
            JOIN edge disease_edge ON disease_edge.src_id = trial_entity.id
                AND disease_edge.predicate = 'for_condition'
            JOIN entity disease ON disease.id = disease_edge.dst_id
                AND disease.kind = 'disease'
            WHERE t.phase_min >= %s
            """

            cur.execute(query, (min_phase,))
            relationships = cur.fetchall()

            print(f"Found {len(relationships)} potential drug-disease relationships")

            # Create inferred edges
            inserted = 0
            seen = set()

            for row in relationships:
                drug_id, drug_name, disease_id, disease_name, phase, nct_id = row

                # Avoid duplicates
                key = (drug_id, disease_id)
                if key in seen:
                    continue
                seen.add(key)

                # Create edge: drug --treats--> disease
                cur.execute(
                    """
                    INSERT INTO edge (src_id, predicate, dst_id, source)
                    VALUES (%s, 'treats', %s, 'inferred_ctgov')
                    ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                    RETURNING id
                    """,
                    (drug_id, disease_id),
                )

                if cur.fetchone():
                    inserted += 1
                    print(f"  ✓ {drug_name} → {disease_name} (Phase {phase}, {nct_id})")

            conn.commit()

    print(f"\n✓ Inferred drug-disease edges: {inserted}")

if __name__ == "__main__":
    # Use Phase 2+ as threshold for considering a drug as "treating" a disease
    infer_drug_disease_relationships(min_phase=2)
