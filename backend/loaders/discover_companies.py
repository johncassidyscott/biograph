#!/usr/bin/env python3
"""
Company discovery - finds all companies mentioned in the knowledge graph.

Discovers companies from:
1. Trial sponsors (ClinicalTrials.gov)
2. Patent assignees (USPTO)
3. Drug developers (ChEMBL - if available)
4. Publication author affiliations (future)

This runs AFTER all data is loaded and discovers companies organically.
"""
from typing import Set, Dict, Tuple
from app.db import get_conn

def discover_companies_from_trials() -> Set[Tuple[str, str]]:
    """
    Extract unique sponsor names from trials.

    Returns set of (sponsor_name, source_nct_id) tuples
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT sponsor_name, nct_id
                FROM trial
                WHERE sponsor_name IS NOT NULL
                  AND sponsor_name != ''
                ORDER BY sponsor_name
            """)

            sponsors = set()
            for row in cur.fetchall():
                sponsor_name = row[0].strip()
                nct_id = row[1]
                if sponsor_name:
                    sponsors.add((sponsor_name, nct_id))

            return sponsors

def discover_companies_from_patents() -> Set[Tuple[str, str]]:
    """
    Extract assignee organizations from patents.

    Returns set of (company_name, patent_number) tuples
    """
    # Patents store assignees in the canonical_id, need to parse
    # For now, we'll skip this and rely on trial sponsors
    # TODO: Enhance patent loader to store assignee separately
    return set()

def normalize_company_name(name: str) -> str:
    """
    Normalize company names for deduplication.

    Examples:
    - "Eli Lilly and Company" → "eli lilly"
    - "Novo Nordisk A/S" → "novo nordisk"
    - "University of California, San Francisco" → "university california san francisco"
    """
    # Remove common suffixes
    suffixes = [
        " Inc.", " Inc", " LLC", " Ltd.", " Ltd", " Corporation", " Corp.",
        " Company", " Co.", " A/S", " AB", " GmbH", " S.A.", " PLC",
        ", Inc.", ", LLC", ", Ltd.", ", Corporation"
    ]

    normalized = name
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]

    # Remove "The" prefix
    if normalized.startswith("The "):
        normalized = normalized[4:]

    # Lowercase and remove extra spaces
    normalized = " ".join(normalized.lower().split())

    return normalized

def classify_organization(name: str) -> str:
    """
    Classify organization type: company, academic, government, nonprofit.
    """
    name_lower = name.lower()

    # Academic institutions
    if any(word in name_lower for word in ["university", "college", "institute", "school of"]):
        return "academic"

    # Government/NIH
    if any(word in name_lower for word in ["national institutes", "nih", "department of", "ministry of"]):
        return "government"

    # Nonprofit/Foundation
    if any(word in name_lower for word in ["foundation", "charity", "nonprofit", "society"]):
        return "nonprofit"

    # Default to company
    return "company"

def discover_all_companies() -> Dict[str, Dict]:
    """
    Discover all companies from the knowledge graph.

    Returns dict of {normalized_name: {
        "canonical_name": str,
        "type": str,
        "sources": [list of NCT/patent IDs],
        "trial_count": int
    }}
    """
    print("Discovering companies from trials...")
    trial_sponsors = discover_companies_from_trials()

    print("Discovering companies from patents...")
    patent_assignees = discover_companies_from_patents()

    # Deduplicate and aggregate
    companies = {}

    for sponsor_name, nct_id in trial_sponsors:
        normalized = normalize_company_name(sponsor_name)

        if normalized not in companies:
            companies[normalized] = {
                "canonical_name": sponsor_name,
                "type": classify_organization(sponsor_name),
                "sources": [],
                "trial_count": 0
            }

        companies[normalized]["sources"].append(f"NCT:{nct_id}")
        companies[normalized]["trial_count"] += 1

    return companies

def insert_discovered_companies(companies: Dict[str, Dict]) -> None:
    """
    Insert discovered companies into entity table.

    Creates company entities with type and metadata.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted_companies = 0
            inserted_edges = 0

            for normalized_name, info in companies.items():
                canonical_name = info["canonical_name"]
                org_type = info["type"]
                trial_count = info["trial_count"]

                # Only insert organizations with 2+ trials (filter noise)
                if trial_count < 2:
                    continue

                # Skip academic/government for now (focus on companies)
                if org_type != "company":
                    print(f"  Skipping {org_type}: {canonical_name}")
                    continue

                print(f"  Adding: {canonical_name} ({trial_count} trials)")

                # Create canonical_id (will be enriched later with CIK if found)
                canonical_id = f"DISCOVERED:{normalized_name.replace(' ', '_')}"

                # Insert company entity
                cur.execute("""
                    INSERT INTO entity (kind, canonical_id, name)
                    VALUES ('company', %s, %s)
                    ON CONFLICT (kind, canonical_id) DO UPDATE
                      SET name = EXCLUDED.name,
                          updated_at = NOW()
                    RETURNING id
                """, (canonical_id, canonical_name))

                company_entity_id = cur.fetchone()['id']
                inserted_companies += 1

                # Link company to trials it sponsors
                for source in info["sources"]:
                    if source.startswith("NCT:"):
                        nct_id = source.replace("NCT:", "")

                        # Find trial entity
                        cur.execute("""
                            SELECT id FROM entity
                            WHERE kind = 'trial' AND canonical_id = %s
                        """, (source,))

                        trial_result = cur.fetchone()
                        if trial_result:
                            trial_entity_id = trial_result['id']

                            # Create edge: trial --sponsored_by--> company
                            cur.execute("""
                                INSERT INTO edge (src_id, predicate, dst_id, source)
                                VALUES (%s, 'sponsored_by', %s, 'discovered')
                                ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                            """, (trial_entity_id, company_entity_id))

                            inserted_edges += cur.rowcount

            conn.commit()

    print(f"\n✓ Companies discovered and inserted: {inserted_companies}")
    print(f"✓ Trial-company edges created: {inserted_edges}")

if __name__ == "__main__":
    companies = discover_all_companies()

    print(f"\nDiscovered {len(companies)} unique organizations")
    print(f"Companies with 2+ trials: {sum(1 for c in companies.values() if c['trial_count'] >= 2 and c['type'] == 'company')}")

    print("\nTop sponsors by trial count:")
    sorted_companies = sorted(companies.items(), key=lambda x: x[1]["trial_count"], reverse=True)
    for normalized_name, info in sorted_companies[:20]:
        print(f"  {info['trial_count']:3d} trials: {info['canonical_name']} ({info['type']})")

    print("\nInserting companies into graph...")
    insert_discovered_companies(companies)
