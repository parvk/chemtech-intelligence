"""
Tests for Stage 1 - Molecule Resolution.

Unit tests mock PubChem so they run offline.
Integration tests (marked integration) hit the real PubChem API - skip in CI with:
    pytest -m "not integration"
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.models.molecule import InputFormat, MoleculeInput
from app.services.molecule_service import (
    AmbiguousInputError,
    InvalidStructureError,
    MoleculeResolutionError,
    MoleculeService,
    PubChemLookupError,
    detect_format,
)

ETHANOL_SMILES = "CCO"
ETHANOL_CAS = "64-17-5"
ETHANOL_IUPAC = "ethanol"
ETHANOL_INCHI = "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3"
ETHANOL_INCHIKEY = "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"

PUBCHEM_ETHANOL = {
    "CID": 702,
    "IsomericSMILES": "CCO",
    "CanonicalSMILES": "CCO",
    "MolecularFormula": "C2H6O",
    "MolecularWeight": 46.07,
    "IUPACName": "ethanol",
    "InChI": ETHANOL_INCHI,
    "InChIKey": ETHANOL_INCHIKEY,
}

CHIRAL_SMILES = "C[C@@H](O)F"  # (S)-1-fluoroethanol - one chiral centre


@pytest.fixture
def svc():
    return MoleculeService()


def mock_pubchem(props: dict = PUBCHEM_ETHANOL):
    return patch.object(MoleculeService, "_pubchem_fetch", new=AsyncMock(return_value=props))


# ── Format detection ──────────────────────────────────────────────────────────

class TestFormatDetection:
    def test_inchi_detected(self):
        assert detect_format(ETHANOL_INCHI) == InputFormat.INCHI

    def test_inchi_with_whitespace_detected(self):
        assert detect_format(f"  {ETHANOL_INCHI}  ") == InputFormat.INCHI

    def test_cas_detected(self):
        assert detect_format("64-17-5") == InputFormat.CAS
        assert detect_format("50-00-0") == InputFormat.CAS      # formaldehyde
        assert detect_format("1234567-89-0") == InputFormat.CAS  # max digits

    def test_cas_wrong_format_not_detected(self):
        # not a valid CAS pattern - falls through to name
        assert detect_format("1-2-3-4") == InputFormat.PLAIN_LANGUAGE

    def test_smiles_with_special_chars_detected(self):
        assert detect_format("CC(=O)O") == InputFormat.SMILES      # acetic acid
        assert detect_format("c1ccccc1") == InputFormat.SMILES      # benzene
        assert detect_format("C[C@@H](O)F") == InputFormat.SMILES  # chiral
        assert detect_format("CC#N") == InputFormat.SMILES          # triple bond

    def test_ambiguous_smiles_raises(self):
        # "CO" parses as SMILES (methanol) but has no special chars
        with pytest.raises(AmbiguousInputError, match="format explicitly"):
            detect_format("CO")

    def test_single_atom_smiles_raises(self):
        with pytest.raises(AmbiguousInputError):
            detect_format("C")   # methane SMILES or element symbol?

    def test_plain_name_detected(self):
        assert detect_format("ethanol") == InputFormat.PLAIN_LANGUAGE
        assert detect_format("aspirin") == InputFormat.PLAIN_LANGUAGE
        assert detect_format("2-acetoxybenzoic acid") == InputFormat.PLAIN_LANGUAGE

    def test_explicit_format_skips_detection(self):
        # "CO" would raise AmbiguousInputError if auto-detected,
        # but providing format explicitly bypasses detection entirely
        inp = MoleculeInput(value="CO", format=InputFormat.SMILES)
        assert inp.format == InputFormat.SMILES


# ── Auto-detection end-to-end (via resolve) ───────────────────────────────────

class TestAutoDetectionResolve:
    @pytest.mark.asyncio
    async def test_inchi_auto_detected_and_resolved(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_INCHI))
        assert result.canonical_smiles == "CCO"
        assert result.detected_format == InputFormat.INCHI

    @pytest.mark.asyncio
    async def test_cas_auto_detected_and_resolved(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_CAS))
        assert result.canonical_smiles == "CCO"
        assert result.detected_format == InputFormat.CAS

    @pytest.mark.asyncio
    async def test_smiles_auto_detected_and_resolved(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value="CC(=O)O"))  # acetic acid
        assert result.canonical_smiles
        assert result.detected_format == InputFormat.SMILES

    @pytest.mark.asyncio
    async def test_plain_name_auto_detected_and_resolved(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value="ethanol"))
        assert result.canonical_smiles == "CCO"
        assert result.detected_format == InputFormat.PLAIN_LANGUAGE

    @pytest.mark.asyncio
    async def test_ambiguous_input_raises_before_resolution(self, svc):
        with pytest.raises(AmbiguousInputError):
            await svc.resolve(MoleculeInput(value="CO"))

    @pytest.mark.asyncio
    async def test_explicit_format_has_no_detected_format(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_SMILES, format=InputFormat.SMILES))
        assert result.detected_format is None


# ── SMILES resolution ─────────────────────────────────────────────────────────

class TestSMILESResolution:
    @pytest.mark.asyncio
    async def test_canonical_smiles_returned(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value="OCC", format=InputFormat.SMILES))
        assert result.canonical_smiles == "CCO"

    @pytest.mark.asyncio
    async def test_rdkit_metadata_populated(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_SMILES, format=InputFormat.SMILES))
        assert result.molecular_formula == "C2H6O"
        assert result.molecular_weight == pytest.approx(46.069, abs=0.01)
        assert result.inchi == ETHANOL_INCHI
        assert result.inchikey == ETHANOL_INCHIKEY

    @pytest.mark.asyncio
    async def test_pubchem_cid_merged(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_SMILES, format=InputFormat.SMILES))
        assert result.pubchem_cid == 702
        assert result.iupac_name == "ethanol"

    @pytest.mark.asyncio
    async def test_pubchem_failure_does_not_fail_smiles_resolution(self, svc):
        with patch.object(MoleculeService, "_pubchem_fetch", new=AsyncMock(side_effect=PubChemLookupError("not found"))):
            result = await svc.resolve(MoleculeInput(value=ETHANOL_SMILES, format=InputFormat.SMILES))
        assert result.canonical_smiles == "CCO"
        assert result.pubchem_cid is None

    @pytest.mark.asyncio
    async def test_invalid_smiles_raises(self, svc):
        with pytest.raises(InvalidStructureError):
            await svc.resolve(MoleculeInput(value="not-a-smiles", format=InputFormat.SMILES))

    @pytest.mark.asyncio
    async def test_empty_smiles_raises(self, svc):
        with pytest.raises(InvalidStructureError):
            await svc.resolve(MoleculeInput(value="", format=InputFormat.SMILES))


# ── Chiral centre detection ───────────────────────────────────────────────────

class TestChiralDetection:
    @pytest.mark.asyncio
    async def test_chiral_molecule_detected(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=CHIRAL_SMILES, format=InputFormat.SMILES))
        assert result.has_chiral_centres is True
        assert result.chiral_centre_count == 1

    @pytest.mark.asyncio
    async def test_achiral_molecule(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_SMILES, format=InputFormat.SMILES))
        assert result.has_chiral_centres is False
        assert result.chiral_centre_count == 0

    @pytest.mark.asyncio
    async def test_multiple_chiral_centres(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value="[C@@H]([C@H](O)C(=O)O)(O)C(=O)O", format=InputFormat.SMILES))
        assert result.chiral_centre_count == 2


# ── InChI resolution ──────────────────────────────────────────────────────────

class TestInChIResolution:
    @pytest.mark.asyncio
    async def test_inchi_returns_canonical_smiles(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_INCHI, format=InputFormat.INCHI))
        assert result.canonical_smiles == "CCO"

    @pytest.mark.asyncio
    async def test_invalid_inchi_raises(self, svc):
        with pytest.raises(InvalidStructureError):
            await svc.resolve(MoleculeInput(value="InChI=1S/INVALID", format=InputFormat.INCHI))


# ── CAS / IUPAC / Plain language ──────────────────────────────────────────────

class TestPubChemNameLookup:
    @pytest.mark.asyncio
    async def test_cas_resolves_to_canonical_smiles(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_CAS, format=InputFormat.CAS))
        assert result.canonical_smiles == "CCO"

    @pytest.mark.asyncio
    async def test_iupac_resolves_to_canonical_smiles(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_IUPAC, format=InputFormat.IUPAC))
        assert result.canonical_smiles == "CCO"

    @pytest.mark.asyncio
    async def test_plain_language_resolves_to_canonical_smiles(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value="ethanol", format=InputFormat.PLAIN_LANGUAGE))
        assert result.canonical_smiles == "CCO"

    @pytest.mark.asyncio
    async def test_unknown_cas_raises(self, svc):
        with patch.object(MoleculeService, "_pubchem_fetch", new=AsyncMock(side_effect=PubChemLookupError("404"))):
            with pytest.raises(MoleculeResolutionError):
                await svc.resolve(MoleculeInput(value="99-99-9999", format=InputFormat.CAS))

    @pytest.mark.asyncio
    async def test_pubchem_returns_no_smiles_raises(self, svc):
        with mock_pubchem({"CID": 1, "MolecularFormula": "C2H6O"}):
            with pytest.raises(MoleculeResolutionError, match="no SMILES"):
                await svc.resolve(MoleculeInput(value=ETHANOL_CAS, format=InputFormat.CAS))


# ── ResolvedMolecule contract ─────────────────────────────────────────────────

class TestResolvedMoleculeContract:
    """canonical_smiles must always be populated - that is the Stage 1 contract."""

    @pytest.mark.asyncio
    async def test_smiles_always_present_for_smiles_input(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value="c1ccccc1", format=InputFormat.SMILES))
        assert result.canonical_smiles
        assert isinstance(result.canonical_smiles, str)

    @pytest.mark.asyncio
    async def test_smiles_always_present_for_inchi_input(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_INCHI, format=InputFormat.INCHI))
        assert result.canonical_smiles

    @pytest.mark.asyncio
    async def test_smiles_always_present_for_cas_input(self, svc):
        with mock_pubchem():
            result = await svc.resolve(MoleculeInput(value=ETHANOL_CAS, format=InputFormat.CAS))
        assert result.canonical_smiles


# ── Integration tests (real PubChem - skip in CI) ─────────────────────────────

@pytest.mark.integration
class TestPubChemIntegration:
    @pytest.mark.asyncio
    async def test_cas_ethanol_live(self):
        svc = MoleculeService()
        result = await svc.resolve(MoleculeInput(value=ETHANOL_CAS, format=InputFormat.CAS))
        assert result.canonical_smiles == "CCO"
        assert result.pubchem_cid == 702
        assert result.iupac_name == "ethanol"

    @pytest.mark.asyncio
    async def test_iupac_aspirin_live(self):
        svc = MoleculeService()
        result = await svc.resolve(MoleculeInput(value="2-acetoxybenzoic acid", format=InputFormat.IUPAC))
        assert result.canonical_smiles
        assert result.pubchem_cid == 2244

    @pytest.mark.asyncio
    async def test_smiles_caffeine_live(self):
        svc = MoleculeService()
        result = await svc.resolve(MoleculeInput(value="Cn1cnc2c1c(=O)n(c(=O)n2C)C", format=InputFormat.SMILES))
        assert result.canonical_smiles
        assert result.molecular_formula == "C8H10N4O2"

    @pytest.mark.asyncio
    async def test_auto_detect_cas_live(self):
        svc = MoleculeService()
        result = await svc.resolve(MoleculeInput(value=ETHANOL_CAS))
        assert result.canonical_smiles == "CCO"
        assert result.detected_format == InputFormat.CAS

    @pytest.mark.asyncio
    async def test_auto_detect_smiles_live(self):
        svc = MoleculeService()
        result = await svc.resolve(MoleculeInput(value="CC(=O)O"))  # acetic acid
        assert result.canonical_smiles
        assert result.detected_format == InputFormat.SMILES
