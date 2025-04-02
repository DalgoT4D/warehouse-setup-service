from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import infra_router, task_router, health_router
from app.core.config import settings

app = FastAPI(
    title="Infrastructure Service API",
    description="Lightweight API for infrastructure provisioning",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include the simplified router structure
app.include_router(infra_router, prefix="/api/infra")
app.include_router(task_router, prefix="/api/task")
app.include_router(health_router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Welcome to the Infrastructure Service API. See /docs for documentation."} 