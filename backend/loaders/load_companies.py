"""Load pharmaceutical company data."""
from typing import List, Dict
from app.db import get_conn

def load_companies(company_list: List[Dict[str, str]]):
    """Load company entities."""
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            companies_inserted = 0
            
            for company in company_list:
                name = company["name"]
                cik = company["cik"]
                
                print(f"Processing: {name} (CIK:{cik})")
                
                cur.execute("""
                    INSERT INTO entity (external_id, kind, name, attributes)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (external_id) DO UPDATE
                    SET name = EXCLUDED.name
                    RETURNING id
                """, (
                    f"CIK:{cik}",
                    'company',
                    name,
                    {'cik': cik}
                ))
                companies_inserted += 1
            
            conn.commit()
            print(f"\n✓ Companies inserted: {companies_inserted}")
