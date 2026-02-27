from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger = get_logger(__name__)
    logger.info("chemtech_intelligence_starting", env=settings.app_env)
    yield
    logger.info("chemtech_intelligence_shutdown")


app = FastAPI(
    title="ChemFlow Intelligence API",
    description="AI inference service — retrosynthesis, scoring, and explainability",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "chemtech-intelligence", "env": settings.app_env}
