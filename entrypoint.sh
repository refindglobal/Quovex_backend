#!/bin/sh

# ── Fix Railway's postgres:// → postgresql:// (SQLAlchemy 2.x requirement) ───
if [ -n "$DATABASE_URL" ]; then
    DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|^postgres://|postgresql://|')
    export DATABASE_URL
    echo "==> DATABASE_URL dialect: $(echo $DATABASE_URL | cut -d: -f1)"
fi

# ── Run Alembic migrations (non-fatal — log errors, continue startup) ─────────
echo "==> Running Alembic migrations..."
if alembic upgrade head; then
    echo "==> Migrations OK"
else
    echo "==> WARNING: Alembic migration failed (see above). Starting anyway..."
fi

# ── Start uvicorn ─────────────────────────────────────────────────────────────
echo "==> Starting Quovex API on port ${PORT:-8000}..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${UVICORN_WORKERS:-2}" \
  --log-level info
