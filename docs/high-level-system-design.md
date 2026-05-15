# High-Level System Design

## Purpose

Disk Space Manager is a local Unix-like disk maintenance application for macOS
and Linux. It can run as a terminal CLI or as an optional FastAPI + React web
dashboard. Both interfaces use the same Python core to scan a selected
filesystem tree, report disk usage, identify removable cache-like files, find
old large files, and archive selected files to an external drive or local
folder while preserving directory structure.

The system is intentionally conservative. Destructive operations are separated
from analysis, support dry-run previews, require explicit confirmation during
normal runs, and record action logs for review.

## Users and Workflows

The primary user is a macOS or Linux user who wants local visibility into disk
usage and safe cleanup decisions. They may use:

- The CLI for direct terminal workflows and scriptable checks.
- The web dashboard for visual summaries, job history, live progress, and
  interactive candidate review.

The main workflows are:

- Analyze disk usage with `analyze` to understand file counts, total size,
  large files, large directories, and top file extensions.
- Preview and remove cache-like files with `clean`, using dry-run mode when the
  user wants a non-mutating check.
- Archive old large files with `archive`, using either a local archive folder,
  a specified external drive path, or auto-detected external storage.
- Generate a comprehensive read-only report with `full-report`, including scan
  progress, cache candidates, old-file candidates, duplicate candidates, and
  potential savings.
- Start `disk-space-manager-web` to create report jobs, watch live progress,
  review charts/tables, select persisted candidates, and run dry-run or
  confirmed clean/archive actions.

## System Context

The application runs as a local Python process on the user's machine or on a
server that has access to the filesystem being managed. It interacts with:

- The local filesystem through `os.scandir`, stat calls, copy, delete, and
  symlink operations.
- Unix-like mount information through macOS `diskutil`, `/Volumes`, or Linux
  `/proc/self/mountinfo`.
- The terminal through Click command parsing and Rich tables, panels, and
  progress indicators.
- A local FastAPI server and packaged React frontend for the optional web
  dashboard.
- SQLite at `~/.disk-space-manager-web.sqlite3` by default for web job,
  report, candidate, and action history.
- Server-Sent Events for web report progress updates.
- Offline media libraries for duplicate analysis; no external services or APIs
  are used for file analysis.
- A local action log at `~/.disk-space-manager-actions.log`.

The web server binds to `127.0.0.1` by default and requires a token for API
routes. It can be bound to another host explicitly, but the token must be kept
private.

## Major Subsystems

### CLI and Terminal Presentation

`src/disk_space_manager/cli.py` owns the Click command group and command option
declarations. It delegates work to `workflows.py`, keeping the command layer
thin. `ui.py` owns Rich output, progress displays, summaries, and confirmation
prompts. The root `main.py` is only a checkout compatibility shim.

### Web API and Frontend

`src/disk_space_manager/web/` owns the optional FastAPI app:

- `server.py` exposes the `disk-space-manager-web` command, token setup,
  default host/port, database path, and Vite dev mode.
- `app.py` declares the HTTP API, token dependencies, SSE progress endpoint,
  and static frontend serving.
- `jobs.py` queues long-running report jobs on a single background worker.
- `services.py` translates web requests into scanner/analyzer/duplicate/action
  operations.
- `repository.py` persists web state in SQLite.
- `security.py` creates and validates API tokens.

`frontend/` contains the React/Vite source for the dashboard. The production
build is checked into `src/disk_space_manager/web/static/` so the packaged
Python web command can serve the UI without starting Vite.

### Workflow Orchestration

`workflows.py` creates scanner, analyzer, duplicate detector, and executor
objects for CLI commands. It sequences the read-only and mutating command flows
and gates destructive operations behind confirmation prompts. `archive_targets.py`
resolves archive destinations using the precedence `--target-path`, then
`--external-path`, then auto-detected external drive.

The web service layer performs equivalent orchestration for report jobs and
candidate-based actions. It stores report summaries and actionable candidates,
then only allows clean/archive actions against candidate IDs produced by a
completed job.

### Filesystem Scanner

`src/disk_space_manager/scanner.py` traverses a root path and returns file
metadata plus directory size totals. It is optimized for large trees by using
`os.scandir`, scanning top-level subdirectories in parallel, batching progress
events, and storing raw epoch timestamps instead of converting every timestamp
into `datetime` objects.

### Analyzer

`src/disk_space_manager/analyzer.py` classifies scanned file dictionaries. It
detects cache candidates using configured Unix-like directory patterns,
extensions, and filename markers. It detects old files using access time and a
minimum size threshold. It also calculates summary statistics and potential
space savings.

### Duplicate Detector

`src/disk_space_manager/duplicates.py` finds read-only exact duplicates and
advisory near duplicates. Exact matches use streamed SHA-256 hashes for
same-size candidates. Near matches use capped offline fingerprints for text,
images, videos, and audio, and skip unsupported or decode-failing files without
aborting the report.

### Action Executor

`src/disk_space_manager/executor.py` performs deletion and archive operations.
It handles dry-run accounting, writes action log entries, deletes cache files
through shared safe delete helpers, and archives old files by copying them to
the target, deleting the original file, and creating a symlink at the original
path.

### External Drive Detection

`src/disk_space_manager/drive_detector.py` discovers writable mounted external
drives. On macOS it uses `diskutil` with a `/Volumes` fallback. On Linux it
parses `/proc/self/mountinfo`, ignores pseudo/system filesystems, and considers
writable non-root mounts under common external-drive locations such as
`/media`, `/mnt`, and `/run/media`.

### Progress Estimation

`src/disk_space_manager/progress_estimator.py` turns scanner progress snapshots
into determinate Rich progress values and heuristic ETA text for CLI
`full-report`, where the final number of files is unknown until traversal
finishes. The web app persists simpler phase, percent, and message fields and
streams those job snapshots through SSE.

## Data Flow

CLI data flow:

1. Click parses options such as scan path, age threshold, duplicate flags, and
   dry-run state.
2. `workflows.py` resolves paths and creates core objects.
3. `DiskScanner.scan()` returns `files`, `directories`, `total_scanned`, and
   `errors`.
4. `FileAnalyzer` produces usage summaries, cache candidates, old-file
   candidates, and savings estimates.
5. `DuplicateDetector` produces exact and near-duplicate groups for
   `full-report` unless disabled.
6. `ui.py` renders read-only command results directly.
7. Mutating CLI workflows show summaries, request confirmation unless in
   dry-run mode, then call `ActionExecutor`.
8. `ActionExecutor` records each intended or completed action in memory and in
   the action log.

Web data flow:

1. React submits a token-authenticated report job request.
2. FastAPI validates the request and `JobManager` queues it on a single
   background worker.
3. `ReportService` runs the scanner, analyzer, and optional duplicate detector,
   while `WebRepository` persists job progress.
4. SQLite stores the job, report summary JSON, cache candidates, old-file
   candidates, and action results. It intentionally does not store every
   scanned file.
5. React receives job progress through `/api/jobs/{job_id}/events`.
6. React fetches `/api/jobs/{job_id}/report` after completion and displays
   charts, tables, duplicate groups, and actionable candidates.
7. Clean/archive requests send stored candidate IDs. Real actions require the
   job's confirmation phrase; dry-run actions do not.
8. `ActionService` reloads selected candidates from SQLite and calls
   `ActionExecutor`.

## Safety Model

Safety is a top-level system requirement because the tool can delete or move
user files.

- `analyze`, `full-report`, duplicate detection, and report-job generation are
  read-only.
- Duplicate and near-duplicate sections are advisory report output only.
- CLI `clean` and `archive` require explicit confirmation before mutating files
  unless the global `--dry-run` flag is used.
- Web clean/archive actions require token authentication, a completed report
  job, and explicit candidate IDs from that job.
- Web real actions require the action-specific confirmation phrase. Web action
  requests default to dry-run.
- Dry-run executor behavior does not delete, move, create archive output, or
  create symlinks, but it does calculate result counts and log intended actions
  as dry-run entries.
- Web dry-run archive previews with a local `target_path` avoid creating the
  target directory.
- Archive operations preserve directory structure under `archived_files`.
- Archive operations leave symlinks at original file locations so applications
  can continue resolving the old paths.
- If an archive target is inside the scanned tree, the target is excluded from
  CLI archive scans to avoid re-archiving previous output.
- Archive candidate generation skips symlink paths.
- Permission and filesystem errors are handled without aborting the whole scan
  where possible.

Automated validation must use temporary directories or intentionally small test
paths. It must not run destructive `clean` or `archive` operations against a
real home directory, system path, or external drive.

## Performance Design

The scanner is designed for large filesystem trees. Key choices are:

- Use `os.scandir` and `DirEntry.stat()` to avoid unnecessary `Path` object
  churn and repeated stat calls.
- Scan top-level directories concurrently with `ThreadPoolExecutor`, relying on
  filesystem I/O and stat calls to benefit from parallelism.
- Precompute exclusion prefixes once per scan.
- Store raw timestamps and defer `datetime` conversion to report-size result
  subsets.
- Batch progress events from worker threads to avoid excessive cross-thread
  communication.
- Duplicate detection hashes only same-size exact candidates and caps
  near-duplicate fingerprinting by media type to protect report runtime.
- The web backend runs one heavy report job at a time to avoid multiple broad
  scans competing for the same disk.

The profiling workflow in `scripts/profile_report_generation.py` owns
`downloads/benchmark`, can generate large sparse benchmark datasets, runs CLI
`full-report`, and cleans up by default.

## Operating Boundaries

The system targets Unix-like filesystems on macOS and Linux and assumes Python
3.9 or newer. It depends on Click and Rich for CLI behavior, FastAPI/Uvicorn
and Pydantic for the web API, React/Vite for the web frontend source, SQLite
for web persistence, offline media libraries for duplicate analysis, pytest for
tests, and `uv` for the documented development workflow. Node.js and npm are
needed only for frontend development or rebuilding packaged static assets.

External-drive auto-detection is best-effort and can always be bypassed with
`--target-path` or `--external-path`.

The tool does not guarantee it can inspect every file. Filesystem permissions,
system protections, broken symlinks, unmounted drives, concurrent file changes,
decoder support, and scan-time filesystem churn can all affect scan and
execution results.

The web token model is intended for local or carefully controlled server use.
It is not a multi-user login, role-based authorization system, or public hosted
service.
