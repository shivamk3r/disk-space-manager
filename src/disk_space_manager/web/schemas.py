"""Pydantic models for the web API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from disk_space_manager.config import DEFAULT_AGE_THRESHOLD_MONTHS


class JobCreateRequest(BaseModel):
    """Request body for a report job."""

    path: Optional[str] = None
    age_months: int = Field(default=DEFAULT_AGE_THRESHOLD_MONTHS, ge=1, le=120)
    include_duplicates: bool = True
    include_near_duplicates: bool = True


class JobResponse(BaseModel):
    """Serialized job status."""

    id: str
    status: str
    path: str
    age_months: int
    include_duplicates: bool
    include_near_duplicates: bool
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    progress_phase: str
    progress_percent: float
    progress_message: str
    confirmation_phrases: Dict[str, str]


class JobsListResponse(BaseModel):
    jobs: List[JobResponse]


class ActionRequest(BaseModel):
    candidate_ids: List[str] = Field(default_factory=list)
    dry_run: bool = True
    confirmation_phrase: Optional[str] = None
    target_path: Optional[str] = None
    external_path: Optional[str] = None


class ActionResponse(BaseModel):
    id: str
    job_id: str
    action_type: str
    dry_run: bool
    selected_count: int
    skipped_count: int
    result: Dict[str, Any]
    created_at: str
