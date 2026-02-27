"""
Stage 2 — Retrosynthesis Inference
MCTS-guided retrosynthetic search via AiZynthFinder.
Phase 1: AiZynthFinder (Option A). Migration path to seq2seq (Option B) in Phase 2.
"""
from app.core.config import settings
from app.core.logging import get_logger
from app.models.route import SynthesisRoute

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
        raise NotImplementedError

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
        """
        logger.info("retrosynthesis_start", smiles=canonical_smiles[:80], max_routes=max_routes)

        # TODO:
        # 1. Run finder.target_smiles = canonical_smiles
        # 2. finder.tree_analysis()
        # 3. Extract routes from finder.routes
        # 4. Validate each route (atom balance, SMILES validity)
        # 5. Out-of-domain detection via Tanimoto similarity vs. training stock
        # 6. Return top N routes as SynthesisRoute objects
        raise NotImplementedError

    def _detect_out_of_domain(self, smiles: str) -> tuple[bool, float]:
        """Returns (is_out_of_domain, max_tanimoto_similarity)."""
        # TODO: fingerprint comparison against training set
        raise NotImplementedError
