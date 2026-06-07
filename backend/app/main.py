import os
import sys

# Ensure the parent directory is in sys.path so 'app.*' imports work when run directly
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from app.api.routes_jobs import router as jobs_router, job_router
from app.api.routes_candidates import router as candidates_router, legacy_router

# Initialize FastAPI
api = FastAPI(title="AI ATS Evaluator API")

# Add CORS Middleware
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
api.include_router(jobs_router)
api.include_router(job_router)
api.include_router(candidates_router)
api.include_router(legacy_router)


if __name__ == "__main__":
    import uvicorn
    # When running directly, reload 'app.main:api' relative to backend/ directory
    uvicorn.run("app.main:api", host="0.0.0.0", port=8000, reload=True)
