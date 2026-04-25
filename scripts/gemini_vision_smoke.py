#!/usr/bin/env python3
"""Smoke-test Gemini CLI vision support with a local image file.

This intentionally prints only a short response preview and does not expose
environment variables or credentials.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--prompt",
        default=(
            "Look at this slide image. Reply in Korean with exactly three short "
            "facts: the main title, whether a table is present, and one visible "
            "column/header label. Do not output JSON."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image = args.image.resolve()
    if not image.exists():
        print(f"missing image: {image}", file=sys.stderr)
        return 2

    prompt = f"@{image}\n\n{args.prompt}"
    cmd = ["gemini", "-m", args.model, "-o", "json", "-p", prompt]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {args.timeout}s: model={args.model}", file=sys.stderr)
        return 124

    print(f"exit_code={proc.returncode}")
    if proc.stderr.strip():
        print("stderr_preview=" + proc.stderr.strip()[:1200])

    stdout = proc.stdout.strip()
    if not stdout:
        print("stdout_preview=")
        return 1 if proc.returncode else 0

    try:
        data = json.loads(stdout)
        content = data.get("response") or data.get("text") or data.get("content") or ""
        print("content_preview=" + str(content).strip()[:1200])
    except json.JSONDecodeError:
        print("stdout_preview=" + stdout[:1200])
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
