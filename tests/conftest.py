import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.molecule import OptimisationDimension
from app.models.route import ReactionStep, RouteScores, SynthesisRoute


def pytest_addoption(parser):
    parser.addoption(
        "--smiles",
        action="store",
        default=None,
        help="Target SMILES string for smoke/integration tests (overrides the default test molecule)",
    )


@pytest.fixture
def target_smiles(request):
    """SMILES to use in smoke tests - pass via --smiles or falls back to aspirin."""
    return request.config.getoption("--smiles") or "CC(=O)Oc1ccccc1C(=O)O"


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def make_step(
    step_number: int = 1,
    product: str = "CCO",
    confidence: float = 0.85,
    reaction_class: str = "Reduction",
) -> ReactionStep:
    return ReactionStep(
        step_number=step_number,
        reactants_smiles=["CC=O"],
        reagents_smiles=["[NaBH4]"],
        product_smiles=product,
        reaction_smiles="CC=O>>[NaBH4]>CCO",
        reaction_class=reaction_class,
        confidence=confidence,
    )


def make_route(
    route_id: str = "route-1",
    step_count: int = 3,
    sa_score: float | None = 2.5,
    route_maturity: float | None = 0.8,
    green_index: float | None = 72.0,
    cost_index: float | None = 1.5,
    reach_compliant: bool = True,
    overall_confidence: float = 0.85,
    out_of_domain: bool = False,
) -> SynthesisRoute:
    steps = [make_step(i + 1) for i in range(step_count)]
    return SynthesisRoute(
        route_id=route_id,
        steps=steps,
        step_count=step_count,
        overall_confidence=overall_confidence,
        out_of_domain=out_of_domain,
        scores=RouteScores(
            sa_score=sa_score,
            route_maturity=route_maturity,
            green_index=green_index,
            cost_index=cost_index,
            reach_compliant=reach_compliant,
        ),
    )
