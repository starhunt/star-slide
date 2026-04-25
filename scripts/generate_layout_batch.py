#!/usr/bin/env python3
"""Generate per-slide layout JSON files from slide PNGs, then optionally QA them."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


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
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--qa-pptx", type=Path)
    parser.add_argument("--qa-render-dir", type=Path)
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    preview = [*cmd[:2], "..."] if len(cmd) > 2 else cmd
    print("+ " + " ".join(preview), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    layouts: list[Path] = []
    failures: list[dict[str, str]] = []
    for image in args.images:
        output = args.out_dir / f"{image.stem}.layout.json"
        last_error = ""
        for attempt in range(args.retries + 1):
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
            try:
                run(cmd)
                layouts.append(output)
                last_error = ""
                break
            except subprocess.CalledProcessError as exc:
                last_error = str(exc)
                if attempt < args.retries:
                    print(f"retrying {image} after failure ({attempt + 1}/{args.retries})", flush=True)
        if last_error:
            failures.append({"image": str(image), "error": last_error})
            if not args.continue_on_error:
                raise subprocess.CalledProcessError(1, ["generate_layout_batch", str(image)])

    if failures:
        failure_path = args.out_dir / "failures.json"
        failure_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"failures: {failure_path}", flush=True)

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
        run(cmd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
