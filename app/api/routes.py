import os
import re
import logging
import secrets
import string
import time
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from celery.result import AsyncResult
from celery.states import SUCCESS, FAILURE, REVOKED, REJECTED, IGNORED, PENDING, RECEIVED, STARTED, RETRY

from app.core.auth import get_api_key
from app.core.config import settings
from app.schemas.terraform import TerraformResponse, TerraformStatus, TerraformJobStatusResponse
from app.tasks.terraform import run_terraform_commands

logger = logging.getLogger(__name__)

# Define Celery state groups for easier checking
CELERY_TERMINAL_STATES = [SUCCESS, FAILURE, REVOKED, REJECTED, IGNORED]
CELERY_ERROR_STATES = [FAILURE, REVOKED, REJECTED]

# Create routers
api_router = APIRouter()
infra_router = APIRouter(dependencies=[Depends(get_api_key)])
task_router = APIRouter(dependencies=[Depends(get_api_key)])
health_router = APIRouter()

# Request models
class PostgresDBRequest(BaseModel):
    """Request model for PostgreSQL database creation"""
    dbname: str

class SupersetRequest(BaseModel):
    """Request model for Superset creation"""
    org_slug: str

# Utility functions
def generate_secure_password(length=16):
    """Generate a secure random alphanumeric password"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def update_tfvars_with_org_slug(file_path, replacements):
    """Update terraform.tfvars file with org_slug"""
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
        logger.error(f"Error updating tfvars: {str(e)}")
        return False

def get_status_message(status: TerraformStatus, error: str = None) -> str:
    """Generate a human-readable status message"""
    if status == TerraformStatus.PENDING:
        return "Terraform job is pending execution"
    elif status == TerraformStatus.RUNNING:
        return "Terraform job is currently running"
    elif status == TerraformStatus.SUCCESS:
        return "Terraform job completed successfully"
    elif status == TerraformStatus.ERROR:
        return f"Terraform job failed: {error}" if error else "Terraform job failed"
    return "Unknown job status"

def celery_status_to_terraform_status(celery_status):
    """
    Convert Celery task status to TerraformStatus
    
    Handles all standard Celery states:
    - SUCCESS: Task completed successfully
    - FAILURE: Task failed due to an exception or other error
    - REVOKED: Task was revoked before execution
    - REJECTED: Task was rejected by the worker
    - IGNORED: Task was ignored by the worker
    """
    logger.debug(f"Converting Celery status: {celery_status}")
    
    # Check for SUCCESS state
    if celery_status == SUCCESS:
        return TerraformStatus.SUCCESS
    
    # Check for error states (FAILURE, REVOKED, REJECTED)
    elif celery_status in CELERY_ERROR_STATES:
        return TerraformStatus.ERROR
    
    # Check if the state is one of the terminal states but not SUCCESS or in ERROR_STATES
    elif celery_status in CELERY_TERMINAL_STATES:
        # This catches IGNORED
        return TerraformStatus.ERROR
    
    # Check for PENDING and RECEIVED states
    elif celery_status in [PENDING, RECEIVED]:
        return TerraformStatus.PENDING
    
    # STARTED and RETRY indicate the task is running
    elif celery_status in [STARTED, RETRY]:
        return TerraformStatus.RUNNING
    
    # Any other states default to ERROR for safety
    else:
        logger.warning(f"Unrecognized Celery status: {celery_status}, treating as ERROR")
        return TerraformStatus.ERROR

# Health check endpoint
@health_router.get("/health")
async def health_check():
    """Health check endpoint to verify that the API is functioning"""
    return {"status": "ok", "message": "API is healthy"}


# PostgreSQL database creation endpoint
@infra_router.post("/postgres/db", response_model=TerraformResponse)
async def create_postgres_db(payload: PostgresDBRequest):
    """Create a new PostgreSQL database with the provided database name"""
    try:
        # Get the terraform.tfvars file path
        terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
        tfvars_path = os.path.join(terraform_path, "terraform.tfvars")
        
        logger.info(f"Creating PostgreSQL database: {payload.dbname}")
        logger.info(f"Terraform path: {terraform_path}")
        logger.info(f"Terraform vars path: {tfvars_path}")
        
        if not os.path.exists(tfvars_path):
            logger.error(f"Terraform vars file not found: {tfvars_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Terraform vars file not found: {tfvars_path}"
            )
        
        # Generate secure password for APP_DB_PASS
        db_password = generate_secure_password()
        
        # Update the terraform.tfvars file with dbname and generated password
        db_user = f"{payload.dbname}_user"
        replacements = {
            "APP_DB_NAME": payload.dbname,
            "APP_DB_USER": db_user,
            "APP_DB_PASS": db_password,
        }
        
        logger.info(f"Updating tfvars with: {replacements}")
        
        if not update_tfvars_with_org_slug(tfvars_path, replacements):
            logger.error("Failed to update terraform variables")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update terraform variables"
            )
        
        # Extract host and port from terraform.tfvars
        host = "localhost"  # Default value
        port = "5432"       # Default value
        rds_name = None     # Will be used to construct the hostname
        
        try:
            with open(tfvars_path, 'r') as file:
                content = file.read()
                
                # Look for RDS instance name to construct hostname
                rds_match = re.search(r'rdsname\s*=\s*"([^"]*)"', content)
                if rds_match:
                    rds_name = rds_match.group(1)
                    # Construct AWS RDS hostname using the RDS instance name
                    host = f"{rds_name}.cwqixp4vwhou.us-east-1.rds.amazonaws.com"
                    logger.info(f"Constructed RDS hostname: {host}")
                else:
                    logger.warning("RDS instance name not found in tfvars, using default host")
                
                # Look for port variable (DB_PORT, not APP_DB_PORT)
                port_match = re.search(r'DB_PORT\s*=\s*(\d+)', content)
                if port_match:
                    port = port_match.group(1)
                    logger.info(f"Found DB port: {port}")
                else:
                    logger.warning("DB_PORT not found in tfvars, using default port 5432")
                
                # Log the contents of the tfvars file for debugging
                logger.debug(f"terraform.tfvars content: {content}")
                
        except Exception as e:
            logger.warning(f"Could not extract host/port from tfvars: {e}")
        
        # Store credentials with the task
        credentials = {
            "dbname": payload.dbname,
            "host": host,
            "port": port,
            "user": db_user, 
            "password": db_password
        }
        
        logger.info(f"Passing credentials to task: {credentials}")
        
        # Start the Celery task with the run_terraform_commands function
        task = run_terraform_commands.delay(terraform_path, credentials)
        
        logger.info(f"Task started with ID: {task.id}")
        
        # Create a response using the task ID as task_id
        return TerraformResponse(
            task_id=task.id,
        )

    except Exception as e:
        logger.exception(f"Error in create_postgres_db: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Superset creation endpoint
@infra_router.post("/superset", response_model=TerraformResponse)
async def create_superset(payload: SupersetRequest):
    """Create a new Superset instance with the provided organization slug"""
    try:
        # Get the terraform.tfvars file path
        terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET
        tfvars_path = os.path.join(terraform_path, "terraform.tfvars")
        
        logger.info(f"Creating Superset instance for org_slug: {payload.org_slug}")
        logger.info(f"Terraform path: {terraform_path}")
        logger.info(f"Terraform vars path: {tfvars_path}")
        
        if not os.path.exists(tfvars_path):
            logger.error(f"Terraform vars file not found: {tfvars_path}")
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
            "CLIENT_NAME": f"{payload.org_slug}",
            "OUTPUT_DIR": f"../../../{payload.org_slug}",
            "APP_DB_USER": f"superset_{payload.org_slug}",
            "APP_DB_NAME": f"superset_{payload.org_slug}",
            "SUPERSET_SECRET_KEY": secret_key,
            "SUPERSET_ADMIN_PASSWORD": admin_password,
            "APP_DB_PASS": db_password,
            "neworg_name": f"{payload.org_slug}.dalgo.org"
        }
        
        logger.info(f"Updating tfvars with: {replacements}")
        
        if not update_tfvars_with_org_slug(tfvars_path, replacements):
            logger.error("Failed to update terraform variables")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update terraform variables"
            )
        
        # Store credentials with the task
        credentials = {
            "client_name": f"{payload.org_slug}",
            "db_name": f"superset_{payload.org_slug}",
            "db_user": f"superset_{payload.org_slug}",
            "db_password": db_password,
            "admin": "admin",
            "admin_password": admin_password,
            "secret_key": secret_key,
            "neworg_name": f"{payload.org_slug}.dalgo.org"
        }
        
        logger.info(f"Passing credentials to task: {credentials}")
        
        # Start the Celery task with the run_terraform_commands function
        task = run_terraform_commands.apply_async(
            args=[terraform_path, credentials],
            queue='terraform'
        )
        
        logger.info(f"Task started with ID: {task.id}")
        
        # Create a response using the task ID as task_id
        return TerraformResponse(
            task_id=task.id,
        )

    except Exception as e:
        logger.exception(f"Error in create_superset: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Task status endpoint
@task_router.get("/{task_id}", response_model=TerraformJobStatusResponse)
async def get_task_status(task_id: str) -> Any:
    """
    Get the status of a task by its ID.
    
    This endpoint can be polled to check the progress of a long-running job.
    When the job is complete, it will include the task outputs.
    For successful jobs, it will also include credentials that were used
    to configure the resource (database passwords, admin accounts, etc.).
    """
    logger.info(f"Getting status for task: {task_id}")
    
    # Get the task result from Celery
    task_result = AsyncResult(task_id)
    
    if not task_result or not task_result.id:
        logger.warning(f"Task ID {task_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task ID {task_id} not found"
        )
    
    # Convert Celery status to TerraformStatus
    terraform_status = celery_status_to_terraform_status(task_result.status)
    logger.info(f"Task status: {task_result.status}, converted to: {terraform_status}")
    
    # Get task result if available
    result = None
    error = None
    outputs = None
    credentials = None
    
    # Determine error message based on Celery state
    if task_result.status == REVOKED:
        error = "Task was cancelled or revoked"
    elif task_result.status == REJECTED:
        error = "Task was rejected by worker"
    elif task_result.status == IGNORED:
        error = "Task was ignored by worker"
    
    # If the task is in a terminal state (SUCCESS, FAILURE, REVOKED, REJECTED, IGNORED)
    if task_result.status in CELERY_TERMINAL_STATES:
        logger.info(f"Task is in terminal state: {task_result.status}")
        try:
            # Always try to get the result, regardless of success/failure
            result = task_result.result
            logger.info(f"Raw task result type: {type(result)}")
            
            if isinstance(result, dict):
                logger.info(f"Result keys: {result.keys()}")
                # Extract outputs and credentials
                outputs = result.get('outputs')
                credentials = result.get('credentials')
                logger.info(f"Extracted credentials: {credentials}")
                logger.info(f"Extracted outputs: {outputs}")
                
                # If status is successful, ensure we include credentials
                if task_result.status == SUCCESS:
                    logger.info(f"Job successful, including credentials in response")
                
                # If there's an error message, capture it
                if result.get('status') == 'error':
                    error = result.get('error')
                    logger.error(f"Error found in result: {error}")
        except Exception as e:
            logger.exception(f"Error extracting task result: {e}")
            error = str(e)
    
    # Set the error message if task failed but we don't have a specific error yet
    if task_result.status == FAILURE and not error:
        try:
            error = str(task_result.result) if task_result.result else "Task failed"
        except Exception as e:
            error = f"Task failed with inaccessible result: {str(e)}"
        logger.error(f"Task failed: {error}")
    
    # Create status response
    response = TerraformJobStatusResponse(
        task_id=task_id,
        status=terraform_status,
        message=get_status_message(terraform_status, error),
        error=error,
        created_at=datetime.now(timezone.utc),  # Not available from AsyncResult directly
        completed_at=datetime.now(timezone.utc) if task_result.status in CELERY_TERMINAL_STATES else None,
        outputs=outputs,
        credentials=credentials
    )
    
    logger.info(f"Returning response with status: {response.status}, credentials present: {response.credentials is not None}")
    
    return response 