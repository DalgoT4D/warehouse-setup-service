from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class TerraformStatus(str, Enum):
    """Status of a Terraform operation"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class TerraformResponse(BaseModel):
    """Response model for Terraform operations"""
    task_id: str


class TerraformJobStatusResponse(BaseModel):
    """Response model for job status query"""
    id: str
    status: TerraformStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TerraformResult(BaseModel):
    """Detailed result of a terraform operation"""
    id: str
    status: TerraformStatus
    init_output: Optional[str] = None
    apply_output: Optional[str] = None
    error: Optional[str] = None
    stderr: Optional[str] = None
    outputs: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    credentials: Optional[Dict[str, str]] = None 