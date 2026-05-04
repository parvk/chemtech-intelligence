"""
Stage 3 - Route Scoring
Multi-dimensional evaluation of candidate routes.
Phase 1: SA Score, Route Maturity, Green Index (basic), Scale-Up (proxy), Cost Index (reference), REACH/GHS.

STUB: _compute_scale_up_proxy and _compute_cost_index return mock values. Replace with real implementations.
"""
import os
import re
import sys

import httpx
from rdkit.Chem import Descriptors, InchiToInchiKey, MolFromSmiles, MolToInchi, RDConfig

from app.core.config import settings
from app.core.logging import get_logger
from app.models.route import RouteScores, SynthesisRoute

# Load RDKit's SA Score contrib module (sascorer.py + fpscores.pkl.gz)
_SA_SCORE_DIR = os.path.join(RDConfig.RDContribDir, "SA_Score")
if _SA_SCORE_DIR not in sys.path:
    sys.path.insert(0, _SA_SCORE_DIR)
try:
    import sascorer as _sascorer
    _SASCORER_AVAILABLE = True
except ImportError:
    _sascorer = None  # type: ignore[assignment]
    _SASCORER_AVAILABLE = False

logger = get_logger(__name__)

_HCODE_RE = re.compile(r'\bH\d{3}\b')

# H-codes that indicate REACH SVHC concern (CMR + persistent aquatic toxicity)
_REACH_CONCERN_HCODES = frozenset({
    "H340", "H341",  # Mutagenic cat 1/2
    "H350", "H351",  # Carcinogenic cat 1/2
    "H360", "H361",  # Reprotoxic cat 1/2
    "H372", "H373",  # STOT repeated exposure
    "H400", "H410", "H411",  # Aquatic tox (acute + chronic)
})

# Resolved at import time from settings so callsites stay clean
_PUBCHEM_BASE = settings.pubchem_base_url
_PUBCHEM_VIEW_BASE = settings.pubchem_view_base_url


def _extract_hcodes(data: object) -> list[str]:
    """Recursively walk PubChem pug_view JSON and return all H-codes found."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, str):
            found.update(_HCODE_RE.findall(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return sorted(found)


class ScoringService:
    def __init__(self):
        self._echa_base = settings.echa_api_base_url

    async def score_routes(self, routes: list[SynthesisRoute]) -> list[SynthesisRoute]:
        scored = []
        for route in routes:
            scores = await self._score_route(route)
            route.scores = scores
            scored.append(route)
        return scored

    async def _score_route(self, route: SynthesisRoute) -> RouteScores:
        all_smiles = self._collect_all_smiles(route)

        sa_score = self._compute_sa_score(route.steps[-1].product_smiles)
        route_maturity = self._compute_route_maturity(route)
        green_index = self._compute_green_index(route)
        scale_up_readiness = self._compute_scale_up_proxy(route)
        cost_index = self._compute_cost_index(all_smiles)
        reach_compliant, ghs_flags = await self._check_reach_ghs(all_smiles)

        return RouteScores(
            sa_score=sa_score,
            route_maturity=route_maturity,
            green_index=green_index,
            scale_up_readiness=scale_up_readiness,
            cost_index=cost_index,
            reach_compliant=reach_compliant,
            ghs_hazard_flags=ghs_flags,
        )

    def _compute_sa_score(self, smiles: str) -> float | None:
        if not _SASCORER_AVAILABLE:
            logger.warning("sascorer_unavailable", message="SA Score module not loaded")
            return None
        mol = MolFromSmiles(smiles)
        if mol is None:
            logger.warning("sa_score_invalid_smiles", smiles=smiles[:80])
            return None
        score = _sascorer.calculateScore(mol)
        return round(score, 2)

    def _compute_route_maturity(self, route: SynthesisRoute) -> float | None:
        """
        Geometric mean of per-step confidences from AiZynthFinder's filter policy.
        Confidence encodes template feasibility vs. the USPTO/ORD training corpus -
        a natural proxy for literature precedent.
        Phase 2: layer in reaction-class tier adjustments (named reactions → bonus,
        obscure templates → penalty).
        """
        if not route.steps:
            return None
        product = 1.0
        for step in route.steps:
            product *= max(step.confidence, 1e-9)
        return round(product ** (1.0 / len(route.steps)), 4)

    def _compute_green_index(self, route: SynthesisRoute) -> float | None:
        """
        Atom Economy (AE) averaged across all steps.
        AE per step = MW(product) / Σ MW(reactants) × 100.
        Phase 2: add CHEM21/GSK solvent tier scoring and E-factor.
        """
        step_aes: list[float] = []
        for step in route.steps:
            product_mol = MolFromSmiles(step.product_smiles)
            reactant_mols = [MolFromSmiles(s) for s in step.reactants_smiles]
            if product_mol is None or not reactant_mols or any(m is None for m in reactant_mols):
                continue
            mw_product = Descriptors.MolWt(product_mol)
            mw_reactants = sum(Descriptors.MolWt(m) for m in reactant_mols)  # type: ignore[arg-type]
            if mw_reactants == 0:
                continue
            step_aes.append(min((mw_product / mw_reactants) * 100.0, 100.0))

        if not step_aes:
            return None
        return round(sum(step_aes) / len(step_aes), 1)

    def _compute_scale_up_proxy(self, route: SynthesisRoute) -> float | None:
        # TODO: tag-matching against known scale-up challenge patterns
        # (exotherms, gas evolution, cryogenic, high-pressure)
        return 0.75  # STUB

    def _compute_cost_index(self, smiles_list: list[str]) -> float | None:
        # TODO: reference price table lookup per reagent SMILES
        return round(1.5 + len(smiles_list) * 0.3, 2)  # STUB: more reagents → higher cost

    async def _check_reach_ghs(self, smiles_list: list[str]) -> tuple[bool | None, list[str]]:
        """
        Fetch GHS hazard statements from PubChem for each reagent SMILES.
        Returns (reach_compliant, sorted list of unique H-codes found).

        reach_compliant=False if any CMR or persistent aquatic tox H-code is present.
        reach_compliant=None if PubChem lookup failed for all reagents.
        Phase 2: supplement with ECHA C&L Inventory for full SVHC coverage.
        """
        all_hcodes: list[str] = []
        any_lookup_succeeded = False

        async with httpx.AsyncClient(timeout=settings.pubchem_request_timeout) as client:
            for smiles in smiles_list:
                hcodes = await self._fetch_ghs_hcodes(client, smiles)
                if hcodes is not None:
                    any_lookup_succeeded = True
                    all_hcodes.extend(hcodes)

        if not any_lookup_succeeded:
            return None, []

        unique_hcodes = sorted(set(all_hcodes))
        reach_concern = any(h in _REACH_CONCERN_HCODES for h in unique_hcodes)
        return not reach_concern, unique_hcodes

    async def _fetch_ghs_hcodes(self, client: httpx.AsyncClient, smiles: str) -> list[str] | None:
        """Return list of H-codes for a SMILES, or None on lookup failure."""
        try:
            inchikey = self._smiles_to_inchikey(smiles)
            if inchikey is None:
                return []

            cid = await self._pubchem_get_cid(client, inchikey)
            if cid is None:
                return []  # Not in PubChem - novel/proprietary, no flags

            return await self._pubchem_get_hcodes(client, cid)

        except httpx.HTTPError as exc:
            logger.warning("ghs_http_error", smiles=smiles[:80], error=str(exc))
            return None
        except Exception as exc:
            logger.warning("ghs_fetch_error", smiles=smiles[:80], error=str(exc))
            return None

    @staticmethod
    def _smiles_to_inchikey(smiles: str) -> str | None:
        mol = MolFromSmiles(smiles)
        if mol is None:
            return None
        inchi = MolToInchi(mol)
        if inchi is None:
            return None
        return InchiToInchiKey(inchi)

    @staticmethod
    async def _pubchem_get_cid(client: httpx.AsyncClient, inchikey: str) -> int | None:
        url = f"{_PUBCHEM_BASE}/compound/inchikey/{inchikey}/cids/JSON"
        resp = await client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        cids = resp.json().get("IdentifierList", {}).get("CID", [])
        return cids[0] if cids else None

    @staticmethod
    async def _pubchem_get_hcodes(client: httpx.AsyncClient, cid: int) -> list[str]:
        url = f"{_PUBCHEM_VIEW_BASE}/data/compound/{cid}/JSON?heading=GHS+Classification"
        resp = await client.get(url)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return _extract_hcodes(resp.json())

    def _collect_all_smiles(self, route: SynthesisRoute) -> list[str]:
        smiles = set()
        for step in route.steps:
            smiles.update(step.reactants_smiles)
            smiles.update(step.reagents_smiles)
        return list(smiles)
