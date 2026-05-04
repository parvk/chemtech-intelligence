"""
Stage 5 - Explainability Layer
Generates natural language rationale for routes and steps via Claude API.
Falls back to template-based generation on timeout or API error.
"""
import asyncio

import anthropic
from anthropic import APIConnectionError, APIStatusError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger
from app.models.route import SynthesisRoute

logger = get_logger(__name__)

ROUTE_RATIONALE_PROMPT = """You are a senior process chemist reviewing a proposed synthesis route.

Target molecule: {target_smiles}
Synthesis route ({step_count} steps):
{route_summary}

Scores:
- SA Score: {sa_score}
- Route Maturity: {route_maturity}
- Green Index: {green_index}%
- REACH Compliant: {reach_compliant}

Write a concise (3–5 sentence) rationale for this route: why it is viable, what its key strengths are, and what risks a chemist should be aware of. Be direct and technically specific. If there are uncertainties, state them explicitly - do not overstate confidence."""


class ExplainabilityService:
    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    async def enrich_routes(
        self,
        routes: list[SynthesisRoute],
        target_smiles: str,
    ) -> list[SynthesisRoute]:
        async def enrich_one(route: SynthesisRoute) -> None:
            try:
                route.rationale = await self._generate_route_rationale(route, target_smiles)
            except Exception as e:
                logger.warning("rationale_generation_failed", route_id=route.route_id, error=str(e))
                route.rationale = self._template_fallback(route)

        await asyncio.gather(*[enrich_one(r) for r in routes])
        return routes

    @retry(
        retry=retry_if_exception_type((APIStatusError, APIConnectionError)),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=8),
    )
    async def _generate_route_rationale(self, route: SynthesisRoute, target_smiles: str) -> str:
        route_summary = self._format_route_summary(route)
        prompt = ROUTE_RATIONALE_PROMPT.format(
            target_smiles=target_smiles,
            step_count=route.step_count,
            route_summary=route_summary,
            sa_score=route.scores.sa_score,
            route_maturity=route.scores.route_maturity,
            green_index=route.scores.green_index,
            reach_compliant=route.scores.reach_compliant,
        )

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=settings.anthropic_max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _template_fallback(self, route: SynthesisRoute) -> str:
        sa = f"{route.scores.sa_score:.1f}" if route.scores.sa_score else "N/A"
        return (
            f"This {route.step_count}-step route has an SA Score of {sa}. "
            f"Rationale generation was unavailable - review step details and scores manually."
        )

    def _format_route_summary(self, route: SynthesisRoute) -> str:
        lines = []
        for step in route.steps:
            reactants = " + ".join(step.reactants_smiles)
            lines.append(f"Step {step.step_number}: {reactants} → {step.product_smiles} (class: {step.reaction_class or 'unknown'}, confidence: {step.confidence:.2f})")
        return "\n".join(lines)
