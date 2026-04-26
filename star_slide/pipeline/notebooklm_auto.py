"""NotebookLM image-locked deck auto reconstruction pipeline.

This module intentionally orchestrates the current JSON-driven tools instead of
folding every experiment into the legacy OCR/SAM pipeline. The product target is
one command/web request:

    input.pptx -> editable-ish PPTX + QA report

For each slide it builds both a vector reconstruction and a hybrid
raster-group reconstruction, renders both, then picks the safer layout.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from star_slide.input.pptx_extractor import extract_embedded_images, extract_pdf_pages


@dataclass(frozen=True)
class NotebookLmAutoOptions:
    base_url: str = "http://localhost:8300/v1"
    model: str = "gpt-5.5"
    api_key: str = ""
    timeout_sec: float = 600.0
    retries: int = 1
    use_sam3: bool = False
    hybrid_allowed_delta: float = 0.0
    min_objects: int = 3
    llm_parallel: int = 5
    editable_embedded_text: bool = True
    font_scale: float = 0.93
    keep_intermediates: bool = False


@dataclass(frozen=True)
class NotebookLmAutoResult:
    output: Path
    workdir: Path
    selected_layout_dir: Path
    report: Path
    vector_pptx: Path
    hybrid_pptx: Path
    artifact_dir: Path
    montage: Path | None = None


class JobCancelledError(RuntimeError):
    """Raised by convert_notebooklm_auto when the cancel callback returns True."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def script_path(name: str) -> Path:
    return repo_root() / "scripts" / name


def safe_arg_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    return token or "deck"


def redact_cmd(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for part in cmd:
        if hide_next:
            redacted.append("********")
            hide_next = False
            continue
        redacted.append(part)
        if part in {"--api-key", "--vision-api-key"}:
            hide_next = True
    return redacted


def run_cmd(cmd: list[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(cmd, cwd=str(cwd or repo_root()), check=False)
    if completed.returncode != 0:
        printable = " ".join(redact_cmd(cmd))
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {printable}")


def copy_layouts(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(src_dir.glob("*.layout.json")):
        shutil.copy2(path, dst_dir / path.name)


def read_qa(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def dir_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def report_by_slide(path: Path) -> dict[int, dict[str, Any]]:
    return {int(item["slide_no"]): item for item in read_qa(path)}


def has_raster_groups(groups_dir: Path, slide_stem: str) -> bool:
    path = groups_dir / f"{slide_stem}_raster_groups.json"
    if not path.exists():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("raster_groups")
    return isinstance(groups, list) and len(groups) > 0


def build_layout_qa(
    *,
    layout_dir: Path,
    image_root: Path,
    output: Path,
    render_dir: Path,
    allow_images: bool,
    font_scale: float,
) -> None:
    layout_args = []
    for path in sorted(layout_dir.glob("*.layout.json")):
        layout_args.extend(["--layout", str(path)])
    cmd = [
        sys.executable,
        str(script_path("layout_qa.py")),
        *layout_args,
        "--image-root",
        str(image_root),
        "-o",
        str(output),
        "--render-dir",
        str(render_dir),
        "--font-scale",
        str(font_scale),
    ]
    if allow_images:
        cmd.append("--allow-images")
    run_cmd(cmd)


def generate_layouts(
    *,
    images: list[Path],
    out_dir: Path,
    options: NotebookLmAutoOptions,
    cache_buster: str,
) -> None:
    cmd = [
        sys.executable,
        str(script_path("generate_layout_batch.py")),
        "--images",
        *(str(path) for path in images),
        "--out-dir",
        str(out_dir),
        "--base-url",
        options.base_url,
        "--model",
        options.model,
        "--timeout",
        str(options.timeout_sec),
        "--min-objects",
        str(options.min_objects),
        "--cache-buster",
        cache_buster,
        "--continue-on-error",
        "--retries",
        str(options.retries),
        "--parallel",
        str(options.llm_parallel),
    ]
    if options.api_key:
        cmd.extend(["--api-key", options.api_key])
    run_cmd(cmd)


def detect_groups(
    *,
    images: list[Path],
    out_dir: Path,
    options: NotebookLmAutoOptions,
    nonce: str,
) -> None:
    cmd = [
        sys.executable,
        str(script_path("detect_raster_groups.py")),
        "--images",
        *(str(path) for path in images),
        "-o",
        str(out_dir),
        "--base-url",
        options.base_url,
        "--model",
        options.model,
        "--timeout",
        str(options.timeout_sec),
        "--nonce",
        nonce,
        "--parallel",
        str(options.llm_parallel),
    ]
    if options.api_key:
        cmd.extend(["--api-key", options.api_key])
    run_cmd(cmd)


def refine_groups_sam3(*, images: list[Path], groups_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for image in images:
        groups_json = groups_dir / f"{image.stem}_raster_groups.json"
        if not groups_json.exists() or not has_raster_groups(groups_dir, image.stem):
            continue
        run_cmd(
            [
                sys.executable,
                str(script_path("apply_sam3_box_to_raster_groups.py")),
                "--image",
                str(image),
                "--groups-json",
                str(groups_json),
                "-o",
                str(out_dir),
                "--device",
                "auto",
            ]
        )


def build_hybrid_layouts(
    *,
    layout_dir: Path,
    image_root: Path,
    groups_dir: Path,
    sam_dir: Path | None,
    out_dir: Path,
    slide_count: int,
    editable_embedded_text: bool,
) -> None:
    cmd = [
        sys.executable,
        str(script_path("apply_raster_groups_to_layout.py")),
        "--layout-dir",
        str(layout_dir),
        "--layout-template",
        "slide_{slide_no:03d}.layout.json",
        "--image-root",
        str(image_root),
        "--groups-dir",
        str(groups_dir),
        "-o",
        str(out_dir),
        "--slides",
        *(str(i) for i in range(1, slide_count + 1)),
        "--erase-mode",
        "inpaint",
        "--drop-full-slide-grid",
    ]
    if not editable_embedded_text:
        cmd.append("--rasterize-embedded-labels")
    if sam_dir is not None:
        cmd.extend(["--sam-dir", str(sam_dir)])
    run_cmd(cmd)


def select_layouts(
    *,
    vector_layout_dir: Path,
    hybrid_layout_dir: Path,
    groups_dir: Path,
    vector_report: Path,
    hybrid_report: Path,
    out_dir: Path,
    allowed_delta: float,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    vector = report_by_slide(vector_report)
    hybrid = report_by_slide(hybrid_report)
    decisions: list[dict[str, Any]] = []

    for layout in sorted(vector_layout_dir.glob("*.layout.json")):
        stem = layout.stem.removesuffix(".layout")
        slide_no = int(stem.split("_")[-1])
        h_layout = hybrid_layout_dir / layout.name
        v_diff = vector.get(slide_no, {}).get("mean_abs_diff")
        h_diff = hybrid.get(slide_no, {}).get("mean_abs_diff")
        has_groups = has_raster_groups(groups_dir, stem)
        choose_hybrid = bool(
            has_groups
            and h_layout.exists()
            and isinstance(v_diff, int | float)
            and isinstance(h_diff, int | float)
            and h_diff <= v_diff + allowed_delta
        )
        chosen = h_layout if choose_hybrid else layout
        shutil.copy2(chosen, out_dir / layout.name)
        decisions.append(
            {
                "slide_no": slide_no,
                "layout": layout.name,
                "chosen": "hybrid" if choose_hybrid else "vector",
                "has_raster_groups": has_groups,
                "vector_mean_abs_diff": v_diff,
                "hybrid_mean_abs_diff": h_diff,
            }
        )

    (out_dir / "selection_report.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_dir / "selection_report.json"


def copy_tree_files(src: Path, dst: Path, pattern: str = "*") -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.glob(pattern)):
        if path.is_file():
            shutil.copy2(path, dst / path.name)


def make_zip(source_dir: Path, zip_base: Path) -> Path | None:
    if not source_dir.exists():
        return None
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=source_dir)
    return Path(archive)


def remove_generated_sidecars(output_path: Path) -> None:
    sidecar = output_path.parent / f"_{output_path.stem}_assets"
    if sidecar.exists():
        shutil.rmtree(sidecar)


def collect_artifacts(
    *,
    input_path: Path,
    output_path: Path,
    workdir: Path,
    report_path: Path,
    vector_pptx: Path,
    hybrid_pptx: Path,
    vector_layout_dir: Path,
    hybrid_layout_dir: Path,
    selected_layout_dir: Path,
    selected_qa_dir: Path,
    keep_intermediates: bool,
) -> dict[str, Path | None]:
    artifact_dir = workdir.parent / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    final_output = output_path
    vector_artifact = artifact_dir / "candidate_vector.pptx"
    hybrid_artifact = artifact_dir / "candidate_hybrid.pptx"
    report_artifact = artifact_dir / "report.json"
    montage_artifact = artifact_dir / "montage.png"
    layout_dir = artifact_dir / "layouts"

    if vector_pptx.exists():
        shutil.copy2(vector_pptx, vector_artifact)
    if hybrid_pptx.exists():
        shutil.copy2(hybrid_pptx, hybrid_artifact)
    if report_path.exists():
        shutil.copy2(report_path, report_artifact)
    if (selected_qa_dir / "montage.png").exists():
        shutil.copy2(selected_qa_dir / "montage.png", montage_artifact)

    copy_tree_files(vector_layout_dir, layout_dir / "vector", "*.layout.json")
    copy_tree_files(vector_layout_dir, layout_dir / "vector", "*.usage.json")
    copy_tree_files(hybrid_layout_dir, layout_dir / "hybrid", "*.layout.json")
    copy_tree_files(selected_layout_dir, layout_dir / "selected", "*.layout.json")
    if (selected_layout_dir / "selection_report.json").exists():
        shutil.copy2(selected_layout_dir / "selection_report.json", layout_dir / "selected" / "selection_report.json")
    layout_zip = make_zip(layout_dir, artifact_dir / "layout_json")

    summary = {
        "input": str(input_path),
        "output": str(final_output),
        "artifacts": {
            "candidate_vector": str(vector_artifact) if vector_artifact.exists() else None,
            "candidate_hybrid": str(hybrid_artifact) if hybrid_artifact.exists() else None,
            "report": str(report_artifact) if report_artifact.exists() else None,
            "montage": str(montage_artifact) if montage_artifact.exists() else None,
            "layout_json_zip": str(layout_zip) if layout_zip else None,
        },
        "sizes": {
            "input_bytes": dir_size_bytes(input_path),
            "output_bytes": dir_size_bytes(final_output),
            "artifact_dir_bytes": dir_size_bytes(artifact_dir),
            "workdir_before_cleanup_bytes": dir_size_bytes(workdir),
        },
        "keep_intermediates": keep_intermediates,
    }
    (artifact_dir / "artifact_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    remove_generated_sidecars(output_path)
    remove_generated_sidecars(vector_pptx)
    remove_generated_sidecars(hybrid_pptx)
    if not keep_intermediates and workdir.exists():
        shutil.rmtree(workdir)

    return {
        "artifact_dir": artifact_dir,
        "report": report_artifact if report_artifact.exists() else report_path,
        "montage": montage_artifact if montage_artifact.exists() else selected_qa_dir / "montage.png",
        "vector_pptx": vector_artifact if vector_artifact.exists() else vector_pptx,
        "hybrid_pptx": hybrid_artifact if hybrid_artifact.exists() else hybrid_pptx,
        "selected_layout_dir": layout_dir / "selected" if (layout_dir / "selected").exists() else selected_layout_dir,
    }


def convert_notebooklm_auto(
    *,
    input_path: Path,
    output_path: Path,
    workdir: Path,
    options: NotebookLmAutoOptions,
    progress: Callable[..., None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> NotebookLmAutoResult:
    def emit(message: str, percent: float) -> None:
        if progress is not None:
            progress(message, percent)

    def check_cancel() -> None:
        if cancel is not None and cancel():
            raise JobCancelledError("convert_notebooklm_auto cancelled")

    workdir.mkdir(parents=True, exist_ok=True)

    check_cancel()
    emit("슬라이드 이미지 추출 중", 3)
    image_dir = workdir / "images"
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        images = extract_pdf_pages(input_path, image_dir)
    elif suffix == ".pptx":
        images = extract_embedded_images(input_path, image_dir)
    else:
        raise RuntimeError(f"unsupported input file type: {input_path.suffix}")
    if not images:
        raise RuntimeError(f"no slide images extracted from {input_path}")
    images = sorted(images)

    check_cancel()
    emit("Vision LLM layout JSON 생성 중", 10)
    vector_layout_dir = workdir / "layouts_vector"
    generate_layouts(
        images=images,
        out_dir=vector_layout_dir,
        options=options,
        cache_buster=f"job-{safe_arg_token(input_path.stem)}-layout",
    )

    check_cancel()
    emit("vector PPTX 렌더 QA 중", 38)
    vector_pptx = workdir / "vector.pptx"
    vector_qa_dir = workdir / "qa_vector"
    build_layout_qa(
        layout_dir=vector_layout_dir,
        image_root=image_dir,
        output=vector_pptx,
        render_dir=vector_qa_dir,
        allow_images=False,
        font_scale=options.font_scale,
    )

    check_cancel()
    emit("큰 이미지 그룹 탐지 중", 48)
    groups_dir = workdir / "raster_groups"
    detect_groups(
        images=images,
        out_dir=groups_dir,
        options=options,
        nonce=f"job-{safe_arg_token(input_path.stem)}-raster",
    )

    check_cancel()
    emit("SAM3 이미지 그룹 보정 중", 60)
    sam_dir = workdir / "raster_groups_sam3" if options.use_sam3 else None
    if sam_dir is not None:
        refine_groups_sam3(images=images, groups_dir=groups_dir, out_dir=sam_dir)

    check_cancel()
    emit("hybrid layout 생성 중", 70)
    hybrid_layout_dir = workdir / "layouts_hybrid"
    build_hybrid_layouts(
        layout_dir=vector_layout_dir,
        image_root=image_dir,
        groups_dir=groups_dir,
        sam_dir=sam_dir,
        out_dir=hybrid_layout_dir,
        slide_count=len(images),
        editable_embedded_text=options.editable_embedded_text,
    )

    check_cancel()
    emit("hybrid PPTX 렌더 QA 중", 78)
    hybrid_pptx = workdir / "hybrid.pptx"
    hybrid_qa_dir = workdir / "qa_hybrid"
    build_layout_qa(
        layout_dir=hybrid_layout_dir,
        image_root=image_dir,
        output=hybrid_pptx,
        render_dir=hybrid_qa_dir,
        allow_images=True,
        font_scale=options.font_scale,
    )

    check_cancel()
    emit("최종 layout 자동 선택 중", 88)
    selected_layout_dir = workdir / "layouts_selected"
    selection_report = select_layouts(
        vector_layout_dir=vector_layout_dir,
        hybrid_layout_dir=hybrid_layout_dir,
        groups_dir=groups_dir,
        vector_report=vector_qa_dir / "qa_report.json",
        hybrid_report=hybrid_qa_dir / "qa_report.json",
        out_dir=selected_layout_dir,
        allowed_delta=options.hybrid_allowed_delta,
    )

    check_cancel()
    emit("최종 PPTX 생성 및 미리보기 렌더링 중", 93)
    selected_qa_dir = workdir / "qa_selected"
    build_layout_qa(
        layout_dir=selected_layout_dir,
        image_root=image_dir,
        output=output_path,
        render_dir=selected_qa_dir,
        allow_images=True,
        font_scale=options.font_scale,
    )

    combined_report = {
        "input": str(input_path),
        "output": str(output_path),
        "workdir": str(workdir),
        "selection_report": json.loads(selection_report.read_text(encoding="utf-8")),
        "selected_qa": read_qa(selected_qa_dir / "qa_report.json"),
        "vector_qa": read_qa(vector_qa_dir / "qa_report.json"),
        "hybrid_qa": read_qa(hybrid_qa_dir / "qa_report.json"),
    }
    report_path = workdir / "notebooklm_auto_report.json"
    report_path.write_text(json.dumps(combined_report, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = collect_artifacts(
        input_path=input_path,
        output_path=output_path,
        workdir=workdir,
        report_path=report_path,
        vector_pptx=vector_pptx,
        hybrid_pptx=hybrid_pptx,
        vector_layout_dir=vector_layout_dir,
        hybrid_layout_dir=hybrid_layout_dir,
        selected_layout_dir=selected_layout_dir,
        selected_qa_dir=selected_qa_dir,
        keep_intermediates=options.keep_intermediates,
    )
    emit("완료", 100)

    return NotebookLmAutoResult(
        output=output_path,
        workdir=workdir,
        selected_layout_dir=artifacts["selected_layout_dir"] or selected_layout_dir,
        report=artifacts["report"] or report_path,
        vector_pptx=artifacts["vector_pptx"] or vector_pptx,
        hybrid_pptx=artifacts["hybrid_pptx"] or hybrid_pptx,
        artifact_dir=artifacts["artifact_dir"] or workdir.parent / "artifacts",
        montage=artifacts["montage"],
    )
