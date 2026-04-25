"""Vision LLM 호출 — 슬라이드 PNG → VisionSlide JSON.

프록시 endpoint (cliproxy) 특성:
  - HTTP URL만 vision input으로 작동 (base64 data URL 무시)
  - 따라서 슬라이드 PNG들이 위치한 디렉토리를 임시 HTTP 서버로 노출 후 URL 전달
  - prompt 한도 250K chars

순서:
  1. _LocalHttpServer 컨텍스트로 임시 서버 띄움 (자동 포트)
  2. 각 슬라이드 PNG URL → vision API 호출
  3. JSON 응답 파싱 → VisionSlide 객체
"""

from __future__ import annotations

import contextlib
import http.server
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from star_slide.vision_llm.schema import VisionSlide

DEFAULT_BASE_URL = "http://localhost:8300/v1"
DEFAULT_MODEL = "claude-opus-4-6"


SYSTEM_PROMPT = """\
You are a slide-to-JSON parser. Given a presentation slide image, output STRICT JSON
describing every visible element so it can be reconstructed as an editable PowerPoint slide.

Output format (JSON only, no markdown fences, no commentary):
{
  "image_size": [W, H],
  "elements": [
    {
      "type": "text" | "shape" | "path" | "table" | "image",
      "bbox": {"x": ..., "y": ..., "w": ..., "h": ...},   // pixel ints, in image coords

      // for text
      "content": "...",                                    // exact text including punctuation
      "color": "#RRGGBB",                                  // dominant ink color
      "font_size_pt": <float>,                              // estimate at 96dpi
      "weight": "normal" | "bold",
      "italic": <bool>,
      "align": "left" | "center" | "right",
      "language": "ko" | "en" | "mixed",
      "rotation_deg": <float>,                             // 0/90/-90 etc

      // for shape (preset geometry)
      "subtype": "rectangle" | "rounded_rectangle" | "ellipse" | "arrow" | "line" | "polygon",
      "fill": "#RRGGBB" | null,
      "stroke": "#RRGGBB" | null,
      "stroke_width_pt": <float>,
      "corner_radius_pt": <float>,                          // rounded_rectangle only

      // for path (free-form: gauges/curves/icons)
      "description": "...",                                 // short English description

      // for table
      "rows": <int>, "cols": <int>,
      "cells": [
        {"row":..., "col":..., "text":"...", "bbox":{...}, "fill":"#...", "color":"#...",
         "rowspan":1, "colspan":1}
      ],
      "border_color": "#...", "border_width_pt": <float>,

      // for image (preserve as raster)
      "description": "..."
    }
  ]
}

Rules:
- Detect EVERY visible text including small captions, axis labels, watermarks, rotated text.
- For Korean characters, transcribe exactly without ASCII substitutions.
- bbox must use pixel coordinates of the input image.
- Color must be a 6-char uppercase hex prefixed by "#" or null.
- For decorative gauges/donuts/charts use type="path" with description.
- For complex photos/screenshots use type="image".
- Output ONLY the JSON. No prose, no fences.
"""


class VisionExtractError(RuntimeError):
    """Vision LLM 호출 또는 파싱 실패."""


@dataclass
class VisionUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    elapsed_sec: float = 0.0


@dataclass
class VisionExtractor:
    """프록시 vision LLM wrapper.

    한 변환 작업 내에서 동일 인스턴스 재사용 (HTTP 서버 1회만 띄움).
    """

    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout_sec: float = 240.0
    serve_root: Path | None = None  # 임시 서버 루트 (PNG들이 있는 디렉토리)
    last_usage: VisionUsage = field(default_factory=VisionUsage)

    _server: http.server.ThreadingHTTPServer | None = None
    _server_thread: threading.Thread | None = None
    _server_port: int | None = None

    def __post_init__(self) -> None:
        if not self.api_key:
            import os

            self.api_key = (
                os.environ.get("VISION_PROXY_API_KEY")
                or os.environ.get("LOCAL_CLAUDE_API_KEY")
                or ""
            )

    # --- HTTP server ---

    def start_server(self, root: Path) -> None:
        if self._server is not None:
            return
        self.serve_root = root.resolve()

        def _free_port() -> int:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                return int(s.getsockname()[1])

        port = _free_port()
        root_str = str(self.serve_root)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a: Any, **kw: Any) -> None:
                super().__init__(*a, directory=root_str, **kw)

            def log_message(self, *_a: Any, **_kw: Any) -> None:  # 로그 끔
                return

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._server_port = port
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._server_thread.start()

    def stop_server(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._server_thread = None
        self._server_port = None

    @contextmanager
    def serving(self, root: Path) -> Iterator[None]:
        self.start_server(root)
        try:
            yield
        finally:
            self.stop_server()

    def url_for(self, png_path: Path) -> str:
        if self._server_port is None or self.serve_root is None:
            raise VisionExtractError("HTTP 서버가 시작되지 않음. start_server() 먼저 호출.")
        rel = png_path.resolve().relative_to(self.serve_root)
        encoded = urllib.parse.quote(str(rel))
        return f"http://127.0.0.1:{self._server_port}/{encoded}"

    # --- vision call ---

    def extract(self, png_path: Path) -> VisionSlide:
        url = self.url_for(png_path)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Output JSON for this slide."},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                },
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            err_body = ""
            with contextlib.suppress(Exception):
                err_body = exc.read().decode()[:500]
            raise VisionExtractError(
                f"vision API HTTP {exc.code}: {err_body}"
            ) from exc
        except Exception as exc:  # network 등
            raise VisionExtractError(f"vision API 호출 실패: {exc}") from exc

        elapsed = time.perf_counter() - t0
        usage = payload.get("usage") or {}
        self.last_usage = VisionUsage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            elapsed_sec=elapsed,
        )

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise VisionExtractError(f"응답 구조 비정상: {payload!r:.300}") from exc

        return self._parse_json(content)

    @staticmethod
    def _parse_json(text: str) -> VisionSlide:
        # 모델이 markdown 코드블록을 둘러쌀 수 있음 → 제거
        s = text.strip()
        if s.startswith("```"):
            # ```json ... ``` 형식
            lines = s.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        # 첫 '{' ~ 마지막 '}' 추출 (앞뒤 noise 안전)
        first = s.find("{")
        last = s.rfind("}")
        if first < 0 or last < 0 or last <= first:
            raise VisionExtractError(f"JSON 파싱 실패 (괄호 없음): {text[:200]!r}")
        json_text = s[first : last + 1]
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise VisionExtractError(
                f"JSON decode 실패: {exc} / first 200 chars: {json_text[:200]!r}"
            ) from exc

        try:
            return VisionSlide.model_validate(data)
        except ValidationError as exc:
            raise VisionExtractError(f"스키마 검증 실패: {exc}") from exc
