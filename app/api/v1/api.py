from fastapi import APIRouter, Depends

from app.api.v1.endpoints import health, terraform
from app.core.auth import get_api_key

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(terraform.router, prefix="/terraform", tags=["terraform"], dependencies=[Depends(get_api_key)]) 