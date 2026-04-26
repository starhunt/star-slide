"""Star-Slide local web app command."""

from __future__ import annotations

import importlib
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="로컬 웹앱 실행.", no_args_is_help=True)
console = Console()


@app.command("run")
def run(
    host: str = typer.Option("127.0.0.1", "--host", help="바인드 호스트"),
    port: int = typer.Option(8787, "--port", help="바인드 포트"),
    reload: bool = typer.Option(False, "--reload", help="개발용 auto reload"),
    jobs_dir: Path = typer.Option(Path("output/web_jobs"), "--jobs-dir", help="웹 작업 산출물 경로"),
) -> None:
    """업로드/비동기 변환/다운로드 웹앱을 실행한다."""
    try:
        uvicorn = importlib.import_module("uvicorn")
        web_app = importlib.import_module("star_slide.api.web_app")
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    except ImportError as exc:
        console.print("[red]웹앱 의존성이 없습니다.[/]")
        console.print("다음 명령으로 실행하세요: [bold]uv run --extra api star-slide web run[/bold]")
        raise typer.Exit(1) from exc

    web_app.WEB_ROOT = jobs_dir
    jobs_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[bold]Star-Slide 웹앱[/bold] http://{host}:{port}")
    target = "star_slide.api.web_app:app" if reload else web_app.app
    uvicorn.run(target, host=host, port=port, reload=reload)
