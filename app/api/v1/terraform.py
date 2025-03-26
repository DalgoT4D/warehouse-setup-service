from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional
from app.core.config import settings
from app.services.terraform_job_store import TerraformJobStore
from app.tasks.terraform import run_terraform_apply, run_terraform_apply_superset
import uuid

router = APIRouter()

# Initialize the job store with Redis URL from settings
job_store = TerraformJobStore(CELERY_BROKER_URL=settings.CELERY_BROKER_URL)

def verify_api_key(x_api_key: str = Header(...)):
    if not settings.is_valid_api_key(x_api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    return x_api_key

@router.post("/apply")
async def apply_terraform(
    api_key: str = Depends(verify_api_key)
):
    """
    Apply Terraform configuration for warehouse
    """
    job_id = str(uuid.uuid4())
    
    # Create a new job in Redis
    job_store.create_job(job_id)
    
    # Start the Celery task
    task = run_terraform_apply.delay(job_id)
    
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Terraform job is pending execution",
        "error": None,
        "created_at": job_store.get_job(job_id)["created_at"]
    }

@router.post("/apply-superset")
async def apply_terraform_superset(
    api_key: str = Depends(verify_api_key)
):
    """
    Apply Terraform configuration for Superset
    """
    job_id = str(uuid.uuid4())
    
    # Create a new job in Redis
    job_store.create_job(job_id)
    
    # Start the Celery task
    task = run_terraform_apply_superset.delay(job_id)
    
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Terraform job is pending execution",
        "error": None,
        "created_at": job_store.get_job(job_id)["created_at"]
    }

@router.get("/status/{job_id}")
async def get_job_status(
    job_id: str,
    api_key: str = Depends(verify_api_key)
):
    """
    Get the status of a Terraform job
    """
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    return job 