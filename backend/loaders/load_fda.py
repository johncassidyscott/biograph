#!/usr/bin/env python3
"""
FDA drug approvals loader - uses OpenFDA API (official FDA source).

Fetches approval dates, application numbers, and indications for drugs in our graph.
API docs: https://open.fda.gov/apis/drug/drugsfda/
"""
import json
import time
import urllib.request
import urllib.parse
from typing import List, Dict, Optional
from datetime import datetime
from backend.app.db import get_conn

OPENFDA_BASE = "https://api.fda.gov/drug/drugsfda.json"

def search_fda_approvals(drug_name: str) -> List[Dict]:
    """
    Search OpenFDA for drug approvals by drug name.

    Returns list of approval records with dates, application numbers, etc.
    """
    params = {
        "search": f'openfda.brand_name:"{drug_name}" OR openfda.generic_name:"{drug_name}"',
        "limit": "10"
    }

    url = f"{OPENFDA_BASE}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read().decode("utf-8"))

        results = data.get("results", [])
        return results

    except Exception as e:
        print(f"  Warning: OpenFDA search failed for '{drug_name}': {e}")
        return []

def parse_approval_date(date_str: Optional[str]) -> Optional[str]:
    """Parse FDA date format YYYYMMDD to YYYY-MM-DD"""
    if not date_str or len(date_str) != 8:
        return None
    try:
        return f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
    except:
        return None

def load_fda_approvals(drug_list: List[Dict[str, str]]) -> None:
    """
    Load FDA approval data for specific drugs.

    drug_list format:
    [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        ...
    ]

    Creates approval facts linked to drug entities.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Create drug_approval table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drug_approval (
                    id BIGSERIAL PRIMARY KEY,
                    drug_entity_id BIGINT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
                    application_number TEXT NOT NULL,
                    approval_date DATE,
                    approval_type TEXT,
                    sponsor_name TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (drug_entity_id, application_number)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS drug_approval_drug_idx
                ON drug_approval(drug_entity_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS drug_approval_date_idx
                ON drug_approval(approval_date)
            """)

            conn.commit()

            inserted_approvals = 0

            for drug_spec in drug_list:
                name = drug_spec.get("name")
                chembl_id = drug_spec.get("chembl_id")

                if not name or not chembl_id:
                    continue

                print(f"\nSearching FDA approvals: {name}")

                # Get drug entity
                cur.execute(
                    """
                    SELECT id FROM entity
                    WHERE kind = 'drug' AND canonical_id = %s
                    """,
                    (f"CHEMBL:{chembl_id}",),
                )
                result = cur.fetchone()
                if not result:
                    print(f"  Warning: Drug {chembl_id} not found")
                    continue

                drug_entity_id = result[0]

                # Search OpenFDA
                approvals = search_fda_approvals(name)
                print(f"  Found {len(approvals)} FDA records")

                for record in approvals:
                    # Get application info
                    app_num = record.get("application_number")
                    if not app_num:
                        continue

                    sponsor = record.get("sponsor_name", "")

                    # Get products and approval dates
                    products = record.get("products", [])
                    for product in products:
                        approval_date_raw = product.get("marketing_status_date")
                        approval_date = parse_approval_date(approval_date_raw)

                        if not approval_date:
                            continue

                        # Get approval type from application number prefix
                        approval_type = None
                        if app_num.startswith("NDA"):
                            approval_type = "NDA"  # New Drug Application
                        elif app_num.startswith("ANDA"):
                            approval_type = "ANDA"  # Generic
                        elif app_num.startswith("BLA"):
                            approval_type = "BLA"  # Biologics License Application

                        # Insert approval record
                        cur.execute(
                            """
                            INSERT INTO drug_approval (
                                drug_entity_id,
                                application_number,
                                approval_date,
                                approval_type,
                                sponsor_name
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (drug_entity_id, application_number) DO UPDATE
                              SET approval_date = EXCLUDED.approval_date,
                                  approval_type = EXCLUDED.approval_type,
                                  sponsor_name = EXCLUDED.sponsor_name
                            RETURNING id
                            """,
                            (drug_entity_id, app_num, approval_date, approval_type, sponsor),
                        )

                        if cur.fetchone():
                            inserted_approvals += 1
                            print(f"  ✓ {app_num}: {approval_type} approved {approval_date}")

                time.sleep(0.5)  # Be polite to FDA API

            conn.commit()

    print(f"\n✓ FDA approvals recorded: {inserted_approvals}")

if __name__ == "__main__":
    # POC drugs to look up FDA approvals
    poc_drugs = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448"},
        {"name": "Liraglutide", "chembl_id": "CHEMBL1201580"},
        {"name": "Dulaglutide", "chembl_id": "CHEMBL2107834"},
        {"name": "Donepezil", "chembl_id": "CHEMBL502"},
        {"name": "Rivastigmine", "chembl_id": "CHEMBL636"},
        {"name": "Galantamine", "chembl_id": "CHEMBL659"},
        {"name": "Memantine", "chembl_id": "CHEMBL1201384"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL2366541"},
        {"name": "Sotorasib", "chembl_id": "CHEMBL4297299"},
        {"name": "Adagrasib", "chembl_id": "CHEMBL4594668"},
    ]

    load_fda_approvals(poc_drugs)
