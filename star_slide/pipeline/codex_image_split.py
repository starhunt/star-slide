"""단일 이미지 → editable PPTX 변환: Codex Vision + image_gen + SAM2 파이프라인.

experiments/diagram_split/v7_*.py 의 4단계 PoC 를 라이브러리화 한 모듈.
notebooklm_auto.py 의 reconstruction_mode='image_split' 에서 호출된다.

핵심 흐름:
  Step 1. Codex CLI Vision LLM → text_layout.json
          (텍스트 + bbox + font_size_px + color + alignment + bold)
  Step 2. 텍스트 제거 (두 모드):
          - text_erase_mode='codex_imagegen': Codex image_gen 2.0 으로 텍스트 지운 이미지 생성
          - text_erase_mode='solid': 각 bbox 외곽 ring 픽셀 mode 색상으로 fill (빠름)
  Step 3. SAM2.1 auto-mask (글자 간섭 없음) → 깨끗한 객체 alpha PNG crop
  Step 4. 재조합: 깨끗한 배경 + alpha 객체 (z-order) + editable textbox
          (East Asian font 메타 명시)

설계 원칙:
  - notebooklm_auto 와 동일한 emit/check_cancel 시그니처
  - 모든 중간 산출물을 workdir 아래에 저장 (디버깅/QA 용)
  - 외부 도구 (codex CLI) 가 실패하면 fallback (solid fill 모드로 자동 전환)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from star_slide.segmentation.sam2_auto import Sam2Mask, run_sam2_auto

EMU_PER_INCH = 914400
PT_PER_INCH = 72.0
SLIDE_W_EMU = 12192000   # 13.333" — 표준 16:9
SLIDE_H_EMU = 6858000    #  7.5"
DEFAULT_FONT = "Apple SD Gothic Neo"


@dataclass(frozen=True)
class ImageSplitOptions:
    """단일 이미지 분할 변환 옵션."""

    text_erase_mode: str = "codex_imagegen"
    """텍스트 제거 방식: 'codex_imagegen'|'solid'.
    'codex_imagegen' 은 Codex CLI image_gen 2.0 호출 (~30-60s). 그라데이션 보존 우수.
    'solid' 은 주변색 ring sample fill (~1s). 단색 배경에 적합."""

    background_mode: str = "white"
    """슬라이드 배경 처리:
      'white'       — 흰 캔버스 + alpha 객체 + textbox (default, 깔끔)
      'transparent' — 배경 picture 없음 (PowerPoint 기본 슬라이드 배경 유지)
      'clean'       — Codex 가 만든 텍스트 제거 이미지를 통째로 깔기 (시각 충실하지만
                      객체와 이중 합성. 사용자가 객체를 옮기면 배경에 같은 모양 잔존)
    """

    sam_resize: int = 1920
    """SAM2 입력 리사이즈 폭. 0=원본 사용 (정밀하지만 느림)"""

    sam_points_per_side: int = 48
    """SAM2 grid 한 변의 point 수 (총 = side²). dense=48 권장."""

    sam_pred_iou_thresh: float = 0.80
    sam_stability_thresh: float = 0.88

    min_object_area_ratio: float = 0.0005
    max_object_area_ratio: float = 0.55
    object_iou_dedupe_threshold: float = 0.85

    font_name: str = DEFAULT_FONT


@dataclass(frozen=True)
class ImageSplitResult:
    output: Path
    workdir: Path
    text_layout_json: Path
    clean_bg_png: Path
    object_layers_json: Path
    elapsed_sec: float


@dataclass
class _TextItem:
    text: str
    bbox: tuple[float, float, float, float]
    font_size_px: float
    color: str
    is_bold: bool
    alignment: str


@dataclass
class _ObjectLayer:
    bbox: tuple[int, int, int, int]
    z: int
    area_ratio: float
    score: float
    alpha_path: Path


# ============================================================
# Step 1 — Codex Vision 으로 텍스트 layout JSON 추출
# ============================================================


CODEX_TEXT_PROMPT = """이미지의 모든 텍스트를 JSON 으로 추출해주세요. 다른 설명이나 코드블록 없이 순수 JSON만 반환해주세요.

형식:
{
  "image_size": [width_px, height_px],
  "texts": [
    {
      "text": "텍스트 내용",
      "bbox": [x, y, w, h],
      "font_size_px": 60,
      "color": "#hex",
      "is_bold": true,
      "alignment": "center"
    }
  ]
}

요구사항:
- 모든 한글/영문 텍스트 빠짐없이 (제목, 부제, 라벨, 박스 안 글, 따옴표 안 글, footer 등)
- bbox 픽셀 좌표 (좌상단 기준, 가로세로 px)
- font_size_px = 글자 자체 픽셀 높이 (라인 높이 X)
- color = 글자의 주된 hex 색
- 텍스트 라인 단위 (예: '광주 17개 대학 IDP' 한 줄로, 단어 분리하지 말 것)
- alignment = 'left'|'center'|'right'
- is_bold = 굵은 글씨 여부
"""


def normalize_text_layout_to_image_size(
    text_layout: dict,
    actual_image_size: tuple[int, int],
) -> dict:
    """codex 가 다른 해상도 (예: 2048x1152) 로 좌표를 줄 수 있어, 실제 이미지 크기로
    bbox/font_size_px 를 비례 변환.

    text_layout['image_size'] 가 실제와 다르면 모든 텍스트의 좌표를 스케일.
    in-place 수정 후 반환.
    """
    if "image_size" not in text_layout or "texts" not in text_layout:
        return text_layout
    js_w, js_h = text_layout["image_size"]
    real_w, real_h = actual_image_size
    if js_w <= 0 or js_h <= 0:
        return text_layout
    if abs(js_w - real_w) <= 4 and abs(js_h - real_h) <= 4:
        return text_layout  # 같음
    sx = real_w / js_w
    sy = real_h / js_h
    s_avg = (sx + sy) / 2  # 폰트 크기 (가로/세로 평균)
    for t in text_layout["texts"]:
        bbox = t.get("bbox", (0, 0, 0, 0))
        if len(bbox) == 4:
            t["bbox"] = [
                int(bbox[0] * sx),
                int(bbox[1] * sy),
                int(bbox[2] * sx),
                int(bbox[3] * sy),
            ]
        if "font_size_px" in t:
            t["font_size_px"] = float(t["font_size_px"]) * s_avg
    text_layout["image_size"] = [real_w, real_h]
    text_layout["_normalized_from"] = [js_w, js_h]
    return text_layout


def analyze_text_with_codex(
    image_path: Path,
    *,
    out_json: Path,
    timeout_sec: float = 600.0,
) -> dict:
    """Codex CLI Vision LLM 으로 이미지의 텍스트 + 위치 추출.

    PoC 와 동일하게 prompt 를 stdin 으로 전달 (인자로 멀티라인 prompt 를 보내면
    codex 가 `No prompt provided via stdin.` 으로 종료함).
    """
    out_json.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "codex", "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check", "--ephemeral",
        "-i", str(image_path),
        "-o", str(out_json),
    ]
    completed = subprocess.run(
        cmd, input=CODEX_TEXT_PROMPT,
        capture_output=True, text=True, timeout=timeout_sec, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Codex 텍스트 분석 실패 (exit={completed.returncode}): "
            f"{completed.stderr[:500]}"
        )
    if not out_json.exists() or out_json.stat().st_size == 0:
        raise RuntimeError(
            f"Codex 결과 파일이 비어있거나 없음: {out_json}\n"
            f"stdout 마지막 500자:\n{completed.stdout[-500:]}"
        )
    return json.loads(out_json.read_text(encoding="utf-8"))


# ============================================================
# Step 2 — 텍스트 제거
# ============================================================


CODEX_REMOVE_TEXT_PROMPT = """첨부된 한글 인포그래픽에서 모든 텍스트(한글+영문)만 정확히 제거한 새 이미지를 image_gen 도구로 생성해줘.
- 큰 제목, 부제, 라벨, 박스 안 모든 글자, 픽토그램 라벨, 따옴표 안 글, 하단 footer 모두 제거
- 다른 모든 시각 요소(컬러 박스, 픽토그램 아이콘, 화살표, 그라데이션, 박스 형태와 색)는 픽셀 단위로 정확히 보존
- 글자 자리는 주변 배경색/그라데이션으로 자연스럽게 복원
- 입력 이미지의 원본 비율 유지
생성된 PNG 파일 경로만 마지막에 출력.
"""


def remove_text_codex_imagegen(
    image_path: Path,
    *,
    out_png: Path,
    target_size: tuple[int, int] | None = None,
    timeout_sec: float = 600.0,
) -> Path:
    """Codex image_gen 2.0 으로 텍스트만 제거된 이미지 생성.

    PoC 와 동일하게 prompt 를 stdin 으로 전달 (인자 전달은 codex 가 거부).
    Codex 가 image_gen 도구로 새 PNG 를 생성하면 보통 ~/.codex/generated_images/.../ig_*.png
    경로에 저장하고 stdout 마지막 줄에 그 경로(들)를 출력한다.

    stdout 파싱 규칙:
      - 입력 이미지 경로(image_path) 와 동일한 line 은 무시
      - 'ig_' 접두사를 포함하거나 'generated_images' 디렉토리 안의 PNG 를 우선 채택
      - codex 가 image_gen 을 호출하지 않고 입력 그대로 반환한 경우 RuntimeError
    """
    out_png.parent.mkdir(parents=True, exist_ok=True)
    input_abs = str(image_path.resolve())
    cmd = [
        "codex", "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check", "--ephemeral",
        "-i", str(image_path),
    ]
    completed = subprocess.run(
        cmd, input=CODEX_REMOVE_TEXT_PROMPT,
        capture_output=True, text=True, timeout=timeout_sec, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Codex image_gen 실패 (exit={completed.returncode}): "
            f"{completed.stderr[:500]}"
        )
    # 후보 PNG 경로 수집
    stdout_lines = [ln.strip() for ln in completed.stdout.splitlines() if ln.strip()]
    candidates: list[Path] = []
    for line in stdout_lines:
        if not line.endswith(".png"):
            continue
        # codex stdout 에는 절대 경로 외에 다른 텍스트도 섞여 있을 수 있으므로
        # 경로처럼 보이는 부분만 추출 (마지막 공백 이후)
        path_str = line.rsplit(" ", 1)[-1]
        if not Path(path_str).exists():
            continue
        if Path(path_str).resolve() == Path(input_abs).resolve():
            continue
        candidates.append(Path(path_str))

    if not candidates:
        raise RuntimeError(
            "Codex image_gen 출력 PNG 경로를 찾을 수 없음 (image_gen 도구 미호출 의심). "
            f"stdout 마지막 500자:\n{completed.stdout[-500:]}"
        )
    # generated_images 디렉토리 안의 ig_* PNG 를 우선 채택 (가장 최근 mtime)
    generated = [p for p in candidates if "generated_images" in str(p)]
    pool = generated or candidates
    chosen = max(pool, key=lambda p: p.stat().st_mtime)
    shutil.copy2(chosen, out_png)
    if target_size is not None:
        with Image.open(out_png) as im:
            if im.size != target_size:
                im.convert("RGB").resize(target_size, Image.LANCZOS).save(out_png)
    return out_png


def _quantize_color(rgb: tuple[int, int, int], step: int = 16) -> tuple[int, int, int]:
    return tuple((c // step) * step + step // 2 for c in rgb)


def _sample_ring_color(
    arr: np.ndarray,
    bbox: tuple[int, int, int, int],
    *,
    ring_thickness: int = 8,
    pad: int = 2,
) -> tuple[int, int, int]:
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
    rh, rw = region.shape[:2]
    mask = np.ones((rh, rw), dtype=bool)
    mask[inner_y0 - y0:inner_y1 - y0, inner_x0 - x0:inner_x1 - x0] = False
    ring_pixels = region[mask]
    if len(ring_pixels) == 0:
        return (255, 255, 255)
    quant = [_quantize_color(tuple(p)) for p in ring_pixels]
    return tuple(int(c) for c in Counter(quant).most_common(1)[0][0])


def remove_text_solid_fill(
    image_path: Path,
    text_layout: dict,
    *,
    out_png: Path,
    pad: int = 6,
) -> Path:
    """text_layout JSON 의 각 bbox 외곽 ring mode 색으로 fill (빠른 fallback).

    그라데이션이 강한 배경에선 약점이지만 단색/카드 배경엔 우수.
    """
    out_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    arr = np.asarray(image).copy()
    h, w = arr.shape[:2]
    for t in text_layout.get("texts", []):
        bx, by, bw, bh = t.get("bbox", (0, 0, 0, 0))
        bx = int(bx)
        by = int(by)
        bw = int(bw)
        bh = int(bh)
        if bw <= 0 or bh <= 0:
            continue
        bg_color = _sample_ring_color(arr, (bx, by, bw, bh), ring_thickness=8, pad=pad)
        x0 = max(0, bx - pad)
        y0 = max(0, by - pad)
        x1 = min(w, bx + bw + pad)
        y1 = min(h, by + bh + pad)
        arr[y0:y1, x0:x1] = bg_color
    Image.fromarray(arr).save(out_png)
    return out_png


# ============================================================
# Step 3 — SAM2 객체 추출 (깨끗한 배경에서)
# ============================================================


def _upsample_mask(seg_small: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    seg_uint = (seg_small.astype(np.uint8)) * 255
    seg_full = cv2.resize(seg_uint, target_size, interpolation=cv2.INTER_LINEAR)
    return seg_full > 127


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 0.0
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / float(union) if union else 0.0


def _filter_and_dedupe(
    masks: list[Sam2Mask],
    image_size: tuple[int, int],
    *,
    min_ratio: float,
    max_ratio: float,
    iou_threshold: float,
) -> list[Sam2Mask]:
    w, h = image_size
    total = w * h
    filtered = [m for m in masks if min_ratio <= m.area / total <= max_ratio]
    sorted_masks = sorted(filtered, key=lambda m: -m.area)
    kept: list[Sam2Mask] = []
    for m in sorted_masks:
        if not any(_mask_iou(m.segmentation, k.segmentation) > iou_threshold for k in kept):
            kept.append(m)
    return kept


def _export_alpha_crop(
    image: Image.Image,
    mask: np.ndarray,
    *,
    out_dir: Path,
    name: str,
) -> tuple[tuple[int, int, int, int], Path] | None:
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


def extract_objects_sam2_clean(
    clean_image_path: Path,
    *,
    out_dir: Path,
    options: ImageSplitOptions,
) -> tuple[list[_ObjectLayer], Path]:
    """깨끗한(텍스트 제거된) 이미지에서 SAM2 객체 alpha PNG crop 들 생성.

    out_dir/objects/layer_NNN.png 들 + out_dir/object_layers.json 생성.
    """
    image = Image.open(clean_image_path).convert("RGB")
    px_w, px_h = image.size

    sam_input = image
    if options.sam_resize and px_w > options.sam_resize:
        scale = options.sam_resize / px_w
        sam_input = image.resize((options.sam_resize, int(px_h * scale)))
    res = run_sam2_auto(
        sam_input,
        points_per_side=options.sam_points_per_side,
        max_masks=400,
        pred_iou_thresh=options.sam_pred_iou_thresh,
        stability_score_thresh=options.sam_stability_thresh,
    )

    full_masks: list[Sam2Mask] = []
    for m in res.masks:
        seg = _upsample_mask(m.segmentation, (px_w, px_h))
        ys, xs = np.where(seg)
        if len(ys) == 0:
            continue
        bbox = (int(xs.min()), int(ys.min()),
                int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        full_masks.append(Sam2Mask(bbox=bbox, segmentation=seg, score=m.score, area=int(seg.sum())))

    deduped = _filter_and_dedupe(
        full_masks, (px_w, px_h),
        min_ratio=options.min_object_area_ratio,
        max_ratio=options.max_object_area_ratio,
        iou_threshold=options.object_iou_dedupe_threshold,
    )

    obj_dir = out_dir / "objects"
    layers: list[_ObjectLayer] = []
    sorted_masks = sorted(deduped, key=lambda m: -m.area)
    for i, m in enumerate(sorted_masks):
        out = _export_alpha_crop(image, m.segmentation, out_dir=obj_dir, name=f"layer_{i:03d}.png")
        if out is None:
            continue
        bbox, path = out
        layers.append(_ObjectLayer(
            bbox=bbox, z=i,
            area_ratio=float(m.area) / (px_w * px_h),
            score=float(m.score),
            alpha_path=path,
        ))

    json_path = out_dir / "object_layers.json"
    json_path.write_text(json.dumps({
        "image_size": [px_w, px_h],
        "layer_count": len(layers),
        "sam_total_masks": len(full_masks),
        "layers": [
            {
                "bbox": ly.bbox, "z": ly.z,
                "area_ratio": ly.area_ratio, "score": ly.score,
                "alpha_path": str(ly.alpha_path.relative_to(out_dir)),
            }
            for ly in layers
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return layers, json_path


# ============================================================
# Step 4 — PPTX 재조합
# ============================================================


def _set_east_asian_font(rPr, font_name: str) -> None:
    for tag in ("a:ea", "a:cs"):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)
    ea = etree.SubElement(rPr, qn("a:ea"))
    ea.set("typeface", font_name)
    cs = etree.SubElement(rPr, qn("a:cs"))
    cs.set("typeface", font_name)


def _add_textbox(
    slide,
    item: dict,
    *,
    scale: float,
    effective_dpi: float,
    font_name: str,
) -> None:
    bbox = item.get("bbox", (0, 0, 0, 0))
    if len(bbox) != 4:
        return
    x, y, w, h = bbox
    font_px = float(item.get("font_size_px", 18))
    font_pt = font_px * PT_PER_INCH / effective_dpi
    pad_emu = int(font_pt / PT_PER_INCH * EMU_PER_INCH * 0.3)
    left = int(x * scale) - pad_emu // 2
    top = int(y * scale) - pad_emu // 2
    width = int(w * scale) + pad_emu
    min_h_emu = int(font_pt / PT_PER_INCH * EMU_PER_INCH * 1.4)
    height = max(int(h * scale) + pad_emu, min_h_emu)
    if width <= 0 or height <= 0:
        return
    tb = slide.shapes.add_textbox(Emu(left), Emu(top), Emu(width), Emu(height))
    tf = tb.text_frame
    for attr in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, attr, Emu(0))
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = {
        "left": PP_ALIGN.LEFT,
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
    }.get(item.get("alignment", "left"), PP_ALIGN.LEFT)
    run = p.add_run()
    run.text = item.get("text", "")
    run.font.name = font_name
    run.font.size = Pt(round(font_pt, 1))
    run.font.bold = bool(item.get("is_bold", False))
    color_hex = item.get("color", "#222222")
    try:
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        run.font.color.rgb = RGBColor(r, g, b)
    except Exception:
        pass
    _set_east_asian_font(run._r.get_or_add_rPr(), font_name)


def _add_image_split_slide(
    prs: Presentation,
    *,
    image_size: tuple[int, int],
    background_path: Path | None,
    background_mode: str,
    text_layout: dict,
    object_layers: list[_ObjectLayer],
    font_name: str,
) -> None:
    """기존 Presentation 에 1 슬라이드 추가. multi-slide 합성용."""
    px_w, _ = image_size
    scale = prs.slide_width / px_w
    effective_dpi = px_w / (prs.slide_width / EMU_PER_INCH)
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)

    if background_mode == "clean" and background_path is not None:
        # 시각 충실: clean 이미지 통째 깔기 (객체와 이중 합성)
        slide.shapes.add_picture(
            str(background_path), 0, 0,
            width=prs.slide_width, height=prs.slide_height,
        )
    elif background_mode == "white":
        # 흰 캔버스 (default — 깔끔, 객체 분리 명확)
        from pptx.enum.shapes import MSO_SHAPE
        bg = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height,
        )
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(255, 255, 255)
        bg.line.fill.background()
    # 'transparent' 면 아무것도 안 깔음 (PowerPoint 기본 슬라이드 배경 유지)

    # 면적 큰 순 (z 작은) 부터 → 뒤에 깔림. 작은 픽토그램이 위에.
    for ly in sorted(object_layers, key=lambda layer: layer.z):
        x, y, w, h = ly.bbox
        slide.shapes.add_picture(
            str(ly.alpha_path),
            Emu(int(x * scale)), Emu(int(y * scale)),
            width=Emu(int(w * scale)), height=Emu(int(h * scale)),
        )
    # textbox 는 최상단
    for t in text_layout.get("texts", []):
        _add_textbox(slide, t, scale=scale, effective_dpi=effective_dpi, font_name=font_name)


def compose_image_split_pptx(
    *,
    image_size: tuple[int, int],
    background_path: Path | None,
    text_layout: dict,
    object_layers: list[_ObjectLayer],
    out_path: Path,
    font_name: str = DEFAULT_FONT,
    background_mode: str = "white",
) -> Path:
    """단일 슬라이드 PPTX 생성 (compose_image_split_pptx_multi 의 single 버전)."""
    prs = Presentation()
    prs.slide_width = Emu(SLIDE_W_EMU)
    prs.slide_height = Emu(SLIDE_H_EMU)
    _add_image_split_slide(
        prs,
        image_size=image_size,
        background_path=background_path,
        background_mode=background_mode,
        text_layout=text_layout,
        object_layers=object_layers,
        font_name=font_name,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path


def compose_image_split_pptx_multi(
    *,
    slides_data: list[dict],
    out_path: Path,
    font_name: str = DEFAULT_FONT,
    background_mode: str = "white",
) -> Path:
    """N개 슬라이드 image_split 결과를 한 PPTX 로 합성.

    slides_data: [
      {
        'image_size': (w, h),
        'background_path': Path,
        'text_layout': dict,
        'object_layers': list[_ObjectLayer],
      },
      ...
    ]
    """
    prs = Presentation()
    prs.slide_width = Emu(SLIDE_W_EMU)
    prs.slide_height = Emu(SLIDE_H_EMU)
    for sd in slides_data:
        _add_image_split_slide(
            prs,
            image_size=sd["image_size"],
            background_path=sd.get("background_path"),
            background_mode=background_mode,
            text_layout=sd["text_layout"],
            object_layers=sd["object_layers"],
            font_name=font_name,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path


# ============================================================
# 통합 entry point — notebooklm_auto 에서 호출
# ============================================================


def convert_image_split(
    *,
    input_image: Path,
    output_pptx: Path,
    workdir: Path,
    options: ImageSplitOptions,
    progress: Callable[[str, float], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> ImageSplitResult:
    """단일 이미지 → editable PPTX 4단계 파이프라인.

    workdir 아래 모든 중간 산출물 보존:
      workdir/text_layout.json
      workdir/02_clean_bg.png  (Step 2 결과)
      workdir/objects/layer_NNN.png
      workdir/object_layers.json
    """
    def emit(msg: str, pct: float) -> None:
        if progress is not None:
            progress(msg, pct)

    def check_cancel() -> None:
        if cancel is not None and cancel():
            from star_slide.pipeline.notebooklm_auto import JobCancelledError
            raise JobCancelledError("convert_image_split cancelled")

    workdir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    check_cancel()
    emit("Codex Vision 으로 텍스트 + 위치 추출 중", 5)
    text_json_path = workdir / "text_layout.json"
    text_layout = analyze_text_with_codex(input_image, out_json=text_json_path)

    check_cancel()
    image = Image.open(input_image).convert("RGB")
    target_size = image.size

    # codex 가 다른 해상도로 좌표를 줄 수 있어 실제 이미지 크기로 정규화 후 저장
    js_size = text_layout.get("image_size", target_size)
    text_layout = normalize_text_layout_to_image_size(text_layout, target_size)
    if "_normalized_from" in text_layout:
        text_json_path.write_text(
            json.dumps(text_layout, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        emit(
            f"텍스트 {len(text_layout.get('texts', []))}개 추출 "
            f"(좌표 {js_size}→{target_size} 정규화)", 25,
        )
    else:
        emit(f"텍스트 {len(text_layout.get('texts', []))}개 추출", 25)

    clean_path = workdir / "02_clean_bg.png"
    if options.text_erase_mode == "codex_imagegen":
        emit("Codex image_gen 으로 텍스트 제거된 배경 생성 중 (~30-60s)", 30)
        try:
            remove_text_codex_imagegen(
                input_image, out_png=clean_path, target_size=target_size,
            )
        except Exception as exc:
            emit(f"Codex image_gen 실패 → solid fill 로 fallback: {exc}", 40)
            remove_text_solid_fill(input_image, text_layout, out_png=clean_path)
    else:
        emit("주변색 fill 로 텍스트 제거 중", 30)
        remove_text_solid_fill(input_image, text_layout, out_png=clean_path)
    emit("배경 생성 완료", 60)

    check_cancel()
    emit(f"SAM2 로 객체 추출 중 (pps={options.sam_points_per_side})", 65)
    layers, layers_json = extract_objects_sam2_clean(
        clean_path, out_dir=workdir, options=options,
    )
    emit(f"{len(layers)}개 객체 alpha crop", 85)

    check_cancel()
    emit("PPTX 재조합 중", 90)
    compose_image_split_pptx(
        image_size=target_size,
        background_path=clean_path,
        text_layout=text_layout,
        object_layers=layers,
        out_path=output_pptx,
        font_name=options.font_name,
        background_mode=options.background_mode,
    )
    emit("완료", 100)

    return ImageSplitResult(
        output=output_pptx,
        workdir=workdir,
        text_layout_json=text_json_path,
        clean_bg_png=clean_path,
        object_layers_json=layers_json,
        elapsed_sec=round(time.perf_counter() - started, 1),
    )


def convert_image_split_multi(
    *,
    input_images: list[Path],
    output_pptx: Path,
    workdir: Path,
    options: ImageSplitOptions,
    progress: Callable[[str, float], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> ImageSplitResult:
    """N장 이미지 → N-슬라이드 editable PPTX (각 슬라이드마다 image_split 적용).

    workdir 아래에 슬라이드별 sub-dir:
      workdir/slide_001/text_layout.json, 02_clean_bg.png, objects/, ...
      workdir/slide_NNN/...

    progress callback 은 전체 (0~100) 기준으로 emit. 슬라이드 1장당
    pct_per_slide = 100 / N 만큼 진행.
    """
    def emit(msg: str, pct: float) -> None:
        if progress is not None:
            progress(msg, pct)

    def check_cancel() -> None:
        if cancel is not None and cancel():
            from star_slide.pipeline.notebooklm_auto import JobCancelledError
            raise JobCancelledError("convert_image_split_multi cancelled")

    workdir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    n = len(input_images)
    if n == 0:
        raise ValueError("input_images 가 비었습니다")
    pct_per = 100.0 / n

    slides_data: list[dict] = []
    last_clean_bg: Path | None = None
    last_text_json: Path | None = None
    last_layers_json: Path | None = None

    for i, img_path in enumerate(input_images, start=1):
        slide_dir = workdir / f"slide_{i:03d}"
        slide_dir.mkdir(parents=True, exist_ok=True)
        base_pct = (i - 1) * pct_per

        check_cancel()
        emit(f"[{i}/{n}] Codex Vision 으로 텍스트 추출", base_pct)
        text_json = slide_dir / "text_layout.json"
        text_layout = analyze_text_with_codex(img_path, out_json=text_json)
        check_cancel()
        image = Image.open(img_path).convert("RGB")
        target_size = image.size
        text_layout = normalize_text_layout_to_image_size(text_layout, target_size)
        if "_normalized_from" in text_layout:
            text_json.write_text(
                json.dumps(text_layout, ensure_ascii=False, indent=2), encoding="utf-8",
            )

        check_cancel()
        clean_path = slide_dir / "02_clean_bg.png"
        if options.text_erase_mode == "codex_imagegen":
            emit(f"[{i}/{n}] Codex image_gen 으로 텍스트 제거 (~30-60s)", base_pct + pct_per * 0.25)
            try:
                remove_text_codex_imagegen(img_path, out_png=clean_path, target_size=target_size)
            except Exception as exc:
                emit(f"[{i}/{n}] image_gen 실패 → solid fallback: {exc}", base_pct + pct_per * 0.40)
                remove_text_solid_fill(img_path, text_layout, out_png=clean_path)
        else:
            emit(f"[{i}/{n}] 주변색 fill 로 텍스트 제거", base_pct + pct_per * 0.25)
            remove_text_solid_fill(img_path, text_layout, out_png=clean_path)

        check_cancel()
        emit(f"[{i}/{n}] SAM2 로 객체 추출", base_pct + pct_per * 0.65)
        layers, layers_json = extract_objects_sam2_clean(
            clean_path, out_dir=slide_dir, options=options,
        )

        slides_data.append({
            "image_size": target_size,
            "background_path": clean_path,
            "text_layout": text_layout,
            "object_layers": layers,
        })
        last_clean_bg = clean_path
        last_text_json = text_json
        last_layers_json = layers_json
        emit(f"[{i}/{n}] 슬라이드 완료 ({len(text_layout.get('texts', []))} 텍스트, "
             f"{len(layers)} 객체)", base_pct + pct_per)

    check_cancel()
    emit(f"PPTX 합성 ({n} 슬라이드)", 95)
    compose_image_split_pptx_multi(
        slides_data=slides_data,
        out_path=output_pptx,
        font_name=options.font_name,
        background_mode=options.background_mode,
    )
    emit("완료", 100)

    return ImageSplitResult(
        output=output_pptx,
        workdir=workdir,
        text_layout_json=last_text_json or workdir,
        clean_bg_png=last_clean_bg or workdir,
        object_layers_json=last_layers_json or workdir,
        elapsed_sec=round(time.perf_counter() - started, 1),
    )
