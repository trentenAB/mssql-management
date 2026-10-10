#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# Flask development server; binds only to the local machine.
exec .venv/bin/flask --app wsgi run --host 127.0.0.1 --port "${PORT:-8000}"
