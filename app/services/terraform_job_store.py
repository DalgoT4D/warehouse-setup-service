import json
import re
import uuid
from datetime import datetime
from typing import Dict, Optional, Any, List

from app.schemas.terraform import TerraformStatus, TerraformResult, TerraformJobStatusResponse


class TerraformJobStore:
    """In-memory store for Terraform job results"""
    _jobs: Dict[str, TerraformResult] = {}
    
    @classmethod
    def create_job(cls) -> str:
        """Create a new job and return the job ID"""
        job_id = str(uuid.uuid4())
        cls._jobs[job_id] = TerraformResult(
            job_id=job_id,
            status=TerraformStatus.PENDING,
        )
        return job_id
    
    @classmethod
    def get_job(cls, job_id: str) -> Optional[TerraformResult]:
        """Get a job by ID"""
        return cls._jobs.get(job_id)
    
    @classmethod
    def update_job(cls, job_id: str, **kwargs) -> TerraformResult:
        """Update a job with the given attributes"""
        if job_id not in cls._jobs:
            raise ValueError(f"Job ID {job_id} not found")
        
        job = cls._jobs[job_id]
        
        # Update job with the provided attributes
        for key, value in kwargs.items():
            setattr(job, key, value)
        
        return job
    
    @classmethod
    def set_job_running(cls, job_id: str) -> TerraformResult:
        """Mark a job as running"""
        return cls.update_job(job_id, status=TerraformStatus.RUNNING)
    
    @classmethod
    def set_job_success(cls, job_id: str, init_output: str, apply_output: str, outputs: Dict[str, Any]) -> TerraformResult:
        """Mark a job as successful and store the outputs"""
        return cls.update_job(
            job_id,
            status=TerraformStatus.SUCCESS,
            init_output=init_output,
            apply_output=apply_output,
            outputs=outputs,
            completed_at=datetime.utcnow()
        )
    
    @classmethod
    def set_job_error(cls, job_id: str, error: str, stderr: Optional[str] = None) -> TerraformResult:
        """Mark a job as failed"""
        return cls.update_job(
            job_id,
            status=TerraformStatus.ERROR,
            error=error,
            stderr=stderr,
            completed_at=datetime.utcnow()
        )
    
    @classmethod
    def get_job_status(cls, job_id: str) -> Optional[TerraformJobStatusResponse]:
        """Get job status in a format suitable for API response"""
        job = cls.get_job(job_id)
        if not job:
            return None
        
        return TerraformJobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            message=cls._get_status_message(job),
            error=job.error,
            created_at=job.created_at,
            completed_at=job.completed_at,
            outputs=job.outputs,
            task_id=job.task_id
        )
    
    @classmethod
    def _get_status_message(cls, job: TerraformResult) -> str:
        """Generate a human-readable status message based on job status"""
        if job.status == TerraformStatus.PENDING:
            return "Terraform job is pending execution"
        elif job.status == TerraformStatus.RUNNING:
            return "Terraform job is currently running"
        elif job.status == TerraformStatus.SUCCESS:
            return "Terraform job completed successfully"
        elif job.status == TerraformStatus.ERROR:
            return f"Terraform job failed: {job.error}"
        return "Unknown job status"
    
    @staticmethod
    def extract_terraform_outputs(output: str) -> Dict[str, Any]:
        """Extract outputs from terraform apply output"""
        # Parse terraform output section
        outputs = {}
        
        # Find the outputs section in terraform output
        output_section = re.search(r'Outputs:(.*?)(?:\n\n|\Z)', output, re.DOTALL)
        if not output_section:
            return outputs
            
        output_lines = output_section.group(1).strip().split('\n')
        
        current_output = None
        for line in output_lines:
            line = line.strip()
            if not line:
                continue
                
            # Check if this is a new output
            output_match = re.match(r'^([a-zA-Z0-9_-]+) = (.*)$', line)
            if output_match:
                key = output_match.group(1)
                value = output_match.group(2)
                
                # Try to parse as JSON if possible
                try:
                    # Strip quotes from string if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    outputs[key] = value
                except json.JSONDecodeError:
                    outputs[key] = value
        
        return outputs 