"""NotebookLM image-locked PPTX auto conversion command."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from star_slide.pipeline.notebooklm_auto import NotebookLmAutoOptions, convert_notebooklm_auto

app = typer.Typer(help="NotebookLM 이미지 잠금 PPTX 자동 변환.", no_args_is_help=True)
console = Console()


@app.command("run")
def run(
    input_path: Path = typer.Argument(..., exists=True, help="NotebookLM PPTX 경로"),
    output: Path = typer.Option(..., "-o", "--output", help="출력 PPTX 경로"),
    workdir: Path | None = typer.Option(None, "--workdir", help="중간 산출물 디렉터리"),
    base_url: str = typer.Option("http://localhost:8300/v1", "--base-url"),
    model: str = typer.Option("gpt-5.5", "--model"),
    api_key: str = typer.Option("", "--api-key"),
    timeout: float = typer.Option(600.0, "--timeout"),
    retries: int = typer.Option(1, "--retries"),
    llm_parallel: int = typer.Option(
        5,
        "--llm-parallel",
        min=1,
        help="layout/raster group LLM 호출 병렬 수",
    ),
    sam3: bool = typer.Option(True, "--sam3/--no-sam3"),
    hybrid_allowed_delta: float = typer.Option(
        0.0,
        "--hybrid-allowed-delta",
        help="hybrid diff가 vector보다 이 값만큼 나빠도 raster 보존을 위해 hybrid 선택",
    ),
) -> None:
    """PPTX 업로드/배치 자동화와 같은 경로로 NotebookLM deck을 변환한다."""
    resolved_workdir = workdir or output.with_suffix("")
    options = NotebookLmAutoOptions(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_sec=timeout,
        retries=retries,
        llm_parallel=llm_parallel,
        use_sam3=sam3,
        hybrid_allowed_delta=hybrid_allowed_delta,
    )

    t0 = time.perf_counter()
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("NotebookLM 자동 변환 중...", total=None)
        try:
            result = convert_notebooklm_auto(
                input_path=input_path,
                output_path=output,
                workdir=resolved_workdir,
                options=options,
            )
        except Exception as exc:
            progress.stop()
            console.print(f"[red]변환 실패:[/] {exc}")
            raise typer.Exit(1) from exc
        progress.update(task, description="완료")

    elapsed = time.perf_counter() - t0
    console.print()
    console.print(f"[bold green]✓ NotebookLM 자동 변환 완료[/] ({elapsed:.1f}초)")
    console.print(f"  PPTX:   {result.output}")
    console.print(f"  workdir: {result.workdir}")
    console.print(f"  report:  {result.report}")
