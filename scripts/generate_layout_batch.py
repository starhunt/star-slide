#!/usr/bin/env python3
"""Generate per-slide layout JSON files from slide PNGs, then optionally QA them."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", nargs="+", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://localhost:8300/v1")
    parser.add_argument("--model", default="gemini-pro")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--min-objects", type=int, default=10)
    parser.add_argument("--allow-images", action="store_true")
    parser.add_argument("--cache-buster", default="")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument(
        "--fallback-on-error",
        action="store_true",
        help="write full-slide image fallback layouts for slides that still fail after retries",
    )
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--parallel", type=int, default=5)
    parser.add_argument("--qa-pptx", type=Path)
    parser.add_argument("--qa-render-dir", type=Path)
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    preview = [*cmd[:2], "..."] if len(cmd) > 2 else cmd
    print("+ " + " ".join(preview), flush=True)
    subprocess.run(cmd, check=True)


def redact_cmd(cmd: object) -> object:
    if not isinstance(cmd, list):
        return cmd
    redacted = []
    hide_next = False
    for part in cmd:
        if hide_next:
            redacted.append("********")
            hide_next = False
            continue
        redacted.append(part)
        if part == "--api-key":
            hide_next = True
    return redacted


def layout_cmd(args: argparse.Namespace, image: Path, output: Path, attempt: int) -> list[str]:
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("generate_layout_json.py")),
        "--image",
        str(image),
        "-o",
        str(output),
        "--base-url",
        args.base_url,
        "--model",
        args.model,
        "--timeout",
        str(args.timeout),
        "--min-objects",
        str(args.min_objects),
    ]
    if args.api_key:
        cmd.extend(["--api-key", args.api_key])
    if args.cache_buster:
        cmd.extend(["--cache-buster", f"{args.cache_buster}-{image.stem}-try{attempt + 1}"])
    if args.allow_images:
        cmd.append("--allow-images")
    return cmd


def process_image(args: argparse.Namespace, image: Path) -> tuple[Path, str]:
    output = args.out_dir / f"{image.stem}.layout.json"
    last_error = ""
    for attempt in range(args.retries + 1):
        try:
            run(layout_cmd(args, image, output, attempt))
            return output, ""
        except subprocess.CalledProcessError as exc:
            last_error = f"Command {redact_cmd(exc.cmd)!r} returned non-zero exit status {exc.returncode}."
            if attempt < args.retries:
                print(f"retrying {image} after failure ({attempt + 1}/{args.retries})", flush=True)
    output.unlink(missing_ok=True)
    output.with_suffix(output.suffix + ".usage.json").unlink(missing_ok=True)
    return output, last_error


def write_fallback_layout(image: Path, output: Path, *, reason: str = "layout_generation_failed") -> None:
    with Image.open(image) as im:
        width, height = im.size
    layout = {
        "id": image.stem,
        "image": image.name,
        "canvas": {"width": int(width), "height": int(height)},
        "slide_size_emu": [16_256_000, 9_144_000],
        "background": {"mode": "solid", "color": "#FFFFFF", "decorations": []},
        "objects": [
            {
                "type": "image",
                "name": "fallback_source_slide",
                "path": image.name,
                "bbox": [0, 0, int(width), int(height)],
                "replaceable": False,
                "source": "fallback",
            }
        ],
        "metadata": {"fallback_reason": reason},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    layouts: list[Path] = []
    failures: list[dict[str, str]] = []
    max_workers = max(1, int(args.parallel))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(process_image, args, image): image for image in args.images}
        for future in concurrent.futures.as_completed(future_map):
            image = future_map[future]
            output, error = future.result()
            if error:
                failures.append({"image": str(image), "error": error})
            else:
                layouts.append(output)

    layouts = sorted(layouts)
    failures = sorted(failures, key=lambda item: item["image"])
    if failures and not args.continue_on_error:
        raise subprocess.CalledProcessError(1, ["generate_layout_batch", failures[0]["image"]])

    if failures:
        failure_path = args.out_dir / "failures.json"
        failure_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"failures: {failure_path}", flush=True)

    wrote_fallbacks = False
    if failures and args.continue_on_error and args.fallback_on_error:
        fallback_layouts: list[Path] = []
        for item in failures:
            image = Path(item["image"])
            output = args.out_dir / f"{image.stem}.layout.json"
            write_fallback_layout(image, output)
            fallback_layouts.append(output)
            print(f"fallback layout: {output}", flush=True)
        layouts = sorted({*layouts, *fallback_layouts})
        wrote_fallbacks = True

    if args.qa_pptx:
        qa_render_dir = args.qa_render_dir or args.qa_pptx.with_suffix("")
        layout_args = [part for path in layouts for part in ("--layout", str(path))]
        cmd = [
            sys.executable,
            str(Path(__file__).with_name("layout_qa.py")),
            *layout_args,
            "--image-root",
            str(args.images[0].resolve().parent),
            "-o",
            str(args.qa_pptx),
            "--render-dir",
            str(qa_render_dir),
        ]
        if args.allow_images or wrote_fallbacks:
            cmd.append("--allow-images")
        run(cmd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
