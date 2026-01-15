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
                
                try:
                    cur.execute("""
                        INSERT INTO entity (canonical_id, kind, name)
                        VALUES (%s, %s, %s)
                        RETURNING id
                    """, (
                        f"cik:{cik}",
                        'company',
                        name
                    ))
                    companies_inserted += 1
                except:
                    pass  # Skip if already exists
            
            conn.commit()
            print(f"\n✓ Companies inserted: {companies_inserted}")
