"""FastAPI main application."""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from backend.app.db import get_conn
import os

app = FastAPI(title="biograph API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    """Serve index.html"""
    return FileResponse("frontend/index.html")

@app.get("/api/graph/nodes")
def list_nodes(kind: str = Query(None)):
    """Get nodes."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if kind:
                cur.execute(
                    "SELECT id, kind, canonical_id, name FROM entity WHERE kind = %s ORDER BY name",
                    (kind,)
                )
            else:
                cur.execute("SELECT id, kind, canonical_id, name FROM entity ORDER BY name")
            
            nodes = [dict(row) for row in cur.fetchall()]
    return {"nodes": nodes}

@app.get("/api/graph/edges")
def list_edges():
    """Get all edges."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.src_id, e.dst_id, e.type, e1.kind, e2.kind, e1.name, e2.name
                FROM edge e
                JOIN entity e1 ON e.src_id = e1.id
                JOIN entity e2 ON e.dst_id = e2.id
            """)
            edges = [dict(row) for row in cur.fetchall()]
    return {"edges": edges}

@app.get("/api/graph/subgraph/{disease_id}")
def get_subgraph(disease_id: int):
    """Get disease subgraph with targets and drugs."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, canonical_id FROM entity WHERE id = %s AND kind = 'disease'",
                (disease_id,)
            )
            disease_row = cur.fetchone()
            if not disease_row:
                return {"error": "Disease not found"}
            
            cur.execute("""
                SELECT DISTINCT e2.id, e2.name, e2.canonical_id
                FROM edge e
                JOIN entity e2 ON e.dst_id = e2.id
                WHERE e.src_id = %s AND e.type = 'associated_with'
            """, (disease_id,))
            targets = [dict(row) for row in cur.fetchall()]
            
            target_ids = tuple(t["id"] for t in targets)
            drugs = []
            if target_ids:
                cur.execute("""
                    SELECT DISTINCT e2.id, e2.name, e2.canonical_id
                    FROM edge e
                    JOIN entity e2 ON e2.id = e.src_id
                    WHERE e.dst_id = ANY(%s) AND e.type = 'inhibits'
                """, (target_ids,))
                drugs = [dict(row) for row in cur.fetchall()]
    
    return {
        "disease": dict(disease_row),
        "targets": targets,
        "drugs": drugs
    }
