"""
Stage 3 — Route Scoring
Multi-dimensional evaluation of candidate routes.
Phase 1: SA Score, Route Maturity, Green Index (basic), Scale-Up (proxy), Cost Index (reference), REACH/GHS.

STUB: all _compute_* methods return mock values. Replace with real implementations.
"""
import httpx
from app.core.config import settings
from app.core.logging import get_logger
from app.models.route import RouteScores, SynthesisRoute

logger = get_logger(__name__)


class ScoringService:
    def __init__(self):
        self._echa_base = settings.echa_api_base_url

    async def score_routes(self, routes: list[SynthesisRoute]) -> list[SynthesisRoute]:
        scored = []
        for route in routes:
            scores = await self._score_route(route)
            route.scores = scores
            scored.append(route)
        return scored

    async def _score_route(self, route: SynthesisRoute) -> RouteScores:
        all_smiles = self._collect_all_smiles(route)

        sa_score = self._compute_sa_score(route.steps[-1].product_smiles)
        route_maturity = self._compute_route_maturity(route)
        green_index = self._compute_green_index(route)
        scale_up_readiness = self._compute_scale_up_proxy(route)
        cost_index = self._compute_cost_index(all_smiles)
        reach_compliant, ghs_flags = await self._check_reach_ghs(all_smiles)

        return RouteScores(
            sa_score=sa_score,
            route_maturity=route_maturity,
            green_index=green_index,
            scale_up_readiness=scale_up_readiness,
            cost_index=cost_index,
            reach_compliant=reach_compliant,
            ghs_hazard_flags=ghs_flags,
        )

    def _compute_sa_score(self, smiles: str) -> float | None:
        # TODO: from rdkit.Chem import RDConfig; SA Score via Ertl & Schuffenhauer
        return 2.8  # STUB: mock score (1=easy, 10=hard)

    def _compute_route_maturity(self, route: SynthesisRoute) -> float | None:
        # TODO: score based on literature precedent (reaction template coverage in USPTO/ORD)
        return round(0.5 + 0.1 * min(route.step_count, 4), 2)  # STUB: fewer steps → slightly higher maturity proxy

    def _compute_green_index(self, route: SynthesisRoute) -> float | None:
        # TODO: atom economy + CHEM21/GSK solvent guide + E-factor calculation
        return round(70.0 - route.step_count * 5.0, 1)  # STUB: penalise longer routes

    def _compute_scale_up_proxy(self, route: SynthesisRoute) -> float | None:
        # TODO: tag-matching against known scale-up challenge patterns
        # (exotherms, gas evolution, cryogenic, high-pressure)
        return 0.75  # STUB

    def _compute_cost_index(self, smiles_list: list[str]) -> float | None:
        # TODO: reference price table lookup per reagent SMILES
        return round(1.5 + len(smiles_list) * 0.3, 2)  # STUB: more reagents → higher cost

    async def _check_reach_ghs(self, smiles_list: list[str]) -> tuple[bool | None, list[str]]:
        # TODO: ECHA API + PubChem GHS classification per reagent
        return True, []  # STUB: assume compliant, no flags

    def _collect_all_smiles(self, route: SynthesisRoute) -> list[str]:
        smiles = set()
        for step in route.steps:
            smiles.update(step.reactants_smiles)
            smiles.update(step.reagents_smiles)
        return list(smiles)
