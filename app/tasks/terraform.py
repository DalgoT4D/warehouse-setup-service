import os
import subprocess
import json
from typing import Dict, Any
from celery import Task
from celery.utils.log import get_task_logger
from app.core.celery_app import celery_app
from app.core.config import settings
from app.services.terraform_job_store import TerraformJobStore
import time
import re

logger = get_task_logger(__name__)

# Initialize the job store with Redis URL from settings
job_store = TerraformJobStore(CELERY_BROKER_URL=settings.CELERY_BROKER_URL)

class TerraformTask(Task):
    """Base task for Terraform operations"""
    def __init__(self):
        super().__init__()
        # Use the global job store instance
        self.job_store = job_store
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure by updating job status"""
        job_id = args[0] if args else None
        if job_id:
            try:
                self.job_store.set_job_error(job_id, str(exc))
            except Exception as e:
                logger.error(f"Failed to update job status: {e}")
        logger.error(f"Terraform task {task_id} failed: {exc}")
        super().on_failure(exc, task_id, args, kwargs, einfo)

@celery_app.task(bind=True, base=TerraformTask)
def run_terraform_apply(self, job_id: str) -> Dict[str, Any]:
    """
    Run terraform apply in the specified directory
    """
    logger.info(f"Starting Terraform apply job {job_id}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Environment variable from settings: {settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE}")
    
    # Verify job exists first
    if not job_store.get_job(job_id):
        error_msg = f"Job {job_id} not found in Redis"
        logger.error(error_msg)
        job_store.set_job_error(job_id, error_msg)
        return {"status": "error", "error": error_msg}
    
    # Update job status to running
    job_store.set_job_running(job_id)
    
    # Use a hardcoded absolute path as a fallback
    terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
    
    # If the path from settings doesn't exist, try a hardcoded absolute path
    if not os.path.exists(terraform_path):
        logger.warning(f"Path from settings doesn't exist: {terraform_path}")
        # Hardcode the absolute path as a fallback
        terraform_path = "/Users/himanshut4d/Documents/Tech4Dev/Dalgo/warehouse_setup/app/terraform_files/createWarehouse"
        logger.info(f"Using fallback path: {terraform_path}")
    
    return _run_terraform_commands(job_id, terraform_path)

@celery_app.task(bind=True, base=TerraformTask)
def run_terraform_apply_superset(self, job_id: str) -> Dict[str, Any]:
    """
    Run terraform apply for Superset in the specified directory
    """
    logger.info(f"Starting Superset Terraform apply job {job_id}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Environment variable from settings: {settings.TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET}")
    
    # Verify job exists first
    if not job_store.get_job(job_id):
        error_msg = f"Job {job_id} not found in Redis"
        logger.error(error_msg)
        job_store.set_job_error(job_id, error_msg)
        return {"status": "error", "error": error_msg}
    
    # Update job status to running
    job_store.set_job_running(job_id)
    
    # Use a hardcoded absolute path as a fallback
    terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET
    
    # If the path from settings doesn't exist, try a hardcoded absolute path
    if not os.path.exists(terraform_path):
        logger.warning(f"Path from settings doesn't exist: {terraform_path}")
        # Hardcode the absolute path as a fallback
        terraform_path = "/Users/himanshut4d/Documents/Tech4Dev/Dalgo/warehouse_setup/app/terraform_files/createSuperset"
        logger.info(f"Using fallback path: {terraform_path}")
    
    return _run_terraform_commands(job_id, terraform_path)

def _run_terraform_commands(job_id: str, terraform_path: str) -> Dict[str, Any]:
    """
    Common function to run Terraform commands
    """
    main_tf_path = os.path.join(terraform_path, "main.tf")
    
    logger.info(f"Looking for Terraform files at: {terraform_path}")
    logger.info(f"Main.tf path: {main_tf_path}")
    logger.info(f"Directory exists: {os.path.exists(terraform_path)}")
    logger.info(f"File exists: {os.path.exists(main_tf_path)}")
    
    try:
        if not os.path.exists(terraform_path):
            error_msg = f"Terraform script path not found: {terraform_path}"
            logger.error(error_msg)
            job_store.set_job_error(job_id, error_msg)
            return {"status": "error", "error": error_msg}
        
        if not os.path.exists(main_tf_path):
            error_msg = f"main.tf not found at: {main_tf_path}"
            logger.error(error_msg)
            job_store.set_job_error(job_id, error_msg)
            return {"status": "error", "error": error_msg}
        
        os.chdir(terraform_path)
        
        # First, try to force-unlock any existing locks
        logger.info("Checking for and cleaning up any existing state locks...")
        try:
            # Run terraform force-unlock with wildcard to catch any lock IDs
            # Note: In a production environment, you might want to be more specific about which lock to remove
            # We're getting the lock ID first
            state_list_process = subprocess.run(
                ["terraform", "state", "list"],
                capture_output=True,
                text=True,
                check=False
            )
            # If there's an error that mentions a lock, try to extract the lock ID
            if "lock" in state_list_process.stderr.lower():
                lock_id_match = re.search(r'Lock Info:\s+ID:\s+([a-f0-9\-]+)', state_list_process.stderr)
                if lock_id_match:
                    lock_id = lock_id_match.group(1)
                    logger.info(f"Found lock with ID: {lock_id}, attempting to force-unlock")
                    # Force-unlock with the specific lock ID
                    subprocess.run(
                        ["terraform", "force-unlock", "-force", lock_id],
                        capture_output=True,
                        check=False
                    )
                    logger.info("Force-unlock completed")
        except Exception as e:
            logger.warning(f"Error during force-unlock attempt (non-critical): {str(e)}")
        
        # Initialize Terraform
        logger.info(f"Initializing Terraform in {terraform_path}")
        init_process = subprocess.run(
            ["terraform", "init"],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Check if we have a lock issue
        if init_process.returncode != 0 and "lock" in init_process.stderr.lower():
            logger.warning("Terraform init failed due to lock issue, retrying with -lock=false")
            init_process = subprocess.run(
                ["terraform", "init", "-lock=false"],
                capture_output=True,
                text=True,
                check=False
            )
        
        if init_process.returncode != 0:
            error_msg = f"Terraform init failed: {init_process.stderr}"
            logger.error(error_msg)
            job_store.set_job_error(job_id, error_msg, init_process.stderr)
            return {"status": "error", "error": error_msg}

        # Run terraform apply
        logger.info("Running terraform apply")
        apply_process = subprocess.run(
            ["terraform", "apply", "-auto-approve"],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Check if we have a lock issue
        if apply_process.returncode != 0 and "lock" in apply_process.stderr.lower():
            logger.warning("Terraform apply failed due to lock issue, retrying with -lock=false")
            apply_process = subprocess.run(
                ["terraform", "apply", "-auto-approve", "-lock=false"],
                capture_output=True,
                text=True,
                check=False
            )
        
        if apply_process.returncode != 0:
            error_msg = f"Terraform apply failed: {apply_process.stderr}"
            logger.error(error_msg)
            job_store.set_job_error(job_id, error_msg)
            return {"status": "error", "error": error_msg}

        try:
            output_process = subprocess.run(
                ["terraform", "output", "-json"],
                capture_output=True,
                text=True,
                check=False
            )
            outputs = json.loads(output_process.stdout) if output_process.stdout.strip() else {}
        except Exception as e:
            logger.warning(f"Failed to get structured outputs: {e}")
            outputs = {}

        job_store.set_job_success(
            job_id,
            init_process.stdout,
            apply_process.stdout,
            outputs
        )
        
        return {
            "status": "success",
            "job_id": job_id,
            "outputs": outputs
        }
        
    except Exception as e:
        error_msg = f"Unexpected error during Terraform execution: {str(e)}"
        logger.exception(error_msg)
        job_store.set_job_error(job_id, error_msg)
        return {
            "status": "error",
            "job_id": job_id,
            "error": error_msg
        }