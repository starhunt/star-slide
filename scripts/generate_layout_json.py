"""Generate layout.json drafts from slide images via an OpenAI-compatible vision proxy."""

from __future__ import annotations

import argparse
import base64
import contextlib
import http.server
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from layout_qa import validate_layout  # noqa: E402

DEFAULT_BASE_URL = "http://localhost:8300/v1"
DEFAULT_MODEL = "gemini-pro"


LAYOUT_SYSTEM_PROMPT = """\
You are a precise slide-to-editable-PowerPoint layout planner.

You receive one slide image. Output exactly one valid JSON object matching the
schema below. Do not output markdown, comments, explanations, or trailing text.

Core goal:
- The JSON will be rendered into an editable PPTX.
- Do NOT use the original slide image as a background.
- Do NOT use image objects unless the slide contains a real photo/screenshot.
- Do NOT include the NotebookLM watermark/logo in the bottom-right corner.
- Prefer editable text, shape, line, and polyline objects.
- Keep the visual design, hierarchy, text, colors, and approximate coordinates
  as close to the source image as possible.

Coordinate system:
- Pixel coordinates of the input image.
- bbox is [x, y, width, height].
- line points are [x1, y1, x2, y2].
- polyline points are [[x, y], [x, y], ...].
- All bbox and points must be numeric arrays. Never leave a bbox empty.

Supported output:
{
  "id": "sample2_slide03",
  "image": "sample2_slide03.png",
  "canvas": {"width": 1376, "height": 768},
  "slide_size_emu": [16256000, 9144000],
  "background": {
    "mode": "solid",
    "color": "#F8F7F2",
    "decorations": [
      {"type": "grid", "bbox": [0, 0, 1376, 768], "step_x": 8, "step_y": 8, "color": "#EEF0EA", "width": 1},
      {"type": "rect", "bbox": [100, 100, 500, 300], "fill": "#F8F7F2", "outline": "#0B3558", "line_width": 1},
      {"type": "line", "points": [100, 200, 600, 200], "color": "#0B3558", "width": 1}
    ]
  },
  "objects": [
    {"type": "text", "name": "slide_title", "text": "Title", "bbox": [50, 50, 800, 60], "font_size": 32, "bold": true, "color": "#0B3558", "align": "LEFT", "valign": "MIDDLE"},
    {"type": "text", "name": "body", "lines": ["Line 1", "Line 2"], "bbox": [100, 150, 500, 100], "font_size": 18, "bold": false, "color": "#111111", "align": "LEFT", "valign": "TOP"},
    {"type": "shape", "name": "box", "shape": "RECTANGLE", "bbox": [100, 250, 300, 120], "fill": "#F8F7F2", "stroke": "#0B3558", "stroke_width": 1},
    {"type": "line", "name": "rule", "points": [100, 400, 500, 400], "color": "#0B3558", "width": 2},
    {"type": "polyline", "name": "curve", "points": [[100, 500], [200, 480], [300, 450]], "color": "#A95534", "width": 3, "dash": "DASH"}
  ]
}

Supported object.type values: text, shape, line, polyline.
Supported background decoration types: grid, rect, line.
Supported shape values: RECTANGLE, ROUNDED_RECTANGLE, OVAL, ARC, CHEVRON, CUBE,
RIGHT_BRACE, RIGHT_ARROW.
Supported dash values: SOLID, DASH, DASH_DOT, DASH_DOT_DOT, LONG_DASH,
LONG_DASH_DOT, ROUND_DOT, SQUARE_DOT. Use ROUND_DOT for dotted lines.

Strict rules:
- Include every visible text when practical, including small labels.
- Exclude NotebookLM watermarks/logos/brand marks even if visible.
- If text is multi-line, use "lines" instead of embedding newline characters.
- Korean text must be transcribed exactly.
- Use uppercase hex colors like "#0B3558".
- Use "solid" background mode only unless the user explicitly supplies another mode.
- The only valid final answer is JSON that can be parsed by JSON.parse().
"""


@dataclass
class LocalImageServer:
    root: Path
    server: http.server.ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    port: int | None = None

    def __enter__(self) -> LocalImageServer:
        self.root = self.root.resolve()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = int(sock.getsockname()[1])

        root_str = str(self.root)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=root_str, **kwargs)

            def log_message(self, *_args: Any, **_kwargs: Any) -> None:
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        self.server = None
        self.thread = None
        self.port = None

    def url_for(self, path: Path) -> str:
        if self.port is None:
            raise RuntimeError("server is not started")
        rel = path.resolve().relative_to(self.root)
        return f"http://127.0.0.1:{self.port}/{urllib.parse.quote(str(rel))}"


def _extract_json(text: str) -> dict[str, Any]:
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    first = s.find("{")
    if first < 0:
        raise ValueError(f"no JSON object found in response: {text[:200]!r}")
    try:
        parsed, _end = json.JSONDecoder().raw_decode(s[first:])
    except json.JSONDecodeError:
        last = s.rfind("}")
        if last < 0 or last <= first:
            raise ValueError(f"no JSON object found in response: {text[:200]!r}") from None
        parsed = json.loads(s[first : last + 1])
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON response must be an object: {type(parsed).__name__}")
    return parsed


def _api_key(explicit: str) -> str:
    return (
        explicit
        or os.environ.get("VISION_PROXY_API_KEY")
        or os.environ.get("PROXY_API_KEY")
        or os.environ.get("LOCAL_CLAUDE_API_KEY")
        or ""
    )


def _image_data_url(image_path: Path) -> str:
    media_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def _object_text(obj: dict[str, Any]) -> str:
    parts: list[str] = []
    text = obj.get("text")
    if isinstance(text, str):
        parts.append(text)
    lines = obj.get("lines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines)
    return " ".join(parts)


def _drop_notebooklm_watermark(layout: dict[str, Any]) -> None:
    objects = layout.get("objects")
    if not isinstance(objects, list):
        return
    filtered = []
    for obj in objects:
        name = str(obj.get("name", "")).lower()
        text = _object_text(obj).lower()
        if "notebooklm" in name or "notebooklm" in text:
            continue
        filtered.append(obj)
    layout["objects"] = filtered


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float)


def _normalize_polyline_points(layout: dict[str, Any]) -> None:
    objects = layout.get("objects")
    if not isinstance(objects, list):
        return
    for obj in objects:
        if not isinstance(obj, dict) or obj.get("type") != "polyline":
            continue
        points = obj.get("points")
        if not isinstance(points, list):
            continue
        if points and all(_is_number(item) for item in points):
            paired = []
            for idx in range(0, len(points) - 1, 2):
                paired.append([points[idx], points[idx + 1]])
            obj["points"] = paired


def _call_vision_proxy(
    *,
    base_url: str,
    api_key: str,
    model: str,
    image_url: str,
    image_name: str,
    image_size: tuple[int, int],
    layout_id: str,
    timeout_sec: float,
    min_objects: int,
    cache_buster: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    user_prompt = (
        f"Create layout.json for this slide image.\n"
        f"id: {layout_id}\n"
        f"image: {image_name}\n"
        f"canvas: {image_size[0]} x {image_size[1]}\n"
        f"{f'cache_buster: {cache_buster}' + chr(10) if cache_buster else ''}"
        f"Return JSON only."
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": LAYOUT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = ""
        with contextlib.suppress(Exception):
            error_body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"vision proxy HTTP {exc.code}: {error_body}") from exc
    except Exception as exc:
        raise RuntimeError(f"vision proxy call failed: {exc}") from exc

    content = payload["choices"][0]["message"]["content"]
    layout = _extract_json(content)
    objects = layout.get("objects")
    if not isinstance(objects, list) or len(objects) < min_objects:
        raise RuntimeError(
            f"layout generation produced too few objects: "
            f"{0 if not isinstance(objects, list) else len(objects)} < {min_objects}"
        )
    usage = dict(payload.get("usage") or {})
    usage["elapsed_sec"] = round(time.perf_counter() - started, 3)
    return layout, usage


def generate_layout(
    *,
    image_path: Path,
    output: Path,
    base_url: str,
    api_key: str,
    model: str,
    timeout_sec: float,
    strict_editable: bool,
    image_transport: str,
    min_objects: int,
    cache_buster: str,
) -> int:
    image_path = image_path.resolve()
    with Image.open(image_path) as image:
        image_size = image.size

    if image_transport == "data-url":
        image_url = _image_data_url(image_path)
        layout, usage = _call_vision_proxy(
            base_url=base_url,
            api_key=api_key,
            model=model,
            image_url=image_url,
            image_name=image_path.name,
            image_size=image_size,
            layout_id=image_path.stem,
            timeout_sec=timeout_sec,
            min_objects=min_objects,
            cache_buster=cache_buster,
        )
    else:
        with LocalImageServer(image_path.parent) as server:
            layout, usage = _call_vision_proxy(
                base_url=base_url,
                api_key=api_key,
                model=model,
                image_url=server.url_for(image_path),
                image_name=image_path.name,
                image_size=image_size,
                layout_id=image_path.stem,
                timeout_sec=timeout_sec,
                min_objects=min_objects,
                cache_buster=cache_buster,
            )

    layout.setdefault("id", image_path.stem)
    layout.setdefault("image", image_path.name)
    layout.setdefault("canvas", {"width": image_size[0], "height": image_size[1]})
    layout.setdefault("slide_size_emu", [16_256_000, 9_144_000])
    _drop_notebooklm_watermark(layout)
    _normalize_polyline_points(layout)

    errors = validate_layout(layout, strict_editable=strict_editable)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    (output.with_suffix(output.suffix + ".usage.json")).write_text(
        json.dumps(usage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if errors:
        for error in errors:
            print(f"ERROR {error}")
        print(output)
        return 2

    print(output)
    print(output.with_suffix(output.suffix + ".usage.json"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--image-transport", choices=["data-url", "local-url"], default="data-url")
    parser.add_argument("--min-objects", type=int, default=3)
    parser.add_argument("--allow-images", action="store_true")
    parser.add_argument("--cache-buster", default="")
    args = parser.parse_args()

    return generate_layout(
        image_path=args.image,
        output=args.output,
        base_url=args.base_url,
        api_key=_api_key(args.api_key),
        model=args.model,
        timeout_sec=args.timeout,
        strict_editable=not args.allow_images,
        image_transport=args.image_transport,
        min_objects=args.min_objects,
        cache_buster=args.cache_buster,
    )


if __name__ == "__main__":
    raise SystemExit(main())
