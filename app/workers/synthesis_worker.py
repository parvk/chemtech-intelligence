"""
Celery task orchestrating the full 6-stage synthesis planning pipeline.
Runs asynchronously — the API submits this task and returns a job_id immediately.
"""
import asyncio
from datetime import datetime, UTC

from app.workers.celery_app import celery_app
from app.core.logging import get_logger
from app.models.job import JobStatus, SynthesisPlanRequest, SynthesisPlanResult
from app.models.molecule import OptimisationDimension
from app.services.molecule_service import MoleculeService
from app.services.retrosynthesis_service import RetrosynthesisService
from app.services.scoring_service import ScoringService
from app.services.ranking_service import RankingService
from app.services.explainability_service import ExplainabilityService

logger = get_logger(__name__)


def _update_state(task, status: JobStatus, stage_label: str, progress_pct: int):
    task.update_state(
        state="PROGRESS",
        meta={
            "status": status.value,
            "stage_label": stage_label,
            "progress_pct": progress_pct,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


@celery_app.task(bind=True, name="synthesis.plan")
def run_synthesis_plan(self, request_dict: dict) -> dict:
    """
    Full pipeline task:
      Stage 1: Molecule resolution
      Stage 2: Retrosynthesis inference
      Stage 3: Route scoring
      Stage 4: Ranking & filtering
      Stage 5: Explainability
      Stage 6: Output assembly
    """
    started_at = datetime.now(UTC)
    request = SynthesisPlanRequest(**request_dict)
    warnings: list[str] = []

    logger.info("synthesis_pipeline_start", job_id=self.request.id, tenant_id=request.tenant_id)

    async def _run():
        # Stage 1
        _update_state(self, JobStatus.RESOLVING, "Resolving molecule structure", 5)
        mol_service = MoleculeService()
        resolved = await mol_service.resolve(request.molecule)

        # Stage 2
        _update_state(self, JobStatus.INFERRING, "Running retrosynthesis inference", 15)
        retro_service = RetrosynthesisService()
        candidate_routes = await retro_service.run(
            canonical_smiles=resolved.canonical_smiles,
            max_routes=request.max_routes * 3,  # generate more, then filter
            max_depth=request.max_depth,
        )

        if not candidate_routes:
            raise ValueError("No synthesis routes found for this molecule.")

        for route in candidate_routes:
            if route.out_of_domain:
                warnings.append(f"Route {route.route_id}: molecule may be out of training distribution — review with caution.")

        # Stage 3
        _update_state(self, JobStatus.SCORING, "Scoring routes", 60)
        scoring_service = ScoringService()
        scored_routes = await scoring_service.score_routes(candidate_routes)

        # Stage 4
        _update_state(self, JobStatus.RANKING, "Ranking routes", 75)
        ranking_service = RankingService()
        ranked_routes = ranking_service.rank(
            scored_routes,
            dimension=request.optimisation_dimension,
            top_n=request.max_routes,
        )

        # Stage 5
        _update_state(self, JobStatus.EXPLAINING, "Generating route rationale", 80)
        explain_service = ExplainabilityService()
        enriched_routes = await explain_service.enrich_routes(ranked_routes, resolved.canonical_smiles)

        # Stage 6
        _update_state(self, JobStatus.ASSEMBLING, "Assembling response", 95)
        duration = (datetime.now(UTC) - started_at).total_seconds()

        result = SynthesisPlanResult(
            job_id=self.request.id,
            tenant_id=request.tenant_id,
            molecule=resolved,
            optimisation_dimension=request.optimisation_dimension,
            routes=enriched_routes,
            total_routes_generated=len(candidate_routes),
            completed_at=datetime.now(UTC),
            pipeline_duration_seconds=duration,
            warnings=warnings,
        )
        return result.model_dump(mode="json")

    return asyncio.run(_run())
