# Profiling Report Generation

Use `scripts/profile_report_generation.py` to measure how long the `full-report`
command takes against a generated benchmark dataset.

This profiling workflow targets the CLI report pipeline. It does not exercise
the FastAPI web server, SQLite job queue, Server-Sent Events, or React
dashboard.

## Standard Run

From the repository root:

```bash
uv run python scripts/profile_report_generation.py
```

By default, the script owns `downloads/benchmark`, deletes any existing contents,
generates 1,000,000 files under a 100 x 100 directory layout, runs:

```bash
uv run python -m disk_space_manager full-report --path downloads/benchmark --age-months 6
```

and then deletes `downloads/benchmark` in cleanup.

## Smoke Test

For a quicker validation run, use a smaller dataset:

```bash
uv run python scripts/profile_report_generation.py --file-count 10000 --max-bytes 50000000
```

Use `--keep-benchmark` only when debugging the generated tree:

```bash
uv run python scripts/profile_report_generation.py --file-count 10000 --max-bytes 50000000 --keep-benchmark
```

## Dataset Shape

The default dataset creates exactly 1,000,000 files plus directories. It includes
1,000 old sparse files just over 1 MiB so the old-file analysis path is exercised,
plus deterministic cache-like `.log` and `.tmp` files so cache detection is also
covered.

The profiler uses sparse files for non-empty generated files. The report sees the
intended logical file sizes through `st_size`, while the script avoids writing
2 GB of payload bytes. The total logical file size is capped by `--max-bytes`
and defaults to `2,000,000,000`.

## Cleanup Warning

`downloads/benchmark` is treated as profiler-owned scratch space. The script
deletes the entire folder before setup and deletes it again after profiling
unless `--keep-benchmark` is passed.

The script refuses unsafe benchmark paths such as the repository root, the home
directory, the filesystem root, symlinks, or paths outside this repository.
