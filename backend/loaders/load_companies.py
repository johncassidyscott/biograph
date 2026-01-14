#!/usr/bin/env python3
"""
Company enrichment loader - adds major pharmaceutical companies with SEC CIK identifiers.

For POC, we'll focus on companies relevant to our disease areas:
- Obesity/Metabolic: Novo Nordisk, Eli Lilly
- Alzheimer's: Eisai, Biogen
- KRAS Oncology: Amgen, Mirati, various cancer-focused biotechs

CIK numbers from SEC EDGAR: https://www.sec.gov/cgi-bin/browse-edgar
"""
from typing import List, Dict
from app.db import get_conn

def load_companies(company_list: List[Dict[str, str]]) -> None:
    """
    Load company entities and link them to drugs they develop.

    company_list format:
    [
        {
            "name": "Eli Lilly and Company",
            "cik": "0000059478",
            "develops": ["CHEMBL4297448"]  # Tirzepatide
        },
        ...
    ]
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted_companies = 0
            inserted_edges = 0

            for company_spec in company_list:
                name = company_spec.get("name")
                cik = company_spec.get("cik")
                develops_drugs = company_spec.get("develops", [])
                aliases = company_spec.get("aliases", [])

                if not name or not cik:
                    continue

                print(f"Processing: {name} (CIK:{cik})")

                # Insert company entity
                canonical_id = f"CIK:{cik}"
                cur.execute(
                    """
                    INSERT INTO entity (kind, canonical_id, name)
                    VALUES ('company', %s, %s)
                    ON CONFLICT (kind, canonical_id) DO UPDATE
                      SET name = EXCLUDED.name,
                          updated_at = NOW()
                    RETURNING id
                    """,
                    (canonical_id, name),
                )
                company_entity_id = cur.fetchone()[0]
                inserted_companies += 1

                # Add aliases (common variations of company name)
                for alias in aliases:
                    cur.execute(
                        """
                        INSERT INTO alias (entity_id, alias, source)
                        VALUES (%s, %s, 'manual')
                        ON CONFLICT DO NOTHING
                        """,
                        (company_entity_id, alias),
                    )

                # Link to drugs they develop
                for chembl_id in develops_drugs:
                    # Find drug entity
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

                    # Create edge: company --develops--> drug
                    cur.execute(
                        """
                        INSERT INTO edge (src_id, predicate, dst_id, source)
                        VALUES (%s, 'develops', %s, 'manual')
                        ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                        """,
                        (company_entity_id, drug_entity_id),
                    )
                    inserted_edges += cur.rowcount

            conn.commit()

    print(f"\n✓ Companies inserted: {inserted_companies}")
    print(f"✓ Company-drug edges: {inserted_edges}")

if __name__ == "__main__":
    # POC company list - major pharma relevant to our disease areas
    poc_companies = [
        # Obesity/Metabolic leaders
        {
            "name": "Eli Lilly and Company",
            "cik": "0000059478",
            "develops": ["CHEMBL4297448"],  # Tirzepatide (Mounjaro, Zepbound)
            "aliases": ["Eli Lilly", "Lilly"],
        },
        {
            "name": "Novo Nordisk A/S",
            "cik": "0000353278",
            "develops": [
                "CHEMBL2109743",  # Semaglutide (Ozempic, Wegovy)
                "CHEMBL1201580",  # Liraglutide (Victoza, Saxenda)
                "CHEMBL2107834",  # Dulaglutide (Trulicity)
            ],
            "aliases": ["Novo Nordisk", "Novo"],
        },
        # Alzheimer's Disease leaders
        {
            "name": "Eisai Co., Ltd.",
            "cik": "0001062822",
            "develops": ["CHEMBL2366541"],  # Lecanemab (Leqembi)
            "aliases": ["Eisai"],
        },
        {
            "name": "Biogen Inc.",
            "cik": "0000875045",
            "develops": ["CHEMBL4297072"],  # Aducanumab (Aduhelm)
            "aliases": ["Biogen", "Biogen Idec"],
        },
        # KRAS Oncology leaders
        {
            "name": "Amgen Inc.",
            "cik": "0000318154",
            "develops": ["CHEMBL4297299"],  # Sotorasib (Lumakras)
            "aliases": ["Amgen"],
        },
        {
            "name": "Mirati Therapeutics, Inc.",
            "cik": "0001440718",
            "develops": ["CHEMBL4594668"],  # Adagrasib (Krazati)
            "aliases": ["Mirati", "Mirati Therapeutics"],
        },
        # Other major pharma (for broader context)
        {
            "name": "Pfizer Inc.",
            "cik": "0000078003",
            "develops": [],
            "aliases": ["Pfizer"],
        },
        {
            "name": "Johnson & Johnson",
            "cik": "0000200406",
            "develops": [],
            "aliases": ["J&J", "Janssen"],
        },
        {
            "name": "Merck & Co., Inc.",
            "cik": "0000310158",
            "develops": [],
            "aliases": ["Merck", "MSD"],
        },
        {
            "name": "Roche Holding AG",
            "cik": "0001047402",
            "develops": [],
            "aliases": ["Roche", "Genentech"],
        },
    ]

    load_companies(poc_companies)
