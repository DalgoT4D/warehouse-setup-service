import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import get_api_key
from app.core.config import settings
from app.schemas.terraform import TerraformResponse, TerraformStatus, TerraformJobStatusResponse
from app.services.terraform_job_store import TerraformJobStore
from app.tasks.terraform import run_terraform_apply

router = APIRouter()

# Path to Terraform scripts from settings
TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE


@router.post("/apply", response_model=TerraformResponse)
async def start_terraform_job(
    api_key: str = Depends(get_api_key)
) -> Any:
    """
    Run terraform apply to create warehouse infrastructure.
    
    This is a long-running task that executes in the background using Celery.
    Returns a job ID that can be used to check the status later.
    """
    try:
        # Check if the script path exists
        if not os.path.exists(TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Terraform script path not found: {TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE}"
            )
        
        # Create a new job
        job_id = TerraformJobStore.create_job()
        
        # Start the Celery task
        task = run_terraform_apply.delay(job_id)
        
        # Update job with the task ID for reference
        TerraformJobStore.update_job(job_id, task_id=task.id)
        
        # Get the job status to return
        job_status = TerraformJobStore.get_job_status(job_id)
        
        return job_status
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start Terraform job: {str(e)}"
        )


@router.get("/status/{job_id}", response_model=TerraformJobStatusResponse)
async def get_terraform_status(
    job_id: str,
    api_key: str = Depends(get_api_key)
) -> Any:
    """
    Get the status of a Terraform job.
    
    This endpoint can be polled to check the progress of a long-running job.
    When the job is complete, it will include the Terraform outputs.
    """
    job_status = TerraformJobStore.get_job_status(job_id)
    
    if not job_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job ID {job_id} not found"
        )
    
    return job_status 