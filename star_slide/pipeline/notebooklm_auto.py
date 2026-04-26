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
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from star_slide.input.pptx_extractor import extract_embedded_images


@dataclass(frozen=True)
class NotebookLmAutoOptions:
    base_url: str = "http://localhost:8300/v1"
    model: str = "gpt-5.5"
    api_key: str = ""
    timeout_sec: float = 600.0
    retries: int = 1
    use_sam3: bool = True
    hybrid_allowed_delta: float = 0.0
    min_objects: int = 3
    llm_parallel: int = 5
    editable_embedded_text: bool = True


@dataclass(frozen=True)
class NotebookLmAutoResult:
    output: Path
    workdir: Path
    selected_layout_dir: Path
    report: Path
    vector_pptx: Path
    hybrid_pptx: Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def script_path(name: str) -> Path:
    return repo_root() / "scripts" / name


def run_cmd(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd or repo_root()), check=True)


def copy_layouts(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(src_dir.glob("*.layout.json")):
        shutil.copy2(path, dst_dir / path.name)


def read_qa(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def convert_notebooklm_auto(
    *,
    input_path: Path,
    output_path: Path,
    workdir: Path,
    options: NotebookLmAutoOptions,
) -> NotebookLmAutoResult:
    workdir.mkdir(parents=True, exist_ok=True)

    image_dir = workdir / "images"
    images = extract_embedded_images(input_path, image_dir)
    if not images:
        raise RuntimeError(f"no slide images extracted from {input_path}")
    images = sorted(images)

    vector_layout_dir = workdir / "layouts_vector"
    generate_layouts(
        images=images,
        out_dir=vector_layout_dir,
        options=options,
        cache_buster=f"{input_path.stem}-layout",
    )

    vector_pptx = workdir / "vector.pptx"
    vector_qa_dir = workdir / "qa_vector"
    build_layout_qa(
        layout_dir=vector_layout_dir,
        image_root=image_dir,
        output=vector_pptx,
        render_dir=vector_qa_dir,
        allow_images=False,
    )

    groups_dir = workdir / "raster_groups"
    detect_groups(
        images=images,
        out_dir=groups_dir,
        options=options,
        nonce=f"{input_path.stem}-raster",
    )

    sam_dir = workdir / "raster_groups_sam3" if options.use_sam3 else None
    if sam_dir is not None:
        refine_groups_sam3(images=images, groups_dir=groups_dir, out_dir=sam_dir)

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

    hybrid_pptx = workdir / "hybrid.pptx"
    hybrid_qa_dir = workdir / "qa_hybrid"
    build_layout_qa(
        layout_dir=hybrid_layout_dir,
        image_root=image_dir,
        output=hybrid_pptx,
        render_dir=hybrid_qa_dir,
        allow_images=True,
    )

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

    selected_qa_dir = workdir / "qa_selected"
    build_layout_qa(
        layout_dir=selected_layout_dir,
        image_root=image_dir,
        output=output_path,
        render_dir=selected_qa_dir,
        allow_images=True,
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

    return NotebookLmAutoResult(
        output=output_path,
        workdir=workdir,
        selected_layout_dir=selected_layout_dir,
        report=report_path,
        vector_pptx=vector_pptx,
        hybrid_pptx=hybrid_pptx,
    )
