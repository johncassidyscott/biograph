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
   with get_conn() as conn:
       with conn.cursor() as cur:
           for kind, cid, name in rows:
               cur.execute(
                   """
                   INSERT INTO entity (kind, canonical_id, name)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (kind, canonical_id)
                   DO NOTHING
                   """,
                   (kind, cid, name),
               )
       conn.commit()
   return {"seeded": len(rows)}

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