# Warehouse API

A production-grade FastAPI application for warehouse management.

## Features

- RESTful API with FastAPI
- API Key Authentication
- Production-grade structure and best practices
- Comprehensive test suite
- Terraform infrastructure management through API
- Celery for background task processing with Redis
- Job tracking for long-running operations

## Setup

### Prerequisites

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) package manager
- Terraform (for infrastructure management)
- Redis (for Celery task queue)

### Installation

1. Clone this repository
2. Set up the virtual environment:

```bash
uv venv
source .venv/bin/activate  # On Unix/Mac
# or
.venv\Scripts\activate  # On Windows
```

3. Install dependencies:

```bash
uv pip install -e ".[dev]"
```

### Running the API

The easiest way to run the full stack is using Docker Compose:

```bash
docker-compose up -d
```

This will start:
- The FastAPI application
- Redis for task queuing and result storage
- Celery workers for processing tasks
- Celery Flower for monitoring tasks (available at http://localhost:5555)

Alternatively, to run just the API for development:

```bash
# Start Redis separately if not running
# Run the FastAPI server
uvicorn app.main:app --reload
# In a separate terminal, start a Celery worker
 celery -A app.core.celery_app worker -Q terraform -l info 
```

The API will be available at http://localhost:8000

### API Documentation

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Key Authentication

API authentication is handled using a single API key. Set the key in the .env file:

```
API_KEY=your_secure_api_key_here
```

In development, a default key of `development_api_key` is used if none is provided.

To authenticate your API requests, include the API key in the header:

```
X-API-Key: your_secure_api_key_here
```

## API Endpoints

### Warehouse Creation with Terraform

#### Start a Terraform job:

```
POST /api/v1/terraform/apply
```

Required header: `X-API-Key: your_api_key`

This endpoint will run a Terraform script located at `/create-warehouse` path to provision the necessary infrastructure. The operation runs asynchronously using Celery tasks.

**Response:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Check a Terraform job status:

```
GET /api/v1/terraform/status/{task_id}
```

Required header: `X-API-Key: your_api_key`

This endpoint can be polled to check the progress of a Terraform job. Possible status values:
- `pending`: Job is queued but not started yet
- `running`: Job is currently running
- `success`: Job completed successfully
- `error`: Job failed

When a job is complete, the response includes any outputs from the Terraform script, such as database connection details.

**Sample success response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result": {
    "host": "some-db.amazonaws.com",
    "port": "5432",
    "user": "database_user",
    "password": "secure_password123",
    "dbname": "customer_db",
    "database_url": "postgres://user:pass@hostname:5432/db"
  },
  "error": null
}
```

Or in case of an error:

```json
{
  "id": "8a7d463c-7418-4294-9de6-e49326374112",
  "status": "error",
  "result": null,
  "error": "Failed to create database: invalid parameters"
}
```