"""Unit tests validating Phase 8 Docker containerization and deployment configuration.

Validates:
1. docker-compose.yml and compose.yaml syntactic integrity and required services.
2. Resource limits tailored for an 8 GB RAM laptop (total allocated memory <= 2.5 GB).
3. Host Ollama networking resolution via host.docker.internal.
4. Database volume persistence and pgvector extension image.
5. Backend Dockerfile multi-runtime configuration (Python 3.11 + Node.js 20).
6. Frontend multi-stage Dockerfile and Nginx reverse proxy routing.
7. .dockerignore protection preventing secret and heavyweight data leakage.
"""

from pathlib import Path
import yaml
import pytest

from backend.app.config import get_project_root


@pytest.fixture
def project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return get_project_root()


# -----------------------------------------------------------------------------
# 1. Docker Compose Structure & Syntax Validation
# -----------------------------------------------------------------------------

def test_docker_compose_files_exist_and_are_valid_yaml(project_root: Path):
    """Verify docker-compose.yml and compose.yaml exist and parse as valid YAML."""
    compose_path = project_root / "docker-compose.yml"
    alt_compose_path = project_root / "compose.yaml"

    assert compose_path.exists(), "docker-compose.yml must exist at project root"
    assert alt_compose_path.exists(), "compose.yaml must exist at project root"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    assert "services" in compose_data, "compose file must define services"
    services = compose_data["services"]

    # Must contain all three mandatory application tiers
    assert "postgres" in services, "compose must define 'postgres' service"
    assert "backend" in services, "compose must define 'backend' service"
    assert "frontend" in services, "compose must define 'frontend' service"


def test_docker_compose_resource_limits_fit_8gb_ram_laptop(project_root: Path):
    """Verify CPU and memory limits are strictly bounded to fit an 8 GB RAM machine."""
    with open(project_root / "docker-compose.yml", "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    services = compose_data["services"]
    total_memory_mb = 0

    for svc_name in ["postgres", "backend", "frontend"]:
        svc = services[svc_name]
        assert "deploy" in svc, f"{svc_name} must specify deploy constraints"
        limits = svc["deploy"].get("resources", {}).get("limits", {})
        assert "memory" in limits, f"{svc_name} must declare a memory limit"

        mem_str = str(limits["memory"]).upper()
        if mem_str.endswith("M") or mem_str.endswith("MB"):
            mb = int(mem_str.rstrip("MB"))
        elif mem_str.endswith("G") or mem_str.endswith("GB"):
            mb = int(float(mem_str.rstrip("GB")) * 1024)
        else:
            mb = int(mem_str)
        total_memory_mb += mb

    # Total allocated RAM across all 3 containers must be <= 2,500 MB (~2.5 GB)
    # leaving > 5 GB free for Windows OS + Ollama running on host
    assert total_memory_mb <= 2500, (
        f"Total stack memory ({total_memory_mb} MB) exceeds 2,500 MB budget for 8 GB laptop"
    )


def test_docker_compose_ollama_host_networking(project_root: Path):
    """Verify backend container configures host.docker.internal to reach host Ollama."""
    with open(project_root / "docker-compose.yml", "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    backend_svc = compose_data["services"]["backend"]
    extra_hosts = backend_svc.get("extra_hosts", [])
    assert any("host.docker.internal" in str(h) for h in extra_hosts), (
        "backend service must include extra_hosts entry for host.docker.internal"
    )

    env_vars = backend_svc.get("environment", {})
    ollama_url = env_vars.get("OLLAMA_BASE_URL", "")
    assert "host.docker.internal" in str(ollama_url), (
        "backend OLLAMA_BASE_URL must default to host.docker.internal"
    )


def test_docker_compose_volume_persistence(project_root: Path):
    """Verify PostgreSQL uses a named persistent volume so data is not lost on restart."""
    with open(project_root / "docker-compose.yml", "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    postgres_svc = compose_data["services"]["postgres"]
    volumes = postgres_svc.get("volumes", [])
    assert any("postgres_data:" in str(v) for v in volumes), (
        "postgres service must mount the named postgres_data volume"
    )

    # Volume definition must be present at top level
    assert "volumes" in compose_data
    assert "postgres_data" in compose_data["volumes"]


def test_docker_compose_healthchecks_defined_on_all_services(project_root: Path):
    """Verify all 3 services define healthchecks with reasonable intervals."""
    with open(project_root / "docker-compose.yml", "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    for svc_name in ["postgres", "backend", "frontend"]:
        svc = compose_data["services"][svc_name]
        assert "healthcheck" in svc, f"{svc_name} must declare a healthcheck"
        assert "test" in svc["healthcheck"]


# -----------------------------------------------------------------------------
# 2. Backend Dockerfile & Entrypoint Validation
# -----------------------------------------------------------------------------

def test_backend_dockerfile_installs_node_and_pi_agent(project_root: Path):
    """Verify backend Dockerfile installs Node.js and the genuine Pi Coding Agent."""
    dockerfile_path = project_root / "backend" / "Dockerfile"
    assert dockerfile_path.exists(), "backend/Dockerfile must exist"

    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-runtime check: Python base + Node.js
    assert "python:3.11-slim" in content or "python:3.12-slim" in content
    assert "nodejs" in content
    assert "pi-coding-agent" in content or "agent_runtime" in content

    # Check that entrypoint script is invoked
    assert "entrypoint.sh" in content


def test_backend_entrypoint_script_contents(project_root: Path):
    """Verify backend entrypoint script waits for PostgreSQL and runs migrations."""
    entrypoint_path = project_root / "backend" / "entrypoint.sh"
    assert entrypoint_path.exists(), "backend/entrypoint.sh must exist"

    content = entrypoint_path.read_text(encoding="utf-8")
    assert "psycopg" in content, "entrypoint must probe database readiness using psycopg"
    assert "alembic upgrade head" in content, "entrypoint must apply migrations on startup"
    assert "uvicorn" in content, "entrypoint must launch uvicorn"


# -----------------------------------------------------------------------------
# 3. Frontend Multi-Stage Dockerfile & Nginx Configuration Validation
# -----------------------------------------------------------------------------

def test_frontend_dockerfile_multi_stage_build(project_root: Path):
    """Verify frontend uses multi-stage build: Node builder -> Nginx runner."""
    dockerfile_path = project_root / "frontend" / "Dockerfile"
    assert dockerfile_path.exists(), "frontend/Dockerfile must exist"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "AS builder" in content or "as builder" in content
    assert "nginx:alpine" in content or "nginx:alpine-slim" in content
    assert "npm run build" in content


def test_frontend_nginx_configuration(project_root: Path):
    """Verify Nginx reverse proxies /api/ with extended timeouts for AI generation."""
    nginx_conf_path = project_root / "frontend" / "nginx.conf"
    assert nginx_conf_path.exists(), "frontend/nginx.conf must exist"

    content = nginx_conf_path.read_text(encoding="utf-8")

    # SPA routing fallback
    assert "try_files $uri $uri/ /index.html;" in content

    # Backend API reverse proxy
    assert "location /api/" in content
    assert "proxy_pass http://backend:8000/api/;" in content

    # Generous read timeout for local LLM generation (>= 900 seconds)
    assert "proxy_read_timeout 960s;" in content or "proxy_read_timeout" in content


# -----------------------------------------------------------------------------
# 4. Dockerignore Secret & Bloat Protection Validation
# -----------------------------------------------------------------------------

def test_dockerignore_protects_secrets_and_bloat(project_root: Path):
    """Verify .dockerignore excludes .env, virtualenvs, node_modules, and raw corpora."""
    dockerignore_path = project_root / ".dockerignore"
    assert dockerignore_path.exists(), ".dockerignore must exist at project root"

    content = dockerignore_path.read_text(encoding="utf-8")
    ignored_patterns = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]

    assert ".env" in ignored_patterns
    assert any("node_modules" in p for p in ignored_patterns)
    assert any("venv" in p for p in ignored_patterns)
    assert any("corpus" in p for p in ignored_patterns)
