"""Star-Slide CLI 진입점.

Phase 0에서는 골격만 — Phase 1부터 convert/validate/build-fonts 명령 구현.
"""

from __future__ import annotations

import typer
from rich.console import Console

from star_slide import __version__

app = typer.Typer(
    name="star-slide",
    help="AI 슬라이드 이미지를 편집 가능 PPTX로 역변환하는 후처리 엔진.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def version() -> None:
    """버전 출력."""
    console.print(f"star-slide {__version__}")


@app.command()
def status() -> None:
    """현재 단계와 다음 작업 안내 (Phase 0 스켈레톤 표시)."""
    console.print("[bold]Star-Slide[/bold] — Phase 0 (Spike) 스켈레톤")
    console.print("구현 예정 명령: [cyan]convert[/], [cyan]validate[/], [cyan]build-fonts[/]")
    console.print("자세한 내용은 docs/Star-Slide_DevPlan.md 참조.")


if __name__ == "__main__":
    app()
