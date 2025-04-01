import json
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Any

import redis
from redis.connection import ConnectionPool
from app.schemas.terraform import TerraformStatus, TerraformResult, TerraformJobStatusResponse


class TerraformJobStore:
    """Redis-backed store for Terraform job results"""
    
    _pool = None
    
    def __init__(self, CELERY_BROKER_URL: str = 'redis://localhost:6379/0'):
        """
        Initialize Redis connection
        
        Args:
            CELERY_BROKER_URL (str): Redis connection URL
        """
        if TerraformJobStore._pool is None:
            TerraformJobStore._pool = ConnectionPool.from_url(
                CELERY_BROKER_URL,
                decode_responses=True,
                max_connections=10
            )
        self._redis = redis.Redis(connection_pool=TerraformJobStore._pool)
    
    def __del__(self):
        """Cleanup Redis connection"""
        if self._redis:
            self._redis.close()
    
    def create_job(self) -> str:
        """Create a new job and return the job ID"""
        job_id = str(uuid.uuid4())
        
        # Create initial job data
        job_data = {
            'job_id': job_id,
            'status': TerraformStatus.PENDING.value,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Store job data in Redis with expiration (24 hours)
        self._redis.hmset(f'job:{job_id}', job_data)
        self._redis.expire(f'job:{job_id}', 24 * 60 * 60)  # 24 hours
        
        return job_id
    
    def get_job(self, job_id: str) -> Optional[TerraformResult]:
        """Get a job by ID"""
        job_data = self._redis.hgetall(f'job:{job_id}')
        
        if not job_data:
            return None
        
        # Convert timestamps back to datetime objects
        if 'created_at' in job_data:
            job_data['created_at'] = datetime.fromisoformat(job_data['created_at']).replace(tzinfo=timezone.utc)
        if 'completed_at' in job_data:
            job_data['completed_at'] = datetime.fromisoformat(job_data['completed_at']).replace(tzinfo=timezone.utc)
        
        # Parse outputs if exists
        if 'outputs' in job_data:
            try:
                job_data['outputs'] = json.loads(job_data['outputs'])
            except json.JSONDecodeError:
                job_data['outputs'] = {}
        
        # Parse credentials if exists
        if 'credentials' in job_data:
            try:
                job_data['credentials'] = json.loads(job_data['credentials'])
            except json.JSONDecodeError:
                job_data['credentials'] = {}
        
        # Ensure status is a valid enum value
        if 'status' in job_data:
            status_value = job_data['status']
            # If it's already a valid enum value, use it directly
            if status_value in TerraformStatus._value2member_map_:
                job_data['status'] = TerraformStatus(status_value)
            else:
                # Default to ERROR if invalid status
                job_data['status'] = TerraformStatus.ERROR
        
        return TerraformResult(**job_data)
    
    def update_job(self, job_id: str, **kwargs) -> TerraformResult:
        """Update a job with the given attributes"""
        if not self._redis.exists(f'job:{job_id}'):
            raise ValueError(f"Job ID {job_id} not found")
        
        update_data = {}
        
        for key, value in kwargs.items():
            if value is None:
                continue  # Skip None values
                
            if isinstance(value, datetime):
                update_data[key] = value.astimezone(timezone.utc).isoformat()
            elif key == 'outputs':
                update_data[key] = json.dumps(value)
            elif key == 'status':
                # Handle both enum and string values
                if isinstance(value, TerraformStatus):
                    update_data[key] = value.value
                else:
                    update_data[key] = str(value)
            else:
                update_data[key] = str(value)  # Convert all values to strings
        
        if update_data:  # Only update if we have data
            self._redis.hmset(f'job:{job_id}', update_data)
        return self.get_job(job_id)
    
    def set_job_running(self, job_id: str) -> TerraformResult:
        """Mark a job as running"""
        return self.update_job(job_id, status=TerraformStatus.RUNNING.value)
    
    def set_job_success(self, job_id: str, init_output: str, apply_output: str, outputs: Dict[str, Any]) -> TerraformResult:
        """Mark a job as successful and store the outputs"""
        return self.update_job(
            job_id,
            status=TerraformStatus.SUCCESS.value,
            init_output=init_output,
            apply_output=apply_output,
            outputs=outputs,
            completed_at=datetime.now(timezone.utc)
        )
    
    def set_job_error(self, job_id: str, error: str, stderr: Optional[str] = None) -> TerraformResult:
        """Mark a job as failed"""
        update_data = {
            'status': TerraformStatus.ERROR.value,
            'error': error,
            'completed_at': datetime.now(timezone.utc)
        }
        
        if stderr:
            update_data['stderr'] = stderr
            
        return self.update_job(job_id, **update_data)
    
    def get_job_status(self, job_id: str) -> Optional[TerraformJobStatusResponse]:
        """Get job status in a format suitable for API response"""
        job = self.get_job(job_id)
        if not job:
            return None
        
        response = TerraformJobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            message=self._get_status_message(job),
            error=job.error,
            created_at=job.created_at,
            completed_at=job.completed_at,
            outputs=job.outputs,
            task_id=job.task_id
        )
        
        # Only include credentials if the job completed successfully
        if job.status == TerraformStatus.SUCCESS and job.credentials:
            response.credentials = job.credentials
        
        return response
    
    def _get_status_message(self, job: TerraformResult) -> str:
        """Generate a human-readable status message"""
        if job.status == TerraformStatus.PENDING:
            return "Terraform job is pending execution"
        elif job.status == TerraformStatus.RUNNING:
            return "Terraform job is currently running"
        elif job.status == TerraformStatus.SUCCESS:
            return "Terraform job completed successfully"
        elif job.status == TerraformStatus.ERROR:
            return f"Terraform job failed: {job.error}"
        return "Unknown job status"
    
    def store_job_credentials(self, job_id: str, credentials: Dict[str, str]) -> bool:
        """Store credentials for a job"""
        if not credentials or not isinstance(credentials, dict):
            return False
        
        if not self._redis.exists(f'job:{job_id}'):
            return False
        
        # Store credentials as a JSON string
        credentials_json = json.dumps(credentials)
        self._redis.hset(f'job:{job_id}', 'credentials', credentials_json)
        return True
    
    def get_job_credentials(self, job_id: str) -> Optional[Dict[str, str]]:
        """Retrieve credentials for a completed job"""
        credentials_json = self._redis.hget(f'job:{job_id}', 'credentials')
        if not credentials_json:
            return None
        
        try:
            return json.loads(credentials_json)
        except json.JSONDecodeError:
            return None