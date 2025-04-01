import os
from typing import Any, Dict, Optional
import re
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import time

from app.core.auth import get_api_key
from app.core.config import settings
from app.schemas.terraform import TerraformResponse, TerraformStatus, TerraformJobStatusResponse, OrgSlugRequest
from app.services.terraform_job_store import TerraformJobStore
from app.tasks.terraform import run_terraform_apply, run_terraform_apply_superset

router = APIRouter()

# Path to Terraform scripts from settings
TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET = settings.TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET

# Create a single job store instance to be used across the router
job_store = TerraformJobStore(CELERY_BROKER_URL=settings.CELERY_BROKER_URL)

def generate_secure_password(length=16):
    """Generate a secure random alphanumeric password"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def update_tfvars_with_org_slug(file_path, replacements):
    """
    Update terraform.tfvars file with org_slug
    """
    try:
        # Read the file
        with open(file_path, 'r') as file:
            content = file.read()
        
        # Make replacements
        for key, value_template in replacements.items():
            # Create regex to find the variable assignment
            pattern = rf'^({key}\s*=\s*)"[^"]*"(.*)$'
            replacement = rf'\1"{value_template}"\2'
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        
        # Write back to file
        with open(file_path, 'w') as file:
            file.write(content)
            
        return True
    except Exception as e:
        print(f"Error updating tfvars: {str(e)}")
        return False

@router.post("/warehouse", response_model=TerraformResponse)
async def create_warehouse(request: OrgSlugRequest):
    """
    Create a new warehouse database with the provided organization slug
    """
    try:
        # Get the terraform.tfvars file path
        terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
        tfvars_path = os.path.join(terraform_path, "terraform.tfvars")
        
        if not os.path.exists(tfvars_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Terraform vars file not found: {tfvars_path}"
            )
        
        # Generate secure password for APP_DB_PASS
        db_password = generate_secure_password()
        
        # Update the terraform.tfvars file with org_slug and generated password
        replacements = {
            "APP_DB_NAME": f"warehouse_{request.org_slug}",
            "APP_DB_USER": f"warehouse_{request.org_slug}",
            "APP_DB_PASS": db_password
        }
        
        if not update_tfvars_with_org_slug(tfvars_path, replacements):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update terraform variables"
            )
        
        # Create a new job
        job_id = job_store.create_job()
        
        # Store credentials for later retrieval
        job_store.store_job_credentials(job_id, {
            "db_name": f"warehouse_{request.org_slug}",
            "db_user": f"warehouse_{request.org_slug}",
            "db_password": db_password
        })
        
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

@router.post("/superset", response_model=TerraformResponse)
async def create_superset(request: OrgSlugRequest):
    """
    Create a new Superset instance with the provided organization slug
    """
    try:
        # Get the terraform.tfvars file path
        terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET
        tfvars_path = os.path.join(terraform_path, "terraform.tfvars")
        
        if not os.path.exists(tfvars_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Terraform vars file not found: {tfvars_path}"
            )
        
        # Generate secure passwords
        secret_key = generate_secure_password(32)
        admin_password = generate_secure_password()
        db_password = generate_secure_password()
        
        # Update the terraform.tfvars file with org_slug and generated passwords
        replacements = {
            "CLIENT_NAME": f"{request.org_slug}",
            "OUTPUT_DIR": f"../../../{request.org_slug}",
            "APP_DB_USER": f"superset_{request.org_slug}",
            "APP_DB_NAME": f"superset_{request.org_slug}",
            "SUPERSET_SECRET_KEY": secret_key,
            "SUPERSET_ADMIN_PASSWORD": admin_password,
            "APP_DB_PASS": db_password
        }
        
        if not update_tfvars_with_org_slug(tfvars_path, replacements):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update terraform variables"
            )
        
        # Create a new job
        job_id = job_store.create_job()
        
        # Store credentials for later retrieval
        job_store.store_job_credentials(job_id, {
            "client_name": f"{request.org_slug}",
            "db_name": f"superset_{request.org_slug}",
            "db_user": f"superset_{request.org_slug}",
            "db_password": db_password,
            "admin_password": admin_password,
            "secret_key": secret_key
        })
        
        # Start the Celery task
        task = run_terraform_apply_superset.apply_async(args=[job_id], queue='terraform')
        
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
async def get_task_info(
    job_id: str,
    api_key: str = Depends(get_api_key)
) -> Any:
    """
    Get the status of a Terraform job.
    
    This endpoint can be polled to check the progress of a long-running job.
    When the job is complete, it will include the Terraform outputs.
    For successful jobs, it will also include the credentials that were used
    to configure the resource (database passwords, admin accounts, etc.).
    """
    job_status = job_store.get_job_status(job_id)
    
    if not job_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job ID {job_id} not found"
        )
    
    return job_status