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
        pre_cleanup_hook: Any | None = None,
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
        if pre_cleanup_hook is not None:
            pre_cleanup_hook(workdir)
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
    cancel_resp = web_client.post(
        f"/api/jobs/{job_id}/cancel",
        json={},
    )
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
    rerun_resp = web_client.post(f"/api/jobs/{first_id}/rerun", json={})
    assert rerun_resp.status_code == 200
    new_id = rerun_resp.json()["id"]
    assert new_id != first_id
    _wait_for_status(web_client, new_id, {"done"}, timeout=5.0)


def test_cancel_requires_json_content_type(monkeypatch: pytest.MonkeyPatch, web_client: TestClient) -> None:
    """CSRF guard: POST /cancel without application/json must be rejected."""
    started = threading.Event()
    _install_fake_convert(monkeypatch, behaviour="cancel", gate=started)
    response = web_client.post(
        "/api/jobs?filename=sample.pptx",
        content=b"PK\x03\x04",
        headers={"x-star-slide-options": "{}"},
    )
    job_id = response.json()["id"]
    assert started.wait(timeout=2.0)
    bad = web_client.post(f"/api/jobs/{job_id}/cancel")  # no Content-Type
    assert bad.status_code == 415
    # 정상 cancel로 정리
    ok = web_client.post(f"/api/jobs/{job_id}/cancel", json={})
    assert ok.status_code == 200
    _wait_for_status(web_client, job_id, {"cancelled"}, timeout=3.0)


def test_cancelled_job_resists_late_progress(monkeypatch: pytest.MonkeyPatch, web_client: TestClient) -> None:
    """Terminal-state guard: late progress() after cancel must not resurrect status."""
    cancel_seen = threading.Event()

    def fake_convert(
        *,
        input_path: Any,
        output_path: Any,
        workdir: Any,
        options: Any,
        progress: Any | None = None,
        cancel: Any | None = None,
        pre_cleanup_hook: Any | None = None,
    ) -> Any:
        # 진행 콜백 한 번 → cancel 신호 대기 → 그 후에도 progress 한 번 더 → JobCancelledError
        if progress:
            progress("초기 단계", 10)
        for _ in range(50):
            if cancel is not None and cancel():
                # cancel 직후 의도적으로 한 번 더 progress 발생 (race 시뮬레이션)
                if progress:
                    progress("뒤늦은 phase", 60)
                cancel_seen.set()
                raise JobCancelledError("cancelled")
            time.sleep(0.02)
        raise JobCancelledError("timeout")

    monkeypatch.setattr(web_app_module, "convert_notebooklm_auto", fake_convert)
    response = web_client.post(
        "/api/jobs?filename=sample.pptx",
        content=b"PK\x03\x04",
        headers={"x-star-slide-options": "{}"},
    )
    job_id = response.json()["id"]
    _wait_for_status(web_client, job_id, {"running"}, timeout=2.0)
    web_client.post(f"/api/jobs/{job_id}/cancel", json={})
    assert cancel_seen.wait(timeout=2.0)
    final = _wait_for_status(web_client, job_id, {"cancelled"}, timeout=3.0)
    assert final["status"] == "cancelled"
    assert final["phase"] == "취소됨"


def test_ssrf_guard_always_blocks_critical_targets() -> None:
    """Scheme + link-local + multicast + unspecified are blocked regardless of policy."""
    from star_slide.api.web_app import _validate_outbound_url, set_allow_private_networks

    set_allow_private_networks(True)  # most permissive policy
    try:
        ok_cases = [
            "http://localhost:11434/v1",
            "http://127.0.0.1:8300/v1",
            "https://api.openai.com/v1",
        ]
        for url in ok_cases:
            ok, err = _validate_outbound_url(url)
            assert ok, f"unexpectedly rejected {url}: {err}"

        always_bad = [
            "file:///etc/passwd",
            "gopher://x.example/path",
            "ftp://example.com/file",
            "http://169.254.169.254/latest/meta-data",  # cloud IMDS (link-local)
            "http:///no-host",
        ]
        for url in always_bad:
            ok, err = _validate_outbound_url(url)
            assert not ok, f"unexpectedly accepted {url}"
            assert err, f"expected error message for {url}"
    finally:
        set_allow_private_networks(True)


def test_ssrf_guard_loopback_default_allows_private_lan() -> None:
    """Default policy (loopback bind) permits RFC1918 private addresses for LAN LLMs."""
    from star_slide.api.web_app import _validate_outbound_url, set_allow_private_networks

    set_allow_private_networks(True)
    try:
        for url in ["http://10.0.0.1/v1", "http://192.168.1.5/v1", "http://172.16.0.1/v1"]:
            ok, err = _validate_outbound_url(url)
            assert ok, f"unexpectedly rejected {url} under loopback policy: {err}"
    finally:
        set_allow_private_networks(True)


def test_ssrf_guard_strict_blocks_private_lan() -> None:
    """Strict policy (non-loopback bind) blocks RFC1918 to prevent SSRF pivoting."""
    from star_slide.api.web_app import _validate_outbound_url, set_allow_private_networks

    set_allow_private_networks(False)
    try:
        for url in ["http://10.0.0.1/v1", "http://192.168.1.5/v1", "http://172.16.0.1/v1"]:
            ok, err = _validate_outbound_url(url)
            assert not ok, f"unexpectedly accepted {url} under strict policy"
            assert err, f"expected error message for {url}"
    finally:
        set_allow_private_networks(True)


def test_upload_oversize_streamed_rejects_and_unlinks(
    monkeypatch: pytest.MonkeyPatch, web_client: TestClient
) -> None:
    """Streaming upload that exceeds the cap is rejected and partial file removed."""
    monkeypatch.setattr(web_app_module, "MAX_UPLOAD_BYTES", 1024)
    big = b"PK\x03\x04" + b"x" * 4096  # 4100 bytes > 1KB cap
    response = web_client.post(
        "/api/jobs?filename=big.pptx",
        content=big,
        headers={"x-star-slide-options": "{}"},
    )
    assert response.status_code == 413
    # 부분 파일 정리 확인
    web_root: Path = web_app_module.WEB_ROOT
    leftovers = list(web_root.glob("*/big.pptx"))
    assert leftovers == [], f"orphan file(s) left behind: {leftovers}"


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
