from typing import Any, Dict, List, Optional, Union
import os

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True
    )

    PROJECT_NAME: str = "Warehouse API"
    API_V1_STR: str = "/api/v1"
    
    # CORS configuration
    BACKEND_CORS_ORIGINS: List[Union[str, AnyHttpUrl]] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # API Key for authentication - single key approach
    API_KEY_NAME: str = "X-API-Key"
    API_KEY: str = "development_api_key"  # Default value, override in .env
    
    # Terraform Settings
    TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE: str = "/Users/himanshut4d/Documents/Tech4Dev/Dalgo/warehouse_setup/app/terraform_files/createWarehouse"
    
    # Celery and Redis settings
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    def is_valid_api_key(self, key: str) -> bool:
        """Check if an API key is valid"""
        return key == self.API_KEY


settings = Settings() 