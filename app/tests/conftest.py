import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings


@pytest.fixture
def test_client():
    """
    Test client for the FastAPI app.
    """
    return TestClient(app)


@pytest.fixture
def api_key_headers():
    """
    Headers with valid API key.
    """
    return {settings.API_KEY_NAME: settings.API_KEY} 