"""Local FastAPI web app for NotebookLM PPTX conversion."""

from __future__ import annotations

import json
import re
import time
import traceback
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from star_slide.pipeline.notebooklm_auto import NotebookLmAutoOptions, convert_notebooklm_auto

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
except ImportError as exc:  # pragma: no cover - exercised by runtime environment
    raise RuntimeError(
        "FastAPI 의존성이 필요합니다. `uv run --extra api star-slide web run`으로 실행하세요."
    ) from exc


WEB_ROOT = Path("output/web_jobs")
ALLOWED_SUFFIXES = {".pptx", ".pdf"}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024


@dataclass
class JobState:
    id: str
    filename: str
    status: str = "queued"
    phase: str = "대기 중"
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str | None = None
    workdir: str | None = None
    output: str | None = None
    report: str | None = None
    montage: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


jobs: dict[str, JobState] = {}
futures: dict[str, Future[None]] = {}
jobs_lock = Lock()
executor = ThreadPoolExecutor(max_workers=2)


def create_app() -> FastAPI:
    app = FastAPI(title="Star-Slide", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/presets")
    def presets() -> dict[str, Any]:
        return {
            "providers": [
                {
                    "id": "local",
                    "label": "Local Proxy",
                    "baseUrl": "http://localhost:8300/v1",
                    "model": "gpt-5.5",
                    "hint": "star-cliproxy 같은 로컬 OpenAI 호환 프록시",
                },
                {
                    "id": "openai",
                    "label": "OpenAI",
                    "baseUrl": "https://api.openai.com/v1",
                    "model": "",
                    "hint": "OpenAI API key와 vision 지원 모델명을 입력",
                },
                {
                    "id": "gemini",
                    "label": "Gemini",
                    "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "model": "gemini-2.5-flash",
                    "hint": "Gemini OpenAI-compatible endpoint 또는 로컬 프록시 모델명 사용",
                },
                {
                    "id": "custom",
                    "label": "Custom",
                    "baseUrl": "",
                    "model": "",
                    "hint": "OpenAI 호환 /v1/chat/completions endpoint",
                },
            ],
            "defaults": {
                "timeout": 600,
                "retries": 1,
                "llmParallel": 5,
                "fontScale": 0.93,
                "keepIntermediates": False,
                "sam3": True,
                "hybridAllowedDelta": 0.0,
                "editableEmbeddedText": True,
            },
        }

    @app.post("/api/jobs")
    async def submit_job(request: Request) -> JSONResponse:
        filename = request.query_params.get("filename", "upload.pptx")
        safe_name = Path(filename).name
        if Path(safe_name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail="PPTX/PDF 파일만 업로드할 수 있습니다.")

        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="업로드 파일이 비어 있습니다.")
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="업로드 파일이 너무 큽니다.")

        raw_options = request.headers.get("x-star-slide-options", "{}")
        try:
            options_payload = json.loads(raw_options)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="옵션 JSON을 파싱할 수 없습니다.") from exc

        job_id = uuid.uuid4().hex
        job_dir = WEB_ROOT / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        input_path = job_dir / safe_name
        input_path.write_bytes(body)

        state = JobState(
            id=job_id,
            filename=safe_name,
            workdir=str(job_dir / "work"),
            output=str(job_dir / "result.pptx"),
            report=str(job_dir / "artifacts" / "report.json"),
            montage=str(job_dir / "artifacts" / "montage.png"),
            options=public_options(options_payload),
        )
        with jobs_lock:
            jobs[job_id] = state
            futures[job_id] = executor.submit(run_job, job_id, input_path, job_dir, options_payload)
        return JSONResponse(job_snapshot(state))

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        sync_saved_jobs()
        with jobs_lock:
            current_jobs = sorted(jobs.values(), key=lambda item: item.created_at, reverse=True)
        return [job_snapshot(job) for job in current_jobs]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return job_snapshot(require_job(job_id))

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str) -> FileResponse:
        job = require_job(job_id)
        if job.status != "done" or not job.output or not Path(job.output).exists():
            raise HTTPException(status_code=404, detail="완료된 PPTX가 없습니다.")
        return FileResponse(
            job.output,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"{Path(job.filename).stem}_editable.pptx",
        )

    @app.get("/api/jobs/{job_id}/montage")
    def montage(job_id: str) -> FileResponse:
        job = require_job(job_id)
        if not job.montage or not Path(job.montage).exists():
            raise HTTPException(status_code=404, detail="미리보기 이미지가 없습니다.")
        return FileResponse(job.montage, media_type="image/png")

    @app.get("/api/jobs/{job_id}/report")
    def report(job_id: str) -> FileResponse:
        job = require_job(job_id)
        if not job.report or not Path(job.report).exists():
            raise HTTPException(status_code=404, detail="리포트가 없습니다.")
        return FileResponse(job.report, media_type="application/json", filename="notebooklm_auto_report.json")

    @app.get("/api/jobs/{job_id}/report-summary")
    def report_summary(job_id: str) -> dict[str, Any]:
        job = require_job(job_id)
        if not job.report or not Path(job.report).exists():
            raise HTTPException(status_code=404, detail="리포트가 없습니다.")
        return build_report_summary(job, json.loads(Path(job.report).read_text(encoding="utf-8")))

    @app.get("/api/jobs/{job_id}/artifact/{name}")
    def artifact(job_id: str, name: str) -> FileResponse:
        job = require_job(job_id)
        path = resolve_artifact_path(job, name)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="산출물을 찾을 수 없습니다.")
        media_type = "application/zip" if path.suffix == ".zip" else "application/octet-stream"
        if path.suffix == ".pptx":
            media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/api/jobs/{job_id}/layout-summary")
    def layout_summary(job_id: str) -> dict[str, Any]:
        job = require_job(job_id)
        path = resolve_artifact_path(job, "layout-json")
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="Layout JSON 산출물이 없습니다.")
        return build_layout_summary(job, path)

    return app


def sync_saved_jobs() -> None:
    if not WEB_ROOT.exists():
        return
    with jobs_lock:
        known = set(jobs)
    for job_dir in sorted(WEB_ROOT.iterdir()):
        if not job_dir.is_dir() or job_dir.name in known:
            continue
        result = job_dir / "result.pptx"
        report = job_dir / "artifacts" / "report.json"
        montage = job_dir / "artifacts" / "montage.png"
        if not report.exists():
            report = job_dir / "work" / "notebooklm_auto_report.json"
        if not montage.exists():
            montage = job_dir / "work" / "qa_selected" / "montage.png"
        source_files = [
            path
            for suffix in sorted(ALLOWED_SUFFIXES)
            for path in job_dir.glob(f"*{suffix}")
            if path.name != "result.pptx" and not path.name.startswith("result_")
        ]
        source = source_files[0] if source_files else None
        if not result.exists() and not report.exists():
            continue
        created_at = source.stat().st_mtime if source and source.exists() else job_dir.stat().st_mtime
        state = JobState(
            id=job_dir.name,
            filename=source.name if source else job_dir.name,
            status="done" if result.exists() else "failed",
            phase="완료" if result.exists() else "결과 파일 없음",
            progress=100,
            created_at=created_at,
            updated_at=max(result.stat().st_mtime if result.exists() else created_at, report.stat().st_mtime if report.exists() else created_at),
            workdir=str(job_dir / "work"),
            output=str(result),
            report=str(report) if report.exists() else None,
            montage=str(montage) if montage.exists() else None,
        )
        with jobs_lock:
            jobs.setdefault(state.id, state)


def resolve_artifact_path(job: JobState, name: str) -> Path | None:
    allowed = {
        "vector": "candidate_vector.pptx",
        "hybrid": "candidate_hybrid.pptx",
        "layout-json": "layout_json.zip",
        "manifest": "artifact_manifest.json",
    }
    filename = allowed.get(name)
    if filename is None:
        return None
    candidates: list[Path] = []
    if job.report:
        candidates.append(Path(job.report).parent / filename)
    candidates.append(WEB_ROOT / job.id / "artifacts" / filename)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0] if candidates else None


def build_layout_summary(job: JobState, layout_zip: Path) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    with zipfile.ZipFile(layout_zip) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith("selected/") and name.endswith(".layout.json"))
        for name in names:
            payload = json.loads(archive.read(name).decode("utf-8"))
            objects = payload.get("objects") if isinstance(payload.get("objects"), list) else []
            counts: dict[str, int] = {}
            for obj in objects:
                kind = str(obj.get("type", "unknown"))
                counts[kind] = counts.get(kind, 0) + 1
            title = next(
                (
                    object_text(obj)
                    for obj in objects
                    if obj.get("type") == "text" and "title" in str(obj.get("name", "")).lower()
                ),
                "",
            )
            raster_meta = payload.get("metadata", {}).get("raster_group_replacement", {})
            groups = raster_meta.get("groups") if isinstance(raster_meta, dict) else []
            slides.append(
                {
                    "slide_no": len(slides) + 1,
                    "id": payload.get("id"),
                    "title": title,
                    "object_count": len(objects),
                    "type_counts": counts,
                    "raster_group_count": len(groups) if isinstance(groups, list) else 0,
                    "punched_text_regions": raster_meta.get("punched_text_regions") if isinstance(raster_meta, dict) else None,
                }
            )
    return {
        "job": {"id": job.id, "filename": job.filename},
        "layout_zip": str(layout_zip),
        "slide_count": len(slides),
        "slides": slides,
    }


def require_job(job_id: str) -> JobState:
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return job


def job_snapshot(job: JobState) -> dict[str, Any]:
    data = asdict(job)
    if job.status == "done":
        data["artifacts"] = {
            "layout_json": bool((path := resolve_artifact_path(job, "layout-json")) and path.exists()),
            "vector": bool((path := resolve_artifact_path(job, "vector")) and path.exists()),
            "hybrid": bool((path := resolve_artifact_path(job, "hybrid")) and path.exists()),
        }
    if job.status != "running" or not job.workdir:
        return data

    workdir = Path(job.workdir)
    images = sorted((workdir / "images").glob("*.png"))
    total = len(images)
    if total <= 0:
        return data

    vector_layouts = len(list((workdir / "layouts_vector").glob("*.layout.json")))
    raster_groups = len(list((workdir / "raster_groups").glob("*_raster_groups.json")))
    sam_reports = len(list((workdir / "raster_groups_sam3").glob("*_sam3_report.json")))
    hybrid_layouts = len(list((workdir / "layouts_hybrid").glob("*.layout.json")))
    selected_layouts = len(list((workdir / "layouts_selected").glob("*.layout.json")))

    progress = float(data["progress"])
    if progress < 38 and vector_layouts < total:
        data["phase"] = f"Vision LLM layout JSON 생성 중 ({vector_layouts}/{total})"
        data["progress"] = max(progress, 10 + 28 * vector_layouts / total)
    elif progress < 60 and raster_groups < total:
        data["phase"] = f"큰 이미지 그룹 탐지 중 ({raster_groups}/{total})"
        data["progress"] = max(progress, 48 + 12 * raster_groups / total)
    elif progress < 70 and sam_reports < total and (workdir / "raster_groups_sam3").exists():
        data["phase"] = f"SAM3 이미지 그룹 보정 중 ({sam_reports}/{total})"
        data["progress"] = max(progress, 60 + 10 * sam_reports / total)
    elif progress < 78 and hybrid_layouts < total:
        data["phase"] = f"hybrid layout 생성 중 ({hybrid_layouts}/{total})"
        data["progress"] = max(progress, 70 + 8 * hybrid_layouts / total)
    elif progress < 93 and selected_layouts < total:
        data["phase"] = f"최종 layout 자동 선택 중 ({selected_layouts}/{total})"
        data["progress"] = max(progress, 88 + 5 * selected_layouts / total)
    return data


def public_options(options_payload: dict[str, Any]) -> dict[str, Any]:
    public = dict(options_payload)
    if public.get("apiKey"):
        public["apiKey"] = "********"
    return public


def update_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = time.time()


def run_job(job_id: str, input_path: Path, job_dir: Path, payload: dict[str, Any]) -> None:
    def progress(message: str, percent: float) -> None:
        update_job(job_id, status="running", phase=message, progress=percent)

    try:
        update_job(job_id, status="running", phase="작업 시작", progress=1)
        output_path = job_dir / "result.pptx"
        workdir = job_dir / "work"
        options = NotebookLmAutoOptions(
            base_url=str(payload.get("baseUrl") or "http://localhost:8300/v1"),
            model=str(payload.get("model") or "gpt-5.5"),
            api_key=str(payload.get("apiKey") or ""),
            timeout_sec=float(payload.get("timeout") or 600),
            retries=int(payload.get("retries") or 1),
            llm_parallel=int(payload.get("llmParallel") or 5),
            font_scale=float(payload.get("fontScale") or 0.93),
            keep_intermediates=bool(payload.get("keepIntermediates", False)),
            use_sam3=bool(payload.get("sam3", True)),
            hybrid_allowed_delta=float(payload.get("hybridAllowedDelta") or 0.0),
            editable_embedded_text=bool(payload.get("editableEmbeddedText", True)),
        )
        result = convert_notebooklm_auto(
            input_path=input_path,
            output_path=output_path,
            workdir=workdir,
            options=options,
            progress=progress,
        )
        update_job(
            job_id,
            status="done",
            phase="완료",
            progress=100,
            output=str(result.output),
            report=str(result.report),
            montage=str(result.montage) if result.montage else None,
        )
    except Exception as exc:  # pragma: no cover - depends on external tools/model
        error_path = job_dir / "error.log"
        error_path.write_text(sanitize_error(traceback.format_exc()), encoding="utf-8")
        update_job(job_id, status="failed", phase="실패", error=sanitize_error(str(exc)), progress=100)


def sanitize_error(message: str) -> str:
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-********", message)
    message = re.sub(r"(--api-key['\", ]+)([^'\",\\]]+)", r"\1********", message)
    message = re.sub(r"(apiKey['\": ]+)([^'\",\\]]+)", r"\1********", message)
    return message


def _avg_diff(items: list[dict[str, Any]]) -> float | None:
    values = [item.get("mean_abs_diff") for item in items]
    numeric = [float(value) for value in values if isinstance(value, int | float)]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 2)


def _file_size(path: str | None) -> int | None:
    if not path:
        return None
    p = Path(path)
    return p.stat().st_size if p.exists() else None


def object_text(obj: dict[str, Any]) -> str:
    text = obj.get("text")
    if isinstance(text, str):
        return text
    lines = obj.get("lines")
    if isinstance(lines, list):
        return " ".join(str(line) for line in lines)
    return ""


def build_report_summary(job: JobState, report: dict[str, Any]) -> dict[str, Any]:
    selected_qa = report.get("selected_qa") if isinstance(report.get("selected_qa"), list) else []
    vector_qa = report.get("vector_qa") if isinstance(report.get("vector_qa"), list) else []
    hybrid_qa = report.get("hybrid_qa") if isinstance(report.get("hybrid_qa"), list) else []
    decisions = report.get("selection_report") if isinstance(report.get("selection_report"), list) else []

    chosen_counts = {"vector": 0, "hybrid": 0}
    for item in decisions:
        chosen = item.get("chosen")
        if chosen in chosen_counts:
            chosen_counts[chosen] += 1

    worst = sorted(
        (
            item
            for item in selected_qa
            if isinstance(item.get("mean_abs_diff"), int | float)
        ),
        key=lambda item: float(item["mean_abs_diff"]),
        reverse=True,
    )[:5]
    vector_artifact = resolve_artifact_path(job, "vector")
    hybrid_artifact = resolve_artifact_path(job, "hybrid")
    layout_artifact = resolve_artifact_path(job, "layout-json")

    return {
        "job": {
            "id": job.id,
            "filename": job.filename,
            "status": job.status,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "options": job.options,
        },
        "summary": {
            "slide_count": len(selected_qa),
            "selected_avg_diff": _avg_diff(selected_qa),
            "vector_avg_diff": _avg_diff(vector_qa),
            "hybrid_avg_diff": _avg_diff(hybrid_qa),
            "chosen_vector_count": chosen_counts["vector"],
            "chosen_hybrid_count": chosen_counts["hybrid"],
        },
        "worst_slides": [
            {
                "slide_no": item.get("slide_no"),
                "layout_id": item.get("layout_id"),
                "object_count": item.get("object_count"),
                "picture_count": item.get("picture_count"),
                "mean_abs_diff": item.get("mean_abs_diff"),
            }
            for item in worst
        ],
        "decisions": decisions,
        "files": {
            "output": job.output,
            "report": job.report,
            "montage": job.montage,
            "candidate_vector": str(vector_artifact) if vector_artifact else None,
            "candidate_hybrid": str(hybrid_artifact) if hybrid_artifact else None,
            "layout_json": str(layout_artifact) if layout_artifact else None,
            "output_bytes": _file_size(job.output),
            "report_bytes": _file_size(job.report),
            "montage_bytes": _file_size(job.montage),
            "candidate_vector_bytes": _file_size(str(vector_artifact) if vector_artifact else None),
            "candidate_hybrid_bytes": _file_size(str(hybrid_artifact) if hybrid_artifact else None),
            "layout_json_bytes": _file_size(str(layout_artifact) if layout_artifact else None),
        },
    }


app = create_app()


INDEX_HTML = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Star-Slide</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%230b111b'/%3E%3Crect x='13' y='14' width='38' height='28' rx='4' fill='%233b82f6'/%3E%3Cpath d='M20 24h24M20 31h16' stroke='white' stroke-width='4' stroke-linecap='round'/%3E%3Cpath d='M18 49h28' stroke='%232dd4bf' stroke-width='5' stroke-linecap='round'/%3E%3Ccircle cx='49' cy='42' r='6' fill='%232dd4bf'/%3E%3C/svg%3E" />
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b111b;
      --surface: #101827;
      --surface-2: #131f30;
      --surface-3: #172337;
      --ink: #eef4ff;
      --muted: #94a3b8;
      --line: #2a3a50;
      --field: #0d1624;
      --field-border: #34465f;
      --blue: #3b82f6;
      --teal: #2dd4bf;
      --orange: #fb923c;
      --danger: #f87171;
      --shadow: rgba(0, 0, 0, .42);
    }
    body[data-theme="light"] {
      color-scheme: light;
      --bg: #ffffff;
      --surface: #fbfcfe;
      --surface-2: #ffffff;
      --surface-3: #f8fafc;
      --ink: #111827;
      --muted: #667085;
      --line: #d8dee8;
      --field: #ffffff;
      --field-border: #cfd6e4;
      --blue: #2563eb;
      --teal: #0f766e;
      --orange: #ea580c;
      --danger: #b42318;
      --shadow: rgba(15, 23, 42, .20);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
    }
    header {
      height: 64px;
      display: grid;
      grid-template-columns: minmax(160px, 240px) minmax(0, 1fr) minmax(160px, 240px);
      align-items: center;
      padding: 0 28px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }
    .brand { font-size: 19px; font-weight: 750; }
    .tagline {
      min-width: 0;
      text-align: center;
      font-size: 15px;
      font-weight: 800;
      color: var(--ink);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .header-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 12px;
    }
    .theme-toggle {
      min-width: 104px;
      color: var(--ink);
      border-color: var(--field-border);
      background: var(--surface-2);
    }
    .shell {
      display: grid;
      grid-template-columns: minmax(420px, 520px) minmax(0, 1fr);
      min-height: calc(100vh - 64px);
    }
    aside {
      border-right: 1px solid var(--line);
      padding: 22px;
      background: var(--surface);
      overflow-y: auto;
    }
    main { padding: 22px; overflow: auto; }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h2 { font-size: 16px; margin-bottom: 12px; }
    label { display: block; font-size: 12px; font-weight: 700; color: var(--ink); margin: 12px 0 6px; }
    .label-row {
      display: flex;
      align-items: center;
      gap: 6px;
      margin: 12px 0 6px;
    }
    .label-row label { margin: 0; }
    .help {
      width: 18px;
      height: 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--field-border);
      border-radius: 50%;
      color: var(--muted);
      background: var(--surface-2);
      font-size: 12px;
      font-weight: 800;
      cursor: help;
    }
    input, select {
      width: 100%;
      height: 38px;
      border: 1px solid var(--field-border);
      border-radius: 7px;
      padding: 0 10px;
      font-size: 14px;
      color: var(--ink);
      background: var(--field);
    }
    input[type="checkbox"] { width: 16px; height: 16px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .provider-controls {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: end;
      gap: 10px;
    }
    .provider-controls button { white-space: nowrap; }
    .info-box {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      color: var(--muted);
      background: var(--surface-3);
      font-size: 12px;
      line-height: 1.5;
    }
    .custom-provider-fields[hidden] { display: none; }
    .provider-field-actions {
      margin-top: 10px;
      justify-content: flex-start;
    }
    .drop {
      display: grid;
      place-items: center;
      min-height: 168px;
      border: 2px dashed var(--field-border);
      border-radius: 8px;
      background: var(--surface-2);
      text-align: center;
      padding: 20px;
      cursor: pointer;
    }
    .drop.drag { border-color: var(--blue); background: color-mix(in srgb, var(--blue) 13%, var(--surface-2)); }
    .drop strong { display: block; font-size: 17px; margin-bottom: 7px; }
    .hint { color: var(--muted); font-size: 12px; line-height: 1.45; }
    .actions { display: flex; gap: 10px; margin-top: 16px; }
    .upload-actions { margin-top: 12px; }
    button, .button {
      height: 38px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      border: 1px solid #1d4ed8;
      border-radius: 7px;
      padding: 0 14px;
      color: #fff;
      background: var(--blue);
      font-weight: 750;
      text-decoration: none;
      cursor: pointer;
    }
    button.secondary, .button.secondary {
      color: var(--ink);
      border-color: var(--field-border);
      background: var(--surface-2);
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .checkline { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 13px; }
    .jobs {
      display: grid;
      gap: 12px;
    }
    .job {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: var(--surface-2);
    }
    .job-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }
    .job-title { font-weight: 760; overflow-wrap: anywhere; }
    .job-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      color: var(--muted);
      background: var(--surface-3);
      font-size: 12px;
    }
    .badge {
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 750;
      background: color-mix(in srgb, var(--blue) 18%, var(--surface-3));
      color: var(--blue);
      white-space: nowrap;
    }
    .badge.done { background: color-mix(in srgb, var(--teal) 18%, var(--surface-3)); color: var(--teal); }
    .badge.failed { background: color-mix(in srgb, var(--danger) 18%, var(--surface-3)); color: var(--danger); }
    .bar {
      height: 8px;
      border-radius: 999px;
      background: var(--surface-3);
      overflow: hidden;
      margin: 8px 0;
    }
    .bar > div { height: 100%; background: linear-gradient(90deg, var(--blue), var(--teal)); }
    .job-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .pager {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      margin-bottom: 12px;
    }
    .pager button {
      height: 32px;
      padding: 0 10px;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(15, 23, 42, .46);
      z-index: 20;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      width: min(980px, 96vw);
      max-height: 88vh;
      overflow: auto;
      border-radius: 8px;
      background: var(--surface-2);
      box-shadow: 0 24px 80px var(--shadow);
    }
    .modal-head {
      position: sticky;
      top: 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-2);
    }
    .modal-body { padding: 18px; }
    .preview {
      display: block;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
    }
    .report-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 14px 0 18px;
    }
    .report-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface-3);
    }
    .report-card strong { display: block; font-size: 20px; margin-top: 4px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; }
    th { color: var(--muted); background: var(--surface-3); }
    .empty {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 26px;
      color: var(--muted);
      background: var(--surface-2);
    }
    .setting-box {
      border-top: 1px solid var(--line);
      margin-top: 18px;
      padding-top: 16px;
    }
    @media (max-width: 980px) {
      header { grid-template-columns: 1fr auto; height: auto; min-height: 64px; gap: 10px; padding: 14px 18px; }
      .tagline { grid-column: 1 / -1; grid-row: 2; text-align: left; white-space: normal; }
      .shell { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">Star-Slide</div>
    <div class="tagline">이미지 잠금 슬라이드를 편집 가능한 PPTX로 변환합니다</div>
    <div class="header-actions">
      <button id="themeToggle" class="secondary theme-toggle" type="button">라이트 모드</button>
    </div>
  </header>
  <div class="shell">
    <aside>
      <h2>파일 업로드</h2>
      <div id="drop" class="drop">
        <div>
          <strong>PPTX/PDF를 드래그하거나 클릭</strong>
          <span id="fileLabel" class="hint">NotebookLM에서 내려받은 .pptx 또는 .pdf 파일</span>
        </div>
      </div>
      <input id="file" type="file" accept=".pptx,.pdf" hidden />
      <div class="actions upload-actions">
        <button id="start">변환 시작</button>
      </div>

      <div class="setting-box">
        <h2>LLM Provider</h2>
        <div class="info-box">
          LLM은 슬라이드 이미지를 layout JSON으로 해석하고 큰 이미지 영역을 판단하는 데 사용됩니다.
          기본 흐름은 슬라이드당 약 2회 호출이며, retry 설정에 따라 추가 호출될 수 있습니다.
        </div>
        <div class="provider-controls">
          <div>
            <label for="provider">Provider</label>
            <select id="provider"></select>
          </div>
          <button id="addCustom" class="secondary" type="button">Custom 추가</button>
        </div>
        <div id="customProviderFields" class="custom-provider-fields" hidden>
          <label for="customName">Custom Name</label>
          <input id="customName" placeholder="예: 사내 프록시" />
          <div class="actions provider-field-actions">
            <button id="deleteCustom" class="secondary" type="button">Custom 삭제</button>
          </div>
        </div>
        <label for="baseUrl">Base URL</label>
        <input id="baseUrl" placeholder="http://localhost:8300/v1" />
        <label for="model">Model</label>
        <input id="model" placeholder="gpt-5.5" />
        <label for="apiKey">API Key</label>
        <input id="apiKey" type="password" placeholder="sk-..." />
        <div id="providerHint" class="hint"></div>
      </div>

      <div class="setting-box">
        <h2>변환 옵션</h2>
        <div class="row">
          <div>
            <label for="timeout">Timeout</label>
            <input id="timeout" type="number" min="60" step="30" />
          </div>
          <div>
            <label for="retries">Retries</label>
            <input id="retries" type="number" min="0" step="1" />
          </div>
        </div>
        <div class="row">
          <div>
            <div class="label-row">
              <label for="llmParallel">LLM 병렬 수</label>
              <span class="help" title="여러 슬라이드의 LLM 분석 요청을 동시에 몇 개까지 실행할지 정합니다. 값이 높으면 빠르지만 API rate limit이나 로컬 프록시 부하가 커질 수 있습니다.">?</span>
            </div>
            <input id="llmParallel" type="number" min="1" max="10" step="1" />
          </div>
          <div>
            <div class="label-row">
              <label for="fontScale">폰트 배율</label>
              <span class="help" title="PPTX로 다시 렌더링할 때 모든 편집 가능 텍스트 크기에 곱하는 값입니다. 작게 보이면 1.0에 가깝게, 커 보이면 0.9 이하로 낮춥니다.">?</span>
            </div>
            <input id="fontScale" type="number" min="0.5" max="1.5" step="0.01" />
          </div>
        </div>
        <div class="row">
          <div>
            <div class="label-row">
              <label for="hybridAllowedDelta">Hybrid 허용 diff</label>
              <span class="help" title="원본 대비 픽셀 차이(diff)가 vector보다 이 값만큼 더 나빠도 hybrid를 선택합니다. 0이면 hybrid가 같거나 더 좋을 때만 선택합니다. 값을 키우면 이미지 덩어리 보존을 더 선호합니다.">?</span>
            </div>
            <input id="hybridAllowedDelta" type="number" step="0.1" />
          </div>
          <div></div>
        </div>
        <label class="checkline"><input id="sam3" type="checkbox" /> SAM3 bbox refinement <span class="help" title="LLM이 찾은 큰 이미지 영역의 경계를 SAM3로 더 정확히 보정합니다. 켜면 느려질 수 있지만 이미지 객체 crop 품질이 좋아질 수 있습니다.">?</span></label>
        <label class="checkline"><input id="editableEmbeddedText" type="checkbox" /> 큰 이미지 내부 텍스트를 편집 가능하게 유지 <span class="help" title="큰 그림/도식 내부의 텍스트도 PowerPoint 텍스트로 추출하려고 시도합니다. 켜면 편집성은 높아지지만 배경 지우기 흔적이 생길 수 있습니다. 일부 복잡한 패널은 자동으로 이미지 보존을 우선합니다.">?</span></label>
        <label class="checkline"><input id="keepIntermediates" type="checkbox" /> 큰 중간 산출물 보존 <span class="help" title="QA 렌더 PNG, SAM crop, overlay, 임시 asset 등 디버깅용 파일을 모두 남깁니다. 기본은 꺼짐이며 최종 산출물과 리포트만 보존해 용량을 줄입니다.">?</span></label>
      </div>

      <div class="actions">
        <button id="save" class="secondary">설정 저장</button>
      </div>
    </aside>
    <main>
      <h1 style="font-size:22px;margin-bottom:16px;">작업 상태</h1>
      <div id="jobs" class="jobs">
        <div class="empty">아직 실행한 작업이 없습니다.</div>
      </div>
    </main>
  </div>
  <div id="modalBackdrop" class="modal-backdrop" onclick="closeModal(event)">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2 id="modalTitle">상세</h2>
        <button class="secondary" onclick="closeModal()">닫기</button>
      </div>
      <div id="modalBody" class="modal-body"></div>
    </div>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    let presets = null;
    let selectedFile = null;
    let pollTimer = null;
    let activeProvider = "local";
    let currentPage = 1;
    const pageSize = 5;

    const optionFields = ["timeout","retries","llmParallel","fontScale","hybridAllowedDelta","sam3","editableEmbeddedText","keepIntermediates"];
    const settingsKey = "starSlideSettings";
    const themeKey = "starSlideTheme";
    const customPrefix = "custom:";

    async function init() {
      applyTheme(localStorage.getItem(themeKey) || "dark");
      presets = await (await fetch("/api/presets")).json();
      loadSettings();
      $("provider").addEventListener("change", changeProvider);
      $("addCustom").addEventListener("click", addCustomProvider);
      $("deleteCustom").addEventListener("click", deleteCustomProvider);
      $("customName").addEventListener("change", renameSelectedCustomProvider);
      $("save").addEventListener("click", saveSettings);
      $("start").addEventListener("click", submit);
      $("themeToggle").addEventListener("click", toggleTheme);
      setupDrop();
      await refreshJobs();
      pollTimer = setInterval(refreshJobs, 2500);
    }

    function applyTheme(theme) {
      const next = theme === "light" ? "light" : "dark";
      document.body.dataset.theme = next;
      localStorage.setItem(themeKey, next);
      const button = $("themeToggle");
      if (button) button.textContent = next === "dark" ? "라이트 모드" : "다크 모드";
    }

    function toggleTheme() {
      applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
    }

    function loadSettings() {
      const saved = readStoredSettings();
      const selectedProvider = renderProviderOptions(saved.provider || "local");
      $("provider").value = selectedProvider;
      activeProvider = $("provider").value;
      applyProvider(false);
      const merged = {...presets.defaults, ...(saved.options || legacyOptions(saved))};
      for (const key of optionFields) {
        const el = $(key);
        if (!el) continue;
        if (el.type === "checkbox") el.checked = Boolean(merged[key]);
        else el.value = merged[key] ?? "";
      }
    }

    function readStoredSettings() {
      try {
        const saved = JSON.parse(localStorage.getItem(settingsKey) || "{}");
        const normalized = normalizeSettings(saved);
        if (normalized.changed) localStorage.setItem(settingsKey, JSON.stringify(normalized.settings));
        return normalized.settings;
      } catch {
        return normalizeSettings({}).settings;
      }
    }

    function normalizeSettings(raw) {
      const saved = raw && typeof raw === "object" ? raw : {};
      let changed = false;
        if (!saved.providers) {
          const provider = saved.provider || "local";
          saved.providers = {
            [provider]: {
              baseUrl: saved.baseUrl || "",
              model: saved.model || "",
              apiKey: saved.apiKey || "",
            },
          };
        changed = true;
      }
      if (!Array.isArray(saved.customProviders)) {
        saved.customProviders = [];
        changed = true;
      }
      if ((saved.provider === "custom" || saved.providers.custom) && !saved.customProviders.length) {
        const id = makeProviderId();
        const oldCustom = saved.providers.custom || {};
        saved.customProviders.push({
          id,
          name: "Custom Provider",
          baseUrl: oldCustom.baseUrl || saved.baseUrl || "",
          model: oldCustom.model || saved.model || "",
          apiKey: oldCustom.apiKey || saved.apiKey || "",
        });
        saved.provider = `${customPrefix}${id}`;
        delete saved.providers.custom;
        changed = true;
      }
      for (const item of saved.customProviders) {
        if (!item.id) {
          item.id = makeProviderId();
          changed = true;
        }
        if (!item.name) {
          item.name = "Custom Provider";
          changed = true;
        }
      }
      return {settings: saved, changed};
    }

    function makeProviderId() {
      if (window.crypto?.randomUUID) return window.crypto.randomUUID();
      return `custom_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    }

    function writeStoredSettings(settings) {
      localStorage.setItem(settingsKey, JSON.stringify(settings));
    }

    function builtInProviders() {
      return presets.providers.filter(provider => provider.id !== "custom");
    }

    function isCustomProvider(providerId) {
      return String(providerId || "").startsWith(customPrefix);
    }

    function customId(providerId) {
      return String(providerId || "").slice(customPrefix.length);
    }

    function findCustomProvider(settings, providerId) {
      if (!isCustomProvider(providerId)) return null;
      const id = customId(providerId);
      return settings.customProviders.find(item => item.id === id) || null;
    }

    function providerExists(settings, providerId) {
      if (isCustomProvider(providerId)) return Boolean(findCustomProvider(settings, providerId));
      return builtInProviders().some(provider => provider.id === providerId);
    }

    function renderProviderOptions(selectedProvider) {
      const saved = readStoredSettings();
      const selected = providerExists(saved, selectedProvider) ? selectedProvider : "local";
      const builtIns = builtInProviders().map(provider => `<option value="${provider.id}">${escapeHtml(provider.label)}</option>`).join("");
      const customs = saved.customProviders.map(provider => {
        const label = provider.name || "Custom Provider";
        const detail = provider.baseUrl ? ` · ${provider.baseUrl}` : "";
        return `<option value="${customPrefix}${provider.id}">${escapeHtml(label + detail)}</option>`;
      }).join("");
      $("provider").innerHTML = `
        <optgroup label="기본 Provider">${builtIns}</optgroup>
        ${customs ? `<optgroup label="Custom Provider">${customs}</optgroup>` : ""}
      `;
      $("provider").value = selected;
      return selected;
    }

    function legacyOptions(saved) {
      const data = {};
      for (const key of optionFields) {
        if (saved[key] !== undefined) data[key] = saved[key];
      }
      return data;
    }

    function currentOptionSettings() {
      return {
        timeout: Number($("timeout").value || 600),
        retries: Number($("retries").value || 1),
        llmParallel: Number($("llmParallel").value || 5),
        fontScale: Number($("fontScale").value || 0.93),
        hybridAllowedDelta: Number($("hybridAllowedDelta").value || 0),
        sam3: $("sam3").checked,
        editableEmbeddedText: $("editableEmbeddedText").checked,
        keepIntermediates: $("keepIntermediates").checked,
      };
    }

    function saveCurrentProvider(settings, providerId) {
      if (!providerId) return;
      if (isCustomProvider(providerId)) {
        const provider = findCustomProvider(settings, providerId);
        if (!provider) return;
        provider.name = $("customName").value.trim() || "Custom Provider";
        provider.baseUrl = $("baseUrl").value.trim();
        provider.model = $("model").value.trim();
        provider.apiKey = $("apiKey").value;
        return;
      }
      settings.providers = settings.providers || {};
      settings.providers[providerId] = {
        baseUrl: $("baseUrl").value.trim(),
        model: $("model").value.trim(),
        apiKey: $("apiKey").value,
      };
    }

    function saveSettings(showMessage = true) {
      const saved = readStoredSettings();
      saveCurrentProvider(saved, $("provider").value);
      saved.provider = $("provider").value;
      saved.options = currentOptionSettings();
      writeStoredSettings(saved);
      renderProviderOptions(saved.provider);
      activeProvider = saved.provider;
      if (showMessage) {
        $("save").textContent = "저장됨";
        setTimeout(() => $("save").textContent = "설정 저장", 900);
      }
    }

    function changeProvider() {
      const saved = readStoredSettings();
      saveCurrentProvider(saved, activeProvider);
      saved.provider = $("provider").value;
      saved.options = currentOptionSettings();
      writeStoredSettings(saved);
      activeProvider = $("provider").value;
      applyProvider(false);
    }

    function applyProvider(overwrite = true) {
      const providerId = $("provider").value;
      const saved = readStoredSettings();
      const customProvider = findCustomProvider(saved, providerId);
      $("customProviderFields").hidden = !customProvider;
      if (customProvider) {
        $("customName").value = customProvider.name || "Custom Provider";
        $("baseUrl").value = customProvider.baseUrl || "";
        $("model").value = customProvider.model || "";
        $("apiKey").value = customProvider.apiKey || "";
        $("providerHint").textContent = "등록한 OpenAI 호환 provider입니다. 이름, URL, 모델명, API key를 수정한 뒤 설정 저장을 누르면 목록에 반영됩니다.";
        return;
      }

      const preset = builtInProviders().find(p => p.id === providerId);
      if (!preset) return;
      const providerSettings = (saved.providers || {})[providerId] || {};
      $("baseUrl").value = overwrite ? (preset.baseUrl || "") : (providerSettings.baseUrl ?? preset.baseUrl ?? "");
      $("model").value = overwrite ? (preset.model || "") : (providerSettings.model ?? preset.model ?? "");
      $("apiKey").value = overwrite ? "" : (providerSettings.apiKey ?? "");
      $("providerHint").textContent = preset.hint || "";
    }

    function addCustomProvider() {
      const saved = readStoredSettings();
      saveCurrentProvider(saved, activeProvider);
      const id = makeProviderId();
      const count = saved.customProviders.length + 1;
      saved.customProviders.push({
        id,
        name: `Custom Provider ${count}`,
        baseUrl: "",
        model: "",
        apiKey: "",
      });
      saved.provider = `${customPrefix}${id}`;
      saved.options = currentOptionSettings();
      writeStoredSettings(saved);
      renderProviderOptions(saved.provider);
      activeProvider = saved.provider;
      applyProvider(false);
      $("customName").focus();
    }

    function deleteCustomProvider() {
      const providerId = $("provider").value;
      if (!isCustomProvider(providerId)) return;
      const saved = readStoredSettings();
      saved.customProviders = saved.customProviders.filter(item => item.id !== customId(providerId));
      saved.provider = "local";
      saved.options = currentOptionSettings();
      writeStoredSettings(saved);
      renderProviderOptions(saved.provider);
      activeProvider = saved.provider;
      applyProvider(false);
    }

    function renameSelectedCustomProvider() {
      if (!isCustomProvider($("provider").value)) return;
      const saved = readStoredSettings();
      saveCurrentProvider(saved, $("provider").value);
      saved.provider = $("provider").value;
      saved.options = currentOptionSettings();
      writeStoredSettings(saved);
      renderProviderOptions(saved.provider);
    }

    function readOptions(includeProvider = false) {
      const data = {
        baseUrl: $("baseUrl").value.trim(),
        model: $("model").value.trim(),
        apiKey: $("apiKey").value,
        timeout: Number($("timeout").value || 600),
        retries: Number($("retries").value || 1),
        llmParallel: Number($("llmParallel").value || 5),
        fontScale: Number($("fontScale").value || 0.93),
        hybridAllowedDelta: Number($("hybridAllowedDelta").value || 0),
        sam3: $("sam3").checked,
        editableEmbeddedText: $("editableEmbeddedText").checked,
        keepIntermediates: $("keepIntermediates").checked,
      };
      if (includeProvider) data.provider = $("provider").value;
      return data;
    }

    function setupDrop() {
      const drop = $("drop");
      drop.addEventListener("click", () => $("file").click());
      $("file").addEventListener("change", () => selectFile($("file").files[0]));
      for (const eventName of ["dragenter", "dragover"]) {
        drop.addEventListener(eventName, (event) => { event.preventDefault(); drop.classList.add("drag"); });
      }
      for (const eventName of ["dragleave", "drop"]) {
        drop.addEventListener(eventName, (event) => { event.preventDefault(); drop.classList.remove("drag"); });
      }
      drop.addEventListener("drop", (event) => selectFile(event.dataTransfer.files[0]));
    }

    function selectFile(file) {
      selectedFile = file || null;
      $("fileLabel").textContent = selectedFile ? `${selectedFile.name} (${Math.round(selectedFile.size / 1024 / 1024 * 10) / 10} MB)` : "NotebookLM에서 내려받은 .pptx 또는 .pdf 파일";
    }

    async function submit() {
      if (!selectedFile) {
        alert("먼저 PPTX/PDF 파일을 선택하세요.");
        return;
      }
      saveSettings(false);
      $("start").disabled = true;
      $("start").textContent = "업로드 중";
      try {
        const response = await fetch(`/api/jobs?filename=${encodeURIComponent(selectedFile.name)}`, {
          method: "POST",
          headers: {"x-star-slide-options": JSON.stringify(readOptions(false))},
          body: selectedFile,
        });
        if (!response.ok) throw new Error(await response.text());
        selectedFile = null;
        $("file").value = "";
        $("fileLabel").textContent = "NotebookLM에서 내려받은 .pptx 또는 .pdf 파일";
        await refreshJobs();
      } catch (error) {
        alert(`업로드 실패: ${error.message}`);
      } finally {
        $("start").disabled = false;
        $("start").textContent = "변환 시작";
      }
    }

    async function refreshJobs() {
      const jobs = await (await fetch("/api/jobs")).json();
      const root = $("jobs");
      if (!jobs.length) {
        root.innerHTML = `<div class="empty">아직 실행한 작업이 없습니다.</div>`;
        return;
      }
      const totalPages = Math.max(1, Math.ceil(jobs.length / pageSize));
      currentPage = Math.min(currentPage, totalPages);
      const start = (currentPage - 1) * pageSize;
      const pageJobs = jobs.slice(start, start + pageSize);
      root.innerHTML = renderPager(jobs.length, totalPages) + pageJobs.map(renderJob).join("");
    }

    function renderPager(total, totalPages) {
      if (totalPages <= 1) return "";
      return `
        <div class="pager">
          <span class="hint">총 ${total}건 · ${currentPage}/${totalPages}</span>
          <button class="secondary" ${currentPage <= 1 ? "disabled" : ""} onclick="changePage(-1)">이전</button>
          <button class="secondary" ${currentPage >= totalPages ? "disabled" : ""} onclick="changePage(1)">다음</button>
        </div>
      `;
    }

    function changePage(delta) {
      currentPage = Math.max(1, currentPage + delta);
      refreshJobs();
    }

    function renderJob(job) {
      const statusClass = job.status === "done" ? "done" : job.status === "failed" ? "failed" : "";
      const actions = job.status === "done" ? `
        <div class="job-actions">
          <a class="button" href="/api/jobs/${job.id}/download">PPTX 다운로드</a>
          <button class="secondary" onclick="openReport('${job.id}')">리포트 보기</button>
          ${job.artifacts?.layout_json ? `<button class="secondary" onclick="openLayoutSummary('${job.id}')">Layout JSON 보기</button>` : ""}
          <button class="secondary" onclick="openPreview('${job.id}')">미리보기</button>
        </div>
      ` : "";
      const error = job.error ? `<div class="hint" style="color:var(--danger);">${escapeHtml(job.error)}</div>` : "";
      const pct = Math.max(0, Math.min(100, job.progress || 0));
      return `
        <section class="job">
          <div class="job-head">
            <div class="job-title">${escapeHtml(job.filename)}</div>
            <span class="badge ${statusClass}">${job.status}</span>
          </div>
          <div class="hint">${escapeHtml(job.phase || "")}</div>
          <div class="bar"><div style="width:${pct}%"></div></div>
          <div class="job-meta">
            <span class="metric">${Math.round(pct)}%</span>
            <span class="metric">${new Date(job.created_at * 1000).toLocaleString()}</span>
            <span class="metric">${escapeHtml(job.options?.model || "")}</span>
          </div>
          ${error}
          ${actions}
        </section>
      `;
    }

    function openModal(title, html) {
      $("modalTitle").textContent = title;
      $("modalBody").innerHTML = html;
      $("modalBackdrop").classList.add("open");
    }

    function closeModal(event) {
      if (event && event.target !== $("modalBackdrop")) return;
      $("modalBackdrop").classList.remove("open");
      $("modalBody").innerHTML = "";
    }

    function openPreview(jobId) {
      openModal("미리보기", `<img class="preview" src="/api/jobs/${jobId}/montage?ts=${Date.now()}" />`);
    }

    async function openReport(jobId) {
      openModal("리포트", `<div class="empty">리포트를 불러오는 중입니다.</div>`);
      try {
        const report = await (await fetch(`/api/jobs/${jobId}/report-summary`)).json();
        $("modalBody").innerHTML = renderReport(report);
      } catch (error) {
        $("modalBody").innerHTML = `<div class="empty" style="color:var(--danger);">리포트 로드 실패: ${escapeHtml(error.message)}</div>`;
      }
    }

    function renderReport(report) {
      const s = report.summary || {};
      const worst = report.worst_slides || [];
      const decisions = report.decisions || [];
      const files = report.files || {};
      return `
        <div class="hint">${escapeHtml(report.job?.filename || "")}</div>
        <div class="report-grid">
          <div class="report-card"><span class="hint">슬라이드</span><strong>${s.slide_count ?? "-"}</strong></div>
          <div class="report-card"><span class="hint">최종 평균 diff</span><strong>${fmt(s.selected_avg_diff)}</strong></div>
          <div class="report-card"><span class="hint">Hybrid 선택</span><strong>${s.chosen_hybrid_count ?? 0}</strong></div>
          <div class="report-card"><span class="hint">Vector 선택</span><strong>${s.chosen_vector_count ?? 0}</strong></div>
        </div>
        <h2>해석</h2>
        <p class="hint">
          diff는 원본 이미지와 변환 PPTX 렌더 결과의 평균 픽셀 차이입니다. 낮을수록 원본과 가깝습니다.
          Hybrid는 큰 이미지 객체를 보존한 슬라이드, Vector는 텍스트/도형 중심으로 재구성한 슬라이드입니다.
        </p>
        <h2 style="margin-top:18px;">주의가 필요한 슬라이드</h2>
        ${renderWorstTable(worst)}
        <h2 style="margin-top:18px;">슬라이드별 선택</h2>
        ${renderDecisionTable(decisions)}
        <div class="job-actions">
          <a class="button" href="/api/jobs/${report.job.id}/download">PPTX 다운로드</a>
          ${files.candidate_vector ? `<a class="button secondary" href="/api/jobs/${report.job.id}/artifact/vector">Vector 다운로드</a>` : ""}
          ${files.candidate_hybrid ? `<a class="button secondary" href="/api/jobs/${report.job.id}/artifact/hybrid">Hybrid 다운로드</a>` : ""}
          ${files.layout_json ? `<a class="button secondary" href="/api/jobs/${report.job.id}/artifact/layout-json">Layout JSON 다운로드</a>` : ""}
          <a class="button secondary" href="/api/jobs/${report.job.id}/report">원본 JSON</a>
          <button class="secondary" onclick="openPreview('${report.job.id}')">미리보기</button>
        </div>
        <p class="hint">출력 파일: ${escapeHtml(files.output || "")} · ${formatBytes(files.output_bytes)}</p>
      `;
    }

    function renderWorstTable(items) {
      if (!items.length) return `<div class="empty">diff 정보가 없습니다.</div>`;
      return `<table><thead><tr><th>슬라이드</th><th>diff</th><th>객체</th><th>이미지</th></tr></thead><tbody>${
        items.map(item => `<tr><td>${item.slide_no}</td><td>${fmt(item.mean_abs_diff)}</td><td>${item.object_count ?? "-"}</td><td>${item.picture_count ?? "-"}</td></tr>`).join("")
      }</tbody></table>`;
    }

    function renderDecisionTable(items) {
      if (!items.length) return `<div class="empty">선택 리포트가 없습니다.</div>`;
      return `<table><thead><tr><th>슬라이드</th><th>선택</th><th>Vector diff</th><th>Hybrid diff</th></tr></thead><tbody>${
        items.map(item => `<tr><td>${item.slide_no}</td><td>${escapeHtml(item.chosen || "")}</td><td>${fmt(item.vector_mean_abs_diff)}</td><td>${fmt(item.hybrid_mean_abs_diff)}</td></tr>`).join("")
      }</tbody></table>`;
    }

    async function openLayoutSummary(jobId) {
      openModal("Layout JSON", `<div class="empty">Layout JSON을 해석하는 중입니다.</div>`);
      try {
        const summary = await (await fetch(`/api/jobs/${jobId}/layout-summary`)).json();
        $("modalBody").innerHTML = renderLayoutSummary(summary);
      } catch (error) {
        $("modalBody").innerHTML = `<div class="empty" style="color:var(--danger);">Layout JSON 로드 실패: ${escapeHtml(error.message)}</div>`;
      }
    }

    function renderLayoutSummary(summary) {
      const slides = summary.slides || [];
      const totalObjects = slides.reduce((sum, slide) => sum + Number(slide.object_count || 0), 0);
      const imageObjects = slides.reduce((sum, slide) => sum + Number(slide.type_counts?.image || 0), 0);
      const textObjects = slides.reduce((sum, slide) => sum + Number(slide.type_counts?.text || 0), 0);
      const rasterGroups = slides.reduce((sum, slide) => sum + Number(slide.raster_group_count || 0), 0);
      return `
        <div class="hint">${escapeHtml(summary.job?.filename || "")}</div>
        <div class="report-grid">
          <div class="report-card"><span class="hint">슬라이드</span><strong>${summary.slide_count ?? slides.length}</strong></div>
          <div class="report-card"><span class="hint">전체 객체</span><strong>${totalObjects}</strong></div>
          <div class="report-card"><span class="hint">텍스트 객체</span><strong>${textObjects}</strong></div>
          <div class="report-card"><span class="hint">이미지 객체</span><strong>${imageObjects}</strong></div>
        </div>
        <p class="hint">raster group은 원본 이미지 덩어리로 보존한 도식/일러스트 영역입니다. punched text는 이미지 안의 원본 텍스트를 지우고 PPT 텍스트로 다시 얹은 영역 수입니다.</p>
        <table>
          <thead><tr><th>슬라이드</th><th>제목</th><th>객체</th><th>텍스트</th><th>이미지</th><th>도형</th><th>Raster group</th><th>Punched text</th></tr></thead>
          <tbody>
            ${slides.map(slide => `<tr>
              <td>${slide.slide_no}</td>
              <td>${escapeHtml(slide.title || slide.id || "")}</td>
              <td>${slide.object_count ?? 0}</td>
              <td>${slide.type_counts?.text ?? 0}</td>
              <td>${slide.type_counts?.image ?? 0}</td>
              <td>${slide.type_counts?.shape ?? 0}</td>
              <td>${slide.raster_group_count ?? 0}</td>
              <td>${slide.punched_text_regions ?? "-"}</td>
            </tr>`).join("")}
          </tbody>
        </table>
        <div class="job-actions">
          <a class="button secondary" href="/api/jobs/${summary.job.id}/artifact/layout-json">Layout JSON 다운로드</a>
        </div>
      `;
    }

    function fmt(value) {
      return typeof value === "number" ? value.toFixed(2) : "-";
    }

    function formatBytes(value) {
      if (typeof value !== "number") return "-";
      if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
      if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
      return `${value} B`;
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      }[ch]));
    }

    init();
  </script>
</body>
</html>
"""
