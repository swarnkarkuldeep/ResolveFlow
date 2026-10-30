#!/usr/bin/env sh
# Regenerate frontend/src/api/schema.d.ts from the FastAPI OpenAPI schema (no server needed).
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/backend/.venv/Scripts/python}"
[ -x "$PY" ] || PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
TMP="$(mktemp)"
DATABASE_URL=postgresql+psycopg://x:x@localhost/x REDIS_URL=redis://localhost:6379/0 \
  "$PY" -c "import json; from resolveflow.main import app; print(json.dumps(app.openapi()))" > "$TMP"
cd "$ROOT/frontend" && npx openapi-typescript "$TMP" -o src/api/schema.d.ts
rm -f "$TMP"
