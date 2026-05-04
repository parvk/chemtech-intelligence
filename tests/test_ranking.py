"""
Tests for Stage 4 - Ranking & Filtering.
Pure computation, no external dependencies.
"""
import pytest
from tests.conftest import make_route
from app.models.molecule import OptimisationDimension
from app.services.ranking_service import RankingService, MISSING_SCORE_PENALTY


@pytest.fixture
def svc():
    return RankingService()


# ─── Ranking order ────────────────────────────────────────────────────────────

class TestRankingOrder:
    def test_fewest_steps_prefers_shorter_route(self, svc):
        routes = [
            make_route("r1", step_count=6),
            make_route("r2", step_count=2),
            make_route("r3", step_count=4),
        ]
        ranked = svc.rank(routes, OptimisationDimension.FEWEST_STEPS)
        assert ranked[0].route_id == "r2"
        assert ranked[-1].route_id == "r1"

    def test_lowest_cost_prefers_cheaper_route(self, svc):
        routes = [
            make_route("r1", cost_index=5.0),
            make_route("r2", cost_index=1.0),
            make_route("r3", cost_index=3.0),
        ]
        ranked = svc.rank(routes, OptimisationDimension.LOWEST_COST)
        assert ranked[0].route_id == "r2"
        assert ranked[-1].route_id == "r1"

    def test_greenest_route_prefers_higher_green_index(self, svc):
        routes = [
            make_route("r1", green_index=30.0, sa_score=4.0),
            make_route("r2", green_index=90.0, sa_score=2.0),
            make_route("r3", green_index=60.0, sa_score=3.0),
        ]
        ranked = svc.rank(routes, OptimisationDimension.GREENEST_ROUTE)
        assert ranked[0].route_id == "r2"
        assert ranked[-1].route_id == "r1"

    def test_most_precedented_prefers_higher_route_maturity(self, svc):
        routes = [
            make_route("r1", route_maturity=0.2),
            make_route("r2", route_maturity=0.9),
            make_route("r3", route_maturity=0.5),
        ]
        ranked = svc.rank(routes, OptimisationDimension.MOST_PRECEDENTED)
        assert ranked[0].route_id == "r2"
        assert ranked[-1].route_id == "r1"

    def test_highest_yield_weights_maturity_over_sa(self, svc):
        # r1: high maturity (0.9), poor SA (8.0)
        # r2: low maturity (0.3), great SA (1.5)
        # maturity weight=0.7 should dominate
        routes = [
            make_route("r1", route_maturity=0.9, sa_score=8.0),
            make_route("r2", route_maturity=0.3, sa_score=1.5),
        ]
        ranked = svc.rank(routes, OptimisationDimension.HIGHEST_YIELD)
        assert ranked[0].route_id == "r1"


# ─── top_n slicing ────────────────────────────────────────────────────────────

class TestTopN:
    def test_returns_at_most_top_n(self, svc):
        routes = [make_route(f"r{i}", step_count=i + 1) for i in range(8)]
        ranked = svc.rank(routes, OptimisationDimension.FEWEST_STEPS, top_n=3)
        assert len(ranked) == 3

    def test_returns_all_if_fewer_than_top_n(self, svc):
        routes = [make_route("r1"), make_route("r2")]
        ranked = svc.rank(routes, OptimisationDimension.FEWEST_STEPS, top_n=5)
        assert len(ranked) == 2

    def test_single_route_returns_that_route(self, svc):
        routes = [make_route("only")]
        ranked = svc.rank(routes, OptimisationDimension.FEWEST_STEPS)
        assert len(ranked) == 1
        assert ranked[0].route_id == "only"


# ─── Missing / None scores ────────────────────────────────────────────────────

class TestMissingScores:
    def test_missing_score_penalised_not_excluded(self, svc):
        routes = [
            make_route("r1", cost_index=None),   # missing
            make_route("r2", cost_index=2.0),
        ]
        ranked = svc.rank(routes, OptimisationDimension.LOWEST_COST)
        assert len(ranked) == 2
        # r2 has a real cost and should rank above the missing-score route
        assert ranked[0].route_id == "r2"

    def test_all_missing_scores_still_produces_composite(self, svc):
        routes = [
            make_route("r1", cost_index=None),
            make_route("r2", cost_index=None),
        ]
        ranked = svc.rank(routes, OptimisationDimension.LOWEST_COST)
        for route in ranked:
            assert route.composite_score == pytest.approx(MISSING_SCORE_PENALTY)


# ─── Composite score properties ───────────────────────────────────────────────

class TestCompositeScore:
    def test_composite_score_set_on_all_routes(self, svc):
        routes = [make_route(f"r{i}") for i in range(3)]
        ranked = svc.rank(routes, OptimisationDimension.FEWEST_STEPS)
        for route in ranked:
            assert route.composite_score is not None

    def test_composite_score_between_0_and_1(self, svc):
        routes = [make_route(f"r{i}", step_count=i + 1) for i in range(5)]
        ranked = svc.rank(routes, OptimisationDimension.FEWEST_STEPS)
        for route in ranked:
            assert 0.0 <= route.composite_score <= 1.0

    def test_identical_routes_get_same_composite_score(self, svc):
        routes = [
            make_route("r1", step_count=3, cost_index=2.0),
            make_route("r2", step_count=3, cost_index=2.0),
        ]
        svc.rank(routes, OptimisationDimension.FEWEST_STEPS)
        assert routes[0].composite_score == pytest.approx(routes[1].composite_score)

    def test_empty_routes_returns_empty(self, svc):
        ranked = svc.rank([], OptimisationDimension.FEWEST_STEPS)
        assert ranked == []
