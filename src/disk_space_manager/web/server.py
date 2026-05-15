"""Command entrypoint for the Disk Space Manager web app."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click
import uvicorn

from .app import create_app
from .repository import DEFAULT_DB_PATH, WebRepository
from .security import get_or_create_token


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--dev", is_flag=True, help="Run FastAPI with the Vite dev frontend.")
@click.option("--frontend-port", default=5173, show_default=True, type=int)
@click.option("--db-path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--token", default=None, help="API token. Defaults to env or local token file.")
def main(
    host: str,
    port: int,
    dev: bool,
    frontend_port: int,
    db_path: Path,
    token: Optional[str],
) -> None:
    """Start the web server."""
    api_token = get_or_create_token(token)
    repository = WebRepository(db_path.expanduser())
    frontend_process = None
    dev_origin = None

    if dev:
        frontend_dir = _find_frontend_dir()
        dev_origin = f"http://127.0.0.1:{frontend_port}"
        frontend_process = _start_frontend_dev(frontend_dir, host, port, frontend_port, api_token)
        click.echo(f"Frontend: {dev_origin}?token={api_token}")
        click.echo(f"Backend:  http://{host}:{port}")
    else:
        click.echo(f"Open: http://{host}:{port}/?token={api_token}")

    click.echo(f"Database: {repository.db_path}")
    if host != "127.0.0.1":
        click.echo("Network mode enabled. Keep the printed token private.")

    app = create_app(repository=repository, token=api_token, dev_origin=dev_origin)
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        if frontend_process:
            frontend_process.terminate()
            try:
                frontend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                frontend_process.kill()


def _find_frontend_dir() -> Path:
    candidates = [
        Path.cwd() / "frontend",
        Path(__file__).resolve().parents[3] / "frontend",
    ]
    for candidate in candidates:
        if (candidate / "package.json").exists():
            return candidate
    raise click.ClickException("Cannot find frontend/package.json for --dev mode")


def _start_frontend_dev(
    frontend_dir: Path,
    backend_host: str,
    backend_port: int,
    frontend_port: int,
    token: str,
) -> subprocess.Popen:
    env = os.environ.copy()
    env["VITE_DSM_API_BASE"] = f"http://{backend_host}:{backend_port}"
    env["VITE_DSM_TOKEN"] = token
    cmd = [
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(frontend_port),
    ]
    try:
        return subprocess.Popen(cmd, cwd=str(frontend_dir), env=env)
    except FileNotFoundError as exc:
        raise click.ClickException("npm is required for --dev mode") from exc


if __name__ == "__main__":
    sys.exit(main())
