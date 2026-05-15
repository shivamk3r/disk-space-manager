"""Web-facing services that reuse the core disk-space-manager modules."""

import hashlib
import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from disk_space_manager.analyzer import FileAnalyzer
from disk_space_manager.archive_targets import (
    ArchiveTarget,
    ArchiveTargetError,
    resolve_archive_target,
)
from disk_space_manager.duplicates import DuplicateDetector, empty_duplicate_report
from disk_space_manager.executor import ActionExecutor
from disk_space_manager.scanner import DiskScanner, ScanProgress
from disk_space_manager.utils import format_size

from .repository import WebRepository, confirmation_phrase
from .schemas import ActionRequest, JobCreateRequest


class ServiceError(RuntimeError):
    """Raised for user-correctable service errors."""


class ReportService:
    """Build and persist report jobs for the web API."""

    def __init__(self, repository: WebRepository):
        self.repository = repository

    def generate_report(self, job_id: str, request: JobCreateRequest) -> None:
        """Run a complete report and persist summaries plus candidates."""
        self.repository.mark_job_running(job_id)
        scan_path = _resolve_scan_path(request.path)
        analyzer = FileAnalyzer(age_threshold=timedelta(days=request.age_months * 30))

        def scan_progress(progress: ScanProgress) -> None:
            if progress.is_finished:
                percent = 55.0
            elif progress.directories_discovered:
                ratio = progress.directories_completed / progress.directories_discovered
                percent = min(50.0, max(1.0, ratio * 50.0))
            else:
                percent = 1.0
            self.repository.update_job_progress(
                job_id,
                "scan",
                percent,
                f"Scanned {progress.files_scanned} files",
            )

        scanner = DiskScanner(
            scan_path,
            detailed_progress_callback=scan_progress,
        )
        scan_results = scanner.scan()

        self.repository.update_job_progress(
            job_id,
            "analyze",
            62.0,
            "Analyzing cache candidates",
        )
        cache_files = analyzer.find_cache_files(scan_results["files"])

        self.repository.update_job_progress(
            job_id,
            "analyze",
            70.0,
            "Analyzing old files",
        )
        old_source_files = [
            file_info
            for file_info in scan_results["files"]
            if not os.path.islink(file_info["path"])
        ]
        old_files = analyzer.find_old_files(old_source_files)

        duplicate_report = empty_duplicate_report()
        if request.include_duplicates:
            self.repository.update_job_progress(
                job_id,
                "duplicates",
                78.0,
                "Finding duplicate files",
            )
            duplicate_report = DuplicateDetector().build_report(
                scan_results["files"],
                include_near_duplicates=request.include_near_duplicates,
            )

        exact = duplicate_report.get("exact", {})
        savings = analyzer.calculate_potential_savings(
            cache_files,
            old_files,
            exact_duplicate_reclaimable_size=int(exact.get("reclaimable_size") or 0),
            exact_duplicate_file_count=int(exact.get("duplicate_file_count") or 0),
        )
        summary = _format_usage_summary(
            analyzer.analyze_disk_usage(scan_results["files"], scan_results["directories"])
        )
        report = {
            "job_id": job_id,
            "path": str(scan_path),
            "age_months": request.age_months,
            "scan": {
                "total_scanned": scan_results["total_scanned"],
                "error_count": len(scan_results["errors"]),
                "errors": scan_results["errors"][:100],
            },
            "summary": summary,
            "largest_files": [_format_file(file_info) for file_info in scanner.get_largest_files(20)],
            "largest_directories": [
                {
                    "path": path,
                    "size": size,
                    "size_formatted": format_size(size),
                }
                for path, size in scanner.get_largest_directories(20)
            ],
            "savings": savings,
            "duplicates": _format_duplicate_report(duplicate_report),
            "candidate_counts": {
                "cache": len(cache_files),
                "old": len(old_files),
            },
        }

        candidates = list(_build_candidates(job_id, "cache", cache_files))
        candidates.extend(_build_candidates(job_id, "old", old_files))

        self.repository.update_job_progress(job_id, "persist", 92.0, "Saving report")
        self.repository.save_report(job_id, report, candidates)
        self.repository.mark_job_completed(job_id)


class ActionService:
    """Execute web actions against persisted report candidates."""

    def __init__(self, repository: WebRepository):
        self.repository = repository

    def clean(self, job_id: str, request: ActionRequest) -> Dict[str, Any]:
        self._validate_action_request(job_id, "clean", request)
        candidates = self._load_candidates(job_id, "cache", request.candidate_ids)
        files = [_candidate_to_file(candidate) for candidate in candidates]
        executor = ActionExecutor(dry_run=request.dry_run)
        result = executor.delete_files(files, confirm=False)
        return self.repository.save_action(
            action_id=str(uuid.uuid4()),
            job_id=job_id,
            action_type="clean",
            dry_run=request.dry_run,
            target_path=None,
            selected_count=len(files),
            skipped_count=0,
            result=result,
        )

    def archive(self, job_id: str, request: ActionRequest) -> Dict[str, Any]:
        self._validate_action_request(job_id, "archive", request)
        candidates = self._load_candidates(job_id, "old", request.candidate_ids)
        try:
            target = _resolve_archive_target_for_action(request)
        except ArchiveTargetError as exc:
            raise ServiceError(str(exc)) from exc

        selected_files = [_candidate_to_file(candidate) for candidate in candidates]
        files = [
            file_info
            for file_info in selected_files
            if not _is_under_path(Path(file_info["path"]), target.root)
            and not os.path.islink(file_info["path"])
        ]
        skipped_count = len(selected_files) - len(files)
        if not files:
            raise ServiceError("No selected archive candidates are safe to archive")

        job = self.repository.get_job(job_id)
        executor = ActionExecutor(dry_run=request.dry_run)
        result = executor.archive_files(
            files,
            target.archive_base,
            Path(job["path"]),
            confirm=False,
        )
        return self.repository.save_action(
            action_id=str(uuid.uuid4()),
            job_id=job_id,
            action_type="archive",
            dry_run=request.dry_run,
            target_path=str(target.root),
            selected_count=len(selected_files),
            skipped_count=skipped_count,
            result=result,
        )

    def _validate_action_request(
        self,
        job_id: str,
        action_type: str,
        request: ActionRequest,
    ) -> None:
        if not request.candidate_ids:
            raise ServiceError("Select at least one candidate")
        job = self.repository.get_job(job_id)
        if job["status"] != "completed":
            raise ServiceError("Actions require a completed report job")
        if not request.dry_run:
            expected = confirmation_phrase(action_type, job_id)
            if request.confirmation_phrase != expected:
                raise ServiceError(f"Confirmation phrase must match '{expected}'")

    def _load_candidates(
        self,
        job_id: str,
        kind: str,
        candidate_ids: List[str],
    ) -> List[Dict[str, Any]]:
        candidates = self.repository.list_candidates_by_ids(job_id, candidate_ids, kind)
        if len(candidates) != len(set(candidate_ids)):
            raise ServiceError("One or more selected candidates are invalid")
        return candidates


def _resolve_scan_path(path: Optional[str]) -> Path:
    scan_path = Path(path).expanduser() if path else Path.home()
    if not scan_path.exists() or not scan_path.is_dir():
        raise ServiceError(f"Scan path does not exist or is not a directory: {scan_path}")
    return scan_path


def _resolve_archive_target_for_action(request: ActionRequest) -> ArchiveTarget:
    target_path = Path(request.target_path).expanduser() if request.target_path else None
    external_path = Path(request.external_path).expanduser() if request.external_path else None
    if request.dry_run and target_path:
        return ArchiveTarget(
            root=target_path,
            archive_base=target_path / "archived_files",
            label="local folder",
            source="target_path",
        )
    return resolve_archive_target(target_path=target_path, external_path=external_path)


def _build_candidates(
    job_id: str,
    kind: str,
    files: Iterable[Dict[str, Any]],
) -> Iterable[Dict[str, Any]]:
    for file_info in files:
        path = str(file_info["path"])
        yield {
            "id": _candidate_id(job_id, kind, path),
            "kind": kind,
            "path": path,
            "size": int(file_info.get("size") or 0),
            "metadata": _candidate_metadata(file_info),
        }


def _candidate_id(job_id: str, kind: str, path: str) -> str:
    digest = hashlib.sha256(f"{job_id}:{kind}:{path}".encode("utf-8")).hexdigest()
    return digest[:24]


def _candidate_metadata(file_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in file_info.items()
        if key not in {"path", "size"}
    }


def _candidate_to_file(candidate: Dict[str, Any]) -> Dict[str, Any]:
    file_info = {
        "path": candidate["path"],
        "size": int(candidate["size"]),
    }
    file_info.update(candidate["metadata"])
    return file_info


def _format_usage_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **summary,
        "top_extensions": [
            {
                "extension": extension,
                "count": values["count"],
                "size": values["size"],
                "size_formatted": format_size(values["size"]),
            }
            for extension, values in summary["top_extensions"]
        ],
        "average_file_size_formatted": format_size(int(summary["average_file_size"])),
    }


def _format_file(file_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "path": file_info["path"],
        "size": int(file_info.get("size") or 0),
        "size_formatted": format_size(int(file_info.get("size") or 0)),
        "atime": file_info.get("atime"),
        "mtime": file_info.get("mtime"),
        "ctime": file_info.get("ctime"),
    }


def _format_duplicate_report(report: Dict[str, Any]) -> Dict[str, Any]:
    formatted = {"exact": dict(report.get("exact", {})), "near": dict(report.get("near", {}))}
    for section in ("exact", "near"):
        groups = formatted[section].get("groups", [])
        formatted[section]["groups"] = [_format_duplicate_group(group) for group in groups]
    return formatted


def _format_duplicate_group(group: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(group)
    result["files"] = [_format_file(file_info) for file_info in group.get("files", [])]
    for key in ("size", "total_size", "reclaimable_size", "reviewable_size"):
        if key in result:
            result[f"{key}_formatted"] = format_size(int(result[key]))
    return result


def _is_under_path(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False
