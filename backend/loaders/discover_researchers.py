#!/usr/bin/env python3
"""
Researcher discovery - finds principal investigators and key authors.

Discovers researchers from:
1. Clinical trial investigators (ClinicalTrials.gov)
2. Publication authors (PubMed - future: with ORCID)

Creates person entities and links them to their work.
"""
from typing import Set, Dict, Tuple
from backend.app.db import get_conn
import json
import urllib.request
import time

CTGOV_BASE = "https://clinicaltrials.gov/api/v2/studies"

def fetch_trial_investigators(nct_id: str) -> list:
    """
    Fetch detailed trial information including investigators.

    Returns list of {name, role, affiliation} dicts
    """
    url = f"{CTGOV_BASE}/{nct_id}"

    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))

        protocol = data.get("protocolSection", {})
        contacts = protocol.get("contactsLocationsModule", {})

        investigators = []

        # Overall officials
        officials = contacts.get("overallOfficials", [])
        for official in officials:
            name = official.get("name")
            role = official.get("role", "Overall Official")
            affiliation = official.get("affiliation", "")

            if name:
                investigators.append({
                    "name": name.strip(),
                    "role": role,
                    "affiliation": affiliation.strip()
                })

        return investigators

    except Exception as e:
        print(f"  Warning: Could not fetch investigators for {nct_id}: {e}")
        return []

def discover_researchers_from_trials(limit: int = 100) -> Dict[str, Dict]:
    """
    Discover researchers from clinical trials.

    Args:
        limit: Maximum number of trials to query (API rate limit consideration)

    Returns dict of {normalized_name: {
        "canonical_name": str,
        "affiliations": set,
        "trials": [list of NCT IDs],
        "roles": set
    }}
    """
    researchers = {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get trials for our disease areas
            cur.execute("""
                SELECT DISTINCT t.nct_id
                FROM trial t
                ORDER BY t.last_update_posted DESC
                LIMIT %s
            """, (limit,))

            trials = [row[0] for row in cur.fetchall()]

    print(f"Fetching investigators from {len(trials)} trials...")

    for i, nct_id in enumerate(trials):
        investigators = fetch_trial_investigators(nct_id)

        for inv in investigators:
            name = inv["name"]
            normalized = normalize_person_name(name)

            if normalized not in researchers:
                researchers[normalized] = {
                    "canonical_name": name,
                    "affiliations": set(),
                    "trials": [],
                    "roles": set()
                }

            if inv["affiliation"]:
                researchers[normalized]["affiliations"].add(inv["affiliation"])

            researchers[normalized]["trials"].append(nct_id)
            researchers[normalized]["roles"].add(inv["role"])

        # Be polite to API
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(trials)} trials...")
            time.sleep(1)

    return researchers

def normalize_person_name(name: str) -> str:
    """
    Normalize person names for deduplication.

    Examples:
    - "John Smith, MD" → "john smith"
    - "Smith, John" → "john smith"
    """
    # Remove titles
    titles = [", MD", ", PhD", ", MPH", ", RN", " MD", " PhD", " MPH", " RN", " Dr.", "Dr. "]
    normalized = name
    for title in titles:
        normalized = normalized.replace(title, "")

    # Handle "Last, First" format
    if "," in normalized:
        parts = normalized.split(",")
        if len(parts) == 2:
            normalized = f"{parts[1].strip()} {parts[0].strip()}"

    # Lowercase and clean
    normalized = " ".join(normalized.lower().split())

    return normalized

def insert_discovered_researchers(researchers: Dict[str, Dict]) -> None:
    """
    Insert discovered researchers into entity table.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted = 0
            inserted_edges = 0

            for normalized_name, info in researchers.items():
                canonical_name = info["canonical_name"]
                trial_count = len(info["trials"])

                # Only insert researchers with 2+ trials (filter noise)
                if trial_count < 2:
                    continue

                print(f"  Adding: {canonical_name} ({trial_count} trials)")

                # Create canonical_id (could be enriched with ORCID later)
                canonical_id = f"RESEARCHER:{normalized_name.replace(' ', '_')}"

                # Insert person entity
                cur.execute("""
                    INSERT INTO entity (kind, canonical_id, name)
                    VALUES ('person', %s, %s)
                    ON CONFLICT (kind, canonical_id) DO UPDATE
                      SET name = EXCLUDED.name,
                          updated_at = NOW()
                    RETURNING id
                """, (canonical_id, canonical_name))

                person_entity_id = cur.fetchone()[0]
                inserted += 1

                # Add affiliations as aliases
                for affiliation in list(info["affiliations"])[:3]:  # Limit to top 3
                    if affiliation:
                        cur.execute("""
                            INSERT INTO alias (entity_id, alias, source)
                            VALUES (%s, %s, 'ctgov')
                            ON CONFLICT DO NOTHING
                        """, (person_entity_id, affiliation[:500]))

                # Link to trials
                for nct_id in info["trials"]:
                    cur.execute("""
                        SELECT id FROM entity
                        WHERE kind = 'trial' AND canonical_id = %s
                    """, (f"NCT:{nct_id}",))

                    trial_result = cur.fetchone()
                    if trial_result:
                        trial_entity_id = trial_result[0]

                        # Create edge: person --investigates--> trial
                        cur.execute("""
                            INSERT INTO edge (src_id, predicate, dst_id, source)
                            VALUES (%s, 'investigates', %s, 'ctgov')
                            ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                        """, (person_entity_id, trial_entity_id))

                        inserted_edges += cur.rowcount

            conn.commit()

    print(f"\n✓ Researchers discovered and inserted: {inserted}")
    print(f"✓ Researcher-trial edges created: {inserted_edges}")

if __name__ == "__main__":
    researchers = discover_researchers_from_trials(limit=50)  # Start small

    print(f"\nDiscovered {len(researchers)} unique researchers")
    print(f"Researchers with 2+ trials: {sum(1 for r in researchers.values() if len(r['trials']) >= 2)}")

    print("\nTop investigators by trial count:")
    sorted_researchers = sorted(researchers.items(), key=lambda x: len(x[1]["trials"]), reverse=True)
    for normalized_name, info in sorted_researchers[:10]:
        affiliations = ", ".join(list(info["affiliations"])[:2])
        print(f"  {len(info['trials']):2d} trials: {info['canonical_name']}")
        if affiliations:
            print(f"      {affiliations}")

    print("\nInserting researchers into graph...")
    insert_discovered_researchers(researchers)
