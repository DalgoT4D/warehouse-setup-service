from unittest.mock import patch, MagicMock
from typing import Dict
import uuid

import pytest
from fastapi.testclient import TestClient

from app.schemas.terraform import TerraformStatus
from app.services.terraform_job_store import TerraformJobStore


@patch("os.path.exists")
@patch("app.services.terraform_job_store.TerraformJobStore.create_job")
@patch("app.tasks.terraform.run_terraform_apply.delay")
@patch("app.services.terraform_job_store.TerraformJobStore.update_job")
def test_run_terraform(
    mock_update_job,
    mock_delay,
    mock_create_job,
    mock_exists,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test running terraform apply endpoint.
    """
    # Mock the path exists check
    mock_exists.return_value = True
    
    # Mock job creation
    job_id = str(uuid.uuid4())
    mock_create_job.return_value = job_id
    
    # Mock Celery task
    mock_task = MagicMock()
    mock_task.id = "mocked-task-id"
    mock_delay.return_value = mock_task
    
    response = test_client.post("/api/v1/terraform/apply", headers=api_key_headers)
    assert response.status_code == 200
    
    content = response.json()
    assert content["job_id"] == job_id
    assert content["status"] == TerraformStatus.PENDING
    assert "message" in content
    
    # Verify the task was started and job updated with task ID
    mock_delay.assert_called_once_with(job_id)
    mock_update_job.assert_called_once_with(job_id, task_id=mock_task.id)


@patch("os.path.exists")
def test_run_terraform_path_not_found(
    mock_exists,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test terraform endpoint when the script path doesn't exist.
    """
    # Mock the path exists check to return False
    mock_exists.return_value = False
    
    response = test_client.post("/api/v1/terraform/apply", headers=api_key_headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_run_terraform_unauthorized(test_client: TestClient) -> None:
    """
    Test terraform endpoint without API key.
    """
    response = test_client.post("/api/v1/terraform/apply")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API Key"


@patch("app.services.terraform_job_store.TerraformJobStore.get_job_status")
def test_get_terraform_status(
    mock_get_job_status,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test getting terraform job status.
    """
    job_id = str(uuid.uuid4())
    
    # Create a mock job status response
    mock_status = MagicMock()
    mock_status.job_id = job_id
    mock_status.status = TerraformStatus.SUCCESS
    mock_status.message = "Terraform job completed successfully"
    mock_status.outputs = {"database_url": "postgres://user:pass@hostname:5432/db"}
    mock_status.task_id = "mocked-task-id"
    
    mock_get_job_status.return_value = mock_status
    
    response = test_client.get(f"/api/v1/terraform/status/{job_id}", headers=api_key_headers)
    assert response.status_code == 200
    
    content = response.json()
    assert content["job_id"] == job_id
    assert content["status"] == TerraformStatus.SUCCESS
    assert content["outputs"]["database_url"] == "postgres://user:pass@hostname:5432/db"
    assert content["task_id"] == "mocked-task-id"


@patch("app.services.terraform_job_store.TerraformJobStore.get_job_status")
def test_get_terraform_status_not_found(
    mock_get_job_status,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test getting status for a non-existent job.
    """
    job_id = str(uuid.uuid4())
    mock_get_job_status.return_value = None
    
    response = test_client.get(f"/api/v1/terraform/status/{job_id}", headers=api_key_headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"] 