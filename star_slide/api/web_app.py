"""Local FastAPI web app for NotebookLM PPTX conversion."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import re
import shutil
import time
import traceback
import uuid
import zipfile
from collections.abc import AsyncIterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Any

from star_slide.api.events import EventBus, format_sse
from star_slide.api.preview_assets import (
    PREVIEW_KINDS,
    generate_previews,
    index_previews,
)
from star_slide.pipeline.notebooklm_auto import (
    JobCancelledError,
    NotebookLmAutoOptions,
    convert_notebooklm_auto,
)

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import (
        FileResponse,
        HTMLResponse,
        JSONResponse,
        StreamingResponse,
    )
except ImportError as exc:  # pragma: no cover - exercised by runtime environment
    raise RuntimeError(
        "FastAPI 의존성이 필요합니다. `uv run --extra api star-slide web run`으로 실행하세요."
    ) from exc


WEB_ROOT = Path("output/web_jobs")
ALLOWED_SUFFIXES = {".pptx", ".pdf"}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
SSE_HEARTBEAT_SECONDS = 15.0
TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})


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
    input_path: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    raw_options: dict[str, Any] = field(default_factory=dict)
    cancel_event: Event = field(default_factory=Event)
    bus: EventBus = field(default_factory=EventBus)


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
                    "model": "gemini-3.1-pro-preview",
                    "hint": "Gemini OpenAI-compatible endpoint 또는 로컬 프록시 모델명 사용",
                },
                {
                    "id": "ollama",
                    "label": "Ollama",
                    "baseUrl": "http://localhost:11434/v1",
                    "model": "llama3.2",
                    "hint": "로컬 Ollama. Base URL에 /v1 prefix 필수. API key는 비워두세요.",
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
                "sam3": False,
                "hybridAllowedDelta": 0.0,
                "editableEmbeddedText": True,
            },
        }

    @app.post("/api/test-llm")
    async def test_llm(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="요청 본문이 JSON 형식이어야 합니다.") from exc
        result = await asyncio.to_thread(probe_llm_endpoint, payload)
        return JSONResponse(result)

    @app.post("/api/list-models")
    async def list_models_endpoint(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="요청 본문이 JSON 형식이어야 합니다.") from exc
        base_url = str(payload.get("baseUrl") or "").strip().rstrip("/")
        api_key = str(payload.get("apiKey") or "").strip()
        timeout = float(payload.get("timeout") or 10)
        timeout = max(2.0, min(30.0, timeout))
        if not base_url:
            return JSONResponse({"models": [], "error": "Base URL이 없습니다."}, status_code=400)
        models = await asyncio.to_thread(_list_models, base_url, api_key, timeout)
        return JSONResponse({"models": models})

    @app.get("/api/system-check")
    def system_check() -> dict[str, Any]:
        libreoffice = first_executable(("soffice", "libreoffice"))
        poppler = first_executable(("pdftoppm", "pdfinfo"))
        sam3_ready = python_module_available("torch") and python_module_available("transformers")
        return {
            "items": [
                {
                    "id": "libreoffice",
                    "label": "LibreOffice",
                    "ok": libreoffice is not None,
                    "path": libreoffice,
                    "required": True,
                    "message": "PPTX 렌더 QA와 자동 선택에 필요합니다.",
                },
                {
                    "id": "poppler",
                    "label": "Poppler",
                    "ok": poppler is not None,
                    "path": poppler,
                    "required": False,
                    "message": "PDF 입력 또는 LibreOffice PDF 렌더 경유에 필요할 수 있습니다.",
                },
                {
                    "id": "sam3",
                    "label": "SAM3",
                    "ok": sam3_ready,
                    "path": "torch + transformers" if sam3_ready else None,
                    "required": False,
                    "message": "고품질 bbox 보정 옵션입니다. 사용하려면 gpu-segmentation extra와 SAM3 모델 접근 권한이 필요합니다.",
                },
            ]
        }

    @app.post("/api/jobs")
    async def submit_job(request: Request) -> JSONResponse:
        filename = request.query_params.get("filename", "upload.pptx")
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise HTTPException(status_code=400, detail="파일명이 올바르지 않습니다.")
        if Path(safe_name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail="PPTX/PDF 파일만 업로드할 수 있습니다.")

        raw_options = request.headers.get("x-star-slide-options", "{}")
        try:
            options_payload = json.loads(raw_options)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="옵션 JSON을 파싱할 수 없습니다.") from exc

        job_id = uuid.uuid4().hex
        job_dir = WEB_ROOT / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        input_path = job_dir / safe_name

        # 스트리밍 업로드: 청크 단위로 디스크에 직접 기록하고 누적 크기를 검사한다.
        # 한도 초과 시 부분 파일을 즉시 정리해 디스크 누수를 막는다.
        total = 0
        with input_path.open("wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    fh.close()
                    with contextlib.suppress(OSError):
                        input_path.unlink()
                    raise HTTPException(
                        status_code=413,
                        detail=f"업로드 파일이 너무 큽니다 (한도 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB).",
                    )
                fh.write(chunk)
        if total == 0:
            with contextlib.suppress(OSError):
                input_path.unlink()
            raise HTTPException(status_code=400, detail="업로드 파일이 비어 있습니다.")

        state = JobState(
            id=job_id,
            filename=safe_name,
            workdir=str(job_dir / "work"),
            output=str(job_dir / "result.pptx"),
            report=str(job_dir / "artifacts" / "report.json"),
            montage=str(job_dir / "artifacts" / "montage.png"),
            input_path=str(input_path),
            options=public_options(options_payload),
            raw_options=dict(options_payload),
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

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: str, request: Request) -> StreamingResponse:
        job = require_job(job_id)
        bus = job.bus
        loop = asyncio.get_running_loop()
        queue = bus.subscribe(loop)

        async def stream() -> AsyncIterator[bytes]:
            try:
                yield format_sse(job_snapshot(job), event="snapshot").encode("utf-8")
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except TimeoutError:
                        yield b": heartbeat\n\n"
                        continue
                    if item is None:
                        return
                    yield format_sse(item, event="snapshot").encode("utf-8")
                    if item.get("status") in TERMINAL_STATUSES:
                        return
            finally:
                bus.unsubscribe(loop, queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(request: Request, job_id: str) -> JSONResponse:
        require_json_content_type(request)
        job = require_job(job_id)
        if job.status in TERMINAL_STATUSES:
            return JSONResponse(job_snapshot(job))
        job.cancel_event.set()
        future = futures.get(job_id)
        if future is not None and not future.running():
            future.cancel()
        if job.status == "queued":
            update_job(job_id, status="cancelled", phase="취소됨", progress=100)
        else:
            update_job(job_id, phase="취소 중...", status="cancelling")
        return JSONResponse(job_snapshot(require_job(job_id)))

    @app.post("/api/jobs/{job_id}/rerun")
    def rerun(request: Request, job_id: str) -> JSONResponse:
        require_json_content_type(request)
        job = require_job(job_id)
        if job.status not in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="진행 중인 작업은 다시 실행할 수 없습니다.")
        if not job.input_path or not Path(job.input_path).exists():
            raise HTTPException(status_code=410, detail="원본 입력 파일을 찾을 수 없어 재실행이 불가능합니다.")
        new_job_id = uuid.uuid4().hex
        job_dir = WEB_ROOT / new_job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        new_input = job_dir / Path(job.input_path).name
        shutil.copy2(job.input_path, new_input)
        new_state = JobState(
            id=new_job_id,
            filename=job.filename,
            workdir=str(job_dir / "work"),
            output=str(job_dir / "result.pptx"),
            report=str(job_dir / "artifacts" / "report.json"),
            montage=str(job_dir / "artifacts" / "montage.png"),
            input_path=str(new_input),
            options=public_options(job.raw_options),
            raw_options=dict(job.raw_options),
        )
        with jobs_lock:
            jobs[new_job_id] = new_state
            futures[new_job_id] = executor.submit(run_job, new_job_id, new_input, job_dir, dict(job.raw_options))
        return JSONResponse(job_snapshot(new_state))

    @app.get("/api/jobs/{job_id}/previews")
    def previews_index(job_id: str) -> dict[str, Any]:
        job = require_job(job_id)
        out_dir = previews_dir_for(job)
        entries = index_previews(out_dir)
        return {
            "job": {"id": job.id, "filename": job.filename},
            "kinds": list(PREVIEW_KINDS),
            "slides": [{"slide_no": entry.slide_no, "kinds": list(entry.kinds)} for entry in entries],
        }

    @app.get("/api/jobs/{job_id}/previews/{slide_no}/{kind}")
    def preview_image(job_id: str, slide_no: int, kind: str) -> FileResponse:
        if kind not in PREVIEW_KINDS:
            raise HTTPException(status_code=404, detail="지원하지 않는 preview kind 입니다.")
        job = require_job(job_id)
        out_dir = previews_dir_for(job)
        path = out_dir / f"{slide_no:03d}_{kind}.jpg"
        if not path.exists():
            raise HTTPException(status_code=404, detail="해당 슬라이드 미리보기가 없습니다.")
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=3600"},
        )

    @app.get("/api/jobs/{job_id}/pptx-file")
    def pptx_file(job_id: str, which: str = "result") -> FileResponse:
        """Stream the raw PPTX so the browser can render it client-side.

        `which=result` returns the converted PPTX, `which=original` returns
        the user's input. Used by the slide viewer that loads pptx-preview
        from a CDN, eliminating the LibreOffice round-trip.
        """
        job = require_job(job_id)
        try:
            source = _resolve_source_for_pages(job, which)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if source.suffix.lower() == ".pdf":
            media_type = "application/pdf"
        else:
            media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return FileResponse(
            source,
            media_type=media_type,
            headers={"Cache-Control": "max-age=300"},
        )

    @app.get("/api/jobs/{job_id}/pptx-pages")
    async def pptx_pages_index(job_id: str, which: str = "result") -> JSONResponse:
        job = require_job(job_id)
        try:
            pages = await asyncio.to_thread(render_pptx_pages, job, which)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(
            {
                "job": {"id": job.id, "filename": job.filename},
                "which": which,
                "pages": len(pages),
            }
        )

    @app.get("/api/jobs/{job_id}/pptx-pages/{page_no}")
    def pptx_page_image(job_id: str, page_no: int, which: str = "result") -> FileResponse:
        job = require_job(job_id)
        cache_dir = pptx_pages_cache_dir(job, which)
        path = cache_dir / f"page_{page_no:03d}.png"
        if not path.exists():
            raise HTTPException(status_code=404, detail="해당 페이지가 없습니다. /pptx-pages를 먼저 호출하세요.")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    return app


def previews_dir_for(job: JobState) -> Path:
    if job.report:
        return Path(job.report).parent / "previews"
    return WEB_ROOT / job.id / "artifacts" / "previews"


def _resolve_source_for_pages(job: JobState, which: str) -> Path:
    if which == "result":
        candidate = Path(job.output) if job.output else None
    elif which == "original":
        candidate = Path(job.input_path) if job.input_path else None
    else:
        raise FileNotFoundError(f"지원하지 않는 미리보기 종류 '{which}' (result|original)")
    if candidate is None or not candidate.exists():
        raise FileNotFoundError(f"미리보기 원본 파일을 찾을 수 없습니다 ({which}).")
    return candidate


def pptx_pages_cache_dir(job: JobState, which: str) -> Path:
    return WEB_ROOT / job.id / "preview_cache" / which


def prefetch_pptx_pages_from_workdir(
    job_id: str,
    job_dir: Path,
    workdir: Path,
    result_pptx: Path,
    input_pptx: Path,
) -> None:
    """Reuse workdir's per-page PNGs as the slide viewer cache.

    convert_notebooklm_auto already renders every slide to PNG during QA
    (workdir/qa_selected for the converted result, workdir/images for the
    original input). Copying those into preview_cache/{result,original}/
    means the user's first click on "미리보기/원본 보기/비교 보기" hits the
    cache instead of triggering a fresh LibreOffice run.
    """
    sources = {
        "result": (workdir / "qa_selected", result_pptx),
        "original": (workdir / "images", input_pptx),
    }
    for which, (src_dir, source_file) in sources.items():
        if not src_dir.exists() or not source_file.exists():
            continue
        pngs = sorted(src_dir.glob("*.png"))
        if not pngs:
            continue
        cache_dir = WEB_ROOT / job_id / "preview_cache" / which
        if cache_dir.exists():
            for stale in cache_dir.glob("page_*.png"):
                with contextlib.suppress(OSError):
                    stale.unlink()
        cache_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(pngs, start=1):
            dst = cache_dir / f"page_{i:03d}.png"
            with contextlib.suppress(OSError):
                shutil.copy2(src, dst)
        stat = source_file.stat()
        fingerprint = f"{int(stat.st_mtime)}-{stat.st_size}"
        (cache_dir / "fingerprint").write_text(fingerprint, encoding="utf-8")


def render_pptx_pages(job: JobState, which: str) -> list[Path]:
    """Render the job's PPTX/PDF (result or original) into per-page PNGs (cached).

    Cache keyed on source file mtime+size. Returns sorted PNG paths.
    Raises FileNotFoundError when the source file is missing,
    RuntimeError when LibreOffice/pdftoppm dependencies are unavailable.
    """
    source = _resolve_source_for_pages(job, which)
    cache_dir = pptx_pages_cache_dir(job, which)
    stat = source.stat()
    fingerprint = f"{int(stat.st_mtime)}-{stat.st_size}"
    fingerprint_file = cache_dir / "fingerprint"

    if (
        cache_dir.exists()
        and fingerprint_file.exists()
        and fingerprint_file.read_text(encoding="utf-8").strip() == fingerprint
    ):
        existing = sorted(cache_dir.glob("page_*.png"))
        if existing:
            return existing

    if cache_dir.exists():
        for stale in cache_dir.glob("page_*.png"):
            with contextlib.suppress(OSError):
                stale.unlink()
    cache_dir.mkdir(parents=True, exist_ok=True)

    suffix = source.suffix.lower()
    try:
        if suffix == ".pptx":
            from star_slide.rasterize.libreoffice import render_pptx_to_pngs

            rendered = render_pptx_to_pngs(source, cache_dir)
        elif suffix == ".pdf":
            from pdf2image import convert_from_path

            images = convert_from_path(str(source), dpi=160)
            rendered = []
            for i, img in enumerate(images, start=1):
                out_path = cache_dir / f"page_{i:03d}.png"
                img.save(out_path, "PNG")
                rendered.append(out_path)
        else:
            raise FileNotFoundError(f"지원하지 않는 입력 형식 '{suffix}'")
    except Exception as exc:
        raise RuntimeError(f"미리보기 렌더링 실패: {sanitize_error(str(exc))}") from exc

    # 파일명을 page_NNN.png 규약으로 정렬해서 다시 저장 (libreoffice 출력은 slide_NNN)
    final_pages: list[Path] = []
    for i, src in enumerate(sorted(rendered), start=1):
        target = cache_dir / f"page_{i:03d}.png"
        if src != target:
            with contextlib.suppress(OSError):
                if target.exists():
                    target.unlink()
                src.rename(target)
        final_pages.append(target)

    # libreoffice 헬퍼가 만든 임시 디렉토리 정리
    pdf_dir = cache_dir / "_pdf"
    if pdf_dir.exists():
        with contextlib.suppress(OSError):
            shutil.rmtree(pdf_dir)

    fingerprint_file.write_text(fingerprint, encoding="utf-8")
    return sorted(cache_dir.glob("page_*.png"))


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
            input_path=str(source) if source else None,
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


SERIALIZABLE_JOB_FIELDS = (
    "id",
    "filename",
    "status",
    "phase",
    "progress",
    "created_at",
    "updated_at",
    "error",
    "workdir",
    "output",
    "report",
    "montage",
    "input_path",
    "options",
)


def job_snapshot(job: JobState) -> dict[str, Any]:
    data: dict[str, Any] = {key: getattr(job, key) for key in SERIALIZABLE_JOB_FIELDS}
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


def first_executable(names: tuple[str, ...]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def python_module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def update_job(job_id: str, *, force: bool = False, **changes: Any) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return
        # terminal-state guard: cancel/done/failed 후 도착하는 late progress가
        # status를 비-terminal로 되돌리지 못하도록 차단한다. force=True (run_job 자체
        # 종료 분기)일 때는 통과.
        if not force and job.status in TERMINAL_STATUSES:
            new_status = changes.get("status", job.status)
            if new_status not in TERMINAL_STATUSES:
                return
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = time.time()
        snapshot = job_snapshot(job)
        bus = job.bus
        terminal = job.status in TERMINAL_STATUSES
    bus.publish(snapshot)
    if terminal:
        bus.close()


def run_job(job_id: str, input_path: Path, job_dir: Path, payload: dict[str, Any]) -> None:
    def progress(message: str, percent: float, *_: Any, **__: Any) -> None:
        update_job(job_id, status="running", phase=message, progress=percent)

    with jobs_lock:
        job_for_cancel = jobs.get(job_id)
    cancel_event = job_for_cancel.cancel_event if job_for_cancel else None

    def cancel_check() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    try:
        update_job(job_id, status="running", phase="작업 시작", progress=1, error=None)
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
            use_sam3=bool(payload.get("sam3", False)),
            hybrid_allowed_delta=float(payload.get("hybridAllowedDelta") or 0.0),
            editable_embedded_text=bool(payload.get("editableEmbeddedText", True)),
        )
        result = convert_notebooklm_auto(
            input_path=input_path,
            output_path=output_path,
            workdir=workdir,
            options=options,
            progress=progress,
            cancel=cancel_check,
        )
        previews_dir = job_dir / "artifacts" / "previews"
        with contextlib.suppress(Exception):  # preview generation is best-effort
            generate_previews(workdir=workdir, out_dir=previews_dir)
        # 슬라이드 뷰어용 PNG cache prefetch — workdir에 이미 있는 페이지별 PNG를
        # preview_cache로 복사해 두면 사용자가 "미리보기/원본 보기/비교" 클릭 시
        # LibreOffice 재호출 없이 즉시 표시된다 (~6초 → 0초).
        with contextlib.suppress(Exception):
            prefetch_pptx_pages_from_workdir(job_id, job_dir, workdir, result.output, input_path)
        update_job(
            job_id,
            force=True,
            status="done",
            phase="완료",
            progress=100,
            output=str(result.output),
            report=str(result.report),
            montage=str(result.montage) if result.montage else None,
        )
    except JobCancelledError:
        update_job(job_id, force=True, status="cancelled", phase="취소됨", progress=100, error=None)
    except Exception as exc:  # pragma: no cover - depends on external tools/model
        error_path = job_dir / "error.log"
        error_path.write_text(sanitize_error(traceback.format_exc()), encoding="utf-8")
        update_job(job_id, force=True, status="failed", phase="실패", error=sanitize_error(str(exc)), progress=100)


_LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})

# 사설 네트워크(RFC1918) LLM 호출 허용 여부.
# Default True — 우리 서버가 loopback에만 바인딩됐다는 가정 하에 사내 GPU 서버 등
# 정당한 LAN LLM 사용을 막지 않는다. 우리 서버가 비-loopback host에 바인딩되면
# (cli/web.py가 자동으로) False로 전환해 SSRF 위험을 차단한다.
_allow_private_networks: bool = True


def set_allow_private_networks(allow: bool) -> None:
    """Toggle SSRF guard policy for RFC1918 private IPs.

    Loopback / link-local (169.254.x → cloud IMDS) / multicast / unspecified
    addresses are always rejected regardless of this flag.
    """
    global _allow_private_networks
    _allow_private_networks = bool(allow)


def _validate_outbound_url(url: str) -> tuple[bool, str]:
    """SSRF guard for user-supplied OpenAI-compatible base URLs.

    Always rejects: non-http(s) schemes, link-local (cloud IMDS), multicast,
    unspecified addresses, and resolved loopback unless the hostname literal
    is explicitly localhost/127.0.0.1/::1.
    Conditionally rejects RFC1918 private IPs based on _allow_private_networks.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "http 또는 https URL만 허용됩니다."
    hostname = parsed.hostname
    if not hostname:
        return False, "URL에 호스트가 없습니다."
    if hostname in _LOOPBACK_HOSTNAMES:
        return True, ""
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or 80, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"호스트 '{hostname}'를 해석할 수 없습니다."
    # is_reserved는 NAT64 prefix(64:ff9b::/96) 등 정상 외부 트래픽도 포함하므로
    # 제외한다. link-local(169.254.0.0/16)에는 cloud IMDS가 포함되어 정책과 무관하게
    # 항상 차단한다.
    for _family, _socktype, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except (ValueError, IndexError):
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return False, f"내부 네트워크 주소({ip})는 허용되지 않습니다."
        if ip.is_private and not _allow_private_networks:
            return False, (
                f"사설 네트워크 주소({ip})는 현재 정책에서 차단됩니다 "
                "(서버가 비-loopback host에 바인딩되어 SSRF 방지가 활성화됨)."
            )
    return True, ""


def require_json_content_type(request: Request) -> None:
    """Reject requests without an application/json Content-Type.

    This forces a CORS preflight on cross-origin browser callers, which the
    default same-origin policy then blocks. Trivial CSRF defense for the
    state-mutating POST endpoints (cancel/rerun) that otherwise accept empty
    bodies.
    """
    raw = request.headers.get("content-type", "")
    media_type = raw.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail="Content-Type: application/json 필요 (CSRF 방지).",
        )


def probe_llm_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    """Issue a tiny chat completion to verify the OpenAI-compatible endpoint.

    Empty apiKey is allowed (Ollama/local proxies). On 404 with a base URL
    that does not end with /v1, retries once with /v1 appended and reports
    the auto-correction in the result note.
    """
    base_url = str(payload.get("baseUrl") or "").strip().rstrip("/")
    model = str(payload.get("model") or "").strip()
    api_key = str(payload.get("apiKey") or "").strip()
    timeout = float(payload.get("timeout") or 15)
    timeout = max(3.0, min(60.0, timeout))

    if not base_url:
        return {"ok": False, "error": "Base URL을 입력하세요."}
    if not model:
        return {"ok": False, "error": "Model 이름을 입력하세요."}

    ok, err = _validate_outbound_url(base_url)
    if not ok:
        return {"ok": False, "error": err}

    first = _probe_chat_completions(base_url, model, api_key, timeout)
    if first.get("ok"):
        return first
    if first.get("status_code") == 404 and not base_url.endswith("/v1"):
        retry_base = f"{base_url}/v1"
        retry = _probe_chat_completions(retry_base, model, api_key, timeout)
        if retry.get("ok"):
            retry["note"] = (
                f"Base URL에 '/v1'이 빠져있어 자동 보정했습니다. "
                f"Base URL을 '{retry_base}'로 갱신하는 것을 권장합니다."
            )
            return retry
        first = dict(first)
        first["error"] = (
            f"{first.get('error', '')} · Base URL이 /v1으로 끝나야 할 수 있습니다 "
            f"(예: {base_url}/v1)"
        )
        if _looks_like_model_missing(retry):
            first["available_models"] = _list_models(retry_base, api_key, timeout)
            first["error"] += " · 모델명이 잘못된 것 같습니다. 사용 가능한 모델은 아래 참고."
        return first
    if _looks_like_model_missing(first):
        first = dict(first)
        first["available_models"] = _list_models(base_url, api_key, timeout)
        suffix = " · `ollama pull <model>`로 모델을 다운로드하거나 사용 가능한 모델 중에서 선택하세요."
        first["error"] = f"{first.get('error', '')}{suffix}"
    return first


def _looks_like_model_missing(result: dict[str, Any]) -> bool:
    if result.get("ok"):
        return False
    return bool(result.get("model_missing"))


def _list_models(base_url: str, api_key: str, timeout: float) -> list[str]:
    import httpx

    ok, _ = _validate_outbound_url(base_url)
    if not ok:
        return []

    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(timeout=min(timeout, 8.0), follow_redirects=False) as client:
            response = client.get(f"{base_url}/models", headers=headers)
        if response.status_code >= 400:
            return []
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    items: list[str] = []
    candidates = data.get("data") if isinstance(data, dict) else None
    if isinstance(candidates, list):
        for entry in candidates:
            if isinstance(entry, dict):
                value = entry.get("id") or entry.get("name")
                if isinstance(value, str) and value:
                    items.append(value)
    return items[:12]


def _probe_chat_completions(
    base_url: str,
    model: str,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    import httpx

    url = f"{base_url}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 5,
        "temperature": 0,
    }

    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        return {
            "ok": False,
            "error": f"{timeout:.0f}초 안에 응답이 없습니다.",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "error": f"네트워크 오류: {sanitize_error(str(exc))}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    latency_ms = int((time.perf_counter() - started) * 1000)

    if 300 <= response.status_code < 400:
        # SSRF 회피: 리다이렉트는 허용하지 않음 (내부 메타데이터/사설망 우회 차단).
        return {
            "ok": False,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "error": f"HTTP {response.status_code}: 리다이렉트는 보안상 허용되지 않습니다.",
        }

    if response.status_code >= 400:
        # 응답 본문은 반사하지 않음 (외부 endpoint가 내부 정보/시크릿을 에코할 수 있음).
        # status code + 일반 hint만 클라이언트에 전달.
        hint = ""
        if response.status_code in (401, 403):
            hint = " (API key 또는 권한을 확인하세요)"
        elif response.status_code == 404:
            hint = " (Base URL 또는 모델명을 확인하세요)"
        elif response.status_code == 429:
            hint = " (rate limit 초과 또는 quota 부족)"
        # 내부 판별: model not found 안내를 자동으로 추가하기 위해 본문 일부를 검사.
        # 본문은 응답에 포함하지 않고 model_missing 플래그만 기록한다.
        result: dict[str, Any] = {
            "ok": False,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "error": f"HTTP {response.status_code}{hint}",
        }
        if response.status_code == 404:
            body_lower = response.text[:500].lower()
            if "not found" in body_lower or "no such model" in body_lower or "does not exist" in body_lower:
                result["model_missing"] = True
        return result

    try:
        data = response.json()
    except ValueError:
        return {
            "ok": False,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "error": "응답이 JSON 형식이 아닙니다.",
        }

    sample = ""
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    sample = content.strip()[:120]
    return {
        "ok": True,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "sample": sample,
        "model": model,
    }


def sanitize_error(message: str) -> str:
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-********", message)
    message = re.sub(r"(--api-key['\", ]+)([^'\",\\]]+)", r"\1********", message)
    message = re.sub(r"(apiKey['\": ]+)([^'\",\\]]+)", r"\1********", message)
    # Bearer / Google API key / URL-embedded basic auth credentials
    message = re.sub(r"Bearer\s+\S+", "Bearer ********", message, flags=re.IGNORECASE)
    message = re.sub(r"AIza[0-9A-Za-z_\-]{35}", "AIza********", message)
    message = re.sub(r"(https?://)([^/@\s]+):([^/@\s]+)@", r"\1********:********@", message)
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
      height: 68px;
      display: grid;
      grid-template-columns: minmax(220px, auto) minmax(0, 1fr) minmax(160px, 240px);
      align-items: center;
      padding: 0 28px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, var(--surface) 0%, color-mix(in srgb, var(--surface) 92%, var(--blue)) 100%);
      box-shadow: 0 1px 0 color-mix(in srgb, var(--blue) 18%, transparent);
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-size: 22px;
      font-weight: 800;
      letter-spacing: -0.01em;
      background: linear-gradient(90deg, var(--ink) 0%, var(--teal) 110%);
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }
    .brand-mark {
      width: 28px;
      height: 28px;
      border-radius: 7px;
      background: linear-gradient(135deg, var(--blue), var(--teal));
      display: inline-grid;
      place-items: center;
      color: #fff;
      font-size: 14px;
      font-weight: 800;
      box-shadow: 0 4px 14px color-mix(in srgb, var(--blue) 35%, transparent);
    }
    .tagline {
      min-width: 0;
      text-align: center;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: -0.005em;
      color: color-mix(in srgb, var(--ink) 88%, var(--muted));
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tagline strong {
      color: var(--teal);
      font-weight: 800;
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
      min-height: calc(100vh - 68px);
    }
    aside {
      border-right: 1px solid var(--line);
      padding: 22px;
      background: var(--surface);
      overflow-y: auto;
    }
    main { padding: 26px 28px; overflow: auto; }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h1 {
      font-size: 22px;
      font-weight: 800;
      letter-spacing: -0.01em;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 18px;
    }
    h1::before {
      content: "";
      width: 4px;
      height: 22px;
      border-radius: 4px;
      background: linear-gradient(180deg, var(--blue), var(--teal));
    }
    h2 {
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 10px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    h2::before {
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--teal);
    }
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
    .system-box {
      display: grid;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface-2);
      margin-top: 16px;
    }
    .system-row {
      display: grid;
      grid-template-columns: minmax(92px, auto) 74px minmax(0, 1fr);
      align-items: center;
      gap: 8px;
      font-size: 12px;
    }
    .system-name { font-weight: 750; color: var(--ink); }
    .status-pill {
      display: inline-flex;
      justify-content: center;
      border-radius: 999px;
      padding: 3px 8px;
      font-weight: 800;
      background: color-mix(in srgb, var(--danger) 18%, var(--surface-3));
      color: var(--danger);
    }
    .status-pill.ok {
      background: color-mix(in srgb, var(--teal) 18%, var(--surface-3));
      color: var(--teal);
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
    .badge.cancelled, .badge.cancelling { background: color-mix(in srgb, var(--muted) 22%, var(--surface-3)); color: var(--muted); }
    .keystore-banner {
      padding: 10px 28px;
      font-size: 13px;
      font-weight: 600;
      background: color-mix(in srgb, var(--danger) 18%, var(--surface));
      color: var(--danger);
      border-bottom: 1px solid color-mix(in srgb, var(--danger) 40%, var(--line));
    }
    .api-key-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
    }
    .api-key-row button { white-space: nowrap; }
    .test-result {
      margin-top: 8px;
      padding: 8px 10px;
      border-radius: 6px;
      border: 1px solid var(--field-border);
      background: var(--surface-3);
      font-size: 12px;
      line-height: 1.5;
    }
    .test-result.ok { border-color: color-mix(in srgb, var(--teal) 60%, var(--field-border)); color: var(--teal); }
    .test-result.fail { border-color: color-mix(in srgb, var(--danger) 50%, var(--field-border)); color: var(--danger); }
    .test-result.busy { color: var(--muted); }
    .model-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
    .model-chip {
      height: auto;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 600;
      border: 1px solid var(--field-border);
      border-radius: 999px;
      background: var(--surface-3);
      color: var(--ink);
      cursor: pointer;
    }
    .model-chip:hover { border-color: var(--blue); color: var(--blue); }
    .model-chip.active {
      border-color: var(--blue);
      background: color-mix(in srgb, var(--blue) 22%, var(--surface-3));
      color: var(--blue);
    }
    .upload-progress { margin-top: 12px; display: grid; gap: 6px; }
    .upload-progress-bar { height: 6px; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
    .upload-progress-bar > div { height: 100%; width: 0%; background: linear-gradient(90deg, var(--blue), var(--teal)); transition: width 120ms linear; }
    .modal.viewer-modal { width: min(1200px, 96vw); max-height: 92vh; padding: 0; }
    .modal.viewer-modal.fullscreen { width: 96vw; max-height: 96vh; }
    .viewer {
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: min(90vh, 880px);
      background: var(--surface);
    }
    .viewer.fullscreen { height: 92vh; }
    .viewer-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-2);
    }
    .viewer-title {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      font-size: 13px;
      font-weight: 700;
      color: var(--ink);
    }
    .viewer-title .kind-pill {
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: color-mix(in srgb, var(--blue) 22%, var(--surface-3));
      color: var(--blue);
      white-space: nowrap;
    }
    .viewer-title .kind-pill.original { background: color-mix(in srgb, var(--muted) 26%, var(--surface-3)); color: var(--muted); }
    .viewer-title .filename {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .viewer-title .counter {
      color: var(--muted);
      font-weight: 600;
      white-space: nowrap;
    }
    .viewer-actions { display: flex; align-items: center; gap: 4px; }
    .viewer-icon {
      height: 32px;
      width: 32px;
      padding: 0;
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      border-radius: 7px;
      display: inline-grid;
      place-items: center;
      cursor: pointer;
    }
    .viewer-icon:hover { color: var(--ink); background: var(--surface-3); border-color: var(--field-border); }
    .viewer-stage {
      position: relative;
      display: grid;
      place-items: center;
      background: #0a0e16;
      overflow: hidden;
    }
    body[data-theme="light"] .viewer-stage { background: #1f2937; }
    .viewer-stage img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      box-shadow: 0 6px 28px rgba(0, 0, 0, .35);
      border-radius: 6px;
      background: #fff;
    }
    .viewer-stage .pptx-host {
      width: 100%;
      height: 100%;
      display: grid;
      place-items: center;
      overflow: hidden;
    }
    .viewer-stage .pptx-host > div {
      background: #fff;
      box-shadow: 0 6px 28px rgba(0, 0, 0, .35);
      border-radius: 6px;
      overflow: hidden;
    }
    .viewer-stage.compare {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      padding: 12px 60px;
      align-items: center;
      justify-items: center;
    }
    .viewer-stage.compare .compare-pane {
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 6px;
      width: 100%;
      height: 100%;
      min-height: 0;
      align-items: stretch;
    }
    .viewer-stage.compare .compare-pane .pane-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #cbd5e1;
      text-align: center;
    }
    .viewer-stage.compare .compare-pane .pane-label.result { color: #93c5fd; }
    .viewer-stage.compare .compare-pane .pane-img-wrap {
      display: grid;
      place-items: center;
      min-height: 0;
      overflow: hidden;
    }
    .viewer-stage.compare .compare-pane img,
    .viewer-stage.compare .compare-pane .missing {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
    }
    .viewer-stage.compare .compare-pane .missing {
      display: grid;
      place-items: center;
      width: 100%;
      height: 100%;
      color: var(--muted);
      font-size: 12px;
      border: 1px dashed color-mix(in srgb, var(--muted) 40%, transparent);
      border-radius: 6px;
      background: rgba(255, 255, 255, .03);
    }
    @media (max-width: 900px) {
      .viewer-stage.compare {
        grid-template-columns: 1fr;
        grid-template-rows: 1fr 1fr;
        padding: 12px 50px;
      }
    }
    .viewer-empty { color: var(--muted); font-size: 13px; }
    .viewer-nav {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      width: 44px;
      height: 44px;
      border-radius: 50%;
      border: 0;
      display: grid;
      place-items: center;
      cursor: pointer;
      background: rgba(0, 0, 0, .45);
      color: #fff;
    }
    .viewer-nav:hover:not(:disabled) { background: rgba(0, 0, 0, .65); }
    .viewer-nav:disabled { opacity: .25; cursor: not-allowed; }
    .viewer-nav.prev { left: 12px; }
    .viewer-nav.next { right: 12px; }
    .viewer-foot {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 14px;
      padding: 10px 14px;
      border-top: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--muted);
      font-size: 13px;
    }
    .viewer-foot button {
      height: 32px;
      width: 32px;
      padding: 0;
      border-radius: 50%;
      border: 1px solid var(--field-border);
      background: var(--surface-3);
      color: var(--ink);
      display: inline-grid;
      place-items: center;
      cursor: pointer;
    }
    .viewer-foot button:disabled { opacity: .4; cursor: not-allowed; }
    .preview-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }
    .preview-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: var(--surface-3);
      cursor: pointer;
      display: grid;
      gap: 6px;
    }
    .preview-card:hover { border-color: var(--blue); }
    .preview-card img { width: 100%; height: auto; border-radius: 6px; display: block; background: var(--surface); }
    .preview-card .meta { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); }
    .compare {
      display: grid;
      gap: 12px;
    }
    .compare-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .compare-toolbar .spacer { flex: 1; }
    .compare-toolbar .kind-toggle {
      display: inline-flex;
      gap: 4px;
      padding: 3px;
      border: 1px solid var(--field-border);
      border-radius: 8px;
      background: var(--surface-3);
    }
    .compare-toolbar .kind-toggle button {
      height: 28px;
      padding: 0 10px;
      border-radius: 5px;
      border: 0;
      background: transparent;
      color: var(--ink);
    }
    .compare-toolbar .kind-toggle button.active { background: var(--blue); color: #fff; }
    .compare-pair {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .compare-pane {
      display: grid;
      gap: 6px;
    }
    .compare-pane img {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      display: block;
    }
    .compare-pane .label { font-size: 12px; color: var(--muted); }
    @media (max-width: 720px) {
      .compare-pair { grid-template-columns: 1fr; }
    }
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
    .modal-head h2,
    .modal-body h2 {
      font-size: 15px;
      font-weight: 750;
      text-transform: none;
      letter-spacing: 0;
      color: var(--ink);
      border-bottom: 0;
      padding-bottom: 0;
      margin-bottom: 12px;
      display: block;
    }
    .modal-head h2::before,
    .modal-body h2::before { content: none; }
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
    <div class="brand"><span class="brand-mark" aria-hidden="true">S</span><span>Star-Slide</span></div>
    <div class="tagline">NotebookLM에서 생성한 이미지 슬라이드를 <strong>편집 가능한 PPTX</strong>로 변환</div>
    <div class="header-actions">
      <button id="themeToggle" class="secondary theme-toggle" type="button">라이트 모드</button>
    </div>
  </header>
  <div id="keystoreBanner" class="keystore-banner" hidden role="alert"></div>
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
      <div id="uploadProgress" class="upload-progress" hidden>
        <div class="upload-progress-bar"><div></div></div>
        <div class="upload-progress-label hint">업로드 0%</div>
      </div>
      <div id="systemCheck" class="system-box">
        <div class="hint">시스템 의존성을 확인하는 중입니다.</div>
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
        <div class="api-key-row">
          <input id="model" list="modelOptions" placeholder="gpt-5.5 (로컬은 자동 조회)" autocomplete="off" />
          <button id="refreshModels" class="secondary" type="button" title="사용 가능한 모델 목록 다시 가져오기">↻ 모델</button>
        </div>
        <datalist id="modelOptions"></datalist>
        <div id="modelChips" class="model-chips" hidden></div>
        <div id="modelHint" class="hint"></div>
        <label for="apiKey">API Key</label>
        <div class="api-key-row">
          <input id="apiKey" type="password" placeholder="sk-... (Ollama 등 로컬은 비워두세요)" />
          <button id="testLlm" class="secondary" type="button">테스트</button>
        </div>
        <div id="testResult" class="test-result hint" hidden></div>
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
  <div id="modalBackdrop" class="modal-backdrop" onclick="closeModal(event)" aria-hidden="true">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
      <div class="modal-head">
        <h2 id="modalTitle">상세</h2>
        <button class="secondary" onclick="closeModal()" aria-label="모달 닫기">닫기</button>
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
    const jobCache = new Map();
    const sseSources = new Map();
    let lastJobIds = [];
    // pptx-preview 인스턴스 추적 (모달 닫힐 때 destroy하기 위함). compare 모드는 두 개.
    const viewerState = { jobId: null, filename: "", kind: "result", index: 0, total: 0, fullscreen: false, instances: [], pageInfos: [] };
    let _pptxPreviewModulePromise = null;

    function loadPptxPreview() {
      if (!_pptxPreviewModulePromise) {
        // CDN ESM. 첫 사용 시 ~수백 KB 로드, 이후 브라우저 캐시.
        _pptxPreviewModulePromise = import("https://esm.sh/pptx-preview@1.0.2").catch(err => {
          _pptxPreviewModulePromise = null;
          throw err;
        });
      }
      return _pptxPreviewModulePromise;
    }

    const optionFields = ["timeout","retries","llmParallel","fontScale","hybridAllowedDelta","sam3","editableEmbeddedText","keepIntermediates"];
    const settingsKey = "starSlideSettings";
    const themeKey = "starSlideTheme";
    const customPrefix = "custom:";
    const settingsVersion = 3;

    // === API key 암호화 keystore (WebCrypto AES-GCM + IndexedDB 비추출 키) ===
    const KEYSTORE_DB = "starSlideKeystore";
    const KEYSTORE_STORE = "keys";
    const KEYSTORE_KEY_NAME = "apiKeyMaster.v1";
    let _cryptoKeyPromise = null;
    let _settingsCache = null;
    // 진단: 한번이라도 decrypt가 실패했는가? true면 export(저장)를 막아서
    // 빈 값으로 ciphertext가 덮어써지는 데이터 손실을 차단한다.
    let _decryptFailed = false;

    function openKeystore() {
      return new Promise((resolve, reject) => {
        const req = indexedDB.open(KEYSTORE_DB, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(KEYSTORE_STORE);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }

    async function getOrCreateMasterKey() {
      const db = await openKeystore();
      const existing = await new Promise((resolve, reject) => {
        const tx = db.transaction(KEYSTORE_STORE, "readonly");
        const req = tx.objectStore(KEYSTORE_STORE).get(KEYSTORE_KEY_NAME);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => reject(req.error);
      });
      if (existing) { db.close(); return existing; }
      const key = await crypto.subtle.generateKey(
        { name: "AES-GCM", length: 256 },
        false,
        ["encrypt", "decrypt"]
      );
      await new Promise((resolve, reject) => {
        const tx = db.transaction(KEYSTORE_STORE, "readwrite");
        tx.objectStore(KEYSTORE_STORE).put(key, KEYSTORE_KEY_NAME);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
      db.close();
      return key;
    }

    function masterKey() {
      if (!_cryptoKeyPromise) _cryptoKeyPromise = getOrCreateMasterKey();
      return _cryptoKeyPromise;
    }

    function bytesToBase64(bytes) {
      let s = "";
      for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
      return btoa(s);
    }

    function base64ToBytes(b64) {
      const s = atob(b64);
      const out = new Uint8Array(s.length);
      for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
      return out;
    }

    async function encryptApiKey(plain) {
      if (!plain) return "";
      const key = await masterKey();
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(plain));
      const merged = new Uint8Array(iv.length + ct.byteLength);
      merged.set(iv, 0);
      merged.set(new Uint8Array(ct), iv.length);
      return bytesToBase64(merged);
    }

    async function decryptApiKey(enc) {
      if (!enc) return "";
      try {
        const key = await masterKey();
        const merged = base64ToBytes(enc);
        const iv = merged.slice(0, 12);
        const ct = merged.slice(12);
        const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ct);
        return new TextDecoder().decode(plain);
      } catch (err) {
        console.warn("API key 복호화 실패 (키 회전 또는 저장소 손상)", err);
        _decryptFailed = true;
        return null;  // 센티넬: 호출자는 ciphertext를 그대로 보존해야 한다
      }
    }

    async function importSettingsFromStorage() {
      let raw;
      try { raw = JSON.parse(localStorage.getItem(settingsKey) || "{}"); } catch { raw = {}; }
      if (!raw || typeof raw !== "object") raw = {};
      raw.providers = raw.providers || {};
      for (const id of Object.keys(raw.providers)) {
        const p = raw.providers[id];
        if (!p || typeof p !== "object") continue;
        if (p.apiKeyEnc) {
          const plain = await decryptApiKey(p.apiKeyEnc);
          // null = decrypt 실패. apiKey는 미설정으로 두고 ciphertext는 보존한다.
          if (plain !== null) p.apiKey = plain;
        } else if (typeof p.apiKey !== "string") {
          p.apiKey = "";
        }
      }
      raw.customProviders = Array.isArray(raw.customProviders) ? raw.customProviders : [];
      for (const p of raw.customProviders) {
        if (!p || typeof p !== "object") continue;
        if (p.apiKeyEnc) {
          const plain = await decryptApiKey(p.apiKeyEnc);
          if (plain !== null) p.apiKey = plain;
        } else if (typeof p.apiKey !== "string") {
          p.apiKey = "";
        }
      }
      return raw;
    }

    async function exportSettingsToStorage(settings) {
      const out = JSON.parse(JSON.stringify(settings || {}));
      out.providers = out.providers || {};
      for (const id of Object.keys(out.providers)) {
        const p = out.providers[id];
        if (!p || typeof p !== "object") continue;
        // apiKey가 명시적 string이면 그것만 암호화. undefined(=decrypt 실패로 미설정)
        // 면 기존 apiKeyEnc를 그대로 두어 사용자의 ciphertext를 보존한다.
        if (typeof p.apiKey === "string") {
          p.apiKeyEnc = await encryptApiKey(p.apiKey);
        }
        delete p.apiKey;
      }
      out.customProviders = Array.isArray(out.customProviders) ? out.customProviders : [];
      for (const p of out.customProviders) {
        if (!p || typeof p !== "object") continue;
        if (typeof p.apiKey === "string") {
          p.apiKeyEnc = await encryptApiKey(p.apiKey);
        }
        delete p.apiKey;
      }
      out.settingsVersion = settingsVersion;
      localStorage.setItem(settingsKey, JSON.stringify(out));
    }

    function setKeystoreBanner(message) {
      const el = $("keystoreBanner");
      if (!el) return;
      if (!message) { el.hidden = true; el.textContent = ""; return; }
      el.hidden = false;
      el.textContent = message;
    }

    function hasLegacyPlaintextKey() {
      let raw;
      try { raw = JSON.parse(localStorage.getItem(settingsKey) || "{}"); } catch { return false; }
      if (!raw || typeof raw !== "object") return false;
      const providers = raw.providers || {};
      for (const id of Object.keys(providers)) {
        const p = providers[id];
        if (p && typeof p === "object" && p.apiKey && !p.apiKeyEnc) return true;
      }
      const customs = Array.isArray(raw.customProviders) ? raw.customProviders : [];
      for (const p of customs) {
        if (p && typeof p === "object" && p.apiKey && !p.apiKeyEnc) return true;
      }
      return false;
    }

    async function init() {
      applyTheme(localStorage.getItem(themeKey) || "dark");
      presets = await (await fetch("/api/presets")).json();
      const needsMigration = hasLegacyPlaintextKey();
      _settingsCache = await importSettingsFromStorage();
      // decrypt 실패가 한 번이라도 있었다면 자동 마이그레이션을 건너뛴다 (export가
      // ciphertext를 빈값으로 덮어쓸 위험 차단). 사용자가 명시적으로 키를 다시 입력해
      // save하면 그때 정상 export 된다.
      if (needsMigration && !_decryptFailed) {
        try { await exportSettingsToStorage(_settingsCache); } catch (err) { console.warn("API key 마이그레이션 실패", err); }
      }
      if (_decryptFailed) {
        setKeystoreBanner("⚠ 저장된 API 키를 복호화할 수 없습니다 (브라우저 keystore 손상 또는 시크릿 모드). 기존 ciphertext는 보존되었으니 사용 중인 다른 브라우저에서 확인하거나, 새 키를 입력 후 저장하세요.");
      }
      loadSettings();
      $("provider").addEventListener("change", changeProvider);
      $("addCustom").addEventListener("click", addCustomProvider);
      $("deleteCustom").addEventListener("click", deleteCustomProvider);
      $("customName").addEventListener("change", renameSelectedCustomProvider);
      $("save").addEventListener("click", saveSettings);
      $("testLlm").addEventListener("click", testLlmSettings);
      $("refreshModels").addEventListener("click", () => fetchModelList(true));
      $("start").addEventListener("click", submit);
      $("themeToggle").addEventListener("click", toggleTheme);
      document.addEventListener("keydown", handleGlobalKey);
      setupDrop();
      await loadSystemCheck();
      await refreshJobs();
      pollTimer = setInterval(refreshJobs, 2500);
    }

    function handleGlobalKey(event) {
      if (!$("modalBackdrop").classList.contains("open")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeModal();
        return;
      }
      if (viewerState.jobId == null) return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        moveViewer(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        moveViewer(1);
      } else if (event.key === "f" || event.key === "F") {
        event.preventDefault();
        toggleViewerFullscreen();
      }
    }

    async function loadSystemCheck() {
      try {
        const payload = await (await fetch("/api/system-check")).json();
        $("systemCheck").innerHTML = renderSystemCheck(payload.items || []);
      } catch (error) {
        $("systemCheck").innerHTML = `<div class="hint" style="color:var(--danger);">시스템 의존성 확인 실패: ${escapeHtml(error.message)}</div>`;
      }
    }

    function renderSystemCheck(items) {
      if (!items.length) return `<div class="hint">시스템 의존성 정보가 없습니다.</div>`;
      return `
        <h2 style="margin-bottom:2px;">시스템 상태</h2>
        ${items.map(item => `
          <div class="system-row">
            <span class="system-name">${escapeHtml(item.label)}</span>
            <span class="status-pill ${item.ok ? "ok" : ""}">${item.ok ? "OK" : (item.required ? "필수" : "옵션")}</span>
            <span class="hint">${escapeHtml(item.ok ? item.path : item.message)}</span>
          </div>
        `).join("")}
      `;
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
      const base = _settingsCache && typeof _settingsCache === "object"
        ? JSON.parse(JSON.stringify(_settingsCache))
        : {};
      const normalized = normalizeSettings(base);
      if (normalized.changed) {
        _settingsCache = JSON.parse(JSON.stringify(normalized.settings));
        exportSettingsToStorage(_settingsCache).catch(err => console.warn("settings export 실패", err));
      }
      return normalized.settings;
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
      if (!saved.settingsVersion) {
        saved.options = {...(saved.options || {}), sam3: false};
      }
      if (saved.settingsVersion !== settingsVersion) {
        saved.settingsVersion = settingsVersion;
        changed = true;
      }
      return {settings: saved, changed};
    }

    function makeProviderId() {
      if (window.crypto?.randomUUID) return window.crypto.randomUUID();
      return `custom_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    }

    function writeStoredSettings(settings) {
      _settingsCache = JSON.parse(JSON.stringify(settings));
      exportSettingsToStorage(_settingsCache).catch(err => console.warn("settings export 실패", err));
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
      saved.settingsVersion = settingsVersion;
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
      saved.settingsVersion = settingsVersion;
      writeStoredSettings(saved);
      activeProvider = $("provider").value;
      applyProvider(false);
    }

    function applyProvider(overwrite = true) {
      // provider가 바뀌면 이전 테스트/모델 hint는 컨텍스트가 달라지므로 항상 클리어
      setTestResult(null);
      setModelHint("");
      clearModelOptions();

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
        maybeAutoFetchModels();
        return;
      }

      const preset = builtInProviders().find(p => p.id === providerId);
      if (!preset) return;
      const providerSettings = (saved.providers || {})[providerId] || {};
      $("baseUrl").value = overwrite ? (preset.baseUrl || "") : (providerSettings.baseUrl ?? preset.baseUrl ?? "");
      $("model").value = overwrite ? (preset.model || "") : (providerSettings.model ?? preset.model ?? "");
      $("apiKey").value = overwrite ? "" : (providerSettings.apiKey ?? "");
      $("providerHint").textContent = preset.hint || "";
      maybeAutoFetchModels();
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
      saved.settingsVersion = settingsVersion;
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
      saved.settingsVersion = settingsVersion;
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
      saved.settingsVersion = settingsVersion;
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
      // 새 파일을 고르면 이전 작업의 업로드 진행률/완료 메시지는 무관하므로 즉시 클리어
      setUploadProgress(false, 0, "");
    }

    let currentModelList = [];

    function renderModelChips(models) {
      currentModelList = Array.isArray(models) ? models : [];
      const root = $("modelChips");
      if (!currentModelList.length) { root.hidden = true; root.innerHTML = ""; return; }
      const current = $("model").value.trim();
      root.hidden = false;
      root.innerHTML = currentModelList.map(m => {
        const safe = escapeHtml(m);
        const active = m === current ? " active" : "";
        return `<button type="button" class="model-chip${active}" data-model="${safe}">${safe}</button>`;
      }).join("");
      root.querySelectorAll(".model-chip").forEach(btn => {
        btn.addEventListener("click", () => pickModel(btn.dataset.model));
      });
    }

    function pickModel(name) {
      $("model").value = name;
      renderModelChips(currentModelList);
    }

    function clearModelOptions() {
      $("modelOptions").innerHTML = "";
      $("modelChips").innerHTML = "";
      $("modelChips").hidden = true;
      currentModelList = [];
    }

    function isLocalHost(baseUrl) {
      if (!baseUrl) return false;
      try {
        const u = new URL(baseUrl);
        return ["localhost", "127.0.0.1", "0.0.0.0", "::1"].includes(u.hostname);
      } catch { return false; }
    }

    function setModelHint(message, state) {
      const root = $("modelHint");
      if (!message) { root.textContent = ""; root.style.color = ""; return; }
      root.textContent = message;
      root.style.color = state === "fail" ? "var(--danger)" : state === "ok" ? "var(--teal)" : "";
    }

    async function fetchModelList(manual) {
      const baseUrl = $("baseUrl").value.trim();
      const apiKey = $("apiKey").value;
      if (!baseUrl) {
        if (manual) setModelHint("Base URL을 먼저 입력하세요.", "fail");
        return;
      }
      const button = $("refreshModels");
      button.disabled = true;
      const original = button.textContent;
      button.textContent = "조회 중...";
      setModelHint("모델 목록을 가져오는 중...");
      try {
        const response = await fetch("/api/list-models", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({baseUrl, apiKey, timeout: 10}),
        });
        const data = await response.json();
        const models = Array.isArray(data.models) ? data.models : [];
        const datalist = $("modelOptions");
        datalist.innerHTML = models.map(m => `<option value="${escapeHtml(m)}"></option>`).join("");
        renderModelChips(models);
        if (models.length === 0) {
          setModelHint(manual ? "모델 목록을 가져오지 못했습니다 (서버가 /v1/models를 미지원할 수 있음). 직접 입력하세요." : "", "fail");
        } else {
          if (!$("model").value) {
            $("model").value = models[0];
            renderModelChips(models);
          }
          setModelHint(`사용 가능한 모델 ${models.length}개 — 칩을 클릭하거나 직접 입력하세요`, "ok");
        }
      } catch (error) {
        setModelHint(`모델 목록 요청 실패: ${error.message}`, "fail");
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    }

    function maybeAutoFetchModels() {
      // 로컬 호스트면 자동 페치, 외부 provider면 datalist/chips/hint 모두 클리어
      if (isLocalHost($("baseUrl").value.trim())) {
        fetchModelList(false);
      } else {
        clearModelOptions();
        setModelHint("");
      }
    }

    function setTestResult(state, message) {
      const root = $("testResult");
      if (!state) { root.hidden = true; root.textContent = ""; root.className = "test-result hint"; return; }
      root.hidden = false;
      root.className = `test-result hint ${state}`;
      root.textContent = message;
    }

    async function testLlmSettings() {
      const baseUrl = $("baseUrl").value.trim();
      const model = $("model").value.trim();
      const apiKey = $("apiKey").value;
      if (!baseUrl) { setTestResult("fail", "Base URL을 입력하세요."); return; }
      if (!model) { setTestResult("fail", "Model 이름을 입력하세요."); return; }

      const button = $("testLlm");
      button.disabled = true;
      const original = button.textContent;
      button.textContent = "확인 중...";
      const keyNote = apiKey ? "" : " (API key 미설정 — Ollama/로컬 프록시 모드)";
      setTestResult("busy", `${baseUrl} 로 테스트 호출 중...${keyNote}`);

      try {
        const response = await fetch("/api/test-llm", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({baseUrl, model, apiKey, timeout: 15}),
        });
        const data = await response.json();
        if (data.ok) {
          const sample = data.sample ? ` · "${data.sample}"` : "";
          const note = data.note ? ` · ${data.note}` : "";
          setTestResult("ok", `✓ 성공 · ${data.latency_ms}ms · ${data.model}${sample}${keyNote}${note}`);
        } else {
          const lat = data.latency_ms !== undefined ? ` (${data.latency_ms}ms)` : "";
          setTestResult("fail", `✗ ${data.error || "알 수 없는 오류"}${lat}`);
        }
      } catch (error) {
        setTestResult("fail", `✗ 요청 실패: ${error.message}`);
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    }

    function setUploadProgress(visible, percent, label) {
      const root = $("uploadProgress");
      if (!visible) { root.hidden = true; return; }
      root.hidden = false;
      root.querySelector(".upload-progress-bar > div").style.width = `${Math.max(0, Math.min(100, percent))}%`;
      root.querySelector(".upload-progress-label").textContent = label || `업로드 ${Math.round(percent)}%`;
    }

    function submit() {
      if (!selectedFile) {
        alert("먼저 PPTX/PDF 파일을 선택하세요.");
        return;
      }
      saveSettings(false);
      const file = selectedFile;
      $("start").disabled = true;
      $("start").textContent = "업로드 중";
      setUploadProgress(true, 0, "업로드 0%");

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/jobs?filename=${encodeURIComponent(file.name)}`, true);
      xhr.setRequestHeader("x-star-slide-options", JSON.stringify(readOptions(false)));
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = (event.loaded / event.total) * 100;
          setUploadProgress(true, percent, `업로드 ${Math.round(percent)}%`);
        }
      };
      xhr.onload = () => {
        $("start").disabled = false;
        $("start").textContent = "변환 시작";
        if (xhr.status >= 200 && xhr.status < 300) {
          setUploadProgress(true, 100, "업로드 완료, 변환 대기 중");
          setTimeout(() => setUploadProgress(false, 0, ""), 1500);
          selectedFile = null;
          $("file").value = "";
          $("fileLabel").textContent = "NotebookLM에서 내려받은 .pptx 또는 .pdf 파일";
          refreshJobs();
        } else {
          setUploadProgress(false, 0, "");
          alert(`업로드 실패: ${xhr.responseText || xhr.status}`);
        }
      };
      xhr.onerror = () => {
        $("start").disabled = false;
        $("start").textContent = "변환 시작";
        setUploadProgress(false, 0, "");
        alert("업로드 실패: 네트워크 오류");
      };
      xhr.send(file);
    }

    async function refreshJobs() {
      const jobs = await (await fetch("/api/jobs")).json();
      const root = $("jobs");
      if (!jobs.length) {
        root.innerHTML = `<div class="empty">아직 실행한 작업이 없습니다.</div>`;
        teardownAllSse();
        lastJobIds = [];
        return;
      }
      jobs.forEach(job => jobCache.set(job.id, job));
      const totalPages = Math.max(1, Math.ceil(jobs.length / pageSize));
      currentPage = Math.min(currentPage, totalPages);
      const start = (currentPage - 1) * pageSize;
      const pageJobs = jobs.slice(start, start + pageSize);

      const pageIds = pageJobs.map(job => job.id);
      const reuse = pageIds.length === lastJobIds.length && pageIds.every((id, i) => id === lastJobIds[i]);
      if (!reuse) {
        root.innerHTML = renderPager(jobs.length, totalPages) + pageJobs.map(renderJob).join("");
        lastJobIds = pageIds;
      } else {
        pageJobs.forEach(updateJobCard);
      }
      pageJobs.forEach(maybeSubscribeSse);
      const visibleIds = new Set(pageIds);
      [...sseSources.keys()].forEach(id => {
        if (!visibleIds.has(id)) teardownSse(id);
      });
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

    function statusLabel(status) {
      switch (status) {
        case "done": return "완료";
        case "failed": return "실패";
        case "cancelled": return "취소됨";
        case "cancelling": return "취소 중";
        case "running": return "진행 중";
        case "queued": return "대기 중";
        default: return status;
      }
    }

    function jobActions(job) {
      const parts = [];
      if (job.status === "done") {
        // 사용자 요청 순서: PPTX 다운로드 | 미리보기 | 원본보기 | 비교 | 리포트 | Layout | 다시 실행
        parts.push(`<a class="button" href="/api/jobs/${job.id}/download">PPTX 다운로드</a>`);
        parts.push(`<button class="secondary" onclick="openSlideViewer('${job.id}', 'result')">미리보기</button>`);
        parts.push(`<button class="secondary" onclick="openSlideViewer('${job.id}', 'original')">원본 보기</button>`);
        parts.push(`<button class="secondary" onclick="openCompareViewer('${job.id}')">${ICON_COMPARE_INLINE} 비교 보기</button>`);
        parts.push(`<button class="secondary" onclick="openReport('${job.id}')">리포트 보기</button>`);
        if (job.artifacts?.layout_json) {
          parts.push(`<button class="secondary" onclick="openLayoutSummary('${job.id}')">Layout 보기</button>`);
        }
      }
      if (job.status === "running" || job.status === "queued" || job.status === "cancelling") {
        parts.push(`<button class="secondary" onclick="cancelJob('${job.id}')">취소</button>`);
      }
      if (job.status === "done" || job.status === "failed" || job.status === "cancelled") {
        parts.push(`<button class="secondary" onclick="rerunJob('${job.id}')">다시 실행</button>`);
      }
      if (!parts.length) return "";
      return `<div class="job-actions">${parts.join("")}</div>`;
    }

    function isJobActive(status) {
      return status === "running" || status === "queued" || status === "cancelling";
    }

    function renderJob(job) {
      const pct = Math.max(0, Math.min(100, job.progress || 0));
      const error = job.error ? `<div class="hint job-error" style="color:var(--danger);">${escapeHtml(job.error)}</div>` : "";
      const active = isJobActive(job.status);
      // 진행 중에만 진행률 바와 phase/percent 표시. 완료/실패/취소된 카드는 메타와 액션만 보여 군더더기를 줄인다.
      const progressBlock = active
        ? `
            <div class="hint job-phase">${escapeHtml(job.phase || "")}</div>
            <div class="bar"><div style="width:${pct}%"></div></div>
            <div class="job-meta">
              <span class="metric job-percent">${Math.round(pct)}%</span>
              <span class="metric">${new Date(job.created_at * 1000).toLocaleString()}</span>
              <span class="metric">${escapeHtml(job.options?.model || "")}</span>
            </div>`
        : `
            <div class="job-meta">
              <span class="metric">${new Date(job.created_at * 1000).toLocaleString()}</span>
              ${job.options?.model ? `<span class="metric">${escapeHtml(job.options.model)}</span>` : ""}
            </div>`;
      return `
        <section class="job" data-job-id="${job.id}" data-status="${job.status}">
          <div class="job-head">
            <div class="job-title">${escapeHtml(job.filename)}</div>
            <span class="badge ${job.status}">${statusLabel(job.status)}</span>
          </div>
          ${progressBlock}
          ${error}
          ${jobActions(job)}
        </section>
      `;
    }

    function updateJobCard(job) {
      const card = document.querySelector(`section.job[data-job-id="${job.id}"]`);
      if (!card) return;
      // status 전환(active ↔ terminal)이 발생하면 progress 블록 모양 자체가 바뀌므로 통째로 다시 그린다.
      const prevStatus = card.dataset.status;
      const wasActive = isJobActive(prevStatus);
      const isActive = isJobActive(job.status);
      if (wasActive !== isActive) {
        card.outerHTML = renderJob(job);
        return;
      }
      card.dataset.status = job.status;
      const pct = Math.max(0, Math.min(100, job.progress || 0));
      const badge = card.querySelector(".badge");
      if (badge) {
        badge.className = `badge ${job.status}`;
        badge.textContent = statusLabel(job.status);
      }
      const phase = card.querySelector(".job-phase");
      if (phase) phase.textContent = job.phase || "";
      const bar = card.querySelector(".bar > div");
      if (bar) bar.style.width = `${pct}%`;
      const percent = card.querySelector(".job-percent");
      if (percent) percent.textContent = `${Math.round(pct)}%`;
      const oldErr = card.querySelector(".job-error");
      if (oldErr) oldErr.remove();
      if (job.error) {
        const div = document.createElement("div");
        div.className = "hint job-error";
        div.style.color = "var(--danger)";
        div.textContent = job.error;
        const actions = card.querySelector(".job-actions");
        card.insertBefore(div, actions || null);
      }
      const oldActions = card.querySelector(".job-actions");
      const newHtml = jobActions(job);
      if (oldActions) oldActions.remove();
      if (newHtml) card.insertAdjacentHTML("beforeend", newHtml);
    }

    function maybeSubscribeSse(job) {
      if (job.status === "done" || job.status === "failed" || job.status === "cancelled") {
        teardownSse(job.id);
        return;
      }
      if (sseSources.has(job.id)) return;
      if (typeof EventSource === "undefined") return;
      const es = new EventSource(`/api/jobs/${job.id}/events`);
      sseSources.set(job.id, es);
      es.addEventListener("snapshot", (evt) => {
        try {
          const snap = JSON.parse(evt.data);
          jobCache.set(snap.id, snap);
          updateJobCard(snap);
          if (snap.status === "done" || snap.status === "failed" || snap.status === "cancelled") {
            teardownSse(snap.id);
            refreshJobs();
          }
        } catch {
          /* ignore malformed payload */
        }
      });
      es.onerror = () => teardownSse(job.id);
    }

    function teardownSse(jobId) {
      const es = sseSources.get(jobId);
      if (es) {
        es.close();
        sseSources.delete(jobId);
      }
    }

    function teardownAllSse() {
      sseSources.forEach(es => es.close());
      sseSources.clear();
    }

    async function cancelJob(jobId) {
      if (!confirm("이 작업을 취소하시겠습니까? 진행 단계가 끝난 직후 중단됩니다.")) return;
      try {
        const response = await fetch(`/api/jobs/${jobId}/cancel`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: "{}",
        });
        if (!response.ok) throw new Error(await response.text());
        const snap = await response.json();
        jobCache.set(snap.id, snap);
        updateJobCard(snap);
      } catch (error) {
        alert(`취소 실패: ${error.message}`);
      }
    }

    async function rerunJob(jobId) {
      try {
        const response = await fetch(`/api/jobs/${jobId}/rerun`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: "{}",
        });
        if (!response.ok) throw new Error(await response.text());
        currentPage = 1;
        await refreshJobs();
      } catch (error) {
        alert(`다시 실행 실패: ${error.message}`);
      }
    }

    function openModal(title, html, options) {
      const modal = document.querySelector("#modalBackdrop .modal");
      const head = modal.querySelector(".modal-head");
      modal.classList.toggle("viewer-modal", Boolean(options?.viewer));
      head.style.display = options?.hideHeader ? "none" : "";
      $("modalTitle").textContent = title;
      $("modalBody").innerHTML = html;
      $("modalBackdrop").classList.add("open");
      $("modalBackdrop").setAttribute("aria-hidden", "false");
    }

    function closeModal(event) {
      if (event && event.target !== $("modalBackdrop")) return;
      const modal = document.querySelector("#modalBackdrop .modal");
      // pptx-preview 인스턴스와 MutationObserver 정리
      for (const info of viewerState.pageInfos) {
        try { info?.observer?.disconnect(); } catch { /* ignore */ }
      }
      destroyViewerInstances();
      $("modalBackdrop").classList.remove("open");
      $("modalBackdrop").setAttribute("aria-hidden", "true");
      $("modalBody").innerHTML = "";
      modal.classList.remove("viewer-modal", "fullscreen");
      modal.querySelector(".modal-head").style.display = "";
      viewerState.jobId = null;
      viewerState.kind = "result";
      viewerState.index = 0;
      viewerState.total = 0;
      viewerState.fullscreen = false;
      viewerState.pageInfos = [];
    }

    const ICON_COMPARE_INLINE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><rect x="3" y="5" width="7" height="14" rx="1"/><rect x="14" y="5" width="7" height="14" rx="1"/></svg>`;
    const ICON_PREV = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`;
    const ICON_NEXT = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`;
    const ICON_FULLSCREEN = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>`;
    const ICON_MINIMIZE = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/></svg>`;
    const ICON_DOWNLOAD = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
    const ICON_CLOSE = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;

    function kindLabel(kind) {
      switch (kind) {
        case "original": return "원본";
        case "result": return "변환 결과";
        case "selected": return "변환 결과";
        case "vector": return "Vector";
        case "hybrid": return "Hybrid";
        case "compare": return "비교";
        default: return kind;
      }
    }

    async function openCompareViewer(jobId) {
      return openSlideViewer(jobId, "compare");
    }

    async function fetchPptxArrayBuffer(jobId, which) {
      const response = await fetch(`/api/jobs/${jobId}/pptx-file?which=${encodeURIComponent(which)}`);
      if (!response.ok) throw new Error(`${kindLabel(which)} PPTX: HTTP ${response.status}`);
      return response.arrayBuffer();
    }

    function destroyViewerInstances() {
      for (const inst of viewerState.instances) {
        try { inst?.destroy?.(); } catch { /* ignore */ }
      }
      viewerState.instances = [];
      viewerState.pageInfos = [];
    }

    async function openSlideViewer(jobId, which) {
      const job = jobCache.get(jobId);
      const filename = job?.filename || "";
      destroyViewerInstances();
      viewerState.jobId = jobId;
      viewerState.filename = filename;
      viewerState.kind = which;
      viewerState.index = 0;
      viewerState.total = 0;
      viewerState.fullscreen = false;
      // 모달을 먼저 띄우고 라이브러리 로드 + PPTX 다운로드를 비동기로.
      openModal(
        "",
        `<div class="viewer"><div class="viewer-stage"><div class="viewer-empty">PPTX 미리보기 라이브러리 로딩 중...</div></div></div>`,
        { viewer: true, hideHeader: true }
      );
      try {
        const [{ init }, ...buffers] = await Promise.all([
          loadPptxPreview(),
          ...(which === "compare"
            ? [fetchPptxArrayBuffer(jobId, "original"), fetchPptxArrayBuffer(jobId, "result")]
            : [fetchPptxArrayBuffer(jobId, which)]),
        ]);
        renderViewerShell();
        // shell이 DOM에 생긴 뒤에 컨테이너 측정 + 라이브러리 init
        await new Promise(r => requestAnimationFrame(() => r()));
        if (which === "compare") {
          const [origBuf, resultBuf] = buffers;
          await Promise.all([
            mountPptxInstance("compareOrigHost", origBuf, init, 0),
            mountPptxInstance("compareResultHost", resultBuf, init, 1),
          ]);
        } else {
          await mountPptxInstance("singleHost", buffers[0], init, 0);
        }
        // 페이지 수 추출 (양쪽 instance의 max)
        const totals = viewerState.pageInfos.map(p => p.total).filter(n => n > 0);
        viewerState.total = totals.length ? Math.max(...totals) : 1;
        updateCounter();
      } catch (error) {
        const msg = error?.message || String(error);
        $("modalBody").innerHTML = `<div class="viewer"><div class="viewer-stage"><div class="viewer-empty" style="color:var(--danger);">미리보기 실패: ${escapeHtml(msg)}</div></div></div>`;
      }
    }

    async function mountPptxInstance(hostId, arrayBuffer, init, slot) {
      const host = document.getElementById(hostId);
      if (!host) return;
      // 컨테이너 측정. 모달 사이즈에 맞춰 wrapper를 줄인다.
      const w = Math.max(320, host.clientWidth);
      const h = Math.max(180, host.clientHeight);
      host.innerHTML = "";
      const previewer = init(host, { width: w, height: h, mode: "slide" });
      await previewer.preview(arrayBuffer);
      previewer._host = host;
      viewerState.instances[slot] = previewer;
      applyPptxZoom(host);
      // 라이브러리 내장 nav 버튼/페이지네이션 숨기고 페이지 정보만 추출
      hideNativeNavAndSync(host, slot);
      // DOM 변경 감지 — 페이지 이동/리사이즈 시에도 동기화
      const observer = new MutationObserver(() => hideNativeNavAndSync(host, slot));
      observer.observe(host, { childList: true, subtree: true });
      viewerState.pageInfos[slot] = viewerState.pageInfos[slot] || { current: 1, total: 1, observer };
      viewerState.pageInfos[slot].observer = observer;
    }

    function hideNativeNavAndSync(host, slot) {
      const navBtns = host.querySelectorAll(".pptx-preview-wrapper-next");
      navBtns.forEach(btn => btn.style.setProperty("display", "none", "important"));
      const pagination = host.querySelector(".pptx-preview-wrapper-pagination");
      if (pagination) {
        const text = (pagination.innerText || "").trim();
        const m = text.match(/(\d+)\s*\/\s*(\d+)/);
        if (m) {
          viewerState.pageInfos[slot] = viewerState.pageInfos[slot] || {};
          viewerState.pageInfos[slot].current = parseInt(m[1], 10);
          viewerState.pageInfos[slot].total = parseInt(m[2], 10);
          updateCounter();
        }
        pagination.style.setProperty("display", "none", "important");
      }
    }

    function clickNativeNav(host, direction) {
      // 라이브러리 내장 prev/next 버튼은 wrapper-next 0번(다음), 1번(이전) 순서 (참조 코드 기준)
      const navBtns = host.querySelectorAll(".pptx-preview-wrapper-next");
      const idx = direction === "prev" ? 1 : 0;
      const btn = navBtns[idx];
      if (!btn) return;
      btn.style.setProperty("display", "block");
      btn.click();
      btn.style.setProperty("display", "none", "important");
    }

    function moveViewer(delta) {
      if (viewerState.kind === "compare") {
        const origHost = document.getElementById("compareOrigHost");
        const resultHost = document.getElementById("compareResultHost");
        const dir = delta > 0 ? "next" : "prev";
        if (origHost) clickNativeNav(origHost, dir);
        if (resultHost) clickNativeNav(resultHost, dir);
      } else {
        const host = document.getElementById("singleHost");
        if (host) clickNativeNav(host, delta > 0 ? "next" : "prev");
      }
      // 페이지 정보는 MutationObserver가 자동 갱신하지만, 즉시 카운터 보강
      setTimeout(updateCounter, 60);
    }

    function updateCounter() {
      const counter = document.querySelector(".viewer-title .counter");
      if (!counter) return;
      const slot = viewerState.kind === "compare" ? 1 : 0; // 기준은 변환 결과
      const info = viewerState.pageInfos[slot] || { current: 1, total: viewerState.total || 1 };
      const total = info.total || viewerState.total || 1;
      const current = Math.min(info.current || 1, total);
      counter.textContent = `${current} / ${total}`;
      const footCounter = document.querySelector(".viewer-foot span");
      if (footCounter) footCounter.textContent = `슬라이드 ${current} / ${total}`;
      viewerState.index = current - 1;
    }

    function renderViewerShell() {
      const fullscreenIcon = viewerState.fullscreen ? ICON_MINIMIZE : ICON_FULLSCREEN;
      const fullscreenTitle = viewerState.fullscreen ? "축소 (F)" : "전체화면 (F)";
      const modal = document.querySelector("#modalBackdrop .modal");
      modal.classList.toggle("fullscreen", viewerState.fullscreen);
      const isCompare = viewerState.kind === "compare";
      const titleBlock = isCompare
        ? `<span class="kind-pill original">원본</span><span class="kind-pill">변환 결과</span>`
        : `<span class="kind-pill ${viewerState.kind === "original" ? "original" : ""}">${escapeHtml(kindLabel(viewerState.kind))}</span>`;
      const stage = isCompare
        ? `
            <button class="viewer-nav prev" onclick="moveViewer(-1)" title="이전 (←)">${ICON_PREV}</button>
            <div class="compare-pane">
              <div class="pane-label">원본</div>
              <div class="pane-img-wrap"><div id="compareOrigHost" class="pptx-host"></div></div>
            </div>
            <div class="compare-pane">
              <div class="pane-label result">변환 결과</div>
              <div class="pane-img-wrap"><div id="compareResultHost" class="pptx-host"></div></div>
            </div>
            <button class="viewer-nav next" onclick="moveViewer(1)" title="다음 (→)">${ICON_NEXT}</button>`
        : `
            <button class="viewer-nav prev" onclick="moveViewer(-1)" title="이전 (←)">${ICON_PREV}</button>
            <div id="singleHost" class="pptx-host"></div>
            <button class="viewer-nav next" onclick="moveViewer(1)" title="다음 (→)">${ICON_NEXT}</button>`;
      $("modalBody").innerHTML = `
        <div class="viewer ${viewerState.fullscreen ? "fullscreen" : ""}">
          <div class="viewer-head">
            <div class="viewer-title">
              ${titleBlock}
              <span class="filename" title="${escapeHtml(viewerState.filename)}">${escapeHtml(viewerState.filename)}</span>
              <span class="counter">- / -</span>
            </div>
            <div class="viewer-actions">
              <a class="viewer-icon" href="/api/jobs/${viewerState.jobId}/pptx-file?which=${viewerState.kind === "compare" ? "result" : viewerState.kind}" download title="PPTX 다운로드">${ICON_DOWNLOAD}</a>
              <button class="viewer-icon" onclick="toggleViewerFullscreen()" title="${fullscreenTitle}">${fullscreenIcon}</button>
              <button class="viewer-icon" onclick="closeModal()" title="닫기 (Esc)">${ICON_CLOSE}</button>
            </div>
          </div>
          <div class="viewer-stage ${isCompare ? "compare" : ""}">${stage}</div>
          <div class="viewer-foot">
            <button onclick="moveViewer(-1)" title="이전 (←)">${ICON_PREV}</button>
            <span>슬라이드 - / -</span>
            <button onclick="moveViewer(1)" title="다음 (→)">${ICON_NEXT}</button>
          </div>
        </div>
      `;
    }

    function toggleViewerFullscreen() {
      viewerState.fullscreen = !viewerState.fullscreen;
      const modal = document.querySelector("#modalBackdrop .modal");
      if (modal) modal.classList.toggle("fullscreen", viewerState.fullscreen);
      const viewer = document.querySelector(".viewer");
      if (viewer) viewer.classList.toggle("fullscreen", viewerState.fullscreen);
      // 컨테이너 사이즈가 바뀌었으니 라이브러리 zoom 재적용
      for (const inst of viewerState.instances) {
        const host = inst?._host;
        if (host) applyPptxZoom(host);
      }
      // shell 변경하지 않음 (라이브러리 인스턴스 유지)
    }

    function applyPptxZoom(host) {
      const wrapper = host.querySelector(".pptx-preview-wrapper");
      if (!wrapper) return;
      const baseW = parseInt(wrapper.style.width) || 960;
      const baseH = parseInt(wrapper.style.height) || 540;
      const cw = host.clientWidth;
      const ch = host.clientHeight;
      if (cw <= 0 || ch <= 0) return;
      wrapper.style.zoom = String(Math.min(cw / baseW, ch / baseH));
    }
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
