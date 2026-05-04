"""
Tests for Stage 3 - Route Scoring (ScoringService).

Unit tests mock PubChem so they run offline.
Integration tests (marked integration) hit the real PubChem API - skip in CI with:
    pytest -m "not integration"
"""
import pytest
from unittest.mock import AsyncMock, patch

import app.services.scoring_service as scoring_module
from app.models.route import ReactionStep, RouteScores, SynthesisRoute
from app.services.scoring_service import ScoringService
from tests.conftest import make_route, make_step


@pytest.fixture
def svc():
    return ScoringService()


def make_step_ex(
    step_number: int = 1,
    reactants: list[str] | None = None,
    product: str = "CCO",
    confidence: float = 0.85,
) -> ReactionStep:
    """Extended make_step that allows custom reactant SMILES."""
    reactants = reactants or ["CC=O"]
    return ReactionStep(
        step_number=step_number,
        reactants_smiles=reactants,
        reagents_smiles=[],
        product_smiles=product,
        reaction_smiles=f"{'.'.join(reactants)}>>{product}",
        reaction_class=None,
        confidence=confidence,
    )


def make_route_from_steps(steps: list[ReactionStep], route_id: str = "r1") -> SynthesisRoute:
    return SynthesisRoute(
        route_id=route_id,
        steps=steps,
        step_count=len(steps),
        overall_confidence=0.8,
        out_of_domain=False,
        scores=RouteScores(),
    )


# ─── SA Score ─────────────────────────────────────────────────────────────────

class TestSAScore:
    def test_benzene_score_is_low(self, svc):
        """Benzene is trivially synthesisable - SA Score should be close to 1."""
        if not scoring_module._SASCORER_AVAILABLE:
            pytest.skip("sascorer not installed")
        score = svc._compute_sa_score("c1ccccc1")
        assert score is not None
        assert 1.0 <= score <= 2.0

    def test_aspirin_score_in_range(self, svc):
        if not scoring_module._SASCORER_AVAILABLE:
            pytest.skip("sascorer not installed")
        score = svc._compute_sa_score("CC(=O)Oc1ccccc1C(=O)O")
        assert score is not None
        assert 1.0 <= score <= 4.0

    def test_score_is_rounded_to_2dp(self, svc):
        if not scoring_module._SASCORER_AVAILABLE:
            pytest.skip("sascorer not installed")
        score = svc._compute_sa_score("c1ccccc1")
        assert score == round(score, 2)

    def test_invalid_smiles_returns_none(self, svc):
        score = svc._compute_sa_score("not-a-smiles")
        assert score is None

    def test_sascorer_unavailable_returns_none(self, svc):
        with patch.object(scoring_module, "_SASCORER_AVAILABLE", False):
            score = svc._compute_sa_score("c1ccccc1")
        assert score is None


# ─── Route Maturity ───────────────────────────────────────────────────────────

class TestRouteMaturity:
    def test_empty_route_returns_none(self, svc):
        route = make_route_from_steps([])
        assert svc._compute_route_maturity(route) is None

    def test_single_step_equals_confidence(self, svc):
        route = make_route_from_steps([make_step_ex(confidence=0.75)])
        assert svc._compute_route_maturity(route) == pytest.approx(0.75, abs=0.001)

    def test_uniform_confidences_geometric_mean_equals_value(self, svc):
        steps = [make_step_ex(i + 1, confidence=0.8) for i in range(4)]
        route = make_route_from_steps(steps)
        assert svc._compute_route_maturity(route) == pytest.approx(0.8, abs=0.001)

    def test_low_confidence_step_drags_maturity_down(self, svc):
        """A single weak step should pull the geometric mean well below the strong ones."""
        steps = [
            make_step_ex(1, confidence=0.9),
            make_step_ex(2, confidence=0.9),
            make_step_ex(3, confidence=0.1),  # weak
        ]
        route = make_route_from_steps(steps)
        maturity = svc._compute_route_maturity(route)
        expected = round((0.9 * 0.9 * 0.1) ** (1 / 3), 4)
        assert maturity == pytest.approx(expected, abs=0.001)
        assert maturity < 0.5

    def test_zero_confidence_clamped_does_not_error(self, svc):
        """Confidence of 0.0 is clamped to 1e-9 - must not raise or return None."""
        route = make_route_from_steps([make_step_ex(confidence=0.0)])
        result = svc._compute_route_maturity(route)
        assert result is not None
        assert result >= 0.0

    def test_result_rounded_to_4dp(self, svc):
        steps = [make_step_ex(i + 1, confidence=0.7) for i in range(3)]
        route = make_route_from_steps(steps)
        maturity = svc._compute_route_maturity(route)
        assert maturity == round(maturity, 4)


# ─── Green Index (Atom Economy) ───────────────────────────────────────────────

class TestGreenIndex:
    def test_diels_alder_is_100_percent(self, svc):
        """
        Diels-Alder addition: butadiene + ethylene → cyclohexene.
        All atoms incorporated - atom economy = 100%.
        """
        step = make_step_ex(reactants=["C=CC=C", "C=C"], product="C1CC=CCC1")
        route = make_route_from_steps([step])
        gi = svc._compute_green_index(route)
        assert gi == pytest.approx(100.0, abs=1.0)

    def test_esterification_below_100_percent(self, svc):
        """
        Esterification: acetic acid + ethanol → ethyl acetate.
        Water is lost - AE < 100%.
        """
        step = make_step_ex(
            reactants=["CC(=O)O", "CCO"],  # acetic acid + ethanol
            product="CC(=O)OCC",           # ethyl acetate
        )
        route = make_route_from_steps([step])
        gi = svc._compute_green_index(route)
        assert gi is not None
        assert 50.0 < gi < 100.0

    def test_result_capped_at_100(self, svc):
        """When MW(product) > MW(reactants) (addition reactions), result must not exceed 100."""
        # Hydration: maleic anhydride + water → maleic acid (product heavier than anhydride alone)
        step = make_step_ex(
            reactants=["O=C1OC(=O)C=C1"],  # maleic anhydride
            product="OC(=O)C=CC(=O)O",     # maleic acid
        )
        route = make_route_from_steps([step])
        gi = svc._compute_green_index(route)
        assert gi is not None
        assert gi <= 100.0

    def test_empty_route_returns_none(self, svc):
        route = make_route_from_steps([])
        assert svc._compute_green_index(route) is None

    def test_invalid_smiles_step_skipped(self, svc):
        """Invalid SMILES steps are skipped; valid steps still contribute."""
        valid = make_step_ex(1, reactants=["C=CC=C", "C=C"], product="C1CC=CCC1")
        invalid = ReactionStep(
            step_number=2,
            reactants_smiles=["not-valid"],
            reagents_smiles=[],
            product_smiles="also-invalid",
            reaction_smiles="not-valid>>also-invalid",
            reaction_class=None,
            confidence=0.5,
        )
        route = make_route_from_steps([valid, invalid])
        gi = svc._compute_green_index(route)
        assert gi is not None          # valid step contributes
        assert gi == pytest.approx(100.0, abs=1.0)

    def test_multi_step_averages_per_step_ae(self, svc):
        """Green index is the arithmetic mean of per-step atom economies."""
        diels_alder = make_step_ex(1, reactants=["C=CC=C", "C=C"], product="C1CC=CCC1")   # ~100%
        esterification = make_step_ex(2, reactants=["CC(=O)O", "CCO"], product="CC(=O)OCC")  # ~83%
        route = make_route_from_steps([diels_alder, esterification])
        gi = svc._compute_green_index(route)
        assert gi is not None
        assert 80.0 < gi < 100.0


# ─── Scale-Up Proxy (stub) ────────────────────────────────────────────────────

class TestScaleUpProxy:
    def test_returns_stub_value(self, svc):
        assert svc._compute_scale_up_proxy(make_route()) == 0.75

    def test_returns_float(self, svc):
        result = svc._compute_scale_up_proxy(make_route())
        assert isinstance(result, float)


# ─── Cost Index (stub) ────────────────────────────────────────────────────────

class TestCostIndex:
    def test_returns_float(self, svc):
        result = svc._compute_cost_index(["CCO", "CC(=O)O"])
        assert isinstance(result, float)

    def test_more_reagents_gives_higher_cost(self, svc):
        cost_few = svc._compute_cost_index(["CCO"])
        cost_many = svc._compute_cost_index(["CCO", "CC(=O)O", "c1ccccc1", "CN"])
        assert cost_many > cost_few

    def test_empty_reagent_list_returns_float(self, svc):
        result = svc._compute_cost_index([])
        assert isinstance(result, float)


# ─── REACH / GHS ──────────────────────────────────────────────────────────────

class TestReachGHS:
    @pytest.mark.asyncio
    async def test_no_concern_hcodes_reach_compliant(self, svc):
        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(return_value=["H315", "H319"])):
            compliant, hcodes = await svc._check_reach_ghs(["CCO"])
        assert compliant is True
        assert "H315" in hcodes

    @pytest.mark.asyncio
    async def test_carcinogen_hcode_not_compliant(self, svc):
        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(return_value=["H350"])):
            compliant, hcodes = await svc._check_reach_ghs(["c1ccccc1"])
        assert compliant is False
        assert "H350" in hcodes

    @pytest.mark.asyncio
    async def test_mutagen_hcode_not_compliant(self, svc):
        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(return_value=["H340"])):
            compliant, _ = await svc._check_reach_ghs(["CCO"])
        assert compliant is False

    @pytest.mark.asyncio
    async def test_aquatic_tox_hcode_not_compliant(self, svc):
        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(return_value=["H400"])):
            compliant, _ = await svc._check_reach_ghs(["CCO"])
        assert compliant is False

    @pytest.mark.asyncio
    async def test_all_lookups_fail_returns_none(self, svc):
        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(return_value=None)):
            compliant, hcodes = await svc._check_reach_ghs(["CCO"])
        assert compliant is None
        assert hcodes == []

    @pytest.mark.asyncio
    async def test_hcodes_deduplicated_across_reagents(self, svc):
        """Same H-code from two different reagents must appear only once."""
        async def by_smiles(client, smiles):
            return ["H315", "H319"] if "CCO" in smiles else ["H315", "H400"]

        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(side_effect=by_smiles)):
            _, hcodes = await svc._check_reach_ghs(["CCO", "CC(=O)O"])
        assert hcodes.count("H315") == 1

    @pytest.mark.asyncio
    async def test_hcodes_returned_sorted(self, svc):
        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(return_value=["H400", "H225", "H319"])):
            _, hcodes = await svc._check_reach_ghs(["CCO"])
        assert hcodes == sorted(hcodes)

    @pytest.mark.asyncio
    async def test_novel_compound_no_flags_is_compliant(self, svc):
        """Unknown compound (not in PubChem) returns [] - treated as compliant, no flags."""
        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(return_value=[])):
            compliant, hcodes = await svc._check_reach_ghs(["CC(C)(C)c1ccc(O)cc1"])
        assert compliant is True
        assert hcodes == []

    @pytest.mark.asyncio
    async def test_partial_lookup_failure_uses_successful_results(self, svc):
        """If some lookups return None and some succeed, evaluate only the successes."""
        async def by_smiles(client, smiles):
            return None if smiles == "bad-smiles" else ["H319"]

        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(side_effect=by_smiles)):
            compliant, hcodes = await svc._check_reach_ghs(["bad-smiles", "CCO"])
        assert compliant is True   # H319 is not a REACH concern
        assert hcodes == ["H319"]

    @pytest.mark.asyncio
    async def test_multiple_reagents_all_evaluated(self, svc):
        """Concern H-code on any reagent triggers non-compliance."""
        async def by_smiles(client, smiles):
            return ["H350"] if smiles == "c1ccccc1" else ["H319"]

        with patch.object(svc, "_fetch_ghs_hcodes", new=AsyncMock(side_effect=by_smiles)):
            compliant, hcodes = await svc._check_reach_ghs(["CCO", "c1ccccc1"])
        assert compliant is False
        assert "H350" in hcodes


# ─── H-code extraction ────────────────────────────────────────────────────────

class TestExtractHCodes:
    def test_extracts_from_flat_string(self):
        from app.services.scoring_service import _extract_hcodes
        result = _extract_hcodes("H315 H319 H335")
        assert set(result) == {"H315", "H319", "H335"}

    def test_extracts_from_nested_dict(self):
        from app.services.scoring_service import _extract_hcodes
        data = {"Section": [{"Value": {"StringWithMarkup": [{"String": "H350 H340"}]}}]}
        result = _extract_hcodes(data)
        assert "H350" in result
        assert "H340" in result

    def test_returns_sorted_unique(self):
        from app.services.scoring_service import _extract_hcodes
        result = _extract_hcodes(["H319", "H315", "H319"])
        assert result == sorted(set(result))

    def test_no_hcodes_returns_empty(self):
        from app.services.scoring_service import _extract_hcodes
        assert _extract_hcodes({"key": "no codes here"}) == []

    def test_does_not_match_partial_patterns(self):
        from app.services.scoring_service import _extract_hcodes
        # "H3150" or "1H315" should not match - word boundary required
        result = _extract_hcodes("H3150 prefix-H315-suffix")
        assert "H3150" not in result


# ─── score_routes (end-to-end) ────────────────────────────────────────────────

class TestScoreRoutes:
    @pytest.mark.asyncio
    async def test_returns_same_number_of_routes(self, svc):
        routes = [make_route(f"r{i}") for i in range(3)]
        with patch.object(svc, "_check_reach_ghs", new=AsyncMock(return_value=(True, []))):
            scored = await svc.score_routes(routes)
        assert len(scored) == 3

    @pytest.mark.asyncio
    async def test_scores_object_populated(self, svc):
        routes = [make_route("r1")]
        with patch.object(svc, "_check_reach_ghs", new=AsyncMock(return_value=(True, []))):
            scored = await svc.score_routes(routes)
        assert scored[0].scores is not None

    @pytest.mark.asyncio
    async def test_reach_compliance_wired_through(self, svc):
        routes = [make_route("r1")]
        with patch.object(svc, "_check_reach_ghs", new=AsyncMock(return_value=(False, ["H350"]))):
            scored = await svc.score_routes(routes)
        assert scored[0].scores.reach_compliant is False
        assert "H350" in scored[0].scores.ghs_hazard_flags

    @pytest.mark.asyncio
    async def test_ghs_flags_populated(self, svc):
        routes = [make_route("r1")]
        with patch.object(svc, "_check_reach_ghs", new=AsyncMock(return_value=(True, ["H315", "H319"]))):
            scored = await svc.score_routes(routes)
        assert scored[0].scores.ghs_hazard_flags == ["H315", "H319"]

    @pytest.mark.asyncio
    async def test_scale_up_stub_value_wired(self, svc):
        routes = [make_route("r1")]
        with patch.object(svc, "_check_reach_ghs", new=AsyncMock(return_value=(True, []))):
            scored = await svc.score_routes(routes)
        assert scored[0].scores.scale_up_readiness == 0.75


# ─── Integration (real PubChem - skip in CI) ──────────────────────────────────

@pytest.mark.integration
class TestScoringIntegration:
    @pytest.mark.asyncio
    async def test_benzene_flagged_as_carcinogen(self):
        """Benzene (CID 241) should return H340/H350 from PubChem GHS."""
        svc = ScoringService()
        compliant, hcodes = await svc._check_reach_ghs(["c1ccccc1"])
        assert compliant is False
        assert any(h in hcodes for h in {"H340", "H350"})

    @pytest.mark.asyncio
    async def test_aspirin_has_ghs_flags(self):
        svc = ScoringService()
        compliant, hcodes = await svc._check_reach_ghs(["CC(=O)Oc1ccccc1C(=O)O"])
        assert isinstance(hcodes, list)

    @pytest.mark.asyncio
    async def test_unknown_smiles_returns_compliant(self):
        """A molecule not in PubChem should not trigger REACH concern."""
        svc = ScoringService()
        compliant, hcodes = await svc._check_reach_ghs(["CC(C)(C)CC(C)(C)C"])
        assert hcodes == [] or compliant is not False

    def test_sa_score_benzene_real(self):
        if not scoring_module._SASCORER_AVAILABLE:
            pytest.skip("sascorer not installed")
        svc = ScoringService()
        score = svc._compute_sa_score("c1ccccc1")
        assert score == pytest.approx(1.0, abs=0.1)

    def test_sa_score_aspirin_real(self):
        if not scoring_module._SASCORER_AVAILABLE:
            pytest.skip("sascorer not installed")
        svc = ScoringService()
        score = svc._compute_sa_score("CC(=O)Oc1ccccc1C(=O)O")
        assert score is not None
        assert 1.0 <= score <= 4.0
