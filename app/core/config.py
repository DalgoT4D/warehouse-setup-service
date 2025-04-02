from typing import Any, Dict, List, Optional, Union
import os
import re
from pathlib import Path

from pydantic import AnyHttpUrl, field_validator, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class TerraformModuleSettings(BaseModel):
    """Module-specific settings loaded from a module's terraform.tfvars file"""
    
    # AWS Credentials
    AWS_ACCESS_KEY: str = ""
    AWS_SECRET_KEY: str = ""
    
    # RDS Configuration
    RDS_INSTANCE_NAME: str = ""
    RDS_DOMAIN: str = ""
    
    # Database Configuration
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    DB_PORT: int = 5432
    
    # EC2 Configuration
    EC2_INSTANCE_ID: str = ""
    REMOTE_USER: str = ""
    SSH_KEY_PATH: str = ""
    
    def get_rds_hostname(self) -> str:
        """Get the full RDS hostname"""
        return f"{self.RDS_INSTANCE_NAME}.{self.RDS_DOMAIN}"


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
    
    # Terraform Settings - Paths
    TERRAFORM_SCRIPT_PATH_CREATE_WAREHOUSE: str = "app/terraform_files/createWarehouse"
    TERRAFORM_SCRIPT_PATH_CREATE_SUPERSET: str = "app/terraform_files/createSuperset"
    
    # Celery and Redis settings
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    def is_valid_api_key(self, key: str) -> bool:
        """Check if an API key is valid"""
        return key == self.API_KEY
    
    def _parse_tfvars_file(self, tfvars_path: str) -> Dict[str, Any]:
        """Parse terraform.tfvars file and extract variables"""
        result = {}
        
        if not os.path.exists(tfvars_path):
            return result
            
        with open(tfvars_path, 'r') as f:
            for line in f:
                # Skip comments and empty lines
                if line.strip().startswith('#') or not line.strip():
                    continue
                
                # Extract key-value pairs
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    
                    # Remove comments at the end of value
                    value = re.sub(r'#.*$', '', value).strip()
                    
                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    
                    # Convert to appropriate type if possible
                    if value.isdigit():
                        value = int(value)
                    elif value.lower() == 'true':
                        value = True
                    elif value.lower() == 'false':
                        value = False
                    
                    result[key] = value
        
        return result
    
    def get_terraform_module_settings(self, module_path: str) -> TerraformModuleSettings:
        """Load module-specific settings from the module's terraform.tfvars file"""
        tfvars_path = os.path.join(module_path, "terraform.tfvars")
        
        # Initialize settings with empty values
        settings_dict = {}
        
        # If tfvars file exists, parse it and update settings
        if os.path.exists(tfvars_path):
            tfvars_data = self._parse_tfvars_file(tfvars_path)
            
            # Map terraform.tfvars keys to TerraformModuleSettings fields
            key_mapping = {
                'aws_access_key': 'AWS_ACCESS_KEY',
                'aws_secret_key': 'AWS_SECRET_KEY',
                'rdsname': 'RDS_INSTANCE_NAME',
                'RDS_DOMAIN': 'RDS_DOMAIN',
                'POSTGRES_USER': 'POSTGRES_USER',
                'POSTGRES_PASSWORD': 'POSTGRES_PASSWORD',
                'DB_PORT': 'DB_PORT',
                'PORT': 'DB_PORT',
                'ec2_instance_id': 'EC2_INSTANCE_ID',
                'REMOTE_USER': 'REMOTE_USER',
                'SSH_KEY': 'SSH_KEY_PATH'
            }
            
            # Update settings with values from tfvars
            for tfvar_key, setting_key in key_mapping.items():
                if tfvar_key in tfvars_data:
                    settings_dict[setting_key] = tfvars_data[tfvar_key]
        
        # Create and return the settings object
        return TerraformModuleSettings(**settings_dict)


settings = Settings() 