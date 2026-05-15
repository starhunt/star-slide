"""v7-Step3 — 텍스트 제거된 깨끗한 이미지에서 SAM2 객체 추출.

글자 간섭 없으니 픽토그램/박스/화살표 분리 정밀도 대폭 상승 기대.
classify_masks 단계 불필요(텍스트 없음). 면적 필터 + IoU dedupe 만.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from star_slide.segmentation.sam2_auto import Sam2Mask, run_sam2_auto


@dataclass
class ObjectLayer:
    bbox: tuple[int, int, int, int]
    z: int
    area_ratio: float
    score: float
    alpha_path: str


def upsample_mask(seg_small, target_size):
    seg_uint = (seg_small.astype(np.uint8)) * 255
    seg_full = cv2.resize(seg_uint, target_size, interpolation=cv2.INTER_LINEAR)
    return seg_full > 127


def mask_iou(a, b):
    if a.shape != b.shape:
        return 0.0
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / float(union) if union else 0.0


def filter_by_area(masks, image_size, *, min_ratio, max_ratio):
    w, h = image_size
    total = w * h
    return [m for m in masks if min_ratio <= m.area / total <= max_ratio]


def dedupe(masks, *, iou_threshold=0.85):
    sorted_masks = sorted(masks, key=lambda m: -m.area)
    kept = []
    for m in sorted_masks:
        if not any(mask_iou(m.segmentation, k.segmentation) > iou_threshold for k in kept):
            kept.append(m)
    return kept


def export_alpha_crop(image, mask, *, out_dir, name):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    arr = np.asarray(image.convert("RGB"))
    crop_rgb = arr[y0:y1, x0:x1]
    crop_mask = mask[y0:y1, x0:x1]
    rgba = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
    rgba[:, :, :3] = crop_rgb
    rgba[:, :, 3] = (crop_mask.astype(np.uint8)) * 255
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    Image.fromarray(rgba, mode="RGBA").save(p)
    return (x0, y0, x1 - x0, y1 - y0), p


def render_overlay(image, masks, out_path):
    rng = np.random.default_rng(42)
    arr = np.asarray(image.convert("RGB")).copy().astype(np.float32)
    overlay = np.zeros_like(arr)
    for m in masks:
        color = rng.integers(50, 255, size=3)
        overlay[m.segmentation] = color
    blended = arr * 0.55 + overlay * 0.45
    Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8)).save(out_path)


def render_box_overlay(image, layers, out_path):
    arr = np.asarray(image.convert("RGB")).copy()
    for ly in layers:
        x, y, w, h = ly.bbox
        cv2.rectangle(arr, (x, y), (x + w, y + h), (0, 200, 0), 2)
    Image.fromarray(arr).save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean-image", type=Path, required=True,
                    help="텍스트 제거된 입력 이미지 (Step 2 출력)")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--sam-resize", type=int, default=1920)
    ap.add_argument("--sam-points", type=int, default=48)
    ap.add_argument("--min-area", type=float, default=0.0005)
    ap.add_argument("--max-area", type=float, default=0.55)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    image = Image.open(args.clean_image).convert("RGB")
    px_w, px_h = image.size
    print(f"[1/4] 입력 (clean) {px_w}x{px_h}")

    sam_input = image
    if args.sam_resize and px_w > args.sam_resize:
        scale = args.sam_resize / px_w
        sam_input = image.resize((args.sam_resize, int(px_h * scale)))
    print(f"[2/4] SAM2 (input={sam_input.size}, pps={args.sam_points})")
    res = run_sam2_auto(
        sam_input, points_per_side=args.sam_points, max_masks=400,
        pred_iou_thresh=0.80, stability_score_thresh=0.88,
    )
    print(f"     {len(res.masks)} masks, {res.elapsed_sec:.1f}s on {res.device}")

    full_masks: list[Sam2Mask] = []
    for m in res.masks:
        seg = upsample_mask(m.segmentation, (px_w, px_h))
        ys, xs = np.where(seg)
        if len(ys) == 0:
            continue
        bbox = (int(xs.min()), int(ys.min()),
                int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        full_masks.append(Sam2Mask(bbox=bbox, segmentation=seg, score=m.score, area=int(seg.sum())))
    render_overlay(image, full_masks, args.out_dir / "step3_01_sam2_all.png")

    print("[3/4] 면적 필터 + IoU dedupe")
    filtered = filter_by_area(full_masks, (px_w, px_h),
                              min_ratio=args.min_area, max_ratio=args.max_area)
    deduped = dedupe(filtered, iou_threshold=0.85)
    print(f"     {len(full_masks)} → 면적 {len(filtered)} → dedupe {len(deduped)}")

    print("[4/4] alpha crop 저장")
    layers: list[ObjectLayer] = []
    obj_dir = args.out_dir / "objects"
    sorted_masks = sorted(deduped, key=lambda m: -m.area)
    for i, m in enumerate(sorted_masks):
        out = export_alpha_crop(image, m.segmentation,
                                out_dir=obj_dir, name=f"layer_{i:03d}.png")
        if out is None:
            continue
        bbox, path = out
        layers.append(ObjectLayer(
            bbox=bbox, z=i,
            area_ratio=float(m.area) / (px_w * px_h),
            score=float(m.score),
            alpha_path=str(path.relative_to(args.out_dir)),
        ))
    render_box_overlay(image, layers, args.out_dir / "step3_02_layers.png")

    out_json = args.out_dir / "object_layers.json"
    out_json.write_text(json.dumps({
        "image_size": [px_w, px_h],
        "layer_count": len(layers),
        "elapsed_sec": round(time.perf_counter() - started, 1),
        "layers": [asdict(l) for l in layers],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(layers)} 레이어 저장 → {out_json}")


if __name__ == "__main__":
    main()
