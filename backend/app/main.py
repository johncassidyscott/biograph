import os

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row

from .db import get_conn

app = FastAPI(title="BioGraph API", version="0.1.0")

# ---- Simple UI (served at /) ----
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ---- API ----
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/meta")
def meta():
    return {
        "service": "biograph-api",
        "endpoints": ["/health", "/docs", "/seed", "/entities", "/seed_edges", "/edges"],
        "ui": "/",
    }


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
            # Get total count
            cur.execute(
                """
                SELECT COUNT(*) as total
                FROM entity
                WHERE kind = %s
                """,
                (kind,),
            )
            total_count = cur.fetchone()["total"]

            # Get items
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
    return JSONResponse(content={"count": total_count, "items": items})


@app.get("/entity/{entity_id}")
def get_entity_detail(entity_id: int):
    """Get full details for a single entity including aliases and type-specific data"""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Get basic entity info (including description and metadata)
            cur.execute("""
                SELECT id, kind, canonical_id, name, description, metadata, created_at, updated_at
                FROM entity
                WHERE id = %s
            """, (entity_id,))
            entity = cur.fetchone()

            if not entity:
                return JSONResponse(content={"error": "Entity not found"}, status_code=404)

            result = dict(entity)
            if result.get("created_at"):
                result["created_at"] = result["created_at"].isoformat()
            if result.get("updated_at"):
                result["updated_at"] = result["updated_at"].isoformat()

            # Extract resolution confidence from metadata
            if result.get("metadata") and isinstance(result["metadata"], dict):
                if "resolution_confidence" in result["metadata"]:
                    result["resolution_confidence"] = result["metadata"]["resolution_confidence"]

            # Get aliases
            cur.execute("""
                SELECT alias, source
                FROM alias
                WHERE entity_id = %s
                ORDER BY alias
            """, (entity_id,))
            result["aliases"] = cur.fetchall()

            # Get external identifiers
            cur.execute("""
                SELECT identifier_type, identifier, source, verified_at
                FROM entity_identifier
                WHERE entity_id = %s
                ORDER BY identifier_type
            """, (entity_id,))
            identifiers = cur.fetchall()
            if identifiers:
                # Convert verified_at timestamps to ISO format
                result["identifiers"] = [
                    {
                        **dict(id_row),
                        "verified_at": id_row["verified_at"].isoformat() if id_row.get("verified_at") else None
                    }
                    for id_row in identifiers
                ]

            # Get industry classifications
            cur.execute("""
                SELECT classification_type, code, is_primary, source
                FROM entity_classification
                WHERE entity_id = %s
                ORDER BY is_primary DESC, classification_type, code
            """, (entity_id,))
            classifications = cur.fetchall()
            if classifications:
                result["classifications"] = classifications

            # Get type-specific data based on kind
            kind = result["kind"]

            if kind == "trial":
                cur.execute("""
                    SELECT nct_id, phase, status, enrollment, start_date, completion_date, brief_title
                    FROM trial
                    WHERE entity_id = %s
                """, (entity_id,))
                trial_data = cur.fetchone()
                if trial_data:
                    result["trial_details"] = dict(trial_data)

            elif kind == "news":
                cur.execute("""
                    SELECT url, published_date, source, summary
                    FROM news_item
                    WHERE entity_id = %s
                """, (entity_id,))
                news_data = cur.fetchone()
                if news_data:
                    result["news_details"] = dict(news_data)
                    if result["news_details"].get("published_date"):
                        result["news_details"]["published_date"] = result["news_details"]["published_date"].isoformat()

                # Get MeSH terms for news
                cur.execute("""
                    SELECT mesh_ui, mesh_name, confidence, is_major_topic, source
                    FROM news_mesh
                    WHERE news_entity_id = %s
                    ORDER BY confidence DESC, mesh_name
                """, (entity_id,))
                result["mesh_terms"] = cur.fetchall()

            elif kind == "disease":
                # Get MeSH tree numbers
                mesh_ui = result.get("canonical_id", "").replace("MESH:", "")
                if mesh_ui:
                    cur.execute("""
                        SELECT tree_number
                        FROM mesh_tree
                        WHERE ui = %s
                        ORDER BY tree_number
                    """, (mesh_ui,))
                    result["mesh_trees"] = [r["tree_number"] for r in cur.fetchall()]

            elif kind == "publication":
                # Get MeSH indexing for publication
                cur.execute("""
                    SELECT mesh_ui, mesh_name, is_major_topic, confidence, source
                    FROM article_mesh
                    WHERE article_entity_id = %s
                    ORDER BY is_major_topic DESC, confidence DESC
                """, (entity_id,))
                result["mesh_terms"] = cur.fetchall()

                # Get publication types
                cur.execute("""
                    SELECT pub_type
                    FROM publication_type
                    WHERE article_entity_id = %s
                    ORDER BY pub_type
                """, (entity_id,))
                result["publication_types"] = [r["pub_type"] for r in cur.fetchall()]

            # Get relationship counts
            cur.execute("""
                SELECT COUNT(*) as count FROM edge WHERE src_id = %s
            """, (entity_id,))
            result["outgoing_count"] = cur.fetchone()["count"]

            cur.execute("""
                SELECT COUNT(*) as count FROM edge WHERE dst_id = %s
            """, (entity_id,))
            result["incoming_count"] = cur.fetchone()["count"]

            result["total_relationships"] = result["outgoing_count"] + result["incoming_count"]

    return JSONResponse(content=result)


@app.post("/seed_edges")
def seed_edges():
    """
    Creates a few edges between the seeded entities so the graph is real.
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select id, canonical_id from entity")
            id_by = {r["canonical_id"]: r["id"] for r in cur.fetchall()}

            edges = [
                ("CHEMBL:CHEMBL25", "treats", "MESH:D009765"),
                ("CHEMBL:CHEMBL4297448", "treats", "MESH:D009765"),
                ("CHEMBL:CHEMBL25", "targets", "UNIPROT:P41159"),
                ("CHEMBL:CHEMBL4297448", "targets", "UNIPROT:P41159"),
                ("CHEMBL:CHEMBL4297448", "targets", "UNIPROT:Q9HBX9"),
                ("CIK:0000059478", "develops", "CHEMBL:CHEMBL4297448"),
                ("CIK:0000353278", "develops", "CHEMBL:CHEMBL25"),
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

    # Get total count
    count_sql = f"""
      select count(*) as total
      from edge e
      {where_sql}
    """

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
             e.confidence,
             e.created_at
      from edge e
      join entity s on s.id = e.src_id
      join entity d on d.id = e.dst_id
      {where_sql}
      order by e.id
      limit %s
    """

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Get total count
            cur.execute(count_sql, params if where else [])
            total_count = cur.fetchone()["total"]

            # Get items
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()

    items = []
    for r in rows:
        d = dict(r)
        if d.get("created_at") is not None:
            d["created_at"] = d["created_at"].isoformat()
        items.append(d)

    return {"count": total_count, "items": items}