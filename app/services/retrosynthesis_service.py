"""
Stage 2 - Retrosynthesis Inference
MCTS-guided retrosynthetic search via AiZynthFinder.
Phase 1: AiZynthFinder with USPTO pre-trained models.
Phase 2 migration path: swap expansion policy for specialty-chemical fine-tuned model.
"""
import asyncio
import threading
import uuid
from functools import cached_property

from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs

from app.core.config import settings
from app.core.logging import get_logger
from app.models.route import ReactionStep, RouteScores, SynthesisRoute

logger = get_logger(__name__)

# ── AiZynthFinder import guard ────────────────────────────────────────────────
# AiZynthFinder is required at runtime. If unavailable (e.g. local dev without
# models), a clear error will surface at job execution time, not import time.
try:
    from aizynthfinder.aizynthfinder import AiZynthFinder as _AiZynthFinder

    AIZYNTHFINDER_AVAILABLE = True
except ImportError:
    _AiZynthFinder = None  # type: ignore[assignment,misc]
    AIZYNTHFINDER_AVAILABLE = False
    logger.warning(
        "aizynthfinder_unavailable",
        message="aizynthfinder not installed - retrosynthesis will fail at runtime",
    )

# Tanimoto similarity below which we flag a molecule as potentially out-of-domain
# Configurable via OOD_SIMILARITY_THRESHOLD env var
_OOD_SIMILARITY_THRESHOLD = settings.ood_similarity_threshold

# Reference Morgan fingerprints for OOD check.
# Phase 1: small representative set of common building blocks.
# Phase 2: replace with a precomputed fingerprint array derived from the training stock.
_REFERENCE_SMILES = [
    "c1ccccc1",        # benzene
    "C1CCCCC1",        # cyclohexane
    "CC(=O)O",         # acetic acid
    "CCO",             # ethanol
    "c1ccncc1",        # pyridine
    "CC(N)=O",         # acetamide
    "O=C(O)c1ccccc1",  # benzoic acid
    "NC(=O)c1ccccc1",  # benzamide
    "Cc1ccccc1",       # toluene
    "c1ccc(Cl)cc1",    # chlorobenzene
]


class RetrosynthesisService:
    """
    Wraps AiZynthFinder in an async-compatible, thread-safe singleton.

    One finder instance is shared per worker process. AiZynthFinder is not
    re-entrant, so a threading.Lock guards each search. With Celery concurrency=1
    the lock is never contended; it is there for safety if concurrency is raised.
    """

    _instance: "_AiZynthFinder | None" = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._config_path = settings.aizynthfinder_config_path

    @cached_property
    def _reference_fps(self) -> list:
        fps = []
        for smi in _REFERENCE_SMILES:
            mol = Chem.MolFromSmiles(smi)
            if mol:
                fps.append(AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048))
        return fps

    def _get_finder(self) -> "_AiZynthFinder":
        if not AIZYNTHFINDER_AVAILABLE:
            raise RuntimeError(
                "aizynthfinder is not installed. "
                "Run: pip install 'aizynthfinder>=4.2.0'"
            )
        if RetrosynthesisService._instance is None:
            logger.info("aizynthfinder_init", config=self._config_path)
            instance = _AiZynthFinder(configfile=self._config_path)
            instance.expansion_policy.select_all()
            instance.filter_policy.select_all()
            RetrosynthesisService._instance = instance
            logger.info("aizynthfinder_ready")
        return RetrosynthesisService._instance

    async def run(
        self,
        canonical_smiles: str,
        max_routes: int = 5,
        max_depth: int = 6,
    ) -> list[SynthesisRoute]:
        """
        Run MCTS retrosynthesis for a canonical SMILES string.
        Runs AiZynthFinder in a thread executor to avoid blocking the event loop.
        """
        logger.info("retrosynthesis_start", smiles=canonical_smiles[:80], max_routes=max_routes)

        ood, similarity = self._check_out_of_domain(canonical_smiles)
        if ood:
            logger.warning(
                "retrosynthesis_ood_warning",
                smiles=canonical_smiles[:80],
                max_tanimoto=round(similarity, 3),
            )

        loop = asyncio.get_event_loop()
        routes = await loop.run_in_executor(
            None,
            self._run_sync,
            canonical_smiles,
            max_routes,
            max_depth,
            ood,
            similarity,
        )

        logger.info("retrosynthesis_complete", routes_found=len(routes))
        return routes

    def _run_sync(
        self,
        canonical_smiles: str,
        max_routes: int,
        max_depth: int,
        out_of_domain: bool,
        ood_similarity: float,
    ) -> list[SynthesisRoute]:
        """Blocking AiZynthFinder call - runs in a thread executor."""
        finder = self._get_finder()

        with self._lock:
            finder.target_smiles = canonical_smiles
            finder.max_transforms = max_depth
            finder.tree_search()
            finder.build_routes()
            finder.routes.compute_scores(
                finder.scorers["state score"],
                finder.scorers["number of reactions"],
            )

            return self._extract_routes(
                finder,
                out_of_domain=out_of_domain,
                ood_similarity=ood_similarity,
                max_routes=max_routes,
            )

    def _extract_routes(
        self,
        finder: "_AiZynthFinder",
        out_of_domain: bool,
        ood_similarity: float,
        max_routes: int,
    ) -> list[SynthesisRoute]:
        synthesis_routes: list[SynthesisRoute] = []

        for route in finder.routes:
            try:
                route_dict = route["reaction_tree"].to_dict()
                steps = self._parse_route_tree(route_dict)

                if not steps:
                    continue

                overall_confidence = self._geometric_mean([s.confidence for s in steps])

                ood_warning = None
                if out_of_domain:
                    ood_warning = (
                        f"Target molecule has low similarity to training data "
                        f"(max Tanimoto: {ood_similarity:.2f}). "
                        "Route quality may be reduced - review with caution."
                    )

                synthesis_routes.append(
                    SynthesisRoute(
                        route_id=str(uuid.uuid4()),
                        steps=steps,
                        step_count=len(steps),
                        overall_confidence=round(overall_confidence, 4),
                        scores=RouteScores(),
                        out_of_domain=out_of_domain,
                        out_of_domain_warning=ood_warning,
                    )
                )

                if len(synthesis_routes) >= max_routes:
                    break

            except Exception as exc:
                logger.warning("route_parse_error", error=str(exc))
                continue

        return synthesis_routes

    def _parse_route_tree(self, route_dict: dict) -> list[ReactionStep]:
        """
        Walk the AiZynthFinder route tree and return steps in forward-synthesis order.

        AiZynthFinder serializes routes as alternating mol/reaction nodes:
          mol_node → reaction_node → [reactant mol_nodes → ...]

        mol node:      {"type": "mol", "smiles": "...", "in_stock": bool, "children": [...]}
        reaction node: {"type": "reaction", "metadata": {...}, "children": [mol_nodes]}

        The product of each reaction is the parent mol node's smiles.
        Reactants are the smiles of the reaction node's children.

        The tree is retrosynthetic (target at root), so we collect reactions
        during traversal then reverse to give forward-synthesis order.
        """
        reactions: list[dict] = []

        def walk(mol_node: dict) -> None:
            for child in mol_node.get("children", []):
                if child.get("type") != "reaction":
                    continue

                reactant_smiles: list[str] = []
                for reactant_node in child.get("children", []):
                    if reactant_node.get("type") == "mol":
                        reactant_smiles.append(reactant_node["smiles"])
                        walk(reactant_node)

                product = mol_node["smiles"]
                metadata = child.get("metadata", {})

                # Prefer feasibility (filter policy score) over raw policy probability
                raw_confidence = metadata.get(
                    "feasibility", metadata.get("policy_probability", 0.5)
                )
                confidence = float(max(0.0, min(1.0, raw_confidence)))

                reactions.append(
                    {
                        "product_smiles": product,
                        "reactants_smiles": reactant_smiles,
                        "reaction_smiles": f"{'.'.join(reactant_smiles)}>>{product}",
                        "confidence": confidence,
                        "classification": metadata.get("classification"),
                    }
                )

        walk(route_dict)

        # Reverse: tree traversal collected in retrosynthetic order (target → SM).
        # We want forward synthesis order (SM → target) for the UI/scoring stages.
        reactions.reverse()

        return [
            ReactionStep(
                step_number=i + 1,
                reactants_smiles=r["reactants_smiles"],
                reagents_smiles=[],
                product_smiles=r["product_smiles"],
                reaction_smiles=r["reaction_smiles"],
                reaction_class=r["classification"],
                confidence=r["confidence"],
            )
            for i, r in enumerate(reactions)
        ]

    def _check_out_of_domain(self, smiles: str) -> tuple[bool, float]:
        """
        Tanimoto check against a reference fingerprint set.
        Returns (is_out_of_domain, max_similarity).

        Phase 1: compared against a small representative set of building blocks.
        Phase 2: replace _reference_fps with a precomputed array from the training stock.
        """
        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return False, 1.0

            target_fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)
            ref_fps = self._reference_fps

            if not ref_fps:
                return False, 1.0

            max_similarity = max(
                DataStructs.TanimotoSimilarity(target_fp, ref_fp) for ref_fp in ref_fps
            )
            return max_similarity < _OOD_SIMILARITY_THRESHOLD, max_similarity

        except Exception as exc:
            logger.warning("ood_check_failed", error=str(exc))
            return False, 1.0

    @staticmethod
    def _geometric_mean(values: list[float]) -> float:
        if not values:
            return 0.0
        product = 1.0
        for v in values:
            product *= max(v, 1e-9)
        return product ** (1.0 / len(values))
