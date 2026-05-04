"""
Stage 4 - Ranking & Filtering
Re-ranks scored routes by selected optimisation dimension.
Re-rank is pure computation - no re-inference needed (< 1s).
"""
from app.core.logging import get_logger
from app.models.molecule import OptimisationDimension
from app.models.route import SynthesisRoute

logger = get_logger(__name__)

# (score_field, weight, ascending)
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

MISSING_SCORE_PENALTY = 0.1


class RankingService:
    def rank(
        self,
        routes: list[SynthesisRoute],
        dimension: OptimisationDimension,
        top_n: int = 5,
    ) -> list[SynthesisRoute]:
        logger.info("ranking_routes", dimension=dimension, total=len(routes))

        weights = DIMENSION_WEIGHTS.get(dimension, [])
        ranges = self._compute_ranges(routes, weights)

        for route in routes:
            route.composite_score = self._compute_composite(route, weights, ranges)

        ranked = sorted(routes, key=lambda r: r.composite_score or 0.0, reverse=True)
        return ranked[:top_n]

    def _compute_ranges(
        self,
        routes: list[SynthesisRoute],
        weights: list[tuple[str, float, bool]],
    ) -> dict[str, tuple[float, float]]:
        """Compute min/max for each scored field across all routes for normalisation."""
        raw: dict[str, list[float]] = {field: [] for field, _, _ in weights}
        for route in routes:
            for field, _, _ in weights:
                val = self._get_field(route, field)
                if val is not None:
                    raw[field].append(val)
        return {
            field: (min(vals), max(vals))
            for field, vals in raw.items()
            if vals
        }

    def _compute_composite(
        self,
        route: SynthesisRoute,
        weights: list[tuple[str, float, bool]],
        ranges: dict[str, tuple[float, float]],
    ) -> float:
        if not weights:
            return 0.0

        total_weight = sum(w for _, w, _ in weights)
        score = 0.0

        for field, weight, ascending in weights:
            val = self._get_field(route, field)
            normalised = self._normalise(val, ranges.get(field), ascending)
            score += normalised * weight

        return score / total_weight

    def _get_field(self, route: SynthesisRoute, field: str) -> float | None:
        if field == "step_count":
            return float(route.step_count)
        val = getattr(route.scores, field, None)
        return float(val) if val is not None else None

    def _normalise(
        self,
        val: float | None,
        range_tuple: tuple[float, float] | None,
        ascending: bool,
    ) -> float:
        if val is None:
            return MISSING_SCORE_PENALTY
        if range_tuple is None:
            return 1.0  # only one route - trivially best
        min_val, max_val = range_tuple
        if max_val == min_val:
            return 1.0
        normalised = (val - min_val) / (max_val - min_val)
        return (1.0 - normalised) if ascending else normalised
