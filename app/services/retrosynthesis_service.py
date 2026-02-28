"""
Stage 2 — Retrosynthesis Inference
MCTS-guided retrosynthetic search via AiZynthFinder.
Phase 1: AiZynthFinder (Option A). Migration path to seq2seq (Option B) in Phase 2.

STUB: run() returns mock routes. Replace with AiZynthFinder integration when available.
"""
import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.models.route import ReactionStep, RouteScores, SynthesisRoute

logger = get_logger(__name__)


class RetrosynthesisService:
    def __init__(self):
        self._config_path = settings.aizynthfinder_config_path
        self._stock_file = settings.aizynthfinder_stock_file
        # TODO: initialise AiZynthFinder finder instance (lazy-load on first call)
        self._finder = None

    def _load_finder(self):
        # TODO: from aizynthfinder.aizynthfinder import AiZynthFinder
        # self._finder = AiZynthFinder(configfile=self._config_path)
        # self._finder.stock.select(self._stock_file)
        raise NotImplementedError("AiZynthFinder not yet integrated")

    async def run(
        self,
        canonical_smiles: str,
        max_routes: int = 5,
        max_depth: int = 6,
    ) -> list[SynthesisRoute]:
        """
        Run retrosynthesis inference for a canonical SMILES.
        Returns up to max_routes candidate routes.
        This is a CPU/GPU-bound operation — called from a Celery worker, not the API thread.

        STUB: returns two placeholder routes. Replace with AiZynthFinder call.
        TODO:
          1. finder.target_smiles = canonical_smiles
          2. finder.tree_analysis()
          3. Extract + validate routes (atom balance, SMILES validity)
          4. Out-of-domain detection via Tanimoto similarity vs. training stock
          5. Return top N as SynthesisRoute objects
        """
        logger.info("retrosynthesis_start", smiles=canonical_smiles[:80], max_routes=max_routes)
        logger.warning("retrosynthesis_stub", message="Returning mock routes — AiZynthFinder not integrated")

        routes = [
            self._mock_route_2step(canonical_smiles),
            self._mock_route_3step(canonical_smiles),
        ]
        return routes[:max_routes]

    # ── Mock route builders (remove when AiZynthFinder is integrated) ──────────

    def _mock_route_2step(self, target_smiles: str) -> SynthesisRoute:
        intermediate = "CC(=O)O"  # acetic acid placeholder
        precursor = "CCO"         # ethanol placeholder
        steps = [
            ReactionStep(
                step_number=1,
                reactants_smiles=[precursor],
                reagents_smiles=["[O]"],
                product_smiles=intermediate,
                reaction_smiles=f"{precursor}>>[O]>{intermediate}",
                reaction_class="oxidation",
                confidence=0.82,
            ),
            ReactionStep(
                step_number=2,
                reactants_smiles=[intermediate],
                reagents_smiles=["[NaBH4]"],
                product_smiles=target_smiles,
                reaction_smiles=f"{intermediate}>>[NaBH4]>{target_smiles}",
                reaction_class="reduction",
                confidence=0.75,
            ),
        ]
        return SynthesisRoute(
            route_id=str(uuid.uuid4()),
            steps=steps,
            step_count=len(steps),
            overall_confidence=0.78,
            scores=RouteScores(),
            out_of_domain=False,
        )

    def _mock_route_3step(self, target_smiles: str) -> SynthesisRoute:
        precursor = "c1ccccc1"    # benzene placeholder
        intermediate1 = "CC=O"    # acetaldehyde placeholder
        intermediate2 = "CC(=O)O" # acetic acid placeholder
        steps = [
            ReactionStep(
                step_number=1,
                reactants_smiles=[precursor],
                reagents_smiles=["[Cl]"],
                product_smiles=intermediate1,
                reaction_smiles=f"{precursor}>>[Cl]>{intermediate1}",
                reaction_class="halogenation",
                confidence=0.65,
            ),
            ReactionStep(
                step_number=2,
                reactants_smiles=[intermediate1],
                reagents_smiles=["[KOH]"],
                product_smiles=intermediate2,
                reaction_smiles=f"{intermediate1}>>[KOH]>{intermediate2}",
                reaction_class="elimination",
                confidence=0.70,
            ),
            ReactionStep(
                step_number=3,
                reactants_smiles=[intermediate2],
                reagents_smiles=["[LiAlH4]"],
                product_smiles=target_smiles,
                reaction_smiles=f"{intermediate2}>>[LiAlH4]>{target_smiles}",
                reaction_class="reduction",
                confidence=0.68,
            ),
        ]
        return SynthesisRoute(
            route_id=str(uuid.uuid4()),
            steps=steps,
            step_count=len(steps),
            overall_confidence=0.68,
            scores=RouteScores(),
            out_of_domain=False,
        )

    def _detect_out_of_domain(self, smiles: str) -> tuple[bool, float]:
        """Returns (is_out_of_domain, max_tanimoto_similarity)."""
        # TODO: fingerprint comparison against training set
        raise NotImplementedError("Out-of-domain detection not yet implemented")
