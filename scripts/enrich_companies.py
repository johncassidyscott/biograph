#!/usr/bin/env python3
import requests
import psycopg
import os
import json
import time
import re

DATABASE_URL = os.environ["DATABASE_URL"]

# Our 7 companies with SEC tickers
COMPANIES = [
    {"id": 6032, "name": "Merck & Co.", "wikidata_query": "Merck & Co.", "ticker": "MRK"},
    {"id": 6033, "name": "Takeda Pharmaceutical", "wikidata_query": "Takeda Pharmaceutical Company", "ticker": "TAK"},
    {"id": 6034, "name": "Regeneron Pharmaceuticals", "wikidata_query": "Regeneron Pharmaceuticals", "ticker": "REGN"},
    {"id": 6035, "name": "Sanofi", "wikidata_query": "Sanofi", "ticker": "SNY"},
    {"id": 6036, "name": "Amgen", "wikidata_query": "Amgen", "ticker": "AMGN"},
    {"id": 6037, "name": "Novartis", "wikidata_query": "Novartis", "ticker": "NVS"},
    {"id": 6038, "name": "Biogen", "wikidata_query": "Biogen", "ticker": "BIIB"}
]

def fetch_sec_cik(ticker):
    """Fetch CIK from SEC EDGAR"""
    url = "https://www.sec.gov/cgi-bin/browse-edgar"
    headers = {"User-Agent": "biograph research@example.com"}
    params = {"action": "getcompany", "CIK": ticker, "type": "", "dateb": "", "owner": "exclude", "output": "atom"}
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        
        # Extract CIK from response
        match = re.search(r'<CIK>(\d+)</CIK>', r.text)
        if match:
            cik = match.group(1).zfill(10)  # Pad to 10 digits
            return cik
    except Exception as e:
        print(f"  SEC error: {e}")
    
    return None

def fetch_wikidata(name):
    """Fetch company data from Wikidata"""
    query = f"""
    SELECT ?company ?companyLabel ?founded ?hqLabel ?countryLabel ?website ?employees ?revenue ?ticker WHERE {{
      ?company rdfs:label "{name}"@en .
      ?company wdt:P31/wdt:P279* wd:Q4830453 .  # instance of pharmaceutical company
      OPTIONAL {{ ?company wdt:P571 ?founded . }}
      OPTIONAL {{ ?company wdt:P159 ?hq . }}
      OPTIONAL {{ ?company wdt:P17 ?country . }}
      OPTIONAL {{ ?company wdt:P856 ?website . }}
      OPTIONAL {{ ?company wdt:P1128 ?employees . }}
      OPTIONAL {{ ?company wdt:P2139 ?revenue . }}
      OPTIONAL {{ ?company wdt:P249 ?ticker . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
    }}
    LIMIT 1
    """
    
    url = "https://query.wikidata.org/sparql"
    headers = {"User-Agent": "biograph/0.1", "Accept": "application/json"}
    
    try:
        r = requests.get(url, params={"query": query}, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if data["results"]["bindings"]:
            row = data["results"]["bindings"][0]
            return {
                "wikidata_id": row.get("company", {}).get("value", "").split("/")[-1],
                "founded": row.get("founded", {}).get("value"),
                "headquarters": row.get("hqLabel", {}).get("value"),
                "country": row.get("countryLabel", {}).get("value"),
                "website": row.get("website", {}).get("value"),
                "employees": row.get("employees", {}).get("value"),
                "revenue": row.get("revenue", {}).get("value"),
                "ticker": row.get("ticker", {}).get("value")
            }
    except Exception as e:
        print(f"  Wikidata error: {e}")
    
    return {}

def fetch_opencorporates(name):
    """Fetch company data from OpenCorporates (free tier, no API key)"""
    # OpenCorporates free tier requires API key, skip for now
    # Could scrape the website instead, but let's focus on SEC/Wikidata
    return {}

def main():
    conn = psycopg.connect(DATABASE_URL)
    
    for company in COMPANIES:
        print(f"\nEnriching: {company['name']}")
        
        # Fetch from Wikidata
        wikidata = fetch_wikidata(company["wikidata_query"])
        time.sleep(1)  # Be nice to APIs
        
        # Fetch CIK from SEC
        cik = fetch_sec_cik(company["ticker"])
        if cik:
            wikidata["cik"] = cik
            wikidata["sec_url"] = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
        time.sleep(1)
        
        # Add ticker
        wikidata["ticker"] = company["ticker"]
        
        if wikidata:
            print(f"  Found: {list(wikidata.keys())}")
            
            # Update entity props
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE entity SET props = props || %s::jsonb WHERE id = %s",
                    (json.dumps(wikidata), company["id"])
                )
            conn.commit()
        else:
            print(f"  No data found")
    
    conn.close()
    print("\n✓ Companies enriched with CIK, Wikidata, and SEC links!")

if __name__ == "__main__":
    main()
