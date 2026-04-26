#!/usr/bin/env python3
"""Refine detected raster-group boxes with SAM3 box prompts.

This is an experiment for NotebookLM slide reconstruction:
vision finds coarse, semantic large-image groups; SAM3 tries to turn those
boxes into transparent PNG crops that can be inserted as replaceable PPTX
picture objects.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from star_slide.segmentation.sam3 import run_sam3_box_prompts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--groups-json", required=True, type=Path)
    parser.add_argument("-o", "--out-dir", required=True, type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--model-id", default="facebook/sam3")
    return parser.parse_args()


def read_groups(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("raster_groups", [])
    return groups if isinstance(groups, list) else []


def save_mask_crop(
    image: Image.Image,
    mask: np.ndarray,
    bbox: tuple[int, int, int, int],
    out_path: Path,
) -> None:
    x, y, w, h = bbox
    crop = image.crop((x, y, x + w, y + h)).convert("RGBA")
    crop_mask = mask[y : y + h, x : x + w]
    # SAM occasionally leaves pinholes inside low-contrast illustration regions.
    # For PPTX image-object extraction, filled interiors are preferable.
    crop_mask = ndimage.binary_closing(crop_mask, structure=np.ones((3, 3)), iterations=1)
    crop_mask = ndimage.binary_fill_holes(crop_mask)
    alpha = (crop_mask.astype(np.uint8) * 255)
    crop.putalpha(Image.fromarray(alpha, mode="L"))
    crop.save(out_path)


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    groups = read_groups(args.groups_json)
    boxes = [tuple(float(v) for v in group["bbox"]) for group in groups]

    image = Image.open(args.image).convert("RGBA")
    result = run_sam3_box_prompts(
        args.image,
        boxes,
        model_id=args.model_id,
        device=args.device,
        threshold=0.0,
        mask_threshold=0.5,
    )

    overlay = image.convert("RGBA")
    draw = ImageDraw.Draw(overlay)
    report: list[dict[str, Any]] = []
    for idx, mask in enumerate(result.masks, start=1):
        x, y, w, h = [round(v) for v in mask.bbox]
        name = groups[mask.source_box_idx or 0].get("name", f"group_{idx}")
        draw.rectangle((x, y, x + w, y + h), outline="#27AE60", width=5)
        draw.text((x + 8, y + 8), f"{idx}:{name}", fill="#27AE60")
        save_mask_crop(
            image,
            mask.segmentation,
            (x, y, w, h),
            args.out_dir / f"{args.image.stem}_sam3_group_{idx:02d}.png",
        )
        report.append(
            {
                "name": name,
                "source_box_idx": mask.source_box_idx,
                "input_bbox": groups[mask.source_box_idx or 0].get("bbox"),
                "sam_bbox": [x, y, w, h],
                "score": mask.score,
            }
        )

    overlay.save(args.out_dir / f"{args.image.stem}_sam3_overlay.png")
    (args.out_dir / f"{args.image.stem}_sam3_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
