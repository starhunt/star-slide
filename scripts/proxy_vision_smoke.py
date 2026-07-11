#!/usr/bin/env python3
"""Smoke-test OpenAI-compatible proxy vision with a data URL image."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--base-url", default="http://localhost:8300/v1")
    parser.add_argument("--model", default="gemini-pro")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--nonce", default="")
    parser.add_argument("--timeout", type=int, default=90)
    return parser.parse_args()


def image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def main() -> int:
    args = parse_args()
    image = args.image.resolve()
    if not image.exists():
        print(f"missing image: {image}", file=sys.stderr)
        return 2

    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "이 슬라이드 이미지를 보고 한국어로 짧게 답하세요. "
                            "1) 메인 제목 2) 표가 있는지 3) 보이는 헤더 하나"
                            + (f"\nnonce: {args.nonce}" if args.nonce else "")
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_data_url(image)}},
                ],
            }
        ],
        "temperature": 0,
    }

    req = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer "
            + (
                args.api_key
                or os.environ.get("VISION_PROXY_API_KEY")
                or os.environ.get("PROXY_API_KEY")
                or os.environ.get("LOCAL_CLAUDE_API_KEY")
                or ""
            ),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(
            f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:1200]}",
            file=sys.stderr,
        )
        return 1
    except urllib.error.URLError as exc:
        print(f"URLERROR: {exc.reason}", file=sys.stderr)
        return 1
    except TimeoutError:
        print(f"TIMEOUT after {args.timeout}s: model={args.model}", file=sys.stderr)
        return 124

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(str(content).strip()[:1600])
    return 0 if content else 1


if __name__ == "__main__":
    raise SystemExit(main())
