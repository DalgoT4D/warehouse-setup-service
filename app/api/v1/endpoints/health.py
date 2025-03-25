from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint.
    """
    return {"status": "ok", "message": "API is running"} 