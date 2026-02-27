from pydantic import BaseModel, Field


class ReactionStep(BaseModel):
    step_number: int
    reactants_smiles: list[str]
    reagents_smiles: list[str]
    product_smiles: str
    reaction_smiles: str
    reaction_class: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    literature_refs: list[str] = Field(default_factory=list)
    rationale: str | None = None


class RouteScores(BaseModel):
    sa_score: float | None = Field(None, ge=1.0, le=10.0, description="Synthetic Accessibility Score (1=easy, 10=hard)")
    route_maturity: float | None = Field(None, ge=0.0, le=1.0, description="Literature precedent score")
    green_index: float | None = Field(None, ge=0.0, le=100.0, description="Green chemistry score (%)")
    scale_up_readiness: float | None = Field(None, ge=0.0, le=1.0, description="Scale-up readiness proxy score")
    cost_index: float | None = Field(None, description="Estimated relative reagent cost index")
    reach_compliant: bool | None = None
    ghs_hazard_flags: list[str] = Field(default_factory=list)
    # Phase 2
    inventory_match: float | None = Field(None, description="Fraction of reagents in customer inventory")
    # Phase 3
    ip_risk_flag: bool | None = None


class SynthesisRoute(BaseModel):
    route_id: str
    steps: list[ReactionStep]
    step_count: int
    overall_confidence: float = Field(ge=0.0, le=1.0)
    scores: RouteScores
    composite_score: float | None = None
    rationale: str | None = None
    out_of_domain: bool = False
    out_of_domain_warning: str | None = None
