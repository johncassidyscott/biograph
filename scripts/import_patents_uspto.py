import os, re, json, time, urllib.parse, requests, psycopg2

DB_URL = os.environ.get("DATABASE_URL")
PV_URL = "https://api.patentsview.org/patents/query"

def get_conn(): 
    if not DB_URL: raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DB_URL)

def upsert_entity(cur, kind, cid, name):
    cur.execute("SELECT id FROM entity WHERE canonical_id=%s AND kind=%s", (cid, kind))
    r = cur.fetchone()
    if r: return r[0]
    cur.execute("INSERT INTO entity(kind, canonical_id, name) VALUES(%s,%s,%s) RETURNING id", (kind, cid, name[:255]))
    return cur.fetchone()[0]

def upsert_edge(cur, src_id, dst_id, typ, props=None):
    cur.execute("SELECT id FROM edge WHERE src_id=%s AND dst_id=%s AND type=%s", (src_id, dst_id, typ))
    if cur.fetchone(): return
    cur.execute("INSERT INTO edge(src_id,dst_id,type,props) VALUES(%s,%s,%s,%s::jsonb)", (src_id, dst_id, typ, json.dumps(props or {"source":"patentsview"})))

def fetch_drugs(cur):
    cur.execute("SELECT id, name FROM entity WHERE kind='drug' ORDER BY name")
    return cur.fetchall()

def patents_for_term(term, limit=3):
    q = {"_text_any":{"patent_title": term}}
    f = ["patent_number","patent_title","patent_date","assignees","assignees.assignee_organization"]
    params = {
        "q": json.dumps(q),
        "f": json.dumps(f),
        "o": json.dumps({"per_page": limit})
    }
    url = PV_URL + "?" + urllib.parse.urlencode(params)
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json().get("patents", [])

def main():
    with get_conn() as conn:
        with conn.cursor() as cur:
            drugs = fetch_drugs(cur)
            print(f"Drugs: {len(drugs)}")
            for drug_id, drug_name in drugs:
                print(f"\nSearching patents for {drug_name}...")
                try:
                    pts = patents_for_term(drug_name, limit=3)
                except Exception as e:
                    print(f"  PatentsView error: {e}")
                    continue
                if not pts:
                    print("  No patents found.")
                    continue
                for p in pts:
                    pnum = p.get("patent_number")
                    ptitle = p.get("patent_title") or pnum or "Unknown patent"
                    if not pnum:
                        continue
                    patent_id = upsert_entity(cur, "patent", f"PATENT:{pnum}", ptitle)
                    upsert_edge(cur, drug_id, patent_id, "protected_by", {"source":"patentsview"})
                    # Assignees
                    for a in (p.get("assignees") or [])[:2]:
                        org = (a.get("assignee_organization") or "").strip()
                        if not org: continue
                        comp_id = upsert_entity(cur, "company", f"ORG:{re.sub(r'\s+','_',org.upper())[:120]}", org)
                        upsert_edge(cur, patent_id, comp_id, "assigned_to", {"source":"patentsview"})
                conn.commit()
                time.sleep(0.5)

if __name__ == "__main__":
    main()
