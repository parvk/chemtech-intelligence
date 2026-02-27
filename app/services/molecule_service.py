"""
Stage 1 — Input Processing
Resolves molecule input to canonical SMILES and validates structure.
"""
import httpx
from app.core.config import settings
from app.core.logging import get_logger
from app.models.molecule import InputFormat, MoleculeInput, ResolvedMolecule

logger = get_logger(__name__)


class MoleculeResolutionError(Exception):
    pass


class MoleculeService:
    def __init__(self):
        self._pubchem_base = settings.pubchem_base_url

    async def resolve(self, molecule_input: MoleculeInput) -> ResolvedMolecule:
        logger.info("resolving_molecule", format=molecule_input.format, value=molecule_input.value[:50])

        match molecule_input.format:
            case InputFormat.SMILES:
                return await self._resolve_from_smiles(molecule_input.value)
            case InputFormat.CAS:
                return await self._resolve_from_cas(molecule_input.value)
            case InputFormat.IUPAC:
                return await self._resolve_from_iupac(molecule_input.value)
            case InputFormat.INCHI:
                return await self._resolve_from_inchi(molecule_input.value)
            case InputFormat.PLAIN_LANGUAGE:
                return await self._resolve_from_plain_language(molecule_input.value)
            case _:
                raise MoleculeResolutionError(f"Unsupported input format: {molecule_input.format}")

    async def _resolve_from_smiles(self, smiles: str) -> ResolvedMolecule:
        # TODO: canonicalise via RDKit, then enrich via PubChem
        raise NotImplementedError

    async def _resolve_from_cas(self, cas: str) -> ResolvedMolecule:
        # TODO: PubChem CAS lookup → canonical SMILES
        raise NotImplementedError

    async def _resolve_from_iupac(self, iupac: str) -> ResolvedMolecule:
        # TODO: PubChem IUPAC lookup → canonical SMILES
        raise NotImplementedError

    async def _resolve_from_inchi(self, inchi: str) -> ResolvedMolecule:
        # TODO: RDKit InChI → SMILES, then PubChem enrichment
        raise NotImplementedError

    async def _resolve_from_plain_language(self, description: str) -> ResolvedMolecule:
        # TODO: Claude API interpretation → candidate SMILES → validation
        # This is an NLP problem distinct from SMILES parsing
        raise NotImplementedError

    async def _pubchem_lookup(self, namespace: str, identifier: str) -> dict:
        url = f"{self._pubchem_base}/compound/{namespace}/{identifier}/JSON"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
