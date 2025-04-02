import os
import subprocess
import json
import shutil
from typing import Dict, Any
from celery import Task
from celery.utils.log import get_task_logger
from app.core.celery_app import celery_app
from app.core.config import settings
import time
import re
from datetime import datetime, timezone

logger = get_task_logger(__name__)

class TerraformTask(Task):
    """Base task for Terraform operations"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure by updating job status"""
        logger.error(f"Terraform task {task_id} failed: {exc}")
        # Clean up task-specific tfvars file
        try:
            settings.cleanup_task_tfvars(task_id)
        except Exception as e:
            logger.error(f"Failed to clean up task tfvars: {e}")
        super().on_failure(exc, task_id, args, kwargs, einfo)
    
    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success by cleaning up resources"""
        try:
            settings.cleanup_task_tfvars(task_id)
        except Exception as e:
            logger.error(f"Failed to clean up task tfvars: {e}")
        return super().on_success(retval, task_id, args, kwargs)

@celery_app.task(bind=True, base=TerraformTask)
def run_terraform_commands(self, terraform_path: str, credentials: Dict[str, str] = None, replacements: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Run a sequence of terraform commands (init, plan, apply) with proper error handling
    
    If init or plan fails, stops and returns error
    If apply fails, attempts to run terraform destroy and returns error
    
    Args:
        terraform_path: Path to the terraform module directory
        credentials: Credentials to include in the response (for DB access, etc.)
        replacements: Dictionary of key-value pairs to replace in the tfvars file
    """
    task_id = self.request.id
    logger.info(f"Starting Terraform command sequence job {task_id}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Received credentials: {credentials}")
    logger.info(f"Received replacements: {replacements}")
    
    # Update task state to STARTED (running)
    self.update_state(state='STARTED', meta={'status': 'running'})
    
    # Verify terraform_path exists or use fallback from settings
    if not os.path.exists(terraform_path):
        logger.warning(f"Path does not exist: {terraform_path}")
        # Check if this is for warehouse or superset based on the path
        if "createWarehouse" in terraform_path or "warehouse" in terraform_path.lower():
            terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE
        else:
            terraform_path = settings.TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET
        logger.info(f"Using fallback path from settings: {terraform_path}")
    
    # Determine module type for task-specific file naming
    if "createWarehouse" in terraform_path or "warehouse" in terraform_path.lower():
        module_type = "warehouse"
    else:
        module_type = "superset"
    
    main_tf_path = os.path.join(terraform_path, "main.tf")
    original_tfvars_path = os.path.join(terraform_path, "terraform.tfvars")
    
    logger.info(f"Looking for Terraform files at: {terraform_path}")
    logger.info(f"Main.tf path: {main_tf_path}")
    logger.info(f"Original terraform.tfvars path: {original_tfvars_path}")
    logger.info(f"Directory exists: {os.path.exists(terraform_path)}")
    logger.info(f"Main.tf exists: {os.path.exists(main_tf_path)}")
    logger.info(f"terraform.tfvars exists: {os.path.exists(original_tfvars_path)}")
    
    # Path for task-specific tfvars file
    task_tfvars_path = None
    
    try:
        if not os.path.exists(terraform_path):
            error_msg = f"Terraform script path not found: {terraform_path}"
            logger.error(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": credentials
            }
        
        if not os.path.exists(main_tf_path):
            error_msg = f"main.tf not found at: {main_tf_path}"
            logger.error(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": credentials
            }
            
        # Load module settings to get SSH key path
        module_settings = settings.get_terraform_module_settings(terraform_path)
        logger.info(f"Loaded module settings: RDS Instance Name: {module_settings.RDS_INSTANCE_NAME}")
        logger.info(f"SSH Key Path from module settings: {module_settings.SSH_KEY_PATH}")
        
        # Check if SSH key exists
        if not os.path.exists(module_settings.SSH_KEY_PATH):
            logger.error(f"SSH key not found at: {module_settings.SSH_KEY_PATH}")
            error_msg = f"Terraform apply would fail: SSH key not found at {module_settings.SSH_KEY_PATH}"
            
            # We'll continue with execution but log the warning
            logger.warning("Continuing with execution despite missing SSH key, expect terraform to fail")
        
        # Create task-specific tfvars file
        task_tfvars_path = settings.create_task_specific_tfvars(
            terraform_path, 
            task_id, 
            replacements
        )
        logger.info(f"Created task-specific tfvars file at: {task_tfvars_path}")
        
        # Ensure task_tfvars_path is an absolute path
        if not os.path.isabs(task_tfvars_path):
            task_tfvars_path = os.path.abspath(task_tfvars_path)
            logger.info(f"Using absolute path for tfvars file: {task_tfvars_path}")
            
        # Verify that the task-specific tfvars file exists
        if not os.path.exists(task_tfvars_path):
            error_msg = f"Task-specific tfvars file not found at: {task_tfvars_path}"
            logger.error(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": credentials
            }
        
        # Change to terraform directory
        os.chdir(terraform_path)
        
        # 1. Clean up any existing locks
        logger.info("Checking for and cleaning up any existing state locks...")
        try:
            state_list_process = subprocess.run(
                ["terraform", "state", "list"],
                capture_output=True,
                text=True,
                check=False
            )
            if "lock" in state_list_process.stderr.lower():
                lock_id_match = re.search(r'Lock Info:\s+ID:\s+([a-f0-9\-]+)', state_list_process.stderr)
                if lock_id_match:
                    lock_id = lock_id_match.group(1)
                    logger.info(f"Found lock with ID: {lock_id}, attempting to force-unlock")
                    subprocess.run(
                        ["terraform", "force-unlock", "-force", lock_id],
                        capture_output=True,
                        check=False
                    )
                    logger.info("Force-unlock completed")
        except Exception as e:
            logger.warning(f"Error during force-unlock attempt (non-critical): {str(e)}")
        
        # 2. Run terraform init
        logger.info(f"Initializing Terraform in {terraform_path}")
        init_process = subprocess.run(
            ["terraform", "init"],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Check if we have a lock issue with init
        if init_process.returncode != 0 and "lock" in init_process.stderr.lower():
            logger.warning("Terraform init failed due to lock issue, retrying with -lock=false")
            init_process = subprocess.run(
                ["terraform", "init", "-lock=false"],
                capture_output=True,
                text=True,
                check=False
            )
        
        # If init failed, return error
        if init_process.returncode != 0:
            error_msg = f"Terraform init failed: {init_process.stderr}"
            logger.error(error_msg)
            return {
                "status": "error",
                "phase": "init",
                "error": error_msg,
                "stderr": init_process.stderr,
                "init_output": init_process.stdout,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": credentials
            }
        
        # 3. Run terraform plan with task-specific var file
        logger.info(f"Running terraform plan with task-specific var file: {task_tfvars_path}")
        plan_process = subprocess.run(
            ["terraform", "plan", f"-var-file={task_tfvars_path}"],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Check if we have a lock issue with plan
        if plan_process.returncode != 0 and "lock" in plan_process.stderr.lower():
            logger.warning("Terraform plan failed due to lock issue, retrying with -lock=false")
            plan_process = subprocess.run(
                ["terraform", "plan", f"-var-file={task_tfvars_path}", "-lock=false"],
                capture_output=True,
                text=True,
                check=False
            )
        
        # If plan failed, return error
        if plan_process.returncode != 0:
            error_msg = f"Terraform plan failed: {plan_process.stderr}"
            logger.error(error_msg)
            return {
                "status": "error",
                "phase": "plan",
                "error": error_msg,
                "stderr": plan_process.stderr,
                "init_output": init_process.stdout,
                "plan_output": plan_process.stdout,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": credentials
            }
        
        # 4. Run terraform apply with task-specific var file
        logger.info(f"Running terraform apply with task-specific var file: {task_tfvars_path}")
        apply_process = subprocess.run(
            ["terraform", "apply", "-auto-approve", f"-var-file={task_tfvars_path}"],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Check if we have a lock issue with apply
        if apply_process.returncode != 0 and "lock" in apply_process.stderr.lower():
            logger.warning("Terraform apply failed due to lock issue, retrying with -lock=false")
            apply_process = subprocess.run(
                ["terraform", "apply", "-auto-approve", f"-var-file={task_tfvars_path}", "-lock=false"],
                capture_output=True,
                text=True,
                check=False
            )
        
        # If apply failed, try to run terraform destroy and return error
        if apply_process.returncode != 0:
            error_msg = f"Terraform apply failed: {apply_process.stderr}"
            logger.error(error_msg)
            
            # Attempt to destroy resources to avoid dangling infrastructure
            logger.info("Apply failed, attempting to run terraform destroy for cleanup")
            destroy_process = subprocess.run(
                ["terraform", "destroy", "-auto-approve", f"-var-file={task_tfvars_path}"],
                capture_output=True,
                text=True,
                check=False
            )
            
            destroy_output = "Destroy not attempted"
            destroy_status = "not_attempted"
            
            if destroy_process.returncode == 0:
                destroy_output = destroy_process.stdout
                destroy_status = "success"
            else:
                destroy_output = f"Destroy failed: {destroy_process.stderr}"
                destroy_status = "failed"
            
            # For demonstration, we'll simulate success with credentials even though there was an error
            # In a production environment, you would handle this differently
            if credentials:
                logger.info("Returning credentials for users despite error, but setting status to error")
                return {
                    "status": "error",
                    "init_output": init_process.stdout,
                    "plan_output": plan_process.stdout,
                    "apply_output": "Error: " + error_msg,
                    "outputs": {},
                    "error": error_msg,
                    "credentials": credentials,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }
            else:
                return {
                    "status": "error",
                    "phase": "apply",
                    "error": error_msg,
                    "stderr": apply_process.stderr,
                    "init_output": init_process.stdout,
                    "plan_output": plan_process.stdout,
                    "apply_output": apply_process.stdout,
                    "destroy_output": destroy_output,
                    "destroy_status": destroy_status,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "credentials": credentials
                }
        
        # 5. Get outputs if apply succeeded
        try:
            output_process = subprocess.run(
                ["terraform", "output", "-json"],
                capture_output=True,
                text=True,
                check=False
            )
            outputs = json.loads(output_process.stdout) if output_process.stdout.strip() else {}
            logger.info(f"Terraform outputs: {outputs}")
        except Exception as e:
            logger.warning(f"Failed to get structured outputs: {e}")
            outputs = {}
        
        # Log the final result before returning
        logger.info(f"Terraform job completed successfully, credentials: {credentials}")
        result = {
            "status": "success",
            "init_output": init_process.stdout,
            "plan_output": plan_process.stdout,
            "apply_output": apply_process.stdout,
            "outputs": outputs,
            "credentials": credentials,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"Returning result with credentials: {result['credentials'] is not None}")
        return result
        
    except Exception as e:
        error_msg = f"Unexpected error during Terraform execution: {str(e)}"
        logger.exception(error_msg)
        return {
            "status": "error",
            "error": error_msg,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "credentials": credentials
        }
    finally:
        # Clean up task-specific tfvars file if needed
        # We leave the cleanup to the on_success/on_failure handlers
        pass