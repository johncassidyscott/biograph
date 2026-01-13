import os

from fastapi import FastAPI, Query

from fastapi.responses import JSONResponse

from .db import get_conn, init_db

app = FastAPI(title="BioGraph API", version="0.1.0")

@app.on_event("startup")

def startup() -> None:

    # Initialize schema on startup (fine for POC)

    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")

    init_db(schema_path)

@app.get("/health")

def health():

    return {"ok": True, "service": "biograph-api"}

@app.get("/entities")

def list_entities(

    kind: str = Query(default="drug"),

    q: str | None = Query(default=None, description="Optional name search substring"),

    limit: int = Query(default=50, ge=1, le=200),

):

    sql = """

        select id, kind, canonical_id, name, created_at, updated_at

        from entity

        where kind = %s

          and (%s is null or name ilike ('%%' || %s || '%%'))

        order by updated_at desc

        limit %s

    """

    with get_conn() as conn:

        with conn.cursor() as cur:

            cur.execute(sql, (kind, q, q, limit))

            rows = cur.fetchall()

    return {"count": len(rows), "items": rows}

@app.post("/seed")

def seed():

    # Minimal seed so you can see something in the UI quickly

    seed_rows = [

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

            for kind, canonical_id, name in seed_rows:

                cur.execute(

                    """

                    insert into entity (kind, canonical_id, name)

                    values (%s, %s, %s)

                    on conflict (kind, canonical_id) do update

                      set name = excluded.name,

                          updated_at = now()

                    """,

                    (kind, canonical_id, name),

                )

        conn.commit()

    return JSONResponse({"seeded": len(seed_rows)})
 