# Code Architecture

## Overview

Disk Space Manager is packaged under `src/disk_space_manager` with two public
entrypoints: the Click CLI and the optional FastAPI web dashboard. The
repository root stays small: `main.py` is only a compatibility shim for
`uv run python main.py ...`, while the preferred interfaces are:

```bash
uv run disk-space-manager ...
uv run python -m disk_space_manager ...
uv run disk-space-manager-web
```

The CLI runtime pipeline is still intentionally direct:

```text
Click command -> workflow -> DiskScanner -> FileAnalyzer -> Rich UI
                         |          \-> DuplicateDetector -> Rich UI
                         v
                  ActionExecutor
```

The web runtime wraps the same core modules with service and persistence layers:

```text
React UI -> FastAPI routes -> web services -> DiskScanner/FileAnalyzer
                                      |      \-> DuplicateDetector
                                      v
                              SQLite + ActionExecutor
```

The architectural goal is separation of concerns. Click declarations, web
route declarations, workflow sequencing, service orchestration, terminal
presentation, frontend presentation, target resolution, scanning, analysis,
persistence, and file mutation each have clear module ownership.

## Runtime Package

### `src/disk_space_manager/cli.py`

Defines the Click command group, global `--dry-run` flag, and command options
for `analyze`, `clean`, `archive`, and `full-report`.

This module should stay thin. It parses CLI inputs and delegates to
`workflows.py`; it should not contain scanning, rendering, archive selection, or
file-mutation logic.

### `src/disk_space_manager/workflows.py`

Coordinates command behavior:

- Resolves the scan path, defaulting to `Path.home()`.
- Creates `DiskScanner`, `FileAnalyzer`, and `ActionExecutor` instances.
- Creates `DuplicateDetector` for `full-report` unless duplicate checks are
  disabled.
- Sequences scan, analysis, preview, confirmation, and execution steps.
- Keeps destructive operations behind confirmation unless dry-run mode is
  active.
- Excludes archive targets from archive scans and skips symlink archive
  candidates.

Workflow functions are command-sized orchestration units. Domain details should
stay in scanner, analyzer, executor, or archive target modules.

### `src/disk_space_manager/ui.py`

Owns terminal presentation and prompts:

- Header and dry-run banner.
- Rich tables, summaries, progress bars, and scan ETA display.
- Cache and old-file preview rendering.
- Confirmation prompts for destructive command paths.
- Final execution summaries and action-log location display.

No filesystem mutation should happen in this module.

### `src/disk_space_manager/archive_targets.py`

Resolves archive destinations and returns an `ArchiveTarget` dataclass with:

- `root`: selected target directory.
- `archive_base`: `<root>/archived_files`.
- `label`: user-facing target label.
- `source`: target source, such as `target_path`, `external_path`, or
  `auto_detected`.

Target precedence is deliberate and must remain:

1. `--target-path`
2. `--external-path`
3. Auto-detected external drive

### `src/disk_space_manager/scanner.py`

Owns filesystem traversal. `DiskScanner.scan()` returns:

- `files`: list of dictionaries with `path`, `size`, `atime`, `mtime`, and
  `ctime`.
- `directories`: mapping of directory path strings to byte totals.
- `total_scanned`: total number of scanned files.
- `errors`: non-fatal scan errors.

Important implementation details:

- Uses `os.scandir` and `DirEntry.stat()` for low per-file overhead.
- Scans top-level subdirectories in worker threads.
- Does not follow directory symlinks.
- Precomputes configured and caller-supplied exclusion prefixes once per scan.
- Reports simple file-count progress and detailed `ScanProgress` snapshots.
- Batches worker progress events to avoid excessive cross-thread chatter.

`get_largest_directories()` and `get_largest_files()` operate on the scanner's
in-memory results after a scan.

### `src/disk_space_manager/analyzer.py`

Contains `FileAnalyzer`, which operates on scanner file dictionaries.

Primary responsibilities:

- Detect cache candidates using configured directory patterns, extension
  checks, and filename markers.
- Detect old files using access time, configured age threshold, and minimum
  file size.
- Add result metadata such as cache `reason`, old-file `days_old`,
  `age_category`, and display-ready `accessed` datetime.
- Summarize total size, file count, average file size, and top extensions.
- Calculate potential space savings for cache deletion and old-file archiving.
- Include exact duplicate reclaimable bytes in potential savings when supplied.

Performance-oriented constants are prepared at import time.

### `src/disk_space_manager/duplicates.py`

Contains `DuplicateDetector`, which operates on scanner file dictionaries.

Primary responsibilities:

- Group exact duplicates by size and streamed SHA-256 digest.
- Build capped offline near-duplicate fingerprints for text, images, videos,
  and audio.
- Bucket fingerprints before pair comparisons to avoid a global all-pairs scan.
- Return report dictionaries with duplicate groups, reclaimable or reviewable
  bytes, and skip counts.

This module is read-only and best-effort. Decode failures, unsupported formats,
and over-cap files are skipped rather than failing the report.

### `src/disk_space_manager/executor.py`

Contains `ActionExecutor`, the only module that performs destructive user-file
operations.

Primary responsibilities:

- Track dry-run state.
- Log every intended or completed action in memory and in
  `~/.disk-space-manager-actions.log`.
- Delete files through `utils.safe_delete`.
- Archive files into a target base directory while preserving paths relative to
  the scan root.
- Copy file metadata with `shutil.copy2`, unlink the original file, and create
  a symlink at the original path pointing to the archived copy.

Confirmation is handled before executor methods are called. The executor keeps
the actual mutation and action-log behavior centralized.

### `src/disk_space_manager/drive_detector.py`

Detects writable external volumes:

- macOS uses `diskutil` and falls back to `/Volumes`.
- Linux parses `/proc/self/mountinfo`, skips pseudo/system filesystems, and
  considers common mount roots such as `/media`, `/mnt`, and `/run/media`.
- Manual external paths are validated for existence and writability.

### `src/disk_space_manager/progress_estimator.py`

Converts `ScanProgress` snapshots into `ScanEstimate` objects suitable for
Rich's determinate progress bars.

The estimator starts with a placeholder total, estimates total work from the
ratio of completed to discovered directories, smooths changes, keeps visible
remaining work while directories remain, and snaps to the actual total when the
scan finishes.

### `src/disk_space_manager/config.py`

Contains repository-wide constants:

- Default old-file age threshold.
- Unix-like cache directory patterns.
- Cache-like file extensions.
- System and user-home scan exclusions.
- Minimum file size for archive candidates.
- Duplicate display limits, per-format near-duplicate caps, sampling counts,
  and similarity thresholds.
- Action log path.

Changes here can materially affect safety, scan scope, and user trust, so pair
them with focused tests.

### `src/disk_space_manager/utils.py`

Contains shared helpers for size formatting, metadata reads, excluded path
checks, directory sizing, available-space checks, safe deletion, link/copy
helpers, and archive target path construction.

### `src/disk_space_manager/web/`

Contains the optional FastAPI application and built React assets.

- `server.py` exposes `disk-space-manager-web`, prints the tokenized URL, and
  can start Vite in `--dev` mode. It owns web command options for host, port,
  frontend port, SQLite path, and token override.
- `app.py` owns FastAPI route declarations, token-protected API dependencies,
  Server-Sent Events, and static frontend serving.
- `services.py` converts core scan/analyze results into persisted web reports
  and runs clean/archive actions only against stored candidate IDs.
- `jobs.py` queues long-running report jobs on a single background worker.
- `repository.py` persists job history, report summaries, candidates, and
  action results in SQLite.
- `schemas.py` contains Pydantic request/response models for jobs and actions.
- `security.py` reads, creates, and validates API tokens.
- `static/` contains the production React build served by FastAPI.

Web modules should remain a wrapper around the core scanner, analyzer,
duplicate detector, archive target resolver, and executor. They should not
reimplement filesystem traversal or mutation behavior.

### `frontend/`

Contains the React/Vite dashboard source.

- `src/App.tsx` owns the dashboard shell, scan form, job history, progress
  display, charts, duplicate review, candidate tables, and action panels.
- `src/api.ts` centralizes token-aware API calls and SSE subscription setup.
- `src/types.ts` mirrors the JSON structures returned by the FastAPI API.
- `vite.config.ts` builds production assets into
  `src/disk_space_manager/web/static/`.

The checked-in static build is what `disk-space-manager-web` serves outside
`--dev` mode. When frontend source changes, rebuild the assets with
`npm run build` from `frontend/`.

## Web API Routes

The web API is token-protected except for `/health`.

- `GET /health`: unauthenticated liveness check.
- `GET /api/config`: default age threshold and feature availability.
- `POST /api/jobs`: create a queued report job.
- `GET /api/jobs`: list recent persisted jobs.
- `GET /api/jobs/{job_id}`: read job status, progress, and confirmation
  phrases.
- `GET /api/jobs/{job_id}/events`: Server-Sent Events stream of job snapshots.
- `GET /api/jobs/{job_id}/report`: completed report plus stored cache and old
  file candidates.
- `POST /api/jobs/{job_id}/actions/clean`: dry-run or confirmed delete action
  for selected cache candidate IDs.
- `POST /api/jobs/{job_id}/actions/archive`: dry-run or confirmed archive
  action for selected old-file candidate IDs.

Report jobs are queued through a `ThreadPoolExecutor` with one worker. Job
state is persisted in SQLite so prior job summaries remain visible after a
restart. The repository stores actionable candidates and report summaries, not
every scanned file.

## Command Flows

### `analyze`

1. `cli.py` parses `--path`.
2. `workflows.run_analyze()` resolves the scan path.
3. `DiskScanner` scans the filesystem.
4. `FileAnalyzer` computes disk usage statistics.
5. `ui.py` renders summary tables, largest directories, and largest files.

This command is read-only.

### `clean`

1. Resolve scan path and age threshold.
2. Scan the filesystem.
3. Find cache candidates.
4. Render preview and savings summary.
5. Confirm deletion unless dry-run mode is active.
6. Delete candidates through `ActionExecutor.delete_files`.
7. Render execution summary and action-log path when actions were logged.

### `archive`

1. Resolve scan path and archive target.
2. Create a local `--target-path` if needed.
3. Build the archive base as `<target>/archived_files`.
4. Scan with `exclude_paths=[archive_target]`.
5. Remove symlink paths from old-file candidates.
6. Find old files above the minimum size threshold.
7. Render preview and savings summary.
8. Confirm move unless dry-run mode is active.
9. Archive candidates through `ActionExecutor.archive_files`.

### `full-report`

1. Resolve scan path and age threshold.
2. Scan with detailed progress and ETA estimation.
3. Find cache candidates with progress.
4. Find old-file candidates with progress.
5. Find exact duplicate groups unless `--no-duplicates` is set.
6. Find near-duplicate groups unless `--no-duplicates` or
   `--no-near-duplicates` is set.
7. Render usage, largest paths, cache, old-file, duplicate, and savings
   sections.

This command is read-only.

### `disk-space-manager-web`

1. Resolve or create an API token from `--token`,
   `DISK_SPACE_MANAGER_WEB_TOKEN`, or `~/.disk-space-manager-web-token`.
2. Open the SQLite repository at `--db-path`, defaulting to
   `~/.disk-space-manager-web.sqlite3`.
3. In normal mode, create the FastAPI app and serve packaged React assets.
4. In `--dev` mode, start Vite with backend URL and token environment values,
   enable CORS for the Vite origin, and run FastAPI.
5. Bind to `--host` and `--port`, defaulting to `127.0.0.1:8765`.

The web command does not run a scan by itself. Scans start when the frontend or
another token-authenticated client posts to `/api/jobs`.

### Web report job

1. Create a queued job row in SQLite.
2. Run the scanner, analyzer, and optional duplicate detector in the background
   worker.
3. Persist progress phase, percent, and message throughout the job.
4. Store report summary JSON and actionable cache/old-file candidates.
5. Mark the job completed or failed.
6. Stream job snapshots to connected SSE clients.

### Web clean/archive action

1. Require a completed job and at least one selected candidate ID.
2. Reload candidates from SQLite by job, kind, and ID.
3. For real actions, require the job's confirmation phrase.
4. For archive, resolve the selected target and skip unsafe selected paths such
   as symlinks or files under the target root.
5. Call `ActionExecutor` with `dry_run` set from the request.
6. Persist the action result in SQLite and rely on `ActionExecutor` for action
   log entries.

## Tests and Profiling

The test suite uses pytest and Click's `CliRunner`. It covers archive behavior,
target precedence, archive target exclusions, repeated archive runs, direct
executor behavior, Linux drive detection, scanner and analyzer progress,
duplicate detection, `full-report` smoke coverage, web token/auth behavior,
web report jobs, web dry-run actions, SQLite repository persistence, and
profiling helper safety.

The frontend test suite uses Vitest and React Testing Library for dashboard
smoke coverage. TypeScript checks and the production Vite build verify the
frontend source and generated static assets.

`scripts/profile_report_generation.py` is the performance harness. It owns and
recreates `downloads/benchmark`, generates deterministic sparse-file datasets,
runs `python -m disk_space_manager full-report`, and removes the benchmark tree
unless `--keep-benchmark` is specified.

## Extension Points

When adding features:

- Add Click option declarations in `cli.py`.
- Add command sequencing in `workflows.py`.
- Add terminal output and prompts in `ui.py`.
- Keep filesystem traversal concerns in `scanner.py`.
- Put classification and summary logic in `analyzer.py`.
- Put exact and near-duplicate matching logic in `duplicates.py`.
- Put file mutations only in `executor.py`.
- Put archive destination rules in `archive_targets.py`.
- Put external-drive discovery in `drive_detector.py`.
- Put web request/response models in `web/schemas.py`.
- Put web route wiring in `web/app.py`.
- Put web orchestration in `web/services.py` and persistence in
  `web/repository.py`.
- Update frontend API types and UI components in `frontend/src/` when web JSON
  shapes or dashboard behavior changes.
- Rebuild packaged frontend assets with `npm run build` when frontend source
  changes.
- Update `config.py` for default thresholds, patterns, and exclusions.
- Add tests using temporary paths, `CliRunner`, FastAPI `TestClient`, or
  frontend mocks as appropriate; avoid broad real filesystem scans in
  automated validation.
