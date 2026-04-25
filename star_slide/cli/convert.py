"""star-slide convert CLI 명령 — Phase 1 vertical slice MVP.

`star-slide convert input.pptx -o output.pptx --report report.json`
"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from star_slide.input.validator import InputError
from star_slide.pipeline.orchestrator import ConvertOptions, convert

app = typer.Typer(help="단일 파일 변환.", no_args_is_help=True)
console = Console()


@app.command()
def run(
    input_path: Path = typer.Argument(..., exists=False, help="입력 PPTX/PDF/이미지 경로"),
    output: Path = typer.Option(
        ...,
        "-o",
        "--output",
        help="출력 PPTX 경로",
    ),
    report: Path | None = typer.Option(
        None,
        "--report",
        help="품질 리포트 JSON 경로 (생략 시 출력 옆에 자동)",
    ),
    workdir: Path | None = typer.Option(
        None,
        "--workdir",
        help="중간 산출물 경로",
    ),
    no_libreoffice: bool = typer.Option(
        False,
        "--no-libreoffice",
        help="LibreOffice 사용 안 함 (임베드 이미지 직접 추출 fallback)",
    ),
    ocr_conf: float = typer.Option(
        0.7,
        "--ocr-confidence",
        help="OCR 라인 채택 최소 신뢰도",
    ),
    inpaint: bool = typer.Option(
        True,
        "--inpaint/--no-inpaint",
        help="LaMa 인페인팅으로 텍스트 자리 배경 자연 복원 (기본 ON)",
    ),
    use_sam: bool = typer.Option(
        True,
        "--sam/--no-sam",
        help="SAM 객체 분리 + SAM 정밀 마스크 인페인팅 (기본 ON)",
    ),
) -> None:
    """input → output 변환."""
    if not input_path.exists():
        console.print(f"[red]입력 파일 없음: {input_path}[/]")
        raise typer.Exit(1)

    if report is None:
        report = output.with_suffix(".report.json")

    options = ConvertOptions(
        use_libreoffice=not no_libreoffice,
        ocr_min_confidence=ocr_conf,
        inpaint=inpaint,
        use_sam=use_sam,
    )

    t0 = time.perf_counter()
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("변환 중...", total=None)
        try:
            _project, qa_report = convert(
                input_path=input_path,
                output_path=output,
                workdir=workdir,
                options=options,
            )
        except InputError as exc:
            progress.stop()
            console.print(f"[red]입력 에러:[/] {exc}")
            raise typer.Exit(1) from exc
        except NotImplementedError as exc:
            progress.stop()
            console.print(f"[yellow]미구현:[/] {exc}")
            raise typer.Exit(2) from exc
        progress.update(task, description="완료")

    elapsed = time.perf_counter() - t0

    # 결과 출력
    console.print()
    console.print(f"[bold green]✓ 변환 완료[/] ({elapsed:.1f}초)")
    console.print(f"  PPTX:   {output}")
    console.print(f"  슬라이드: {qa_report.n_slides}장")
    console.print(f"  객체:    {qa_report.n_objects}개")
    console.print(
        f"  편집 가능 비율: {qa_report.avg_editable_ratio:.0%} "
        f"(텍스트 {qa_report.text_objects_editable}/{qa_report.text_objects_total})"
    )
    if qa_report.warnings:
        console.print(f"[yellow]  경고:[/] {len(qa_report.warnings)}건")
        for w in qa_report.warnings[:3]:
            console.print(f"    - {w}")

    # 리포트 JSON
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        qa_report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    console.print(f"  리포트: {report}")
