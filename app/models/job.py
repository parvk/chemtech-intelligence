from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from app.models.molecule import MoleculeInput, OptimisationDimension, ResolvedMolecule
from app.models.route import SynthesisRoute


class JobStatus(str, Enum):
    PENDING = "pending"
    RESOLVING = "resolving"       # Stage 1: molecule input processing
    INFERRING = "inferring"       # Stage 2: retrosynthesis inference
    SCORING = "scoring"           # Stage 3: route scoring
    RANKING = "ranking"           # Stage 4: ranking & filtering
    EXPLAINING = "explaining"     # Stage 5: explainability
    ASSEMBLING = "assembling"     # Stage 6: output assembly
    COMPLETED = "completed"
    FAILED = "failed"


class SynthesisPlanRequest(BaseModel):
    molecule: MoleculeInput
    optimisation_dimension: OptimisationDimension = OptimisationDimension.FEWEST_STEPS
    max_routes: int = Field(5, ge=1, le=10)
    max_depth: int = Field(6, ge=1, le=10, description="Maximum retrosynthetic depth")
    tenant_id: str = Field("", description="Tenant identifier - injected from X-Tenant-Id header, not supplied in request body")


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    stage_label: str
    progress_pct: int = Field(ge=0, le=100)
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class SynthesisPlanResult(BaseModel):
    job_id: str
    tenant_id: str
    molecule: ResolvedMolecule
    optimisation_dimension: OptimisationDimension
    routes: list[SynthesisRoute]
    total_routes_generated: int
    completed_at: datetime
    pipeline_duration_seconds: float
    warnings: list[str] = Field(default_factory=list)
