#!/usr/bin/env python3
"""Ask a vision model for large raster groups that should remain image objects."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

PROMPT = """\
You are planning an editable PowerPoint reconstruction from a slide image.

Find only the large illustration/image groups that should be preserved as
raster image objects instead of being redrawn as many small vector shapes.
Do not include slide titles, prose blocks, tables, regular text boxes, footers,
or the NotebookLM watermark.

Return exactly one valid JSON object:
{
  "image": "file.png",
  "canvas": {"width": 1376, "height": 768},
  "raster_groups": [
    {
      "name": "main_illustration",
      "bbox": [x, y, width, height],
      "reason": "short reason",
      "keep_text_inside": true
    }
  ]
}

Rules:
- Coordinates are pixels in the input image.
- bbox must tightly cover the visual illustration group, not the whole slide.
- It is OK if the bbox includes small labels that are visually embedded in the illustration.
- Prefer 1-3 large groups per slide.
- If there is a left/right comparison with two large illustrations, return two groups.
- JSON only.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", nargs="+", required=True, type=Path)
    parser.add_argument("-o", "--out-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://localhost:8300/v1")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--nonce", default="")
    parser.add_argument("--parallel", type=int, default=5)
    return parser.parse_args()


def api_key(explicit: str) -> str:
    return (
        explicit
        or os.environ.get("VISION_PROXY_API_KEY")
        or os.environ.get("PROXY_API_KEY")
        or os.environ.get("LOCAL_CLAUDE_API_KEY")
        or ""
    )


def image_data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def extract_json(text: str) -> dict[str, Any]:
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    start = s.find("{")
    if start < 0:
        raise ValueError(text[:300])
    parsed, _end = json.JSONDecoder().raw_decode(s[start:])
    if not isinstance(parsed, dict):
        raise ValueError("response is not JSON object")
    return parsed


def call_model(args: argparse.Namespace, image: Path, key: str) -> dict[str, Any]:
    with Image.open(image) as im:
        width, height = im.size
    body = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"image: {image.name}\n"
                            f"canvas: {width} x {height}\n"
                            f"nonce: {args.nonce or time.time_ns()}"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_data_url(image)}},
                ],
            },
        ],
        "temperature": 0,
    }
    req = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace")[:1200], file=sys.stderr)
        raise
    content = payload["choices"][0]["message"]["content"]
    return extract_json(content)


def draw_overlay(image_path: Path, groups: list[dict[str, Any]], out_path: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    colors = ["#FF3333", "#2F80ED", "#27AE60", "#F2994A"]
    for idx, group in enumerate(groups):
        x, y, w, h = [round(v) for v in group["bbox"]]
        color = colors[idx % len(colors)]
        draw.rectangle((x, y, x + w, y + h), outline=color, width=5)
        draw.text((x + 8, y + 8), group.get("name", f"group_{idx + 1}"), fill=color)
    image.save(out_path)


def export_crops(image_path: Path, groups: list[dict[str, Any]], out_dir: Path) -> None:
    image = Image.open(image_path).convert("RGBA")
    for idx, group in enumerate(groups, start=1):
        x, y, w, h = [round(v) for v in group["bbox"]]
        crop = image.crop((x, y, x + w, y + h))
        crop.save(out_dir / f"{image_path.stem}_raster_group_{idx:02d}.png")


def process_image(args: argparse.Namespace, image: Path, key: str) -> dict[str, Any]:
    result = call_model(args, image, key)
    groups = result.get("raster_groups", [])
    if not isinstance(groups, list):
        groups = []
    draw_overlay(image, groups, args.out_dir / f"{image.stem}_raster_groups_overlay.png")
    export_crops(image, groups, args.out_dir)
    out_json = args.out_dir / f"{image.stem}_raster_groups.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_json, flush=True)
    return result


def main() -> int:
    args = parse_args()
    key = api_key(args.api_key)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    reports_by_image: dict[str, dict[str, Any]] = {}
    max_workers = max(1, int(args.parallel))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(process_image, args, image, key): image for image in args.images
        }
        for future in concurrent.futures.as_completed(future_map):
            image = future_map[future]
            reports_by_image[image.name] = future.result()

    reports = [reports_by_image[image.name] for image in args.images]
    (args.out_dir / "raster_groups_report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
