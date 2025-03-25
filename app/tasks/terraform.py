import os
import subprocess
import json
from typing import Dict, Any, Optional

from celery import Task
from celery.utils.log import get_task_logger

from app.core.celery_app import celery_app
from app.core.config import settings
from app.services.terraform_job_store import TerraformJobStore

logger = get_task_logger(__name__)


class TerraformTask(Task):
    """Base task for Terraform operations"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure by updating job status"""
        job_id = args[0] if args else None
        if job_id:
            # Update job status on failure
            TerraformJobStore.set_job_error(job_id, str(exc))
        logger.error(f"Terraform task {task_id} failed: {exc}")
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(bind=True, base=TerraformTask)
def run_terraform_apply(self, job_id: str) -> Dict[str, Any]:
    """
    Run terraform apply in the specified directory
    
    Args:
        job_id: The ID of the job to update with results
        
    Returns:
        Dict containing the job status and results
    """
    logger.info(f"Starting Terraform apply job {job_id}")
    
    # Update job status to running
    TerraformJobStore.set_job_running(job_id)
    
    # Path to Terraform scripts
    terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
    
    try:
        # Check if the script path exists
        if not os.path.exists(terraform_path):
            error_msg = f"Terraform script path not found: {terraform_path}"
            logger.error(error_msg)
            TerraformJobStore.set_job_error(job_id, error_msg)
            return {"status": "error", "error": error_msg}
        
        # Change to the terraform directory
        os.chdir(terraform_path)
        
        # Initialize terraform
        logger.info(f"Initializing Terraform in {terraform_path}")
        init_process = subprocess.run(
            ["terraform", "init"],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Run terraform apply with auto-approve
        logger.info("Running terraform apply")
        apply_process = subprocess.run(
            ["terraform", "apply", "-auto-approve"],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Extract outputs from terraform output
        outputs = TerraformJobStore.extract_terraform_outputs(apply_process.stdout)
        logger.info(f"Terraform apply completed with outputs: {outputs}")
        
        # Run terraform output in JSON format to get structured outputs
        try:
            output_process = subprocess.run(
                ["terraform", "output", "-json"],
                capture_output=True,
                text=True,
                check=True
            )
            if output_process.stdout.strip():
                structured_outputs = json.loads(output_process.stdout)
                # Extract actual values from the output structure
                outputs = {
                    key: value.get("value") 
                    for key, value in structured_outputs.items()
                }
                logger.info(f"Parsed structured outputs: {outputs}")
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to get structured outputs: {e}")
            # Continue with the previously extracted outputs
        
        # Mark job as successful
        TerraformJobStore.set_job_success(
            job_id,
            init_process.stdout,
            apply_process.stdout,
            outputs
        )
        
        # Return the results
        return {
            "status": "success",
            "job_id": job_id,
            "outputs": outputs
        }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Terraform command failed: {str(e)}"
        logger.error(f"{error_msg}\nStderr: {e.stderr}")
        TerraformJobStore.set_job_error(job_id, error_msg, e.stderr)
        return {
            "status": "error",
            "job_id": job_id,
            "error": error_msg,
            "stderr": e.stderr
        }
        
    except Exception as e:
        error_msg = f"Unexpected error during Terraform execution: {str(e)}"
        logger.exception(error_msg)
        TerraformJobStore.set_job_error(job_id, error_msg)
        return {
            "status": "error",
            "job_id": job_id,
            "error": error_msg
        } 