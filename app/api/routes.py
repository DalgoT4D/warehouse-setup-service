import os
import re
import logging
import secrets
import string
import time
import random
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
    client_name: str
    ec2_machine_id: str
    port: int

# Utility functions
def generate_secure_password(length=16):
    """Generate a secure random alphanumeric password"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def update_tfvars(file_path, replacements):
    """Update terraform.tfvars file with dynamic values"""
    try:
        # Read the file
        with open(file_path, 'r') as file:
            content = file.read()
        
        # Make replacements
        for key, value in replacements.items():
            # Check if the value should include quotes (strings)
            if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                # String value with quotes already included
                pattern = rf'^({key}\s*=\s*).*$'
                replacement = rf'\1{value}'
            elif isinstance(value, str) and not value.isdigit():
                # Regular string, add quotes
                pattern = rf'^({key}\s*=\s*).*$'
                replacement = rf'\1"{value}"'
            else:
                # Numbers or other values without quotes
                pattern = rf'^({key}\s*=\s*).*$'
                replacement = rf'\1{value}'
            
            # Apply the replacement with multiline mode
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

# Debug endpoint to show computed credentials
@health_router.get("/debug/credentials/{dbname}")
async def debug_credentials(dbname: str):
    """Debug endpoint to show what credentials would be created for a given database name"""
    try:
        terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
        tfvars_path = os.path.join(terraform_path, "terraform.tfvars")
        
        if not os.path.exists(tfvars_path):
            return {"error": f"Terraform vars file not found: {tfvars_path}"}
        
        # Load module-specific settings
        module_settings = settings.get_terraform_module_settings(terraform_path)
        
        # Get host and port from module settings
        host = module_settings.get_rds_hostname()
        port = str(module_settings.DB_PORT)
        
        # Generate sample credentials
        db_password = "SAMPLE_PASSWORD_NOT_REAL"
        credentials = {
            "dbname": dbname,
            "host": host,
            "port": port,
            "user": f"{dbname}_user",
            "password": db_password
        }
        
        # Show environment settings
        env_settings = {
            "rds_instance_name": module_settings.RDS_INSTANCE_NAME,
            "rds_domain": module_settings.RDS_DOMAIN,
            "db_port": module_settings.DB_PORT,
            "terraform_path": terraform_path,
            "tfvars_path": tfvars_path
        }
        
        return {
            "credentials": credentials,
            "environment_settings": env_settings,
            "module_tfvars_file": os.path.join(terraform_path, "terraform.tfvars")
        }
    except Exception as e:
        return {"error": str(e)}

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
        
        # Load module-specific settings
        module_settings = settings.get_terraform_module_settings(terraform_path)
        logger.info(f"Loaded module settings for: {terraform_path}")
        
        # Generate secure password for APP_DB_PASS
        db_password = generate_secure_password()
        
        # Prepare replacements for tfvars file (will be used to create task-specific file)
        replacements = {
            "APP_DB_NAME": payload.dbname,
            "APP_DB_USER": f"{payload.dbname}_user",
            "APP_DB_PASS": db_password
        }
        
        logger.info(f"Prepared replacements for task-specific tfvars: {replacements}")
        
        # Get host and port from module settings
        host = module_settings.get_rds_hostname()
        port = str(module_settings.DB_PORT)
        
        # Store credentials with the task
        credentials = {
            "dbname": payload.dbname,
            "host": host,
            "port": port,
            "user": f"{payload.dbname}_user",
            "password": db_password
        }
        
        logger.info(f"Passing credentials to task: {credentials}")
        
        # Start the Celery task with the run_terraform_commands function,
        # passing replacements to create a task-specific tfvars file
        task = run_terraform_commands.apply_async(
            args=[terraform_path, credentials, replacements],
            queue='terraform'
        )
        
        logger.info(f"Task started with ID: {task.id}")
        
        # Create a response using the task ID as id
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
    """Create a new Superset instance with the provided client name"""
    try:
        # Get the terraform.tfvars file path
        terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET
        tfvars_path = os.path.join(terraform_path, "terraform.tfvars")
        
        logger.info(f"Creating Superset for client: {payload.client_name}")
        logger.info(f"Using EC2 instance: {payload.ec2_machine_id}")
        logger.info(f"Using port: {payload.port}")
        logger.info(f"Terraform path: {terraform_path}")
        logger.info(f"Terraform vars path: {tfvars_path}")
        
        if not os.path.exists(tfvars_path):
            logger.error(f"Terraform vars file not found: {tfvars_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Terraform vars file not found: {tfvars_path}"
            )
        
        # Load module-specific settings
        module_settings = settings.get_terraform_module_settings(terraform_path)
        logger.info(f"Loaded module settings for: {terraform_path}")
        
        # Generate secure passwords
        admin_password = generate_secure_password()
        db_password = generate_secure_password()
        secret_key = generate_secure_password(32)
        
        # Prepare replacements for tfvars file (will be used to create task-specific file)
        replacements = {
            "CLIENT_NAME": payload.client_name,
            "OUTPUT_DIR": f"../../../{payload.client_name}",
            "SUPERSET_SECRET_KEY": secret_key,
            "SUPERSET_ADMIN_USERNAME": module_settings.SUPERSET_ADMIN_USERNAME,
            "SUPERSET_ADMIN_PASSWORD": admin_password,
            "APP_DB_USER": f"superset_{payload.client_name}",
            "APP_DB_PASS": db_password,
            "APP_DB_NAME": f"superset_{payload.client_name}",
            "neworg_name": f"{payload.client_name}.dalgo.org",
            "CONTAINER_PORT": str(payload.port),
            "rule_priority": str(payload.port),
            "appli_ec2": payload.ec2_machine_id
        }
        
        logger.info(f"Prepared replacements for task-specific tfvars: {replacements}")
        
        # Store credentials with the task
        credentials = {
            "superset_url": f"https://{payload.client_name}.dalgo.org",
            "admin_username": module_settings.SUPERSET_ADMIN_USERNAME,
            "admin_password": admin_password
        }
        
        logger.info(f"Passing credentials to task: {credentials}")
        
        # Start the Celery task with the run_terraform_commands function,
        # passing replacements to create a task-specific tfvars file
        task = run_terraform_commands.apply_async(
            args=[terraform_path, credentials, replacements],
            queue='terraform'
        )
        
        logger.info(f"Task started with ID: {task.id}")
        
        # Create a response using the task ID as id
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
    
    # Initialize result and error
    result_data = {}
    error = None
    
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
                
                # Check if the result contains an error field
                if result.get('error'):
                    error = result.get('error')
                    logger.error(f"Error found in result: {error}")
                    # Override terraform_status to ERROR if there's an error, regardless of celery status
                    terraform_status = TerraformStatus.ERROR
                # Check if result has explicit status field
                elif result.get('status') == 'error':
                    error = result.get('error')
                    logger.error(f"Error status found in result: {error}")
                    # Override terraform_status to ERROR
                    terraform_status = TerraformStatus.ERROR
                # If status is successful and there's no error, extract outputs and credentials for the result
                elif terraform_status == TerraformStatus.SUCCESS:
                    # Include outputs and credentials in the result
                    if result.get('outputs'):
                        result_data['outputs'] = result.get('outputs')
                    if result.get('credentials'):
                        result_data['credentials'] = result.get('credentials')
                    logger.info(f"Job successful, including data in result field")
        except Exception as e:
            logger.exception(f"Error extracting task result: {e}")
            error = str(e)
            terraform_status = TerraformStatus.ERROR
    
    # Set the error message if task failed but we don't have a specific error yet
    if task_result.status == FAILURE and not error:
        try:
            error = str(task_result.result) if task_result.result else "Task failed"
        except Exception as e:
            error = f"Task failed with inaccessible result: {str(e)}"
        logger.error(f"Task failed: {error}")
    
    # Create status response using id in the response but taking task_id as the source
    response = TerraformJobStatusResponse(
        id=task_id,
        status=terraform_status,
        result=result_data if result_data else None,
        error=error
    )
    
    logger.info(f"Returning response with status: {response.status}, error: {error is not None}, result present: {response.result is not None}")
    
    return response 