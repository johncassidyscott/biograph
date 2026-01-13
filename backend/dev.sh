#!/usr/bin/env bash
set -euo pipefail
cd /workspaces/biograph/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload