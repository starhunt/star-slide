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
    is_loopback = host in LOOPBACK_HOSTS
    # 호스트 기반 동적 SSRF 정책: loopback bind면 사내 LAN LLM 호출을 허용하고,
    # 비-loopback bind면 사설 IP 차단을 켠다. 자세한 내용은 AGENTS.md 참고.
    web_app.set_allow_private_networks(is_loopback)
    if not is_loopback:
        console.print(
            f"[yellow]⚠ 비-loopback host '{host}'에 바인딩합니다. "
            "인증이 없으므로 신뢰된 네트워크에서만 사용하고, "
            "사설 네트워크 LLM 호출(SSRF 방지) 차단이 활성화됩니다.[/]"
        )
    console.print(f"[bold]Star-Slide 웹앱[/bold] http://{host}:{WEB_PORT}")
    target = "star_slide.api.web_app:app" if reload else web_app.app
    uvicorn.run(target, host=host, port=WEB_PORT, reload=reload)
