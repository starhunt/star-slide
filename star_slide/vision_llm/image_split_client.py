"""codex_image_split 용 cliproxy 클라이언트 (chat/completions 전용).

cliproxy(기본 http://localhost:8300/v1) 의 OpenAI 호환 chat/completions 로
이미지 + 프롬프트를 보내 JSON 응답을 받는다 (텍스트/도형 layout 추출).

cliproxy 의 /v1/images/generations 는 prompt-only 라 input-image 를 받는
image-edit 가 불가능하므로, image 생성 (텍스트 제거 배경) 은 별도 codex CLI
subprocess (star_slide/pipeline/codex_image_split.remove_text_with_image_gen) 로
처리한다.

설계 원칙:
  - 외부 의존성 추가 없음 (urllib 표준 라이브러리만)
  - 로컬 프록시는 임시 HTTP URL, 원격 endpoint는 data URL 사용
  - 모델/엔드포인트/api_key 는 호출 파라미터로 받아 단일 출처 보장
"""

from __future__ import annotations

import base64
import contextlib
import http.server
import json
import mimetypes
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class VisionClientError(RuntimeError):
    """cliproxy 호출 또는 응답 파싱 실패."""


# --------------------------------------------------------------
# 로컬 cliproxy용 임시 이미지 HTTP 서버
# --------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def _serve_directory(root: Path) -> Iterator[tuple[str, int]]:
    """root 디렉토리를 임시 HTTP 서버로 노출. (host, port) yield."""
    root_str = str(root.resolve())
    port = _free_port()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=root_str, **kw)

        def log_message(self, *_a: Any, **_kw: Any) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", port
    finally:
        server.shutdown()
        server.server_close()


def _build_image_url(host: str, port: int, image_path: Path, root: Path) -> str:
    rel = image_path.resolve().relative_to(root.resolve())
    return f"http://{host}:{port}/{urllib.parse.quote(str(rel))}"


# --------------------------------------------------------------
# JSON 출력 호출 — chat/completions
# --------------------------------------------------------------


def call_vision_json(
    image_path: Path,
    prompt: str,
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 600.0,
) -> dict[str, Any]:
    """이미지 1장 + prompt → JSON 응답. cliproxy chat/completions 호출.

    - 응답 텍스트에서 첫 '{' ~ 마지막 '}' 를 잘라 JSON 파싱 (markdown fence 제거 포함)
    - loopback endpoint에는 임시 HTTP URL, 원격 endpoint에는 data URL로 이미지 전달
    """
    with contextlib.ExitStack() as stack:
        endpoint_host = urllib.parse.urlparse(base_url).hostname
        if endpoint_host in {"localhost", "127.0.0.1", "::1"}:
            root = image_path.parent
            host, port = stack.enter_context(_serve_directory(root))
            image_url = _build_image_url(host, port, image_path, root)
        else:
            media_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
            encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
            image_url = f"data:{media_type};base64,{encoded_image}"
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
        }
        text = _post_json(
            url=f"{base_url.rstrip('/')}/chat/completions",
            payload=body,
            api_key=api_key,
            timeout_sec=timeout_sec,
        )
    try:
        content = text["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionClientError(f"응답 구조 비정상: {text!r:.300}") from exc
    return _parse_json_loose(content)


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout_sec: float,
) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data: dict[str, Any] = json.loads(resp.read())
            return data
    except urllib.error.HTTPError as exc:
        err_body = ""
        with contextlib.suppress(Exception):
            err_body = exc.read().decode()[:500]
        raise VisionClientError(f"HTTP {exc.code}: {err_body}") from exc
    except Exception as exc:
        raise VisionClientError(f"호출 실패: {exc}") from exc


def _parse_json_loose(text: str) -> dict[str, Any]:
    """모델이 markdown fence 또는 prose 를 둘러쌀 수 있어 관대하게 파싱."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    first = s.find("{")
    last = s.rfind("}")
    if first < 0 or last < 0 or last <= first:
        raise VisionClientError(f"JSON 파싱 실패 (괄호 없음): {text[:200]!r}")
    try:
        data: dict[str, Any] = json.loads(s[first : last + 1])
        return data
    except json.JSONDecodeError as exc:
        raise VisionClientError(
            f"JSON decode 실패: {exc} / first 200 chars: {s[first : first + 200]!r}"
        ) from exc
