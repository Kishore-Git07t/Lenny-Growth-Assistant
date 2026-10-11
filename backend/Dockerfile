# ==============================================================================
# Lenny Growth Assistant - Backend Dockerfile
#
# Multi-runtime image: Python 3.11 (FastAPI) + Node.js 20 (Pi Coding Agent)
# Resource-tuned for 8 GB RAM laptop deployment.
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    NODE_ENV=production \
    PATH="/app/agent_runtime/node_modules/.bin:${PATH}"

# Install curl, ca-certificates, gnupg, and Node.js 22 LTS (pi-coding-agent requires node >=22.19.0)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 2. Install Pi Coding Agent runtime dependencies (@earendil-works/pi-coding-agent)
COPY agent_runtime/package.json agent_runtime/package-lock.json /app/agent_runtime/
WORKDIR /app/agent_runtime
RUN npm ci --omit=dev && npm cache clean --force

# Symlink pi executable to /usr/local/bin so it is globally available on PATH
RUN ln -sf /app/agent_runtime/node_modules/.bin/pi /usr/local/bin/pi

WORKDIR /app

# 3. Copy application backend code, alembic configuration, and local configs
COPY backend/ /app/backend/
COPY .local/pi-agent/ /app/.local/pi-agent/

# Set up entrypoint script permissions (normalize CRLF to LF in case checkout is on Windows)
RUN sed -i 's/\r$//' /app/backend/entrypoint.sh && chmod +x /app/backend/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/app/backend/entrypoint.sh"]
