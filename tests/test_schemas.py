"""
Tests for Pydantic schema validation — input contracts, field constraints, enums.
These run with no external dependencies.
"""
import pytest
from pydantic import ValidationError

from app.models.molecule import InputFormat, MoleculeInput, OptimisationDimension, ResolvedMolecule
from app.models.route import ReactionStep, RouteScores, SynthesisRoute
from app.models.job import JobStatus, SynthesisPlanRequest


# ─── MoleculeInput ────────────────────────────────────────────────────────────

class TestMoleculeInput:
    def test_default_format_is_smiles(self):
        m = MoleculeInput(value="CCO")
        assert m.format == InputFormat.SMILES

    def test_explicit_cas_format(self):
        m = MoleculeInput(value="64-17-5", format=InputFormat.CAS)
        assert m.format == InputFormat.CAS

    def test_all_formats_accepted(self):
        for fmt in InputFormat:
            m = MoleculeInput(value="test", format=fmt)
            assert m.format == fmt

    def test_value_required(self):
        with pytest.raises(ValidationError):
            MoleculeInput()

    def test_invalid_format_rejected(self):
        with pytest.raises(ValidationError):
            MoleculeInput(value="CCO", format="invalid_format")


# ─── RouteScores ──────────────────────────────────────────────────────────────

class TestRouteScores:
    def test_all_none_is_valid(self):
        scores = RouteScores()
        assert scores.sa_score is None
        assert scores.reach_compliant is None

    def test_sa_score_bounds(self):
        RouteScores(sa_score=1.0)
        RouteScores(sa_score=10.0)
        with pytest.raises(ValidationError):
            RouteScores(sa_score=0.5)
        with pytest.raises(ValidationError):
            RouteScores(sa_score=10.1)

    def test_route_maturity_bounds(self):
        RouteScores(route_maturity=0.0)
        RouteScores(route_maturity=1.0)
        with pytest.raises(ValidationError):
            RouteScores(route_maturity=-0.1)
        with pytest.raises(ValidationError):
            RouteScores(route_maturity=1.1)

    def test_green_index_bounds(self):
        RouteScores(green_index=0.0)
        RouteScores(green_index=100.0)
        with pytest.raises(ValidationError):
            RouteScores(green_index=-1.0)
        with pytest.raises(ValidationError):
            RouteScores(green_index=100.1)

    def test_ghs_hazard_flags_defaults_to_empty(self):
        scores = RouteScores()
        assert scores.ghs_hazard_flags == []


# ─── ReactionStep ─────────────────────────────────────────────────────────────

class TestReactionStep:
    def test_valid_step(self):
        step = ReactionStep(
            step_number=1,
            reactants_smiles=["CC=O"],
            reagents_smiles=["[NaBH4]"],
            product_smiles="CCO",
            reaction_smiles="CC=O>>[NaBH4]>CCO",
            confidence=0.9,
        )
        assert step.step_number == 1
        assert step.confidence == 0.9

    def test_confidence_bounds(self):
        base = dict(
            step_number=1,
            reactants_smiles=["CC=O"],
            reagents_smiles=[],
            product_smiles="CCO",
            reaction_smiles="CC=O>>CCO",
        )
        ReactionStep(**base, confidence=0.0)
        ReactionStep(**base, confidence=1.0)
        with pytest.raises(ValidationError):
            ReactionStep(**base, confidence=-0.1)
        with pytest.raises(ValidationError):
            ReactionStep(**base, confidence=1.1)

    def test_literature_refs_defaults_to_empty(self):
        step = ReactionStep(
            step_number=1,
            reactants_smiles=["CCO"],
            reagents_smiles=[],
            product_smiles="CC=O",
            reaction_smiles="CCO>>CC=O",
            confidence=0.7,
        )
        assert step.literature_refs == []


# ─── SynthesisPlanRequest ─────────────────────────────────────────────────────

class TestSynthesisPlanRequest:
    def test_defaults(self):
        req = SynthesisPlanRequest(
            molecule=MoleculeInput(value="CCO"),
            tenant_id="tenant-abc",
        )
        assert req.max_routes == 5
        assert req.max_depth == 6
        assert req.optimisation_dimension == OptimisationDimension.FEWEST_STEPS

    def test_max_routes_bounds(self):
        base = dict(molecule=MoleculeInput(value="CCO"), tenant_id="t1")
        SynthesisPlanRequest(**base, max_routes=1)
        SynthesisPlanRequest(**base, max_routes=10)
        with pytest.raises(ValidationError):
            SynthesisPlanRequest(**base, max_routes=0)
        with pytest.raises(ValidationError):
            SynthesisPlanRequest(**base, max_routes=11)

    def test_max_depth_bounds(self):
        base = dict(molecule=MoleculeInput(value="CCO"), tenant_id="t1")
        SynthesisPlanRequest(**base, max_depth=1)
        SynthesisPlanRequest(**base, max_depth=10)
        with pytest.raises(ValidationError):
            SynthesisPlanRequest(**base, max_depth=0)
        with pytest.raises(ValidationError):
            SynthesisPlanRequest(**base, max_depth=11)

    def test_tenant_id_defaults_to_empty_string(self):
        req = SynthesisPlanRequest(molecule=MoleculeInput(value="CCO"))
        assert req.tenant_id == ""

    def test_all_optimisation_dimensions_accepted(self):
        for dim in OptimisationDimension:
            req = SynthesisPlanRequest(
                molecule=MoleculeInput(value="CCO"),
                tenant_id="t1",
                optimisation_dimension=dim,
            )
            assert req.optimisation_dimension == dim


# ─── JobStatus ────────────────────────────────────────────────────────────────

class TestJobStatus:
    def test_all_stages_defined(self):
        expected = {"pending", "resolving", "inferring", "scoring", "ranking", "explaining", "assembling", "completed", "failed"}
        actual = {s.value for s in JobStatus}
        assert expected == actual
