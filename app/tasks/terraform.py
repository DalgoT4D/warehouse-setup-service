import os
import subprocess
import json
import shutil
from typing import Dict, Any, Tuple
from celery import Task
from celery.utils.log import get_task_logger
from app.core.celery_app import celery_app
from app.core.config import settings
import time
import re
import sys
from datetime import datetime, timezone
import urllib.parse

# Use the celery task logger which is already properly configured
logger = get_task_logger(__name__)

def run_with_live_output(cmd: list, log_prefix: str = "") -> Tuple[int, str, str]:
    """
    Run a command and stream its output to the logger in real-time.
    
    Args:
        cmd: The command to run as a list of strings
        log_prefix: Optional prefix for log messages
        
    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    logger.info(f"{log_prefix} Running command: {' '.join(cmd)}")
    
    # Start the process without capturing output to allow real-time display
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line buffered
    )
    
    # Collect stdout and stderr for returning later
    stdout_lines = []
    stderr_lines = []
    
    # Helper function to read and log output in real-time
    def process_stream(stream, is_error=False, prefix=""):
        collected_lines = stderr_lines if is_error else stdout_lines
        for line in iter(stream.readline, ''):
            if not line:
                break
            line = line.rstrip()
            collected_lines.append(line)
            # Ensure every line is logged with proper level for visibility
            if is_error:
                logger.error(f"{prefix} {line}")
                # Also print to stderr for direct console visibility
                print(f"{prefix} {line}", file=sys.stderr, flush=True)
            else:
                logger.info(f"{prefix} {line}")
                # Also print to stdout for direct console visibility
                print(f"{prefix} {line}", file=sys.stdout, flush=True)
    
    # Process stdout and stderr concurrently
    import threading
    stdout_thread = threading.Thread(
        target=process_stream, 
        args=(process.stdout, False, f"{log_prefix} [STDOUT]")
    )
    stderr_thread = threading.Thread(
        target=process_stream, 
        args=(process.stderr, True, f"{log_prefix} [STDERR]")
    )
    
    stdout_thread.start()
    stderr_thread.start()
    
    # Wait for both streams to be processed
    stdout_thread.join()
    stderr_thread.join()
    
    # Wait for the process to finish and get its return code
    return_code = process.wait()
    
    # Join collected lines into strings
    stdout_str = "\n".join(stdout_lines)
    stderr_str = "\n".join(stderr_lines)
    
    logger.info(f"{log_prefix} Command completed with return code: {return_code}")
    
    return return_code, stdout_str, stderr_str

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
    
    # Ensure the temp_task_configs directory exists
    abs_task_configs_path = os.path.abspath(settings.TERRAFORM_TASK_CONFIGS_PATH) if not os.path.isabs(settings.TERRAFORM_TASK_CONFIGS_PATH) else settings.TERRAFORM_TASK_CONFIGS_PATH
    
    if not os.path.exists(abs_task_configs_path):
        logger.info(f"Creating temp_task_configs directory at: {abs_task_configs_path}")
        os.makedirs(abs_task_configs_path, exist_ok=True)
    else:
        logger.info(f"temp_task_configs directory already exists at: {abs_task_configs_path}")
    
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
    
    # Make sure terraform_path is absolute
    terraform_path = os.path.abspath(terraform_path) if not os.path.isabs(terraform_path) else terraform_path
    
    # Determine module type for task-specific file naming
    # Extract just the directory name for more reliable detection
    module_dir_name = os.path.basename(terraform_path)
    
    # Determine module type based solely on the directory name, not the full path
    # to avoid issues with the word "warehouse" appearing in higher level directories
    if "createSuperset" in module_dir_name or "superset" in module_dir_name.lower():
        module_type = "superset"
        logger.info(f"Detected superset module type from directory name: {module_dir_name}")
    elif "createWarehouse" in module_dir_name or "warehouse" in module_dir_name.lower():
        module_type = "warehouse"
        logger.info(f"Detected warehouse module type from directory name: {module_dir_name}")
    else:
        # If we can't determine from the directory name, check the full path
        # but prioritize superset detection to avoid false matches with warehouse
        if "createSuperset" in terraform_path or "superset" in terraform_path.lower():
            module_type = "superset"
            logger.info(f"Detected superset module type from full path: {terraform_path}")
        elif "createWarehouse" in terraform_path or "warehouse" in terraform_path.lower():
            module_type = "warehouse"
            logger.info(f"Detected warehouse module type from full path: {terraform_path}")
        else:
            # Default to superset if no clear indicator
            module_type = "superset"
            logger.warning(f"Could not determine module type, defaulting to 'superset'")
    
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
                "credentials": None
            }
        
        if not os.path.exists(main_tf_path):
            error_msg = f"main.tf not found at: {main_tf_path}"
            logger.error(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": None
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
                "credentials": None
            }
        
        # Change to terraform directory
        os.chdir(terraform_path)
        
        # 1. Clean up any existing locks
        logger.info("Checking for and cleaning up any existing state locks...")
        try:
            returncode, stdout, stderr = run_with_live_output(
                ["terraform", "state", "list"],
                "STATE LIST"
            )
            
            if "lock" in stderr.lower():
                lock_id_match = re.search(r'Lock Info:\s+ID:\s+([a-f0-9\-]+)', stderr)
                if lock_id_match:
                    lock_id = lock_id_match.group(1)
                    logger.info(f"Found lock with ID: {lock_id}, attempting to force-unlock")
                    run_with_live_output(
                        ["terraform", "force-unlock", "-force", lock_id],
                        "FORCE UNLOCK"
                    )
                    logger.info("Force-unlock completed")
        except Exception as e:
            logger.warning(f"Error during force-unlock attempt (non-critical): {str(e)}")
        
        # 2. Run terraform init
        logger.info(f"Initializing Terraform in {terraform_path}")
        returncode, init_stdout, init_stderr = run_with_live_output(
            ["terraform", "init"],
            "INIT"
        )
        
        # Check if we have a lock issue with init
        if returncode != 0 and "lock" in init_stderr.lower():
            logger.warning("Terraform init failed due to lock issue, retrying with -lock=false")
            returncode, init_stdout, init_stderr = run_with_live_output(
                ["terraform", "init", "-lock=false"],
                "INIT RETRY"
            )
        
        # If init failed, return error
        if returncode != 0:
            error_msg = f"Terraform init failed: {init_stderr}"
            logger.error(error_msg)
            return {
                "status": "error",
                "phase": "init",
                "error": error_msg,
                "stderr": init_stderr,
                "init_output": init_stdout,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": None  # Do not include credentials on error
            }
        
        # 3. Run terraform plan with task-specific var file
        logger.info(f"Running terraform plan with task-specific var file: {task_tfvars_path}")
        returncode, plan_stdout, plan_stderr = run_with_live_output(
            ["terraform", "plan", f"-var-file={task_tfvars_path}"],
            "PLAN"
        )
        
        # Check if we have a lock issue with plan
        if returncode != 0 and "lock" in plan_stderr.lower():
            logger.warning("Terraform plan failed due to lock issue, retrying with -lock=false")
            returncode, plan_stdout, plan_stderr = run_with_live_output(
                ["terraform", "plan", f"-var-file={task_tfvars_path}", "-lock=false"],
                "PLAN RETRY"
            )
        
        # If plan failed, return error
        if returncode != 0:
            error_msg = f"Terraform plan failed: {plan_stderr}"
            logger.error(error_msg)
            logger.info("Stopping execution due to failed terraform plan")
            return {
                "status": "error",
                "phase": "plan",
                "error": error_msg,
                "stderr": plan_stderr,
                "init_output": init_stdout,
                "plan_output": plan_stdout,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": None  # Do not include credentials on error
            }
        
        # 4. Run terraform apply with task-specific var file
        logger.info(f"Running terraform apply with task-specific var file: {task_tfvars_path}")
        returncode, apply_stdout, apply_stderr = run_with_live_output(
            ["terraform", "apply", "-auto-approve", f"-var-file={task_tfvars_path}"],
            "APPLY"
        )
        
        # Check if we have a lock issue with apply
        if returncode != 0 and "lock" in apply_stderr.lower():
            logger.warning("Terraform apply failed due to lock issue, retrying with -lock=false")
            returncode, apply_stdout, apply_stderr = run_with_live_output(
                ["terraform", "apply", "-auto-approve", f"-var-file={task_tfvars_path}", "-lock=false"],
                "APPLY RETRY"
            )
        
        # If apply failed, try to run terraform destroy and return error
        if returncode != 0:
            error_msg = f"Terraform apply failed: {apply_stderr}"
            logger.error(error_msg)
            
            # Attempt to destroy resources to avoid dangling infrastructure
            logger.info("Apply failed, attempting to run terraform destroy for cleanup")
            destroy_returncode, destroy_stdout, destroy_stderr = run_with_live_output(
                ["terraform", "destroy", "-auto-approve", f"-var-file={task_tfvars_path}"],
                "DESTROY"
            )
            
            destroy_output = "Destroy not attempted"
            destroy_status = "not_attempted"
            
            if destroy_returncode == 0:
                destroy_output = destroy_stdout
                destroy_status = "success"
                logger.info("Successfully cleaned up resources with terraform destroy after failed apply")
            else:
                destroy_output = f"Destroy failed: {destroy_stderr}"
                destroy_status = "failed"
                logger.error(f"Failed to clean up resources: {destroy_stderr}")
            
            # Return error status and explicitly set credentials to None
            logger.info("Returning error status due to failed terraform apply, credentials will not be included")
            return {
                "status": "error",
                "phase": "apply",
                "error": error_msg,
                "stderr": apply_stderr,
                "init_output": init_stdout,
                "plan_output": plan_stdout,
                "apply_output": apply_stdout,
                "destroy_output": destroy_output,
                "destroy_status": destroy_status,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credentials": None  # Explicitly do not include credentials on error
            }
        
        # 5. Get outputs if apply succeeded
        try:
            returncode, output_stdout, output_stderr = run_with_live_output(
                ["terraform", "output", "-json"],
                "OUTPUT"
            )
            outputs = json.loads(output_stdout) if output_stdout.strip() else {}
            logger.info(f"Terraform outputs: {outputs}")
            
            # Check if the actual port was different from the requested port
            if 'actual_port' in outputs and outputs['actual_port'].get('value'):
                actual_port = outputs['actual_port'].get('value')
                port_changed = outputs.get('port_changed', {}).get('value', False)
                
                # Update credentials with the actual port and additional information
                if credentials and 'superset_url' in credentials:
                    # Add the port information to credentials
                    credentials['port'] = actual_port
                    
                    # Add information about whether the port was changed from the requested port
                    if port_changed:
                        credentials['port_changed'] = True
                        logger.info(f"Port was changed from the requested port to {actual_port}")
                    else:
                        credentials['port_changed'] = False
                        
                    # Add the actual priority if available
                    if 'actual_priority' in outputs and outputs['actual_priority'].get('value'):
                        credentials['priority'] = outputs['actual_priority'].get('value')
                        
                    logger.info(f"Updated credentials with port information: port={actual_port}, changed={port_changed}")
            
        except Exception as e:
            logger.warning(f"Failed to get structured outputs: {e}")
            outputs = {}
        
        # Log the final result before returning
        logger.info(f"Terraform job completed successfully, credentials: {credentials}")
        result = {
            "status": "success",
            "init_output": init_stdout,
            "plan_output": plan_stdout,
            "apply_output": apply_stdout,
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
            "credentials": None
        }
    finally:
        # Clean up task-specific tfvars file if needed
        # We leave the cleanup to the on_success/on_failure handlers
        pass