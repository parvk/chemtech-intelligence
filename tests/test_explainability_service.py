"""
Tests for Stage 5 — Explainability Layer (ExplainabilityService).

Unit tests mock the Claude API — no API key required.
Integration tests (marked integration) hit the real Claude API — skip in CI with:
    pytest -m "not integration"
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic import APIConnectionError, APIStatusError

from app.services.explainability_service import ExplainabilityService
from tests.conftest import make_route, make_step


@pytest.fixture
def svc():
    svc = ExplainabilityService()
    # Replace the real client with a mock — no network calls in unit tests
    svc._client = MagicMock()
    return svc


def mock_response(text: str = "This route is viable.") -> MagicMock:
    """Build a minimal Anthropic messages.create response mock."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


# ─── _format_route_summary ────────────────────────────────────────────────────

class TestFormatRouteSummary:
    def test_single_step_output_has_step_label(self, svc):
        route = make_route(step_count=1)
        summary = svc._format_route_summary(route)
        assert "Step 1" in summary

    def test_arrow_separator_present(self, svc):
        route = make_route(step_count=1)
        summary = svc._format_route_summary(route)
        assert "→" in summary

    def test_confidence_present(self, svc):
        route = make_route(step_count=1)
        summary = svc._format_route_summary(route)
        assert "confidence:" in summary

    def test_line_count_matches_step_count(self, svc):
        route = make_route(step_count=4)
        lines = svc._format_route_summary(route).strip().split("\n")
        assert len(lines) == 4

    def test_none_reaction_class_shown_as_unknown(self, svc):
        route = make_route(step_count=1)
        route.steps[0].reaction_class = None
        assert "unknown" in svc._format_route_summary(route)

    def test_empty_route_returns_empty_string(self, svc):
        route = make_route(step_count=0)
        assert svc._format_route_summary(route) == ""


# ─── _template_fallback ───────────────────────────────────────────────────────

class TestTemplateFallback:
    def test_includes_step_count(self, svc):
        route = make_route(step_count=4)
        result = svc._template_fallback(route)
        assert "4-step" in result

    def test_includes_sa_score_when_present(self, svc):
        route = make_route(sa_score=2.5)
        result = svc._template_fallback(route)
        assert "2.5" in result

    def test_shows_na_when_sa_score_missing(self, svc):
        route = make_route(sa_score=None)
        result = svc._template_fallback(route)
        assert "N/A" in result

    def test_returns_non_empty_string(self, svc):
        route = make_route()
        assert len(svc._template_fallback(route)) > 0


# ─── _generate_route_rationale ────────────────────────────────────────────────

class TestGenerateRouteRationale:
    @pytest.mark.asyncio
    async def test_returns_claude_text(self, svc):
        svc._client.messages.create = AsyncMock(
            return_value=mock_response("Viable route via esterification.")
        )
        result = await svc._generate_route_rationale(make_route(), "CC(=O)Oc1ccccc1C(=O)O")
        assert result == "Viable route via esterification."

    @pytest.mark.asyncio
    async def test_prompt_contains_target_smiles(self, svc):
        captured: dict = {}

        async def capture(**kwargs):
            captured["messages"] = kwargs["messages"]
            return mock_response()

        svc._client.messages.create = capture
        target = "CC(=O)Oc1ccccc1C(=O)O"
        await svc._generate_route_rationale(make_route(), target)
        assert target in captured["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_prompt_contains_score_values(self, svc):
        captured: dict = {}

        async def capture(**kwargs):
            captured["messages"] = kwargs["messages"]
            return mock_response()

        svc._client.messages.create = capture
        route = make_route(sa_score=2.5, route_maturity=0.8, green_index=72.0)
        await svc._generate_route_rationale(route, "c1ccccc1")

        prompt = captured["messages"][0]["content"]
        assert "2.5" in prompt
        assert "0.8" in prompt
        assert "72.0" in prompt

    @pytest.mark.asyncio
    async def test_uses_configured_model(self, svc):
        captured: dict = {}

        async def capture(**kwargs):
            captured.update(kwargs)
            return mock_response()

        svc._client.messages.create = capture
        await svc._generate_route_rationale(make_route(), "c1ccccc1")
        assert captured["model"] == svc._model

    @pytest.mark.asyncio
    async def test_value_error_not_retried_propagates(self, svc):
        """ValueError is not a transient API error — must propagate immediately."""
        svc._client.messages.create = AsyncMock(side_effect=ValueError("bad data"))
        with pytest.raises(ValueError):
            await svc._generate_route_rationale(make_route(), "c1ccccc1")


# ─── enrich_routes ────────────────────────────────────────────────────────────

class TestEnrichRoutes:
    @pytest.mark.asyncio
    async def test_all_routes_receive_rationale(self, svc):
        svc._client.messages.create = AsyncMock(return_value=mock_response("Good route."))
        routes = [make_route(f"r{i}") for i in range(3)]
        enriched = await svc.enrich_routes(routes, "c1ccccc1")
        for route in enriched:
            assert route.rationale is not None
            assert len(route.rationale) > 0

    @pytest.mark.asyncio
    async def test_api_error_triggers_template_fallback(self, svc):
        svc._client.messages.create = AsyncMock(side_effect=ValueError("unexpected"))
        route = make_route("r1")
        enriched = await svc.enrich_routes([route], "c1ccccc1")
        assert enriched[0].rationale is not None
        # Fallback includes step count
        assert str(enriched[0].step_count) in enriched[0].rationale

    @pytest.mark.asyncio
    async def test_api_status_error_falls_back_after_retries(self, svc):
        """APIStatusError exhausts tenacity retries → fallback template used."""
        svc._client.messages.create = AsyncMock(
            side_effect=APIStatusError(
                "rate limited", response=MagicMock(status_code=429), body={}
            )
        )
        route = make_route("r1")
        enriched = await svc.enrich_routes([route], "c1ccccc1")
        assert enriched[0].rationale is not None

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, svc):
        """One route succeeds via Claude, one fails and falls back."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response("Claude rationale for first route.")
            raise ValueError("API failure on second call")

        svc._client.messages.create = side_effect
        routes = [make_route("r1"), make_route("r2")]
        enriched = await svc.enrich_routes(routes, "c1ccccc1")

        # Both must have a rationale (one from Claude, one from fallback)
        for route in enriched:
            assert route.rationale is not None

        rationales = {r.route_id: r.rationale for r in enriched}
        # One rationale should be the Claude text, one the fallback
        assert any("Claude rationale" in r for r in rationales.values())

    @pytest.mark.asyncio
    async def test_returns_same_list_object(self, svc):
        svc._client.messages.create = AsyncMock(return_value=mock_response())
        routes = [make_route("r1")]
        enriched = await svc.enrich_routes(routes, "c1ccccc1")
        assert enriched is routes

    @pytest.mark.asyncio
    async def test_empty_routes_returns_empty(self, svc):
        enriched = await svc.enrich_routes([], "c1ccccc1")
        assert enriched == []

    @pytest.mark.asyncio
    async def test_routes_enriched_in_parallel(self, svc):
        """All routes should be enriched (asyncio.gather) — no route left without rationale."""
        svc._client.messages.create = AsyncMock(return_value=mock_response("ok"))
        routes = [make_route(f"r{i}") for i in range(5)]
        enriched = await svc.enrich_routes(routes, "c1ccccc1")
        assert all(r.rationale is not None for r in enriched)
        assert svc._client.messages.create.call_count == 5


# ─── Integration (real Claude API — skip in CI) ───────────────────────────────

@pytest.mark.integration
class TestExplainabilityIntegration:
    @pytest.mark.asyncio
    async def test_real_rationale_for_aspirin_route(self):
        """Hit the real Claude API and verify a non-empty rationale is returned."""
        svc = ExplainabilityService()
        routes = [make_route("r1", step_count=2)]
        enriched = await svc.enrich_routes(routes, "CC(=O)Oc1ccccc1C(=O)O")
        assert enriched[0].rationale
        assert len(enriched[0].rationale) > 50

    @pytest.mark.asyncio
    async def test_rationale_is_chemically_plausible_string(self):
        """Rationale should be prose, not JSON or error text."""
        svc = ExplainabilityService()
        routes = [make_route("r1")]
        enriched = await svc.enrich_routes(routes, "c1ccccc1")
        rationale = enriched[0].rationale
        assert rationale is not None
        assert not rationale.startswith("{")   # not JSON
        assert "." in rationale                # at least one sentence
