# ChemFlow Intelligence Service

AI inference service for retrosynthesis, route scoring, and explainability.

---

## Docker Commands

### Local Development

```bash
# First time setup
cp .env.example .env

# Prerequisite: chemtech_network must exist (created by chemtech-be)
# Either start chemtech-be first, or create the network manually:
docker network create chemtech_network

# Start core services (API + worker + postgres + redis)
docker compose up

# Start with hot reload in background
docker compose up -d

# Start with pgadmin + Flower (job monitor)
docker compose --profile tools up

# Stop all
docker compose down

# Stop and remove volumes (wipes database)
docker compose down -v
```

### Production

```bash
# Start production stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Stop production stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# View logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker
```

### Useful One-Liners

```bash
# Tail API logs
docker logs -f chemflow_intelligence_api

# Tail worker logs
docker logs -f chemflow_intelligence_worker

# Open a shell in the API container
docker exec -it chemflow_intelligence_api bash

# Run tests inside container
docker exec -it chemflow_intelligence_api pytest

# Restart just the worker (after code change without hot reload)
docker compose restart worker
```

---

## Port Map (Local)

| Service    | Container Port | Host Port | Notes                          |
|------------|---------------|-----------|--------------------------------|
| API        | 8001          | **8001**  | FastAPI — http://localhost:8001 |
| Postgres   | 5432          | **5434**  | Offset to avoid conflict with chemtech-be (5433) |
| Redis      | 6379          | **6380**  | Offset to avoid conflict        |
| Flower     | 5555          | **5555**  | Job monitor — `--profile tools` only |
| pgAdmin    | 80            | **5051**  | DB UI — `--profile tools` only  |

> In production, Postgres and Redis ports are not exposed outside the container network.

---

## Service URLs (Local)

| URL | Description |
|-----|-------------|
| http://localhost:8001/docs | Swagger / OpenAPI UI |
| http://localhost:8001/redoc | ReDoc API docs |
| http://localhost:8001/health | Health check |
| http://localhost:5555 | Flower (Celery job monitor) |
| http://localhost:5051 | pgAdmin |

---

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/synthesis/plan` | Submit synthesis planning job (returns `job_id`) |
| `GET`  | `/api/v1/synthesis/jobs/{job_id}/status` | Poll job status + progress |
| `GET`  | `/api/v1/synthesis/jobs/{job_id}/result` | Retrieve completed result |
| `GET`  | `/health` | Service health check |
