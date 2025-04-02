from typing import Any, Dict, List, Optional, Union
import os
import re
import shutil
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
    TERRAFORM_TASK_CONFIGS_PATH: str = "app/terraform_files/task_configs"
    
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
    
    def create_task_specific_tfvars(self, module_path: str, task_id: str, replacements: Dict[str, Any] = None) -> str:
        """
        Create a task-specific terraform.tfvars file based on the original with optional replacements.
        
        Args:
            module_path: Path to the terraform module directory
            task_id: Unique task ID to use in the filename
            replacements: Optional dictionary of key-value pairs to replace in the tfvars
            
        Returns:
            Path to the task-specific tfvars file
        """
        # Ensure the task configs directory exists
        os.makedirs(self.TERRAFORM_TASK_CONFIGS_PATH, exist_ok=True)
        
        # Convert paths to absolute paths
        abs_module_path = os.path.abspath(module_path) if not os.path.isabs(module_path) else module_path
        abs_task_configs_path = os.path.abspath(self.TERRAFORM_TASK_CONFIGS_PATH) if not os.path.isabs(self.TERRAFORM_TASK_CONFIGS_PATH) else self.TERRAFORM_TASK_CONFIGS_PATH
        
        # Determine module type (warehouse or superset)
        if "createWarehouse" in abs_module_path or "warehouse" in abs_module_path.lower():
            module_type = "warehouse"
        else:
            module_type = "superset"
        
        # Generate task-specific filename
        task_tfvars_filename = f"{module_type}.{task_id}.tfvars"
        task_tfvars_path = os.path.join(abs_task_configs_path, task_tfvars_filename)
        
        # Path to original tfvars file
        original_tfvars_path = os.path.join(abs_module_path, "terraform.tfvars")
        
        if not os.path.exists(original_tfvars_path):
            raise FileNotFoundError(f"Original terraform.tfvars not found at {original_tfvars_path}")
        
        # Read the original file content
        with open(original_tfvars_path, 'r') as f:
            content = f.read()
        
        # Apply replacements if provided
        if replacements:
            # Process content line by line for more reliable replacements
            lines = content.splitlines()
            for i, line in enumerate(lines):
                for key, value in replacements.items():
                    # Check if this line contains the key we want to replace
                    if re.match(rf"^\s*{key}\s*=", line):
                        # Format the value based on type
                        if isinstance(value, str) and not value.isdigit():
                            formatted_value = f'"{value}"'
                        elif isinstance(value, bool):
                            formatted_value = str(value).lower()  # Ensure booleans are lowercase
                        else:
                            formatted_value = str(value)
                        
                        # Replace the line
                        lines[i] = re.sub(r"=\s*.*$", f"= {formatted_value}", line)
                        break  # Found match for this key, move to next line
            
            # Rebuild content from modified lines
            content = "\n".join(lines)
        
        # Write the modified content to the task-specific file
        with open(task_tfvars_path, 'w') as f:
            f.write(content)
        
        return task_tfvars_path
    
    def get_task_tfvars_path(self, module_type: str, task_id: str) -> str:
        """
        Get the path to a task-specific tfvars file
        
        Args:
            module_type: Either 'warehouse' or 'superset'
            task_id: The unique task ID
            
        Returns:
            Path to the task-specific tfvars file
        """
        task_tfvars_filename = f"{module_type}.{task_id}.tfvars"
        return os.path.join(self.TERRAFORM_TASK_CONFIGS_PATH, task_tfvars_filename)
    
    def cleanup_task_tfvars(self, task_id: str = None) -> None:
        """
        Clean up task-specific tfvars files
        
        Args:
            task_id: If provided, only delete files for this task ID.
                    If None, delete all task-specific tfvars files.
        """
        if not os.path.exists(self.TERRAFORM_TASK_CONFIGS_PATH):
            return
            
        if task_id:
            # Delete specific task files
            for module_type in ['warehouse', 'superset']:
                task_tfvars_path = self.get_task_tfvars_path(module_type, task_id)
                if os.path.exists(task_tfvars_path):
                    os.remove(task_tfvars_path)
        else:
            # Delete all task files (be careful with this!)
            for filename in os.listdir(self.TERRAFORM_TASK_CONFIGS_PATH):
                if filename.endswith('.tfvars'):
                    file_path = os.path.join(self.TERRAFORM_TASK_CONFIGS_PATH, filename)
                    os.remove(file_path)


settings = Settings() 