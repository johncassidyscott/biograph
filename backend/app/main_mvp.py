#!/usr/bin/env python3
"""
BioGraph MVP Flask Application

Investor-grade intelligence graph API.
"""
from flask import Flask
from flask_cors import CORS
from .api_mvp import api

def create_app():
    app = Flask(__name__)
    CORS(app)

    # Register MVP API blueprint
    app.register_blueprint(api)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
