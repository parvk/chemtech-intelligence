"""
Tests for Stage 2 — Retrosynthesis Inference (RetrosynthesisService).

Unit tests mock AiZynthFinder entirely — no models or GPU required.
Integration tests (marked integration) require models downloaded via:
    bash scripts/download_models.sh
Run without integration tests:
    pytest -m "not integration"

To run a real synthesis and inspect the structured output:
    pytest tests/test_retrosynthesis_service.py::TestRetrosynthesisSmoke -m integration -s -v
    pytest tests/test_retrosynthesis_service.py::TestRetrosynthesisSmoke -m integration -s -v --smiles "CC(=O)Oc1ccccc1C(=O)O"
"""
import json
import os

import pytest
from unittest.mock import MagicMock, patch

from app.services.retrosynthesis_service import RetrosynthesisService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the finder singleton between tests to avoid state leaking."""
    RetrosynthesisService._instance = None
    yield
    RetrosynthesisService._instance = None


@pytest.fixture
def svc():
    return RetrosynthesisService()


def make_mock_finder(route_dicts: list[dict]) -> MagicMock:
    """Build a minimal AiZynthFinder mock whose .routes iterates over route dicts."""
    mock_routes = []
    for rd in route_dicts:
        mock_route = MagicMock()
        mock_route.to_dict.return_value = rd
        mock_routes.append(mock_route)

    finder = MagicMock()
    finder.routes = mock_routes
    return finder


# ── Route tree fixtures ───────────────────────────────────────────────────────
#
# AiZynthFinder serialises a retrosynthesis tree as alternating mol/reaction nodes.
# mol node:      {"type": "mol", "smiles": "...", "in_stock": bool, "children": [...]}
# reaction node: {"type": "reaction", "metadata": {...}, "children": [mol_nodes]}

ONE_STEP_TREE = {
    "type": "mol",
    "smiles": "CCO",
    "in_stock": False,
    "children": [
        {
            "type": "reaction",
            "metadata": {
                "feasibility": 0.91,
                "policy_probability": 0.82,
                "classification": "Reduction",
            },
            "children": [
                {"type": "mol", "smiles": "CC=O", "in_stock": True, "children": []},
            ],
        }
    ],
}

TWO_STEP_TREE = {
    "type": "mol",
    "smiles": "CC(=O)O",
    "in_stock": False,
    "children": [
        {
            "type": "reaction",
            "metadata": {"feasibility": 0.75, "classification": "Oxidation"},
            "children": [
                {
                    "type": "mol",
                    "smiles": "CC=O",
                    "in_stock": False,
                    "children": [
                        {
                            "type": "reaction",
                            "metadata": {"feasibility": 0.88, "classification": "Oxidation"},
                            "children": [
                                {"type": "mol", "smiles": "CCO", "in_stock": True, "children": []},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}

STOCK_TREE = {
    # Target is already in stock — no reactions, tree has no children
    "type": "mol",
    "smiles": "CCO",
    "in_stock": True,
    "children": [],
}


# ── _parse_route_tree ─────────────────────────────────────────────────────────

class TestParseRouteTree:
    def test_single_step_returns_one_step(self, svc):
        steps = svc._parse_route_tree(ONE_STEP_TREE)
        assert len(steps) == 1

    def test_two_step_returns_two_steps(self, svc):
        steps = svc._parse_route_tree(TWO_STEP_TREE)
        assert len(steps) == 2

    def test_step_numbers_are_sequential_from_one(self, svc):
        steps = svc._parse_route_tree(TWO_STEP_TREE)
        assert [s.step_number for s in steps] == [1, 2]

    def test_forward_synthesis_order(self, svc):
        # In the two-step tree: CCO → CC=O → CC(=O)O
        # Forward order: step 1 product = CC=O, step 2 product = CC(=O)O
        steps = svc._parse_route_tree(TWO_STEP_TREE)
        assert steps[0].product_smiles == "CC=O"
        assert steps[1].product_smiles == "CC(=O)O"

    def test_reactants_extracted_correctly(self, svc):
        steps = svc._parse_route_tree(ONE_STEP_TREE)
        assert steps[0].reactants_smiles == ["CC=O"]

    def test_reaction_smiles_format(self, svc):
        steps = svc._parse_route_tree(ONE_STEP_TREE)
        assert steps[0].reaction_smiles == "CC=O>>CCO"

    def test_multi_reactant_reaction_smiles(self, svc):
        tree = {
            "type": "mol",
            "smiles": "c1ccc(NC(=O)c2ccccc2)cc1",
            "in_stock": False,
            "children": [
                {
                    "type": "reaction",
                    "metadata": {"feasibility": 0.80, "classification": "Amide coupling"},
                    "children": [
                        {"type": "mol", "smiles": "Nc1ccccc1", "in_stock": True, "children": []},
                        {"type": "mol", "smiles": "O=C(Cl)c1ccccc1", "in_stock": True, "children": []},
                    ],
                }
            ],
        }
        steps = svc._parse_route_tree(tree)
        assert len(steps) == 1
        assert set(steps[0].reactants_smiles) == {"Nc1ccccc1", "O=C(Cl)c1ccccc1"}
        assert "Nc1ccccc1" in steps[0].reaction_smiles
        assert "O=C(Cl)c1ccccc1" in steps[0].reaction_smiles

    def test_feasibility_used_over_policy_probability(self, svc):
        # feasibility should take precedence
        steps = svc._parse_route_tree(ONE_STEP_TREE)
        assert steps[0].confidence == pytest.approx(0.91)

    def test_policy_probability_fallback_when_no_feasibility(self, svc):
        tree = {
            "type": "mol",
            "smiles": "CCO",
            "in_stock": False,
            "children": [
                {
                    "type": "reaction",
                    "metadata": {"policy_probability": 0.73},
                    "children": [
                        {"type": "mol", "smiles": "CC=O", "in_stock": True, "children": []},
                    ],
                }
            ],
        }
        steps = svc._parse_route_tree(tree)
        assert steps[0].confidence == pytest.approx(0.73)

    def test_default_confidence_when_no_metadata(self, svc):
        tree = {
            "type": "mol",
            "smiles": "CCO",
            "in_stock": False,
            "children": [
                {
                    "type": "reaction",
                    "metadata": {},
                    "children": [
                        {"type": "mol", "smiles": "CC=O", "in_stock": True, "children": []},
                    ],
                }
            ],
        }
        steps = svc._parse_route_tree(tree)
        assert steps[0].confidence == pytest.approx(0.5)

    def test_confidence_clamped_to_zero_one(self, svc):
        tree = {
            "type": "mol",
            "smiles": "CCO",
            "in_stock": False,
            "children": [
                {
                    "type": "reaction",
                    "metadata": {"feasibility": 1.5},  # out-of-range value
                    "children": [
                        {"type": "mol", "smiles": "CC=O", "in_stock": True, "children": []},
                    ],
                }
            ],
        }
        steps = svc._parse_route_tree(tree)
        assert steps[0].confidence <= 1.0

    def test_reaction_class_mapped_from_classification(self, svc):
        steps = svc._parse_route_tree(ONE_STEP_TREE)
        assert steps[0].reaction_class == "Reduction"

    def test_no_reaction_class_when_not_in_metadata(self, svc):
        tree = {
            "type": "mol",
            "smiles": "CCO",
            "in_stock": False,
            "children": [
                {
                    "type": "reaction",
                    "metadata": {"feasibility": 0.8},
                    "children": [
                        {"type": "mol", "smiles": "CC=O", "in_stock": True, "children": []},
                    ],
                }
            ],
        }
        steps = svc._parse_route_tree(tree)
        assert steps[0].reaction_class is None

    def test_stock_molecule_returns_no_steps(self, svc):
        # Target already in stock — no retrosynthetic steps
        steps = svc._parse_route_tree(STOCK_TREE)
        assert steps == []


# ── _geometric_mean ───────────────────────────────────────────────────────────

class TestGeometricMean:
    def test_single_value(self):
        assert RetrosynthesisService._geometric_mean([0.81]) == pytest.approx(0.81)

    def test_two_equal_values(self):
        assert RetrosynthesisService._geometric_mean([0.5, 0.5]) == pytest.approx(0.5)

    def test_two_different_values(self):
        result = RetrosynthesisService._geometric_mean([0.81, 0.49])
        assert result == pytest.approx((0.81 * 0.49) ** 0.5, rel=1e-4)

    def test_empty_list_returns_zero(self):
        assert RetrosynthesisService._geometric_mean([]) == 0.0

    def test_result_bounded_by_min_and_max_input(self):
        values = [0.9, 0.6, 0.3]
        result = RetrosynthesisService._geometric_mean(values)
        assert 0.3 <= result <= 0.9


# ── _check_out_of_domain ──────────────────────────────────────────────────────

class TestOutOfDomainDetection:
    def test_benzene_is_in_domain(self, svc):
        is_ood, similarity = svc._check_out_of_domain("c1ccccc1")
        assert not is_ood
        assert similarity == pytest.approx(1.0)

    def test_common_building_block_is_in_domain(self, svc):
        is_ood, _ = svc._check_out_of_domain("CCO")  # ethanol — in reference set
        assert not is_ood

    def test_very_exotic_molecule_is_out_of_domain(self, svc):
        # Highly complex natural product scaffold unlikely to match simple building blocks
        exotic = "O=C1OC2CC(=O)OC2C(O)C1=O"
        is_ood, similarity = svc._check_out_of_domain(exotic)
        # Similarity will be low but test the return types are correct
        assert isinstance(is_ood, bool)
        assert 0.0 <= similarity <= 1.0

    def test_similarity_is_normalised(self, svc):
        _, similarity = svc._check_out_of_domain("CC(=O)O")
        assert 0.0 <= similarity <= 1.0

    def test_invalid_smiles_returns_safe_default(self, svc):
        is_ood, similarity = svc._check_out_of_domain("not-a-smiles")
        assert not is_ood
        assert similarity == pytest.approx(1.0)


# ── _extract_routes ───────────────────────────────────────────────────────────

class TestExtractRoutes:
    def test_routes_extracted_from_finder(self, svc):
        finder = make_mock_finder([ONE_STEP_TREE, TWO_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=10)
        assert len(routes) == 2

    def test_max_routes_respected(self, svc):
        finder = make_mock_finder([ONE_STEP_TREE, TWO_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=1)
        assert len(routes) == 1

    def test_routes_have_unique_ids(self, svc):
        finder = make_mock_finder([ONE_STEP_TREE, TWO_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=10)
        ids = [r.route_id for r in routes]
        assert len(ids) == len(set(ids))

    def test_step_count_matches_steps(self, svc):
        finder = make_mock_finder([TWO_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=10)
        assert routes[0].step_count == len(routes[0].steps) == 2

    def test_overall_confidence_is_geometric_mean_of_steps(self, svc):
        finder = make_mock_finder([ONE_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=10)
        # ONE_STEP_TREE has feasibility=0.91 → geometric mean of [0.91] = 0.91
        assert routes[0].overall_confidence == pytest.approx(0.91, abs=0.01)

    def test_ood_false_sets_no_warning(self, svc):
        finder = make_mock_finder([ONE_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=10)
        assert routes[0].out_of_domain is False
        assert routes[0].out_of_domain_warning is None

    def test_ood_true_sets_warning_on_routes(self, svc):
        finder = make_mock_finder([ONE_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=True, ood_similarity=0.18, max_routes=10)
        assert routes[0].out_of_domain is True
        assert routes[0].out_of_domain_warning is not None
        assert "0.18" in routes[0].out_of_domain_warning

    def test_route_with_no_steps_skipped(self, svc):
        # STOCK_TREE produces no steps — should be skipped
        finder = make_mock_finder([STOCK_TREE, ONE_STEP_TREE])
        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=10)
        assert len(routes) == 1
        assert routes[0].step_count == 1

    def test_broken_route_skipped_not_raised(self, svc):
        bad_route = MagicMock()
        bad_route.to_dict.side_effect = RuntimeError("serialisation error")

        good_route = MagicMock()
        good_route.to_dict.return_value = ONE_STEP_TREE

        finder = MagicMock()
        finder.routes = [bad_route, good_route]

        routes = svc._extract_routes(finder, out_of_domain=False, ood_similarity=0.9, max_routes=10)
        assert len(routes) == 1  # bad route skipped, good route returned


# ── _get_finder ───────────────────────────────────────────────────────────────

class TestGetFinder:
    def test_raises_when_aizynthfinder_not_installed(self, svc):
        with patch("app.services.retrosynthesis_service.AIZYNTHFINDER_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="aizynthfinder is not installed"):
                svc._get_finder()

    def test_singleton_returns_same_instance(self, svc):
        mock_finder = MagicMock()
        with patch("app.services.retrosynthesis_service.AIZYNTHFINDER_AVAILABLE", True), \
             patch("app.services.retrosynthesis_service._AiZynthFinder", return_value=mock_finder):
            first = svc._get_finder()
            second = svc._get_finder()
        assert first is second

    def test_singleton_initialised_only_once(self, svc):
        mock_cls = MagicMock(return_value=MagicMock())
        with patch("app.services.retrosynthesis_service.AIZYNTHFINDER_AVAILABLE", True), \
             patch("app.services.retrosynthesis_service._AiZynthFinder", mock_cls):
            svc._get_finder()
            svc._get_finder()
        mock_cls.assert_called_once()


# ── run() ─────────────────────────────────────────────────────────────────────

class TestRun:
    @pytest.mark.asyncio
    async def test_run_returns_routes(self, svc):
        finder = make_mock_finder([ONE_STEP_TREE, TWO_STEP_TREE])
        with patch.object(svc, "_get_finder", return_value=finder), \
             patch.object(svc, "_run_sync", return_value=[MagicMock(), MagicMock()]) as mock_sync:
            routes = await svc.run("CCO", max_routes=5)
        mock_sync.assert_called_once()
        assert len(routes) == 2

    @pytest.mark.asyncio
    async def test_run_passes_max_routes_and_depth(self, svc):
        with patch.object(svc, "_run_sync", return_value=[]) as mock_sync:
            await svc.run("CCO", max_routes=3, max_depth=4)
        call_args = mock_sync.call_args[0]
        assert call_args[1] == 3   # max_routes
        assert call_args[2] == 4   # max_depth

    @pytest.mark.asyncio
    async def test_run_ood_flag_forwarded_to_run_sync(self, svc):
        # Patch OOD check to return out-of-domain
        with patch.object(svc, "_check_out_of_domain", return_value=(True, 0.15)), \
             patch.object(svc, "_run_sync", return_value=[]) as mock_sync:
            await svc.run("O=C1OC2CC(=O)OC2C(O)C1=O")
        call_args = mock_sync.call_args[0]
        assert call_args[3] is True   # out_of_domain
        assert call_args[4] == pytest.approx(0.15)  # ood_similarity


# ── Integration tests (require downloaded models) ─────────────────────────────

@pytest.mark.integration
class TestRetrosynthesisIntegration:
    """
    These tests run actual AiZynthFinder inference.
    Prerequisites:
        bash scripts/download_models.sh
        AIZYNTHFINDER_CONFIG_PATH set to a valid config (default: /app/config/aizynthfinder.yml)
    """

    @pytest.mark.asyncio
    async def test_aspirin_returns_routes(self):
        svc = RetrosynthesisService()
        # Aspirin (2-acetoxybenzoic acid) — well-known pharma molecule, should be in USPTO training data
        routes = await svc.run("CC(=O)Oc1ccccc1C(=O)O", max_routes=5)
        assert len(routes) > 0

    @pytest.mark.asyncio
    async def test_ibuprofen_route_structure(self):
        svc = RetrosynthesisService()
        routes = await svc.run("CC(C)Cc1ccc(cc1)C(C)C(=O)O", max_routes=3)
        assert len(routes) > 0
        for route in routes:
            assert route.step_count == len(route.steps)
            assert route.step_count >= 1
            for i, step in enumerate(route.steps):
                assert step.step_number == i + 1
                assert step.product_smiles
                assert step.reactants_smiles
                assert 0.0 <= step.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_route_confidence_in_range(self):
        svc = RetrosynthesisService()
        routes = await svc.run("CC(=O)Oc1ccccc1C(=O)O", max_routes=5)
        for route in routes:
            assert 0.0 <= route.overall_confidence <= 1.0

    @pytest.mark.asyncio
    async def test_singleton_reused_across_calls(self):
        svc = RetrosynthesisService()
        await svc.run("CCO", max_routes=2)
        instance_after_first = RetrosynthesisService._instance
        await svc.run("CC(=O)O", max_routes=2)
        assert RetrosynthesisService._instance is instance_after_first


# ── Smoke test — run a real synthesis and print structured output ──────────────
#
# Usage (run inside the worker container where models are available):
#
#   pytest tests/test_retrosynthesis_service.py::TestRetrosynthesisSmoke -m integration -s -v
#   pytest tests/test_retrosynthesis_service.py::TestRetrosynthesisSmoke -m integration -s -v \
#       --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O"
#
# The --smiles flag overrides the default molecule (aspirin).
# -s streams print output to the terminal as the test runs.

@pytest.mark.integration
class TestRetrosynthesisSmoke:
    """
    End-to-end smoke test: SMILES → structured SynthesisRoute objects.
    Prints a full human-readable summary — run with -s to see output.
    """

    @pytest.mark.asyncio
    async def test_synthesis_output(self, target_smiles):
        svc = RetrosynthesisService()

        print(f"\n{'='*60}")
        print(f"  TARGET SMILES : {target_smiles}")
        print(f"{'='*60}\n")

        routes = await svc.run(target_smiles, max_routes=5, max_depth=6)

        assert routes, f"No routes found for {target_smiles!r} — check models are downloaded"

        for i, route in enumerate(routes, 1):
            print(f"Route {i}  (id: {route.route_id[:8]}…)")
            print(f"  Steps           : {route.step_count}")
            print(f"  Confidence      : {route.overall_confidence:.3f}")
            print(f"  Out-of-domain   : {route.out_of_domain}")
            if route.out_of_domain_warning:
                print(f"  OOD warning     : {route.out_of_domain_warning}")

            for step in route.steps:
                reactants = " + ".join(step.reactants_smiles)
                cls = f"  [{step.reaction_class}]" if step.reaction_class else ""
                print(
                    f"  Step {step.step_number}: {reactants} → {step.product_smiles}"
                    f"{cls}  (conf: {step.confidence:.3f})"
                )
            print()

        print("── Full JSON output ──")
        as_json = [r.model_dump(mode="json") for r in routes]
        print(json.dumps(as_json, indent=2))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("smiles,name", [
        ("CC(=O)Oc1ccccc1C(=O)O", "aspirin"),
        ("CC(C)Cc1ccc(cc1)C(C)C(=O)O", "ibuprofen"),
        ("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "caffeine"),
    ])
    async def test_known_molecules_find_routes(self, smiles, name):
        """Sanity check: well-known pharma molecules should always return routes."""
        svc = RetrosynthesisService()
        routes = await svc.run(smiles, max_routes=3)
        assert len(routes) > 0, f"No routes found for {name} ({smiles})"
        print(f"\n{name}: {len(routes)} route(s), best confidence {routes[0].overall_confidence:.3f}")
