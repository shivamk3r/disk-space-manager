"""Tests for the FastAPI web interface."""

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from disk_space_manager.web.app import create_app
from disk_space_manager.web.repository import WebRepository


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_old_large_file(path, size_bytes=1024 * 1024 + 1, age_days=60):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size_bytes)
    old_time = time.time() - age_days * 24 * 60 * 60
    os.utime(path, (old_time, old_time))


def _wait_for_job(client, token, job_id):
    for _ in range(100):
        response = client.get(f"/api/jobs/{job_id}", headers=_auth(token))
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_api_requires_token(tmp_path):
    app = create_app(repository=WebRepository(tmp_path / "web.sqlite3"), token="secret")
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/config", headers=_auth("secret")).status_code == 200


def test_report_job_and_dry_run_clean_action(tmp_path, monkeypatch):
    monkeypatch.setattr("disk_space_manager.executor.ACTION_LOG_FILE", tmp_path / "actions.log")
    source = tmp_path / "source"
    source.mkdir()
    (source / "cache.tmp").write_text("cache")
    _create_old_large_file(source / "old.bin")

    app = create_app(repository=WebRepository(tmp_path / "web.sqlite3"), token="secret")
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        headers=_auth("secret"),
        json={
            "path": str(source),
            "age_months": 1,
            "include_duplicates": False,
            "include_near_duplicates": False,
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]

    job = _wait_for_job(client, "secret", job_id)
    assert job["status"] == "completed"

    report_response = client.get(f"/api/jobs/{job_id}/report", headers=_auth("secret"))
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["candidate_counts"]["cache"] >= 1
    assert report["candidate_counts"]["old"] == 1

    candidate_id = next(
        candidate["id"]
        for candidate in report["cache_candidates"]
        if candidate["path"].endswith("cache.tmp")
    )
    blocked = client.post(
        f"/api/jobs/{job_id}/actions/clean",
        headers=_auth("secret"),
        json={"candidate_ids": [candidate_id], "dry_run": False},
    )
    assert blocked.status_code == 400

    dry_run = client.post(
        f"/api/jobs/{job_id}/actions/clean",
        headers=_auth("secret"),
        json={"candidate_ids": [candidate_id], "dry_run": True},
    )
    assert dry_run.status_code == 200, dry_run.text
    result = dry_run.json()
    assert result["result"]["deleted"] == 1
    assert (source / "cache.tmp").exists()


def test_dry_run_archive_action_uses_candidate_ids(tmp_path, monkeypatch):
    monkeypatch.setattr("disk_space_manager.executor.ACTION_LOG_FILE", tmp_path / "actions.log")
    source = tmp_path / "source"
    archive_target = tmp_path / "archive"
    source.mkdir()
    _create_old_large_file(source / "old.bin")

    app = create_app(repository=WebRepository(tmp_path / "web.sqlite3"), token="secret")
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        headers=_auth("secret"),
        json={
            "path": str(source),
            "age_months": 1,
            "include_duplicates": False,
            "include_near_duplicates": False,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["id"]
    assert _wait_for_job(client, "secret", job_id)["status"] == "completed"

    report = client.get(f"/api/jobs/{job_id}/report", headers=_auth("secret")).json()
    old_id = report["old_candidates"][0]["id"]
    response = client.post(
        f"/api/jobs/{job_id}/actions/archive",
        headers=_auth("secret"),
        json={
            "candidate_ids": [old_id],
            "dry_run": True,
            "target_path": str(archive_target),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["moved"] == 1
    assert (source / "old.bin").exists()
    assert not archive_target.exists()
