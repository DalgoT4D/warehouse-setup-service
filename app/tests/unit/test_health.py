from fastapi.testclient import TestClient


def test_health_check(test_client: TestClient) -> None:
    """
    Test health check endpoint.
    """
    response = test_client.get("/api/v1/health")
    assert response.status_code == 200
    content = response.json()
    assert content["status"] == "ok"
    assert content["message"] == "API is running" 