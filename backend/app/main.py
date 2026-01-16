from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from backend.app.db import get_conn
import json

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
    return FileResponse("frontend/index.html")

@app.get("/api/graph/nodes")
def list_nodes(kind: str = Query(None)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if kind:
                cur.execute("SELECT id, kind, canonical_id, name FROM entity WHERE kind = %s ORDER BY name", (kind,))
            else:
                cur.execute("SELECT id, kind, canonical_id, name FROM entity ORDER BY name")
            nodes = [dict(row) for row in cur.fetchall()]
    return {"nodes": nodes}

@app.get("/api/graph/edges")
def list_edges(min_score: float = Query(0.0), top_per_disease: int = Query(10)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.src_id, e.dst_id, e.type, e1.kind AS src_kind, e2.kind AS dst_kind,
                       e1.name AS src_name, e2.name AS dst_name, e.props
                FROM edge e
                JOIN entity e1 ON e.src_id = e1.id
                JOIN entity e2 ON e.dst_id = e2.id
            """)
            edges = []
            disease_counts = {}
            for row in cur.fetchall():
                d = dict(row)
                props = d.get('props') or {}
                score = props.get('score', 0.0) if isinstance(props, dict) else 0.0
                d['score'] = score
                if d['type'] == 'associated_with' and d['src_kind'] == 'disease':
                    src_id = d['src_id']
                    disease_counts[src_id] = disease_counts.get(src_id, 0) + 1
                    if disease_counts[src_id] > top_per_disease or score < min_score:
                        continue
                edges.append(d)
    return {"edges": edges}

@app.get("/debug.html")
def debug_page():
    return FileResponse("frontend/debug.html")

@app.get("/test.html")
def test_page():
    return FileResponse("frontend/test.html")
