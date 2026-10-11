#!/usr/bin/env bash
set -e

# ==============================================================================
# Lenny Growth Assistant - Backend Container Entrypoint
#
# 1. Waits for PostgreSQL to accept connections.
# 2. Applies Alembic database migrations idempotently (alembic upgrade head).
# 3. Synchronizes Pi Coding Agent configuration with environment settings.
# 4. Launches FastAPI via Uvicorn.
# ==============================================================================

echo "=========================================================="
echo " Starting Lenny Growth Assistant Backend Container"
echo "=========================================================="

# 1. Wait for PostgreSQL readiness
echo "[1/4] Probing PostgreSQL connectivity..."
python - <<'EOF'
import os
import sys
import time

url = os.getenv("DATABASE_URL", "")
if not url:
    print("Notice: DATABASE_URL is not set. Skipping database wait.", flush=True)
    sys.exit(0)

# Normalize SQLAlchemy driver prefix for direct psycopg connection check
clean_url = url.replace("postgresql+psycopg://", "postgresql://")

max_retries = 30
for attempt in range(1, max_retries + 1):
    try:
        import psycopg
        conn = psycopg.connect(clean_url, connect_timeout=3)
        conn.close()
        print(f"PostgreSQL connection verified successfully (attempt {attempt}).", flush=True)
        sys.exit(0)
    except Exception as exc:
        if attempt % 5 == 0 or attempt == 1:
            print(f"Waiting for PostgreSQL to become ready (attempt {attempt}/{max_retries})...", flush=True)
        time.sleep(1)

print("Warning: PostgreSQL wait timed out. Continuing startup...", file=sys.stderr, flush=True)
sys.exit(0)
EOF

# 2. Run Alembic database migrations
echo "[2/4] Applying database migrations..."
if [ -n "$DATABASE_URL" ]; then
    (
        cd /app/backend
        alembic upgrade head
    )
    echo "Database migrations applied successfully."
else
    echo "Notice: DATABASE_URL not set. Skipping migrations."
fi

# 3. Synchronize Pi Coding Agent models.json
echo "[3/4] Initializing Pi Coding Agent runtime configuration..."
python - <<'EOF'
try:
    from backend.app.agent.pi_client import PiClient
    client = PiClient()
    models_file = client.ensure_local_models_config()
    print(f"Pi Coding Agent model configuration ready at: {models_file}", flush=True)
except Exception as err:
    print(f"Notice: Non-blocking error during Pi config init: {err}", file=sys.stderr, flush=True)
EOF

# 4. Start Uvicorn application server
echo "[4/4] Starting FastAPI backend server on 0.0.0.0:8000..."
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1
