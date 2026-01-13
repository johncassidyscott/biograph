from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from .db import get_conn
app = FastAPI(title="BioGraph API", version="0.1.0")

@app.get("/")
def root():
   return {
       "service": "biograph-api",
       "endpoints": ["/health", "/docs", "/seed", "/entities"]
   }

@app.get("/health")
def health():
   return {"ok": True}

@app.post("/seed")
def seed():
   rows = [
       ("drug", "CHEMBL:CHEMBL25", "Semaglutide"),
       ("drug", "CHEMBL:CHEMBL4297448", "Tirzepatide"),
       ("company", "CIK:0000059478", "Eli Lilly and Company"),
       ("company", "CIK:0000353278", "Novo Nordisk A/S"),
       ("target", "UNIPROT:P41159", "GLP1R"),
       ("target", "UNIPROT:Q9HBX9", "GIPR"),
       ("disease", "MESH:D009765", "Obesity"),
   ]
   inserted = 0
   with get_conn() as conn:
       with conn.cursor() as cur:
           for kind, cid, name in rows:
               cur.execute(
                   """
                   INSERT INTO entity (kind, canonical_id, name)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (kind, canonical_id)
                   DO NOTHING
                   RETURNING id
                   """,
                   (kind, cid, name),
               )
               if cur.fetchone() is not None:
                   inserted += 1
       conn.commit()
   return {"attempted": len(rows), "inserted": inserted}

@app.get("/entities")
def entities(
   kind: str = Query(default="drug"),
   limit: int = Query(default=50, ge=1, le=200),
):
   with get_conn() as conn:
       with conn.cursor(row_factory=dict_row) as cur:
           cur.execute(
               """
               SELECT id, kind, canonical_id, name
               FROM entity
               WHERE kind = %s
               ORDER BY id
               LIMIT %s
               """,
               (kind, limit),
           )
           items = cur.fetchall()
   return JSONResponse(
       content={
           "count": len(items),
           "items": items,
       }
   )

@app.post("/seed_edges")
def seed_edges():
   """
   Creates a few edges between the seeded entities so the graph is real.
   """
   with get_conn() as conn:
       with conn.cursor(row_factory=dict_row) as cur:
           # Lookup ids by canonical_id
           cur.execute("select id, canonical_id from entity")
           id_by = {r["canonical_id"]: r["id"] for r in cur.fetchall()}
           # Define edges (src, predicate, dst)
           edges = [
               ("CHEMBL:CHEMBL25", "treats", "MESH:D009765"),              # Semaglutide treats Obesity
               ("CHEMBL:CHEMBL4297448", "treats", "MESH:D009765"),         # Tirzepatide treats Obesity
               ("CHEMBL:CHEMBL25", "targets", "UNIPROT:P41159"),           # Semaglutide targets GLP1R
               ("CHEMBL:CHEMBL4297448", "targets", "UNIPROT:P41159"),      # Tirzepatide targets GLP1R
               ("CHEMBL:CHEMBL4297448", "targets", "UNIPROT:Q9HBX9"),      # Tirzepatide targets GIPR
               ("CIK:0000059478", "develops", "CHEMBL:CHEMBL4297448"),     # Lilly develops Tirzepatide
               ("CIK:0000353278", "develops", "CHEMBL:CHEMBL25"),          # Novo develops Semaglutide (simplified)
           ]
           inserted = 0
           for src_cid, pred, dst_cid in edges:
               if src_cid not in id_by or dst_cid not in id_by:
                   continue
               cur.execute(
                   """
                   insert into edge (src_id, predicate, dst_id, source)
                   values (%s, %s, %s, %s)
                   on conflict (src_id, predicate, dst_id) do nothing
                   returning id
                   """,
                   (id_by[src_cid], pred, id_by[dst_cid], "manual"),
               )
               if cur.fetchone() is not None:
                   inserted += 1
       conn.commit()
   return {"attempted": len(edges), "inserted": inserted}

@app.get("/edges")
def list_edges(
   src_id: int | None = Query(default=None),
   dst_id: int | None = Query(default=None),
   predicate: str | None = Query(default=None),
   limit: int = Query(default=100, ge=1, le=500),
):
   where = []
   params = []
   if src_id is not None:
       where.append("e.src_id = %s")
       params.append(src_id)
   if dst_id is not None:
       where.append("e.dst_id = %s")
       params.append(dst_id)
   if predicate is not None:
       where.append("e.predicate = %s")
       params.append(predicate)
   where_sql = ("where " + " and ".join(where)) if where else ""
   sql = f"""
     select e.id,
            e.src_id,
            s.kind as src_kind,
            s.name as src_name,
            e.predicate,
            e.dst_id,
            d.kind as dst_kind,
            d.name as dst_name,
            e.source,
            e.created_at
     from edge e
     join entity s on s.id = e.src_id
     join entity d on d.id = e.dst_id
     {where_sql}
     order by e.id
     limit %s
   """
   params.append(limit)
   with get_conn() as conn:
       with conn.cursor(row_factory=dict_row) as cur:
           cur.execute(sql, params)
           rows = cur.fetchall()
   items = []
   for r in rows:
       d = dict(r)
       if d.get("created_at") is not None:
           d["created_at"] = d["created_at"].isoformat()
       items.append(d)
   return {"count": len(items), "items": items}