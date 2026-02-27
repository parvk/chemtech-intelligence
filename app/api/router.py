from fastapi import APIRouter
from app.api.routes import synthesis

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(synthesis.router)
