from fastapi import APIRouter

from app.services.ollama_client import ollama_health

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    return await ollama_health()
