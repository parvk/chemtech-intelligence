from enum import Enum
from pydantic import BaseModel, Field


class InputFormat(str, Enum):
    SMILES = "smiles"
    INCHI = "inchi"
    CAS = "cas"
    IUPAC = "iupac"
    PLAIN_LANGUAGE = "plain_language"


class OptimisationDimension(str, Enum):
    FEWEST_STEPS = "fewest_steps"
    HIGHEST_YIELD = "highest_yield"
    LOWEST_COST = "lowest_cost"
    GREENEST_ROUTE = "greenest_route"
    MOST_PRECEDENTED = "most_precedented"


class MoleculeInput(BaseModel):
    value: str = Field(..., description="Molecule identifier — SMILES, CAS, IUPAC name, or plain language description")
    format: InputFormat = Field(InputFormat.SMILES, description="Format of the input value")


class ResolvedMolecule(BaseModel):
    canonical_smiles: str
    inchi: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    pubchem_cid: int | None = None
    iupac_name: str | None = None
    has_chiral_centres: bool = False
    chiral_centre_count: int = 0
    structure_image_url: str | None = None
