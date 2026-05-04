# Testing - chemtech-intelligence

## Overview

| File | What it tests | External deps |
|---|---|---|
| `test_schemas.py` | Pydantic model validation, field constraints, enums | None |
| `test_health.py` | `/health` and `/docs` endpoints | None |
| `test_molecule_service.py` | Stage 1 - molecule resolution, format detection, PubChem lookup | PubChem (mocked in unit tests) |
| `test_retrosynthesis_service.py` | Stage 2 - AiZynthFinder integration, route parsing, OOD detection | AiZynthFinder models (mocked in unit tests) |
| `test_scoring_service.py` | Stage 3 - SA Score, Green Index, Route Maturity, REACH/GHS | PubChem (mocked in unit tests) |
| `test_ranking.py` | Stage 4 - route ranking across all optimisation dimensions | None |
| `test_explainability_service.py` | Stage 5 - rationale generation, Claude API, fallback | Claude API (mocked in unit tests) |
| `test_synthesis_api.py` | API layer - `/synthesis/plan` and `/synthesis/jobs/{id}` endpoints | None (Celery mocked) |

Tests are split into two tiers by marker:

- **Unit tests** - no external services, models, or network. Run anywhere, fast.
- **Integration tests** (`-m integration`) - hit real APIs or require downloaded AI models. Skip in CI.

---

## Running tests

All commands run from the repo root (`chemtech-intelligence/`) or inside the Docker container.

### Unit tests only (default, CI-safe)

```bash
pytest
```

```bash
pytest -m "not integration"
```

### All tests including integration

```bash
pytest -m integration
```

### Single file

```bash
pytest tests/test_retrosynthesis_service.py -v
```

### With coverage

```bash
pytest --cov=app --cov-report=term-missing
```

---

## Running a real synthesis

The smoke test runs actual AiZynthFinder inference and prints structured route output to the terminal. Requires models to be downloaded first (see Prerequisites below).

### Default molecule (aspirin)

```bash
pytest tests/test_retrosynthesis_service.py::TestRetrosynthesisSmoke::test_synthesis_output \
    -m integration -s -v
```

### Custom SMILES via `--smiles` flag

```bash
pytest tests/test_retrosynthesis_service.py::TestRetrosynthesisSmoke::test_synthesis_output \
    -m integration -s -v \
    --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O"
```

Replace the SMILES with any target molecule. The `-s` flag is required to stream the printed output.

### Parametrized known molecules (aspirin, ibuprofen, caffeine)

```bash
pytest tests/test_retrosynthesis_service.py::TestRetrosynthesisSmoke::test_known_molecules_find_routes \
    -m integration -s -v
```

### Example output

```
============================================================
  TARGET SMILES : CC(=O)Oc1ccccc1C(=O)O
============================================================

Route 1  (id: a3f8c2d1…)
  Steps           : 2
  Confidence      : 0.847
  Out-of-domain   : False
  Step 1: OC(=O)c1ccccc1O + CC(=O)O → CC(=O)Oc1ccccc1C(=O)O  [Esterification]  (conf: 0.912)
  Step 2: ...

── Full JSON output ──
[{ "route_id": "...", "steps": [...], "overall_confidence": 0.847, ... }]
```

---

## Prerequisites for integration tests

### 1. Start the stack

```bash
docker compose up --build
```

### 2. Download AI models (one-time, ~500 MB)

Run inside the worker container:

```bash
docker compose exec worker bash scripts/download_models.sh
```

This downloads the pre-trained USPTO expansion model, filter model, and ZINC stock file into `data/models/` and `data/stocks/`.

### 3. Run integration tests inside the worker container

The worker container has AiZynthFinder installed and the config mounted at `/app/config/aizynthfinder.yml`:

```bash
docker compose exec worker pytest tests/test_retrosynthesis_service.py -m integration -s -v
```

---

## Test markers

Markers are declared in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: hits real external APIs - skip in CI with -m 'not integration'",
]
```

Mark a test as integration with:

```python
@pytest.mark.integration
class TestMyIntegration:
    ...
```

---

## Fixtures

Shared fixtures live in `tests/conftest.py`.

| Fixture | Description |
|---|---|
| `client` | Async HTTPX test client wired to the FastAPI app |
| `target_smiles` | SMILES for smoke tests - overridden via `--smiles "..."` flag, defaults to aspirin |
| `make_step()` | Helper to build a `ReactionStep` with sensible defaults |
| `make_route()` | Helper to build a `SynthesisRoute` with configurable scores |

---

## CI behaviour

Integration tests are excluded by default in CI. Add this to your CI command:

```bash
pytest -m "not integration" --cov=app --cov-report=xml
```
