"""v7-Step2A — Codex 텍스트 JSON 으로 텍스트 영역을 주변색으로 덮기.

각 텍스트 bbox 의 외곽 ring 픽셀들의 mode 색을 sample → bbox 안을 그 색으로 채움.
간단하고 빠름. 그라데이션이 강한 배경에선 약점.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def quantize_color(rgb: tuple[int, int, int], step: int = 16) -> tuple[int, int, int]:
    return tuple((c // step) * step + step // 2 for c in rgb)


def sample_ring_color(
    arr: np.ndarray,
    bbox: tuple[int, int, int, int],
    *,
    ring_thickness: int = 6,
    pad: int = 2,
) -> tuple[int, int, int]:
    """bbox 외곽 ring 픽셀 mode 색상 (배경색 추정)."""
    h, w = arr.shape[:2]
    x, y, bw, bh = bbox
    x0 = max(0, x - ring_thickness - pad)
    y0 = max(0, y - ring_thickness - pad)
    x1 = min(w, x + bw + ring_thickness + pad)
    y1 = min(h, y + bh + ring_thickness + pad)
    inner_x0 = max(0, x - pad)
    inner_y0 = max(0, y - pad)
    inner_x1 = min(w, x + bw + pad)
    inner_y1 = min(h, y + bh + pad)

    region = arr[y0:y1, x0:x1].copy()
    if region.size == 0:
        return (255, 255, 255)
    # 안쪽(텍스트 영역) 마스킹
    rh, rw = region.shape[:2]
    ix0 = inner_x0 - x0
    iy0 = inner_y0 - y0
    ix1 = inner_x1 - x0
    iy1 = inner_y1 - y0
    mask = np.ones((rh, rw), dtype=bool)
    mask[iy0:iy1, ix0:ix1] = False
    ring_pixels = region[mask]
    if len(ring_pixels) == 0:
        return (255, 255, 255)

    # 양자화 후 mode
    quantized = [quantize_color(tuple(p)) for p in ring_pixels]
    color = Counter(quantized).most_common(1)[0][0]
    return tuple(int(c) for c in color)


def fill_text_regions(
    image: Image.Image,
    texts: list[dict],
    *,
    pad: int = 4,
) -> Image.Image:
    """각 텍스트 bbox 를 주변 mode 색으로 채워 텍스트 제거."""
    arr = np.asarray(image.convert("RGB")).copy()
    h, w = arr.shape[:2]
    for t in texts:
        x, y, bw, bh = t["bbox"]
        x = int(x); y = int(y); bw = int(bw); bh = int(bh)
        if bw <= 0 or bh <= 0:
            continue
        bg_color = sample_ring_color(arr, (x, y, bw, bh), ring_thickness=8, pad=pad)
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(w, x + bw + pad)
        y1 = min(h, y + bh + pad)
        # bbox 영역을 sample 색으로 채움
        arr[y0:y1, x0:x1] = bg_color
    return Image.fromarray(arr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--text-json", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pad", type=int, default=6)
    args = ap.parse_args()

    image = Image.open(args.input).convert("RGB")
    data = json.loads(args.text_json.read_text(encoding="utf-8"))
    texts = data.get("texts", [])
    print(f"입력 {image.size}, 텍스트 {len(texts)}개")

    cleaned = fill_text_regions(image, texts, pad=args.pad)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(args.out)
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
