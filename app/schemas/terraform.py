from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TerraformStatus(str, Enum):
    """Status of a Terraform operation"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class TerraformResponse(BaseModel):
    """Response model for Terraform operations"""
    job_id: str
    status: TerraformStatus
    message: str
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TerraformJobStatusResponse(BaseModel):
    """Response model for job status query"""
    job_id: str
    status: TerraformStatus
    message: str
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    outputs: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None


class TerraformResult(BaseModel):
    """Detailed result of a terraform operation"""
    job_id: str
    status: TerraformStatus
    init_output: Optional[str] = None
    apply_output: Optional[str] = None
    error: Optional[str] = None
    stderr: Optional[str] = None
    outputs: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    task_id: Optional[str] = None 