"""Integration tests for the web app API.

Cover SSE event streaming, cancel, rerun, and preview endpoints with a
fake conversion pipeline (no LibreOffice / Vision LLM required).
"""

from __future__ import annotations

import importlib
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from PIL import Image

import star_slide.api.web_app as web_app_module
from star_slide.api.preview_assets import generate_previews
from star_slide.pipeline.notebooklm_auto import JobCancelledError


def _write_png(path: Path, *, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), color).save(path, format="PNG")


def _drain_sse_lines(response: Any, *, deadline: float) -> list[str]:
    lines: list[str] = []
    for raw in response.iter_lines():
        if isinstance(raw, bytes):
            line = raw.decode("utf-8")
        else:
            line = raw or ""
        lines.append(line)
        if line.startswith("data:") and ('"status": "done"' in line or '"status": "cancelled"' in line):
            break
        if time.monotonic() > deadline:
            break
    return lines


@pytest.fixture
def web_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(web_app_module, "WEB_ROOT", tmp_path / "web_jobs")
    web_app_module.jobs.clear()
    web_app_module.futures.clear()
    app = web_app_module.create_app()
    with TestClient(app) as client:
        yield client
    web_app_module.jobs.clear()
    web_app_module.futures.clear()


def _install_fake_convert(
    monkeypatch: pytest.MonkeyPatch,
    *,
    behaviour: str = "ok",
    gate: threading.Event | None = None,
) -> None:
    def fake_convert(
        *,
        input_path: Path,
        output_path: Path,
        workdir: Path,
        options: Any,
        progress: Any | None = None,
        cancel: Any | None = None,
    ) -> Any:
        workdir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress("작업 시작", 5)
        for kind in ("images", "qa_vector", "qa_hybrid", "qa_selected"):
            for slide_no in (1, 2):
                _write_png(workdir / kind / f"slide_{slide_no:03d}.png", color=(slide_no * 80, 100, 200))
        if behaviour == "cancel":
            if gate is not None:
                gate.set()
            for _ in range(50):
                if cancel is not None and cancel():
                    raise JobCancelledError("cancelled by test")
                time.sleep(0.02)
            raise JobCancelledError("cancelled by test (timeout)")
        if behaviour == "fail":
            raise RuntimeError("fake convert failure")
        if progress:
            progress("hybrid layout 생성 중", 70)
        report_path = workdir / "notebooklm_auto_report.json"
        report_path.write_text(json.dumps({"selected_qa": [], "vector_qa": [], "hybrid_qa": []}), encoding="utf-8")
        output_path.write_bytes(b"PK\x03\x04 fake pptx")
        return type(
            "Result",
            (),
            {
                "output": output_path,
                "workdir": workdir,
                "selected_layout_dir": workdir / "selected",
                "report": report_path,
                "vector_pptx": workdir / "vector.pptx",
                "hybrid_pptx": workdir / "hybrid.pptx",
                "artifact_dir": output_path.parent / "artifacts",
                "montage": None,
            },
        )()

    monkeypatch.setattr(web_app_module, "convert_notebooklm_auto", fake_convert)


def _wait_for_status(client: TestClient, job_id: str, target: set[str], *, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in target:
            return payload
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not reach {target} within {timeout}s")


def test_done_job_streams_terminal_event(monkeypatch: pytest.MonkeyPatch, web_client: TestClient) -> None:
    _install_fake_convert(monkeypatch, behaviour="ok")
    response = web_client.post(
        "/api/jobs?filename=sample.pptx",
        content=b"PK\x03\x04 fake input",
        headers={"x-star-slide-options": "{}"},
    )
    assert response.status_code == 200
    job_id = response.json()["id"]
    _wait_for_status(web_client, job_id, {"done"}, timeout=5.0)

    with web_client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        lines = _drain_sse_lines(stream, deadline=time.monotonic() + 3.0)
    data_lines = [line for line in lines if line.startswith("data:")]
    assert any('"status": "done"' in line for line in data_lines)


def test_cancel_endpoint_stops_running_job(monkeypatch: pytest.MonkeyPatch, web_client: TestClient) -> None:
    started = threading.Event()
    _install_fake_convert(monkeypatch, behaviour="cancel", gate=started)
    response = web_client.post(
        "/api/jobs?filename=sample.pptx",
        content=b"PK\x03\x04",
        headers={"x-star-slide-options": "{}"},
    )
    job_id = response.json()["id"]
    assert started.wait(timeout=2.0)
    cancel_resp = web_client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    final = _wait_for_status(web_client, job_id, {"cancelled"}, timeout=3.0)
    assert final["status"] == "cancelled"


def test_rerun_endpoint_creates_new_job(monkeypatch: pytest.MonkeyPatch, web_client: TestClient) -> None:
    _install_fake_convert(monkeypatch, behaviour="fail")
    response = web_client.post(
        "/api/jobs?filename=sample.pptx",
        content=b"PK\x03\x04",
        headers={"x-star-slide-options": "{}"},
    )
    first_id = response.json()["id"]
    _wait_for_status(web_client, first_id, {"failed"}, timeout=3.0)

    _install_fake_convert(monkeypatch, behaviour="ok")
    rerun_resp = web_client.post(f"/api/jobs/{first_id}/rerun")
    assert rerun_resp.status_code == 200
    new_id = rerun_resp.json()["id"]
    assert new_id != first_id
    _wait_for_status(web_client, new_id, {"done"}, timeout=5.0)


def test_previews_endpoint_serves_jpegs(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    for kind in ("images", "qa_vector", "qa_hybrid", "qa_selected"):
        for slide_no in (1, 2, 3):
            _write_png(workdir / kind / f"slide_{slide_no:03d}.png", color=(40, slide_no * 60, 200))
    out_dir = tmp_path / "previews"
    result = generate_previews(workdir=workdir, out_dir=out_dir, max_width=240, quality=70)
    assert len(result.entries) == 3
    for entry in result.entries:
        assert tuple(entry.kinds) == ("original", "vector", "hybrid", "selected")
    sample = next(out_dir.glob("001_original.jpg"))
    with Image.open(sample) as img:
        assert img.format == "JPEG"
        assert img.size[0] <= 240
