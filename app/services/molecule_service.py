"""
Stage 1 — Input Processing
Resolves any supported input format to a canonical SMILES string.
Always returns canonical SMILES — that is the contract.

Supported inputs:
  SMILES        -> RDKit canonicalise + validate
  InChI         -> RDKit convert -> canonical SMILES
  CAS number    -> PubChem name lookup -> canonical SMILES
  IUPAC name    -> PubChem name lookup -> canonical SMILES
  Plain language -> PubChem compound name search (best-effort, Phase 1)

Format detection (when format=None):
  InChI   -- unambiguous: starts with "InChI="
  CAS     -- unambiguous: matches r'\\d{2,7}-\\d{2}-\\d'
  SMILES  -- confident: RDKit parses it AND contains SMILES-specific characters
  SMILES  -- ambiguous: RDKit parses it but no special chars (e.g. "CO", "C") -> FAIL LOUDLY
  Name    -- fallback: RDKit cannot parse it -> treated as IUPAC/plain language name

Out of scope (Phase 2+):
  - Claude API interpretation for complex functional descriptions
  - Partial SMILES / typo correction
"""
import asyncio
import re
import httpx
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Chem.inchi import InchiToInchiKey, MolFromInchi, MolToInchi

from app.core.config import settings
from app.core.logging import get_logger
from app.models.molecule import InputFormat, MoleculeInput, ResolvedMolecule

logger = get_logger(__name__)

# CID is not a requestable property — PubChem includes it automatically in every response
PUBCHEM_PROPERTIES = "IsomericSMILES,CanonicalSMILES,MolecularFormula,MolecularWeight,IUPACName,InChI,InChIKey"

# Characters / patterns that only appear in SMILES, never in compound names:
#   =  #  (  )  [  ]  /  \  @  +  %   — explicit bond/stereo/charge notation
#   c1 n1 o1 s1 p1 b1                  — aromatic atom + ring closure digit
_SMILES_CHARS = re.compile(r'[=\#\(\)\[\]/\\@\+\%]|[cnospb]\d')

# Strict CAS pattern: 2–7 digits, dash, 2 digits, dash, 1 digit
_CAS_PATTERN = re.compile(r'^\d{2,7}-\d{2}-\d$')


class MoleculeResolutionError(Exception):
    pass


class InvalidStructureError(MoleculeResolutionError):
    pass


class AmbiguousInputError(MoleculeResolutionError):
    pass


class PubChemLookupError(MoleculeResolutionError):
    pass


def detect_format(value: str) -> InputFormat:
    """
    Infer the input format from the value string.

    Detection order (priority):
      1. InChI prefix       — certain
      2. CAS regex          — certain
      3. SMILES with special chars + RDKit valid — confident
      4. RDKit valid but no special chars — AMBIGUOUS → raises AmbiguousInputError
      5. RDKit invalid      — treated as IUPAC / plain language name

    Raises AmbiguousInputError when the input is a valid SMILES but contains no
    SMILES-specific characters, making it indistinguishable from a compound name.
    In that case the caller must supply format explicitly.
    """
    v = value.strip()

    # 1. InChI — unambiguous prefix
    if v.startswith("InChI="):
        return InputFormat.INCHI

    # 2. CAS — strict format
    if _CAS_PATTERN.match(v):
        return InputFormat.CAS

    # 3 & 4. SMILES vs name — use RDKit + character heuristic
    mol = Chem.MolFromSmiles(v)
    if mol is not None:
        if _SMILES_CHARS.search(v):
            return InputFormat.SMILES  # confident: special chars + valid parse
        else:
            raise AmbiguousInputError(
                f"Input {v!r} is a valid SMILES but contains no SMILES-specific characters "
                f"(e.g. {v!r} could be methanol SMILES or a compound abbreviation). "
                f"Please supply format explicitly: smiles, cas, iupac, or plain_language."
            )

    # 5. RDKit parse failed — treat as IUPAC name / plain language
    return InputFormat.PLAIN_LANGUAGE


class MoleculeService:
    def __init__(self):
        self._pubchem_base = settings.pubchem_base_url

    async def resolve(self, molecule_input: MoleculeInput) -> ResolvedMolecule:
        fmt = molecule_input.format
        detected: InputFormat | None = None

        if fmt is None:
            detected = await asyncio.to_thread(detect_format, molecule_input.value)
            fmt = detected
            logger.info("format_detected", detected=fmt, value=molecule_input.value[:60])
        else:
            logger.info("resolving_molecule", format=fmt, value=molecule_input.value[:60])

        result = await self._dispatch(molecule_input.value, fmt)

        if detected is not None:
            result = result.model_copy(update={"detected_format": detected})

        return result

    async def _dispatch(self, value: str, fmt: InputFormat) -> ResolvedMolecule:
        match fmt:
            case InputFormat.SMILES:
                return await self._resolve_from_smiles(value)
            case InputFormat.INCHI:
                return await self._resolve_from_inchi(value)
            case InputFormat.CAS:
                return await self._resolve_from_pubchem_name(value, label="CAS")
            case InputFormat.IUPAC:
                return await self._resolve_from_pubchem_name(value, label="IUPAC")
            case InputFormat.PLAIN_LANGUAGE:
                return await self._resolve_from_pubchem_name(value, label="name")

    # ── SMILES ────────────────────────────────────────────────────────────────

    async def _resolve_from_smiles(self, smiles: str) -> ResolvedMolecule:
        if not smiles.strip():
            raise InvalidStructureError("SMILES string is empty")
        mol = await asyncio.to_thread(Chem.MolFromSmiles, smiles)
        if mol is None:
            raise InvalidStructureError(f"Invalid SMILES: {smiles!r}")

        canonical = Chem.MolToSmiles(mol)
        base = self._rdkit_metadata(mol, canonical)

        # Best-effort PubChem enrichment — adds CID and IUPAC name if found
        try:
            props = await self._pubchem_fetch("smiles", canonical)
            base = self._merge_pubchem(base, props)
        except PubChemLookupError:
            pass  # PubChem miss is not a failure for SMILES input

        return base

    # ── InChI ─────────────────────────────────────────────────────────────────

    async def _resolve_from_inchi(self, inchi: str) -> ResolvedMolecule:
        mol = await asyncio.to_thread(MolFromInchi, inchi)
        if mol is None:
            raise InvalidStructureError(f"Could not parse InChI: {inchi!r}")

        canonical = Chem.MolToSmiles(mol)
        base = self._rdkit_metadata(mol, canonical)

        try:
            props = await self._pubchem_fetch("inchi", inchi)
            base = self._merge_pubchem(base, props)
        except PubChemLookupError:
            pass

        return base

    # ── CAS / IUPAC / Plain Language (all via PubChem name search) ────────────

    async def _resolve_from_pubchem_name(self, name: str, label: str) -> ResolvedMolecule:
        try:
            props = await self._pubchem_fetch("name", name)
        except PubChemLookupError as e:
            raise MoleculeResolutionError(f"Could not resolve {label} {name!r} via PubChem: {e}") from e

        # PubChem returns different SMILES key names depending on the lookup namespace
        smiles = (props.get("IsomericSMILES") or props.get("CanonicalSMILES")
                  or props.get("SMILES") or props.get("ConnectivitySMILES"))
        if not smiles:
            raise MoleculeResolutionError(f"PubChem returned no SMILES for {label} {name!r}")

        mol = await asyncio.to_thread(Chem.MolFromSmiles, smiles)
        if mol is None:
            raise InvalidStructureError(f"PubChem SMILES failed RDKit validation: {smiles!r}")

        canonical = Chem.MolToSmiles(mol)
        base = self._rdkit_metadata(mol, canonical)
        return self._merge_pubchem(base, props)

    # ── PubChem API ───────────────────────────────────────────────────────────

    async def _pubchem_fetch(self, namespace: str, identifier: str) -> dict:
        url = f"{self._pubchem_base}/compound/{namespace}/{identifier}/property/{PUBCHEM_PROPERTIES}/JSON"
        async with httpx.AsyncClient(timeout=settings.pubchem_request_timeout) as client:
            try:
                response = await client.get(url)
            except httpx.RequestError as e:
                raise PubChemLookupError(f"PubChem request failed: {e}") from e

        if response.status_code == 404:
            raise PubChemLookupError(f"Not found in PubChem: {identifier!r}")
        if response.status_code != 200:
            raise PubChemLookupError(f"PubChem HTTP {response.status_code} for {identifier!r}")

        data = response.json()
        try:
            return data["PropertyTable"]["Properties"][0]
        except (KeyError, IndexError) as e:
            raise PubChemLookupError("Unexpected PubChem response structure") from e

    # ── RDKit metadata extraction ─────────────────────────────────────────────

    def _rdkit_metadata(self, mol, canonical_smiles: str) -> ResolvedMolecule:
        inchi = MolToInchi(mol)
        inchikey = InchiToInchiKey(inchi) if inchi else None
        formula = rdMolDescriptors.CalcMolFormula(mol)
        weight = round(Descriptors.MolWt(mol), 4)
        chiral_centres = Chem.FindMolChiralCenters(mol, includeUnassigned=True)

        return ResolvedMolecule(
            canonical_smiles=canonical_smiles,
            inchi=inchi,
            inchikey=inchikey,
            molecular_formula=formula,
            molecular_weight=weight,
            has_chiral_centres=len(chiral_centres) > 0,
            chiral_centre_count=len(chiral_centres),
        )

    def _merge_pubchem(self, base: ResolvedMolecule, props: dict) -> ResolvedMolecule:
        return base.model_copy(update={
            "pubchem_cid": props.get("CID"),
            "iupac_name": props.get("IUPACName") or base.iupac_name,
            "structure_image_url": (
                f"{settings.pubchem_base_url}/compound/cid/{props['CID']}/PNG"
                if props.get("CID") else None
            ),
        })
