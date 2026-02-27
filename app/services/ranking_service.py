"""
Stage 4 — Ranking & Filtering
Re-ranks scored routes by selected optimisation dimension.
Re-rank is pure computation — no re-inference needed (< 1s).
"""
from app.core.logging import get_logger
from app.models.molecule import OptimisationDimension
from app.models.route import RouteScores, SynthesisRoute

logger = get_logger(__name__)

# Dimension-specific score weights: (score_field, weight, ascending)
# ascending=True means lower value = better (e.g. SA Score, step count)
DIMENSION_WEIGHTS: dict[OptimisationDimension, list[tuple[str, float, bool]]] = {
    OptimisationDimension.FEWEST_STEPS: [
        ("step_count", 1.0, True),
    ],
    OptimisationDimension.HIGHEST_YIELD: [
        ("route_maturity", 0.7, False),
        ("sa_score", 0.3, True),
    ],
    OptimisationDimension.LOWEST_COST: [
        ("cost_index", 1.0, True),
    ],
    OptimisationDimension.GREENEST_ROUTE: [
        ("green_index", 0.8, False),
        ("sa_score", 0.2, True),
    ],
    OptimisationDimension.MOST_PRECEDENTED: [
        ("route_maturity", 1.0, False),
    ],
}


class RankingService:
    def rank(
        self,
        routes: list[SynthesisRoute],
        dimension: OptimisationDimension,
        top_n: int = 5,
    ) -> list[SynthesisRoute]:
        logger.info("ranking_routes", dimension=dimension, total=len(routes))

        weights = DIMENSION_WEIGHTS.get(dimension, [])
        for route in routes:
            route.composite_score = self._compute_composite(route, weights)

        ranked = sorted(routes, key=lambda r: r.composite_score or 0.0, reverse=True)
        return ranked[:top_n]

    def _compute_composite(
        self,
        route: SynthesisRoute,
        weights: list[tuple[str, float, bool]],
    ) -> float:
        # TODO: normalise each dimension across the route set, apply weights
        # Handle missing (None) scores gracefully — penalise but don't exclude
        raise NotImplementedError
