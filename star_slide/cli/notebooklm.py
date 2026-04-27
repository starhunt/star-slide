"""NotebookLM image-locked PPTX auto conversion command."""

from __future__ import annotations

import json
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from star_slide.pipeline.notebooklm_auto import NotebookLmAutoOptions, convert_notebooklm_auto

app = typer.Typer(help="NotebookLM 이미지 잠금 PPTX/PDF 자동 변환.", no_args_is_help=True)
console = Console()


@app.command("run")
def run(
    input_path: Path = typer.Argument(..., exists=True, help="NotebookLM PPTX/PDF 경로"),
    output: Path = typer.Option(..., "-o", "--output", help="출력 PPTX 경로"),
    workdir: Path | None = typer.Option(None, "--workdir", help="중간 산출물 디렉터리"),
    base_url: str = typer.Option(
        "http://localhost:8300/v1",
        "--base-url",
        envvar="STAR_SLIDE_BASE_URL",
    ),
    model: str = typer.Option("gpt-5.5", "--model", envvar="STAR_SLIDE_MODEL"),
    api_key: str = typer.Option(
        "",
        "--api-key",
        envvar=["STAR_SLIDE_API_KEY", "VISION_PROXY_API_KEY"],
    ),
    timeout: float = typer.Option(600.0, "--timeout", envvar="STAR_SLIDE_TIMEOUT"),
    retries: int = typer.Option(1, "--retries", envvar="STAR_SLIDE_RETRIES"),
    llm_parallel: int = typer.Option(
        5,
        "--llm-parallel",
        min=1,
        envvar="STAR_SLIDE_LLM_PARALLEL",
        help="layout/raster group LLM 호출 병렬 수",
    ),
    sam3: bool = typer.Option(False, "--sam3/--no-sam3", envvar="STAR_SLIDE_SAM3"),
    hybrid_allowed_delta: float = typer.Option(
        0.0,
        "--hybrid-allowed-delta",
        help="hybrid diff가 vector보다 이 값만큼 나빠도 raster 보존을 위해 hybrid 선택",
    ),
    editable_embedded_text: bool = typer.Option(
        True,
        "--editable-embedded-text/--rasterize-embedded-text",
        help="큰 이미지 그룹 내부에서 추출된 텍스트를 editable text로 유지",
    ),
    font_scale: float = typer.Option(
        0.93,
        "--font-scale",
        min=0.5,
        max=1.5,
        help="PPTX로 렌더링할 때 적용할 전역 텍스트 크기 배율",
    ),
    keep_intermediates: bool = typer.Option(
        False,
        "--keep-intermediates/--clean-intermediates",
        help="완료 후 QA 렌더/asset 등 큰 중간 산출물을 보존",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="진행 표시와 안내 메시지를 모두 끈다 (CI/agent 환경에 적합).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="완료 시 결과 메타데이터를 stdout에 JSON으로 출력 (에이전트 친화).",
    ),
) -> None:
    """PPTX/PDF 업로드/배치 자동화와 같은 경로로 NotebookLM deck을 변환한다.

    환경변수 (CLI 옵션이 있으면 우선):
      STAR_SLIDE_API_KEY (alias: VISION_PROXY_API_KEY), STAR_SLIDE_BASE_URL,
      STAR_SLIDE_MODEL, STAR_SLIDE_TIMEOUT, STAR_SLIDE_RETRIES,
      STAR_SLIDE_LLM_PARALLEL, STAR_SLIDE_SAM3.

    Exit code: 성공 0, 실패 1. --json 모드에서도 동일.
    """
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
        editable_embedded_text=editable_embedded_text,
        font_scale=font_scale,
        keep_intermediates=keep_intermediates,
    )

    show_progress = not (quiet or json_output)

    t0 = time.perf_counter()
    progress_ctx: Any = (
        Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        if show_progress
        else nullcontext()
    )
    with progress_ctx as progress:
        task_id = progress.add_task("NotebookLM 자동 변환 중...", total=None) if show_progress else None
        try:
            result = convert_notebooklm_auto(
                input_path=input_path,
                output_path=output,
                workdir=resolved_workdir,
                options=options,
            )
        except Exception as exc:
            if show_progress:
                progress.stop()
            if json_output:
                typer.echo(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            elif not quiet:
                console.print(f"[red]변환 실패:[/] {exc}")
            raise typer.Exit(1) from exc
        if show_progress and task_id is not None:
            progress.update(task_id, description="완료")

    elapsed = time.perf_counter() - t0

    if json_output:
        payload = {
            "ok": True,
            "elapsed_sec": round(elapsed, 2),
            "output": str(result.output),
            "workdir": str(result.workdir),
            "report": str(result.report),
            "vector_pptx": str(result.vector_pptx),
            "hybrid_pptx": str(result.hybrid_pptx),
            "artifact_dir": str(result.artifact_dir),
            "montage": str(result.montage) if result.montage else None,
            "selected_layout_dir": str(result.selected_layout_dir),
        }
        typer.echo(json.dumps(payload, ensure_ascii=False))
        return

    if quiet:
        return

    console.print()
    console.print(f"[bold green]✓ NotebookLM 자동 변환 완료[/] ({elapsed:.1f}초)")
    console.print(f"  PPTX:   {result.output}")
    console.print(f"  workdir: {result.workdir}")
    console.print(f"  report:  {result.report}")
