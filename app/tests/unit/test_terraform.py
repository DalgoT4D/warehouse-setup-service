from unittest.mock import patch, MagicMock
from typing import Dict
import uuid

import pytest
from fastapi.testclient import TestClient
from celery.result import AsyncResult
from celery.states import SUCCESS, FAILURE

from app.schemas.terraform import TerraformStatus


@patch("os.path.exists")
@patch("app.tasks.terraform.run_terraform_commands.apply_async")
def test_run_terraform(
    mock_delay,
    mock_exists,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test running terraform apply endpoint for PostgreSQL database creation.
    """
    # Mock the path exists check
    mock_exists.return_value = True
    
    # Mock Celery task
    mock_task = MagicMock()
    mock_task.id = "mocked-task-id"
    mock_delay.return_value = mock_task
    
    response = test_client.post("/api/infra/postgres/db", json={"dbname": "test-db"}, headers=api_key_headers)
    assert response.status_code == 200
    
    content = response.json()
    assert content["task_id"] == mock_task.id
    # The TerraformResponse model doesn't include status field
    assert "task_id" in content
    
    # Verify the task was started
    mock_delay.assert_called_once()


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
    
    response = test_client.post("/api/infra/postgres/db", json={"dbname": "test-db"}, headers=api_key_headers)
    assert response.status_code == 500  # Now expecting 500 since we're handling it as an internal error
    assert "not found" in response.json()["detail"].lower()


def test_run_terraform_unauthorized(test_client: TestClient) -> None:
    """
    Test terraform endpoint without API key.
    """
    response = test_client.post("/api/infra/postgres/db", json={"dbname": "test-db"})
    assert response.status_code == 401
    assert "Invalid API Key" in response.json()["detail"]


@patch("app.api.routes.AsyncResult")
def test_get_terraform_status(
    mock_async_result,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test getting terraform job status.
    """
    task_id = "mocked-task-id"
    
    # Create a mock AsyncResult with correct Celery SUCCESS constant
    mock_result = MagicMock()
    mock_result.id = task_id
    mock_result.status = SUCCESS  # Use Celery constant instead of string
    mock_result.successful.return_value = True
    mock_result.failed.return_value = False
    mock_result.ready.return_value = True
    mock_result.result = {
        "outputs": {"database_url": "postgres://user:pass@hostname:5432/db"},
        "credentials": {
            "dbname": "test-db",
            "host": "superset.cwqixp4vwhou.us-east-1.rds.amazonaws.com",
            "port": "5432",
            "user": "test-db_user",
            "password": "test_password"
        }
    }
    
    mock_async_result.return_value = mock_result
    
    response = test_client.get(f"/api/task/{task_id}", headers=api_key_headers)
    assert response.status_code == 200
    
    content = response.json()
    assert content["id"] == task_id
    assert content["status"] == "SUCCESS"  # Check the string value instead of enum
    # Check for flattened result structure (no nested credentials object)
    assert content["result"]["database_url"] == "postgres://user:pass@hostname:5432/db"
    assert content["result"]["dbname"] == "test-db"
    assert content["result"]["host"] == "superset.cwqixp4vwhou.us-east-1.rds.amazonaws.com"
    assert content["result"]["port"] == "5432"
    assert content["result"]["user"] == "test-db_user"
    assert content["result"]["password"] == "test_password"
    assert content["error"] is None


@patch("app.api.routes.AsyncResult")
def test_get_terraform_status_not_found(
    mock_async_result,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test getting status for a non-existent job.
    """
    task_id = "nonexistent-task-id"
    
    # Mock AsyncResult with no ID to simulate task not found
    mock_result = MagicMock()
    mock_result.id = None  # This will trigger the 404 condition
    mock_async_result.return_value = mock_result
    
    response = test_client.get(f"/api/task/{task_id}", headers=api_key_headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower() 


@patch("app.api.routes.AsyncResult")
def test_get_terraform_status_failed(
    mock_async_result,
    test_client: TestClient,
    api_key_headers: Dict[str, str]
) -> None:
    """
    Test getting terraform job status for a failed task.
    """
    task_id = "failed-task-id"
    
    # Create a mock AsyncResult with FAILURE status
    mock_result = MagicMock()
    mock_result.id = task_id
    mock_result.status = FAILURE  # Use Celery constant for FAILURE
    mock_result.successful.return_value = False
    mock_result.failed.return_value = True
    mock_result.ready.return_value = True
    mock_result.result = {
        "status": "ERROR",
        "error": "Failed to create Superset instance",
        "phase": "apply"
    }
    
    mock_async_result.return_value = mock_result
    
    response = test_client.get(f"/api/task/{task_id}", headers=api_key_headers)
    assert response.status_code == 200
    
    content = response.json()
    assert content["id"] == task_id
    assert content["status"] == "ERROR"  # Check the string value instead of enum
    assert content["result"] is None
    assert content["error"] == "Failed to create Superset instance" 