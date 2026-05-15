"""FastAPI application factory for Disk Space Manager Web."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from disk_space_manager.config import DEFAULT_AGE_THRESHOLD_MONTHS

from .jobs import JobManager
from .repository import DEFAULT_DB_PATH, WebRepository
from .schemas import (
    ActionRequest,
    ActionResponse,
    JobCreateRequest,
    JobResponse,
    JobsListResponse,
)
from .security import make_token_dependency
from .services import ActionService, ServiceError


STATIC_DIR = Path(__file__).with_name("static")


def create_app(
    repository: Optional[WebRepository] = None,
    token: str = "",
    static_dir: Optional[Path] = None,
    dev_origin: Optional[str] = None,
) -> FastAPI:
    """Create the FastAPI app with injected persistence and token config."""
    repo = repository or WebRepository(DEFAULT_DB_PATH)
    job_manager = JobManager(repo)
    action_service = ActionService(repo)
    verify_token = make_token_dependency(token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        job_manager.shutdown()

    app = FastAPI(title="Disk Space Manager Web", lifespan=lifespan)
    app.state.repository = repo
    app.state.job_manager = job_manager

    if dev_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[dev_origin],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config", dependencies=[Depends(verify_token)])
    def config() -> dict:
        return {
            "default_age_months": DEFAULT_AGE_THRESHOLD_MONTHS,
            "duplicate_detection": True,
            "near_duplicate_detection": True,
        }

    @app.post(
        "/api/jobs",
        response_model=JobResponse,
        dependencies=[Depends(verify_token)],
    )
    def create_job(request: JobCreateRequest) -> dict:
        try:
            return job_manager.submit_report(request)
        except ServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get(
        "/api/jobs",
        response_model=JobsListResponse,
        dependencies=[Depends(verify_token)],
    )
    def list_jobs() -> dict:
        return {"jobs": repo.list_jobs()}

    @app.get(
        "/api/jobs/{job_id}",
        response_model=JobResponse,
        dependencies=[Depends(verify_token)],
    )
    def get_job(job_id: str) -> dict:
        try:
            return repo.get_job(job_id)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    @app.get("/api/jobs/{job_id}/events", dependencies=[Depends(verify_token)])
    async def job_events(job_id: str) -> StreamingResponse:
        try:
            repo.get_job(job_id)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        async def stream():
            while True:
                job = repo.get_job(job_id)
                payload = json.dumps(job)
                yield f"event: progress\ndata: {payload}\n\n"
                if job["status"] in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/jobs/{job_id}/report", dependencies=[Depends(verify_token)])
    def get_report(job_id: str) -> dict:
        try:
            report = repo.get_report(job_id)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
        report["cache_candidates"] = repo.list_candidates(job_id, "cache")
        report["old_candidates"] = repo.list_candidates(job_id, "old")
        report["job"] = repo.get_job(job_id)
        return report

    @app.post(
        "/api/jobs/{job_id}/actions/clean",
        response_model=ActionResponse,
        dependencies=[Depends(verify_token)],
    )
    def clean(job_id: str, request: ActionRequest) -> dict:
        try:
            return action_service.clean(job_id, request)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        except ServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post(
        "/api/jobs/{job_id}/actions/archive",
        response_model=ActionResponse,
        dependencies=[Depends(verify_token)],
    )
    def archive(job_id: str, request: ActionRequest) -> dict:
        try:
            return action_service.archive(job_id, request)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        except ServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    resolved_static_dir = static_dir or STATIC_DIR
    if (resolved_static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(resolved_static_dir), html=True), name="static")

    return app
