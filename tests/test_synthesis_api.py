"""
Tests for Stage synthesis planning API endpoints.
Celery task execution is mocked - these test the API layer only.
"""
import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app

BASE = "/api/v1/synthesis"
HEADERS = {"x-tenant-id": "test-tenant"}


def _mock_task(task_id: str = "job-abc-123"):
    task = MagicMock()
    task.id = task_id
    return task


# ─── POST /synthesis/plan ─────────────────────────────────────────────────────

class TestSubmitSynthesisPlan:
    @pytest.mark.asyncio
    async def test_submit_returns_202_and_job_id(self):
        with patch("app.api.routes.synthesis.run_synthesis_plan") as mock_task:
            mock_task.delay.return_value = _mock_task("job-123")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"{BASE}/plan",
                    json={"molecule": {"value": "CCO", "format": "smiles"}},
                    headers=HEADERS,
                )
        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == "job-123"
        assert body["status"] == "pending"

    @pytest.mark.asyncio
    async def test_submit_without_tenant_header_returns_422(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"{BASE}/plan",
                json={"molecule": {"value": "CCO"}},
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_without_molecule_returns_422(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"{BASE}/plan",
                json={},
                headers=HEADERS,
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_with_all_options(self):
        with patch("app.api.routes.synthesis.run_synthesis_plan") as mock_task:
            mock_task.delay.return_value = _mock_task("job-456")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"{BASE}/plan",
                    json={
                        "molecule": {"value": "64-17-5", "format": "cas"},
                        "optimisation_dimension": "lowest_cost",
                        "max_routes": 3,
                        "max_depth": 4,
                    },
                    headers=HEADERS,
                )
        assert response.status_code == 202
        assert response.json()["job_id"] == "job-456"


# ─── GET /synthesis/jobs/{id}/status ─────────────────────────────────────────

class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_pending_job(self):
        with patch("app.api.routes.synthesis.AsyncResult") as mock_result_cls:
            mock_result_cls.return_value.state = "PENDING"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"{BASE}/jobs/job-123/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["progress_pct"] == 0

    @pytest.mark.asyncio
    async def test_in_progress_job(self):
        with patch("app.api.routes.synthesis.AsyncResult") as mock_result_cls:
            mock_result = MagicMock()
            mock_result.state = "PROGRESS"
            mock_result.info = {
                "status": "inferring",
                "stage_label": "Running retrosynthesis inference",
                "progress_pct": 15,
                "updated_at": "2026-02-27T10:00:00+00:00",
            }
            mock_result_cls.return_value = mock_result
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"{BASE}/jobs/job-123/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "inferring"
        assert body["progress_pct"] == 15
        assert body["stage_label"] == "Running retrosynthesis inference"

    @pytest.mark.asyncio
    async def test_completed_job(self):
        with patch("app.api.routes.synthesis.AsyncResult") as mock_result_cls:
            mock_result_cls.return_value.state = "SUCCESS"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"{BASE}/jobs/job-123/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["progress_pct"] == 100

    @pytest.mark.asyncio
    async def test_failed_job(self):
        with patch("app.api.routes.synthesis.AsyncResult") as mock_result_cls:
            mock_result = MagicMock()
            mock_result.state = "FAILURE"
            mock_result.info = Exception("Inference timeout")
            mock_result_cls.return_value = mock_result
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"{BASE}/jobs/job-123/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error"] is not None


# ─── GET /synthesis/jobs/{id}/result ─────────────────────────────────────────

class TestGetJobResult:
    @pytest.mark.asyncio
    async def test_result_not_ready_returns_400(self):
        with patch("app.api.routes.synthesis.AsyncResult") as mock_result_cls:
            mock_result_cls.return_value.state = "PROGRESS"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"{BASE}/jobs/job-123/result")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_job_returns_404(self):
        with patch("app.api.routes.synthesis.AsyncResult") as mock_result_cls:
            mock_result_cls.return_value.state = "PENDING"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"{BASE}/jobs/nonexistent/result")
        assert response.status_code == 404
