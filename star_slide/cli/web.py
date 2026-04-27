"""Star-Slide local web app command."""

from __future__ import annotations

import importlib
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="로컬 웹앱 실행.", no_args_is_help=True)
console = Console()

WEB_PORT = 5400
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@app.command("run")
def run(
    host: str = typer.Option("127.0.0.1", "--host", help="바인드 호스트"),
    reload: bool = typer.Option(False, "--reload", help="개발용 auto reload"),
    jobs_dir: Path = typer.Option(Path("output/web_jobs"), "--jobs-dir", help="웹 작업 산출물 경로"),
) -> None:
    """업로드/비동기 변환/다운로드 웹앱을 실행한다.

    포트는 5400으로 고정되어 있다 (다른 포트 사용 금지).
    """
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
    if host not in LOOPBACK_HOSTS:
        console.print(
            f"[yellow]⚠ 비-loopback host '{host}'에 바인딩합니다. "
            "이 웹앱은 인증이 없으니 신뢰된 네트워크에서만 사용하세요.[/]"
        )
    console.print(f"[bold]Star-Slide 웹앱[/bold] http://{host}:{WEB_PORT}")
    target = "star_slide.api.web_app:app" if reload else web_app.app
    uvicorn.run(target, host=host, port=WEB_PORT, reload=reload)
