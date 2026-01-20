#!/usr/bin/env python3
"""BioGraph Cyberpunk Dashboard"""
from flask import Flask, render_template, jsonify, request, g
from flask_cors import CORS
import sys
import os
import logging
import uuid
import atexit
from functools import wraps
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from backend.app.db import get_conn, init_pool, close_pool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(request_id)s] %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize connection pool at startup
try:
    init_pool(min_size=2, max_size=10)
    logger.info("Database connection pool initialized")
except Exception as e:
    logger.error(f"Failed to initialize connection pool: {e}")
    # Continue anyway - will fall back to per-request connections

# Cleanup pool at shutdown
atexit.register(close_pool)

# Parse admin API keys from environment
ADMIN_API_KEYS = set(filter(None, os.getenv('ADMIN_API_KEYS', '').split(',')))
if ADMIN_API_KEYS:
    logger.info(f"Admin API key authentication enabled ({len(ADMIN_API_KEYS)} keys)")

# ============================================================================
# MIDDLEWARE: Request ID
# ============================================================================

@app.before_request
def add_request_id():
    """Add unique request ID for tracing."""
    g.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))

@app.after_request
def add_request_id_header(response):
    """Add request ID to response headers."""
    if hasattr(g, 'request_id'):
        response.headers['X-Request-ID'] = g.request_id
    return response

# ============================================================================
# MIDDLEWARE: Error Handling
# ============================================================================

@app.errorhandler(Exception)
def handle_error(e):
    """Global error handler to prevent stack trace leakage."""
    request_id = g.get('request_id', 'unknown')
    logger.exception(f"[{request_id}] Unhandled error: {e}")
    return jsonify({
        'error': 'Internal server error',
        'request_id': request_id
    }), 500

@app.errorhandler(404)
def handle_not_found(e):
    """Handle 404 errors."""
    return jsonify({
        'error': 'Not found',
        'request_id': g.get('request_id', 'unknown')
    }), 404

# ============================================================================
# MIDDLEWARE: API Key Authentication
# ============================================================================

def require_api_key(f):
    """
    Decorator to require API key authentication.

    Usage:
        @app.route('/admin/curate')
        @require_api_key
        def curate():
            ...

    API key should be provided in X-API-Key header.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key not in ADMIN_API_KEYS:
            logger.warning(f"[{g.get('request_id')}] Unauthorized API key attempt")
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

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
    """
    Health check endpoint.

    Returns:
        200: Service healthy, database connected
        503: Service degraded, database disconnected
    """
    health_status = {
        'status': 'ok',
        'request_id': g.get('request_id', 'unknown')
    }

    # Check database connectivity
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                if result and result[0] == 1:
                    health_status['database'] = 'connected'
                else:
                    health_status['database'] = 'unhealthy'
                    health_status['status'] = 'degraded'
    except Exception as e:
        logger.error(f"Health check database error: {e}")
        health_status['database'] = 'disconnected'
        health_status['status'] = 'degraded'
        return jsonify(health_status), 503

    return jsonify(health_status), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
