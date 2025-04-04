import logging
import sys
from typing import Dict, Any

# Define log format for consistency
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def configure_logging():
    """
    Set up basic logging configuration to ensure all output is visible in terminal.
    """
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler that outputs to stdout
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(LOG_FORMAT)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Configure terraform logger specifically
    terraform_logger = logging.getLogger("app.tasks.terraform")
    terraform_logger.setLevel(logging.INFO)
    terraform_logger.propagate = True  # Ensure logs propagate to root logger
    
    # Configure celery logger
    celery_logger = logging.getLogger("celery")
    celery_logger.setLevel(logging.INFO)
    celery_logger.propagate = True  # Ensure logs propagate to root logger

def get_logging_config() -> Dict[str, Any]:
    """
    Get the logging configuration as a dictionary for programmatic use.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": LOG_FORMAT
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "standard",
                "stream": "ext://sys.stdout"
            }
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["console"],
                "level": "INFO",
                "propagate": True
            },
            "app.tasks.terraform": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": True
            },
            "celery": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": True
            }
        }
    }

# Apply logging configuration when the module is imported
configure_logging() 