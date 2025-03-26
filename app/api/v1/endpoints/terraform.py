import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import time

from app.core.auth import get_api_key
from app.core.config import settings
from app.schemas.terraform import TerraformResponse, TerraformStatus, TerraformJobStatusResponse
from app.services.terraform_job_store import TerraformJobStore
from app.tasks.terraform import run_terraform_apply

router = APIRouter()

# Path to Terraform scripts from settings
TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE

# Create a single job store instance to be used across the router
job_store = TerraformJobStore(CELERY_BROKER_URL=settings.CELERY_BROKER_URL)

@router.post("/apply", response_model=TerraformResponse)
async def create_warehouse():
    try:
        # Get the base project directory path
        terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
        main_tf_path = os.path.join(terraform_path, "main.tf")
        
        if not os.path.exists(main_tf_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Terraform script path not found: {main_tf_path}"
            )
        
        # Create a new job
        job_id = job_store.create_job()
        
        # Start the Celery task
        task = run_terraform_apply.delay(job_id)
        
        # Update job with the task ID
        job_store.update_job(job_id, task_id=task.id)
        
        # Return the job status
        return job_store.get_job_status(job_id)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
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
    job_status = job_store.get_job_status(job_id)
    
    if not job_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job ID {job_id} not found"
        )
    
    return job_status