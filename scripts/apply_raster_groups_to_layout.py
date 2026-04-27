#!/usr/bin/env python3
"""Convert selected slide regions into replaceable raster-group objects.

The output layout keeps the normal editable reconstruction, but replaces
complex illustration fragments with cropped PNG picture objects. Text that is
kept editable is punched out of the cropped PNG to avoid duplicate source text
under the PowerPoint text boxes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

TEXT_NAME_HINTS = (
    "title",
    "subtitle",
    "bullet",
    "bottom",
    "callout",
    "info",
    "label",
    "heading",
    "subheading",
    "watermark",
)

PRIMARY_TEXT_NAME_HINTS = (
    "title",
    "subtitle",
    "bullet",
    "bottom",
    "info",
    "heading",
    "subheading",
)

RASTER_NATIVE_TEXT_GROUP_HINTS = (
    "equipment_specification_tag",
    "strength_panel",
    "weakness_panel",
    "comparison_panel",
    "intended_design_diagram",
    "bug_implementation_diagram",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout-dir", required=True, type=Path)
    parser.add_argument("--image-root", required=True, type=Path)
    parser.add_argument("--groups-dir", required=True, type=Path)
    parser.add_argument("--sam-dir", type=Path)
    parser.add_argument("-o", "--out-dir", required=True, type=Path)
    parser.add_argument("--slides", nargs="+", required=True, type=int)
    parser.add_argument("--layout-template", default="sample1_slide{slide_no:02d}.layout.json")
    parser.add_argument("--punchout-padding", type=int, default=6)
    parser.add_argument("--nontext-overlap-threshold", type=float, default=0.20)
    parser.add_argument("--erase-mode", choices=["inpaint", "alpha", "none"], default="inpaint")
    parser.add_argument("--drop-full-slide-grid", action="store_true")
    parser.add_argument("--rasterize-embedded-labels", action="store_true")
    return parser.parse_args()


def box_intersection(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax + aw, bx + bw)
    iy2 = min(ay + ah, by + bh)
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def box_area(box: list[float]) -> float:
    return max(0.0, float(box[2])) * max(0.0, float(box[3]))


def overlap_ratio(obj_box: list[float], group_box: list[float]) -> float:
    area = box_area(obj_box)
    return 0.0 if area <= 0 else box_intersection(obj_box, group_box) / area


def center_inside(obj_box: list[float], group_box: list[float]) -> bool:
    x, y, w, h = obj_box
    gx, gy, gw, gh = group_box
    cx = x + w / 2
    cy = y + h / 2
    return gx <= cx <= gx + gw and gy <= cy <= gy + gh


def object_box(obj: dict[str, Any]) -> list[float] | None:
    if obj.get("type") in {"text", "shape", "image"}:
        box = obj.get("bbox")
        if isinstance(box, list) and len(box) == 4:
            return [float(v) for v in box]
    if obj.get("type") == "line":
        points = obj.get("points")
        if isinstance(points, list) and len(points) == 4:
            x1, y1, x2, y2 = [float(v) for v in points]
            return [min(x1, x2), min(y1, y2), abs(x2 - x1) or 1.0, abs(y2 - y1) or 1.0]
    if obj.get("type") == "polyline":
        points = obj.get("points")
        if isinstance(points, list) and points:
            xs = [float(p[0]) for p in points if isinstance(p, list) and len(p) == 2]
            ys = [float(p[1]) for p in points if isinstance(p, list) and len(p) == 2]
            if xs and ys:
                return [min(xs), min(ys), max(xs) - min(xs) or 1.0, max(ys) - min(ys) or 1.0]
    return None


def object_text(obj: dict[str, Any]) -> str:
    parts: list[str] = []
    text = obj.get("text")
    if isinstance(text, str):
        parts.append(text)
    lines = obj.get("lines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines)
    return " ".join(parts)


def is_notebooklm_watermark(obj: dict[str, Any]) -> bool:
    name = str(obj.get("name", "")).lower()
    text = object_text(obj).lower()
    return "notebooklm" in name or "notebooklm" in text


def group_prefers_raster_text(group: dict[str, Any]) -> bool:
    """Preserve text inside complex generated panels instead of repainting it.

    Some NotebookLM/Nano Banana style assets are better treated as a single
    replaceable image: spec tags, stamps, distressed panels, and similar
    generated cards. Extracting their internal text creates inpaint artifacts
    and often makes the result less editable in practice.
    """
    name = str(group.get("name", "")).lower()
    return any(hint in name for hint in RASTER_NATIVE_TEXT_GROUP_HINTS)


def should_keep_text(
    obj: dict[str, Any],
    group_box: list[float],
    *,
    rasterize_embedded_labels: bool,
) -> bool:
    box = object_box(obj)
    if box is None or box_intersection(box, group_box) <= 0:
        return True
    name = str(obj.get("name", "")).lower()
    font_size = float(obj.get("font_size", 0))
    text = str(obj.get("text") or " ".join(obj.get("lines", [])))
    stripped = text.strip()
    if rasterize_embedded_labels:
        obj_overlap = overlap_ratio(box, group_box)
        if any(hint in name for hint in PRIMARY_TEXT_NAME_HINTS):
            return True
        if "label" in name and obj_overlap >= 0.85:
            return False
        return bool(font_size >= 24 and obj_overlap < 0.85)
    if is_raster_native_micro_label(obj, stripped):
        return False
    if stripped:
        return True
    if any(hint in name for hint in TEXT_NAME_HINTS):
        return True
    return bool(font_size >= 18 and len(stripped) >= 2)


def is_raster_native_micro_label(obj: dict[str, Any], text: str) -> bool:
    """Keep tiny embedded badge labels/icons in the raster illustration.

    These labels are usually already well rendered in the source image. Making
    them editable creates visible inpaint seams inside small white badge panels.
    Larger Korean/primary diagram labels are still kept editable.
    """
    name = str(obj.get("name", "")).lower()
    font_size = float(obj.get("font_size", 0))
    if "icon" in name or "dim_label" in name:
        return True
    if font_size > 16:
        return False
    if not text:
        return False
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return False
    return len(text) <= 18


def load_group_boxes(
    slide_stem: str,
    groups_dir: Path,
    sam_dir: Path | None,
) -> list[dict[str, Any]]:
    if sam_dir is not None:
        sam_report = sam_dir / f"{slide_stem}_sam3_report.json"
        if sam_report.exists():
            data = json.loads(sam_report.read_text(encoding="utf-8"))
            groups = []
            for idx, item in enumerate(data, start=1):
                groups.append(
                    {
                        "name": item.get("name", f"raster_group_{idx}"),
                        "bbox": item["sam_bbox"],
                        "source": "sam3",
                    }
                )
            if groups:
                return groups

    groups_json = groups_dir / f"{slide_stem}_raster_groups.json"
    data = json.loads(groups_json.read_text(encoding="utf-8"))
    return [
        {
            "name": item.get("name", f"raster_group_{idx}"),
            "bbox": item["bbox"],
            "source": "vision",
        }
        for idx, item in enumerate(data.get("raster_groups", []), start=1)
    ]


def punchout_rects(
    image: Image.Image,
    group_box: list[float],
    rects: list[list[float]],
    padding: int,
) -> None:
    alpha = image.getchannel("A")
    draw = ImageDraw.Draw(alpha)
    gx, gy, _gw, _gh = [round(v) for v in group_box]
    for rect in rects:
        x, y, w, h = rect
        lx1 = max(0, round(x - gx) - padding)
        ly1 = max(0, round(y - gy) - padding)
        lx2 = min(image.width, round(x + w - gx) + padding)
        ly2 = min(image.height, round(y + h - gy) + padding)
        draw.rectangle((lx1, ly1, lx2, ly2), fill=0)
    image.putalpha(alpha)


def inpaint_text_regions(
    image: Image.Image,
    group_box: list[float],
    rects: list[list[float]],
    padding: int,
) -> None:
    rgb = np.array(image.convert("RGB"))
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    gx, gy, _gw, _gh = [round(v) for v in group_box]

    for rect in rects:
        x, y, w, h = rect
        lx1 = max(0, round(x - gx) - padding)
        ly1 = max(0, round(y - gy) - padding)
        lx2 = min(image.width, round(x + w - gx) + padding)
        ly2 = min(image.height, round(y + h - gy) + padding)
        if lx2 <= lx1 or ly2 <= ly1:
            continue

        region = rgb[ly1:ly2, lx1:lx2]
        gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
        sat = hsv[:, :, 1]
        local_median = float(np.median(gray)) if gray.size else 255.0

        # Text over flat colored diagram blocks is common. Avoid treating the
        # colored block itself as "colored text"; only apply that heuristic on
        # light backgrounds. White text on orange/blue blocks is handled by the
        # light-on-dark rule.
        dark_ink = gray < min(145.0, local_median - 35.0)
        colored_ink = (local_median > 200) & (sat > 45) & (gray < 220)
        light_ink_on_dark = (gray > max(175.0, local_median + 30.0)) & (local_median < 210)
        region_mask = dark_ink | colored_ink | light_ink_on_dark
        mask[ly1:ly2, lx1:lx2] = np.maximum(
            mask[ly1:ly2, lx1:lx2],
            region_mask.astype(np.uint8) * 255,
        )

    if not mask.any():
        return

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=6)
    repaired = cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA)
    alpha = image.getchannel("A")
    image.paste(Image.fromarray(repaired).convert("RGBA"))
    image.putalpha(alpha)


def make_asset(
    *,
    image_path: Path,
    group: dict[str, Any],
    punchouts: list[list[float]],
    out_dir: Path,
    slide_stem: str,
    index: int,
    padding: int,
    erase_mode: str,
) -> Path:
    x, y, w, h = [round(v) for v in group["bbox"]]
    with Image.open(image_path).convert("RGBA") as source:
        crop = source.crop((x, y, x + w, y + h))
    if punchouts and erase_mode == "alpha":
        punchout_rects(crop, [x, y, w, h], punchouts, padding)
    elif punchouts and erase_mode == "inpaint":
        inpaint_text_regions(crop, [x, y, w, h], punchouts, padding)
    asset_dir = out_dir / "assets" / slide_stem
    asset_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(group["name"]))
    asset_path = asset_dir / f"{index:02d}_{safe_name}.png"
    crop.save(asset_path)
    return asset_path


def apply_to_layout(
    *,
    layout_path: Path,
    image_root: Path,
    groups_dir: Path,
    sam_dir: Path | None,
    out_dir: Path,
    punchout_padding: int,
    nontext_overlap_threshold: float,
    erase_mode: str,
    drop_full_slide_grid: bool,
    rasterize_embedded_labels: bool,
) -> dict[str, Any]:
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    slide_stem = Path(layout["image"]).stem
    image_path = image_root / layout["image"]
    groups = load_group_boxes(slide_stem, groups_dir, sam_dir)

    if drop_full_slide_grid:
        canvas = layout.get("canvas", {})
        canvas_area = float(canvas.get("width", 0) * canvas.get("height", 0))
        decorations = []
        for item in layout.get("background", {}).get("decorations", []):
            if item.get("type") == "grid":
                bbox = item.get("bbox", [0, 0, 0, 0])
                step = min(float(item.get("step_x", item.get("step", 999))), float(item.get("step_y", item.get("step", 999))))
                if canvas_area > 0 and box_area([float(v) for v in bbox]) / canvas_area > 0.70 and step <= 12:
                    continue
            decorations.append(item)
        layout.get("background", {})["decorations"] = decorations

    text_punchouts_by_group: list[list[list[float]]] = [[] for _ in groups]
    kept_objects: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    # raster group 안쪽에서 keep된 text의 bbox 모음. 이 텍스트의 배경으로 깔린
    # shape(예: 흰색 라벨 박스)가 같은 group 영역에 있어도 함께 보호되도록
    # shape 처리 단계에서 참조한다. (단순히 그룹 안에 있다는 이유로 배경 shape를
    # 지우면 raster는 inpaint로 비워지고 floating 텍스트만 남아 깨져 보인다.)
    kept_text_companion_boxes: list[list[float]] = []

    pending_shapes: list[tuple[dict[str, Any], list[float], list[int]]] = []

    for obj in layout.get("objects", []):
        if is_notebooklm_watermark(obj):
            removed.append(obj)
            continue
        box = object_box(obj)
        if box is None:
            kept_objects.append(obj)
            continue
        hit_indices = [
            idx
            for idx, group in enumerate(groups)
            if box_intersection(box, [float(v) for v in group["bbox"]]) > 0
        ]
        if not hit_indices:
            kept_objects.append(obj)
            continue

        if obj.get("type") == "text":
            keep_hit_indices = []
            for idx in hit_indices:
                if group_prefers_raster_text(groups[idx]):
                    continue
                if should_keep_text(
                    obj,
                    [float(v) for v in groups[idx]["bbox"]],
                    rasterize_embedded_labels=rasterize_embedded_labels,
                ):
                    keep_hit_indices.append(idx)
            if keep_hit_indices:
                kept_objects.append(obj)
                for idx in keep_hit_indices:
                    text_punchouts_by_group[idx].append(box)
                kept_text_companion_boxes.append(box)
            else:
                removed.append(obj)
            continue

        # shape는 이번 pass에서 결정 보류 — 모든 텍스트 keep 여부를 본 뒤 판단.
        pending_shapes.append((obj, box, hit_indices))

    text_companion_overlap_threshold = 0.85
    for obj, box, hit_indices in pending_shapes:
        # 동반 보호: 같은 raster group 안에서 keep된 텍스트와 box가 거의 일치하는
        # shape(예: 라벨 배경 rect)는 텍스트와 함께 살려야 한다. 한쪽 방향이라도
        # 충분히 겹치면 동반으로 본다 (배경이 텍스트보다 살짝 크거나 작은 경우 모두).
        protects_text = False
        for tbox in kept_text_companion_boxes:
            if (
                overlap_ratio(box, tbox) >= text_companion_overlap_threshold
                or overlap_ratio(tbox, box) >= text_companion_overlap_threshold
            ):
                protects_text = True
                break
        if protects_text:
            kept_objects.append(obj)
            continue

        should_remove = False
        for idx in hit_indices:
            group_box = [float(v) for v in groups[idx]["bbox"]]
            if overlap_ratio(box, group_box) >= nontext_overlap_threshold or center_inside(box, group_box):
                should_remove = True
                break
        if should_remove:
            removed.append(obj)
        else:
            kept_objects.append(obj)

    image_objects = []
    for idx, group in enumerate(groups, start=1):
        bbox = [round(float(v), 2) for v in group["bbox"]]
        asset = make_asset(
            image_path=image_path,
            group=group,
            punchouts=text_punchouts_by_group[idx - 1],
            out_dir=out_dir,
            slide_stem=slide_stem,
            index=idx,
            padding=punchout_padding,
            erase_mode=erase_mode,
        )
        image_objects.append(
            {
                "type": "image",
                "name": f"replaceable_{group['name']}",
                "path": str(asset.resolve()),
                "bbox": bbox,
                "replaceable": True,
                "source": group.get("source", "vision"),
            }
        )

    layout["objects"] = image_objects + kept_objects
    layout.setdefault("metadata", {})
    layout["metadata"]["raster_group_replacement"] = {
        "groups": groups,
        "removed_object_count": len(removed),
        "punched_text_regions": sum(len(items) for items in text_punchouts_by_group),
        "erase_mode": erase_mode,
        "rasterize_embedded_labels": rasterize_embedded_labels,
    }
    return layout


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for slide_no in args.slides:
        layout_path = args.layout_dir / args.layout_template.format(slide_no=slide_no)
        layout = apply_to_layout(
            layout_path=layout_path,
            image_root=args.image_root,
            groups_dir=args.groups_dir,
            sam_dir=args.sam_dir,
            out_dir=args.out_dir,
            punchout_padding=args.punchout_padding,
            nontext_overlap_threshold=args.nontext_overlap_threshold,
            erase_mode=args.erase_mode,
            drop_full_slide_grid=args.drop_full_slide_grid,
            rasterize_embedded_labels=args.rasterize_embedded_labels,
        )
        out_path = args.out_dir / layout_path.name
        out_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = layout["metadata"]["raster_group_replacement"]
        print(
            f"{out_path}: groups={len(meta['groups'])} "
            f"removed={meta['removed_object_count']} punchouts={meta['punched_text_regions']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
