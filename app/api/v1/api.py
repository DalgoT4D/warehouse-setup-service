from fastapi import APIRouter

from app.api.v1.endpoints import  health, terraform

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(terraform.router, prefix="/terraform", tags=["terraform"]) 