"""
Stage 3 — Route Scoring
Multi-dimensional evaluation of candidate routes.
Phase 1: SA Score, Route Maturity, Green Index (basic), Scale-Up (proxy), Cost Index (reference), REACH/GHS.
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
        raise NotImplementedError

    def _compute_route_maturity(self, route: SynthesisRoute) -> float | None:
        # TODO: score based on literature precedent (reaction template coverage in USPTO/ORD)
        raise NotImplementedError

    def _compute_green_index(self, route: SynthesisRoute) -> float | None:
        # TODO: atom economy + CHEM21/GSK solvent guide + E-factor calculation
        raise NotImplementedError

    def _compute_scale_up_proxy(self, route: SynthesisRoute) -> float | None:
        # TODO: tag-matching against known scale-up challenge patterns
        # (exotherms, gas evolution, cryogenic, high-pressure)
        raise NotImplementedError

    def _compute_cost_index(self, smiles_list: list[str]) -> float | None:
        # TODO: reference price table lookup per reagent SMILES
        raise NotImplementedError

    async def _check_reach_ghs(self, smiles_list: list[str]) -> tuple[bool | None, list[str]]:
        # TODO: ECHA API + PubChem GHS classification per reagent
        raise NotImplementedError

    def _collect_all_smiles(self, route: SynthesisRoute) -> list[str]:
        smiles = set()
        for step in route.steps:
            smiles.update(step.reactants_smiles)
            smiles.update(step.reagents_smiles)
        return list(smiles)
