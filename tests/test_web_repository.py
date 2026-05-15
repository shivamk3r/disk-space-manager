"""Tests for web SQLite persistence."""

from pathlib import Path

from disk_space_manager.web.repository import WebRepository
from disk_space_manager.web.schemas import JobCreateRequest


def test_repository_persists_jobs_reports_candidates_and_actions(tmp_path):
    repo = WebRepository(tmp_path / "web.sqlite3")
    request = JobCreateRequest(path=str(tmp_path), age_months=3)

    job = repo.create_job("job-1", request, Path(tmp_path))
    assert job["status"] == "queued"
    assert job["confirmation_phrases"]["clean"] == "CLEAN job-1"

    repo.mark_job_running("job-1")
    repo.update_job_progress("job-1", "scan", 25.0, "Scanning")
    repo.save_report(
        "job-1",
        {"summary": {"file_count": 1}},
        [
            {
                "id": "candidate-1",
                "kind": "cache",
                "path": str(tmp_path / "cache.tmp"),
                "size": 10,
                "metadata": {"reason": "cache extension"},
            }
        ],
    )
    repo.mark_job_completed("job-1")

    saved = repo.get_job("job-1")
    assert saved["status"] == "completed"
    assert saved["progress_percent"] == 100.0
    assert repo.get_report("job-1")["summary"]["file_count"] == 1

    candidates = repo.list_candidates("job-1", "cache")
    assert len(candidates) == 1
    assert candidates[0]["metadata"]["reason"] == "cache extension"

    action = repo.save_action(
        "action-1",
        "job-1",
        "clean",
        True,
        None,
        1,
        0,
        {"deleted": 1, "failed": 0},
    )
    assert action["dry_run"] is True
    assert action["result"]["deleted"] == 1
