"""Background job management for the web API."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict

from .repository import WebRepository
from .schemas import JobCreateRequest
from .services import ReportService, ServiceError


class JobManager:
    """Queue long-running report jobs behind a single worker."""

    def __init__(self, repository: WebRepository):
        self.repository = repository
        self.report_service = ReportService(repository)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dsm-web")

    def submit_report(self, request: JobCreateRequest) -> Dict:
        scan_path = Path(request.path).expanduser() if request.path else Path.home()
        if not scan_path.exists() or not scan_path.is_dir():
            raise ServiceError(
                f"Scan path does not exist or is not a directory: {scan_path}"
            )
        job_id = str(uuid.uuid4())
        job = self.repository.create_job(job_id, request, scan_path)
        self.executor.submit(self._run_report_job, job_id, request)
        return job

    def _run_report_job(self, job_id: str, request: JobCreateRequest) -> None:
        try:
            self.report_service.generate_report(job_id, request)
        except Exception as exc:
            self.repository.mark_job_failed(job_id, str(exc))

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
