#!/usr/bin/env python3
"""BioGraph Cyberpunk Dashboard"""
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from backend.app.db import get_conn

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT kind, COUNT(*) as count 
                    FROM entity 
                    GROUP BY kind 
                    ORDER BY count DESC
                """)
                entities = {row['kind']: row['count'] for row in cur.fetchall()}
                
                cur.execute("SELECT COUNT(*) as count FROM edge")
                edges = cur.fetchone()['count']
                
                return jsonify({
                    'status': 'online',
                    'entities': entities,
                    'edges': edges,
                    'timestamp': 'LIVE'
                })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/search')
def search():
    query = request.args.get('q', '').strip()
    kind = request.args.get('kind', '')
    
    if not query:
        return jsonify([])
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if kind:
                    cur.execute("""
                        SELECT id, kind, canonical_id, name
                        FROM entity
                        WHERE kind = %s AND name ILIKE %s
                        LIMIT 20
                    """, (kind, f'%{query}%'))
                else:
                    cur.execute("""
                        SELECT id, kind, canonical_id, name
                        FROM entity
                        WHERE name ILIKE %s
                        LIMIT 20
                    """, (f'%{query}%',))
                
                results = [dict(row) for row in cur.fetchall()]
                return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
