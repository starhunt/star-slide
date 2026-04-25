"""H1 검증: SAM 슬라이드 객체 분리 IoU.

SAM 3 (facebook/sam3)는 gated repo이므로 SAM 2.1 hiera-large 자동 마스크 모드로 fallback.
ADR-001의 SAM 2 fallback 경로 활용.

10장 H1 priority 슬라이드에 자동 마스크 생성 → 마스크 → bbox → 측정:
  1. **Text recall**: PaddleOCR이 검출한 텍스트 bbox 대비 SAM 마스크 매칭률 (recall@IoU=0.5)
  2. **시각 검수**: SAM 마스크 오버레이 PNG 생성 → 사용자 정성 판단

처리 시간/마스크 수는 모두 기록 (Mac MPS 추론 시간 추정용).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw
from rich.console import Console
from rich.table import Table

from star_slide.ocr.paddleocr_worker import run_ocr
from star_slide.segmentation.iou import bbox_iou
from star_slide.segmentation.sam2_auto import run_sam2_auto

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples" / "notebooklm"
LABELS = ROOT / "data" / "labels" / "notebooklm"
RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)
(RESULTS / "overlays").mkdir(exist_ok=True)

# 텍스트 매칭 IoU 임계 (recall 계산용)
TEXT_MATCH_IOU = 0.5


def _draw_overlay_with_ocr(
    pil: Image.Image,
    sam_masks: list,
    ocr_bboxes: list[tuple[float, float, float, float]],
    out_path: Path,
) -> None:
    """SAM 마스크(파랑) + OCR text bbox(빨강) 오버레이.

    - 파랑 = SAM 자동 마스크 bbox
    - 빨강 = PaddleOCR 텍스트 라인 (confidence ≥ 0.7)
    """
    overlay = pil.copy()
    draw = ImageDraw.Draw(overlay)
    for m in sam_masks:
        x, y, w, h = m.bbox
        draw.rectangle([x, y, x + w, y + h], outline=(50, 100, 220), width=1)
    for x, y, w, h in ocr_bboxes:
        draw.rectangle([x, y, x + w, y + h], outline=(220, 50, 50), width=2)
    overlay.save(out_path)


def _bbox_contains_ratio(
    container: tuple[float, float, float, float],
    target: tuple[float, float, float, float],
) -> float:
    """target이 container에 얼마나 포함됐는가 (target 면적 기준).

    SAM 마스크가 OCR 텍스트 영역을 감싸는지 측정 (객체 단위 차이 보정).
    """
    cx, cy, cw, ch = container
    tx, ty, tw, th = target
    if tw <= 0 or th <= 0:
        return 0.0
    ix1 = max(cx, tx)
    iy1 = max(cy, ty)
    ix2 = min(cx + cw, tx + tw)
    iy2 = min(cy + ch, ty + th)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    return (iw * ih) / (tw * th)


def _text_recall(
    sam_masks: list,
    ocr_bboxes: list[tuple[float, float, float, float]],
    iou_thresh: float = TEXT_MATCH_IOU,
    containment_thresh: float = 0.7,
) -> tuple[float, float, int, int, int]:
    """OCR 텍스트 bbox 대비 SAM 마스크 매칭률 두 가지 측정.

    1. recall@IoU≥0.5: 엄격한 IoU 매칭
    2. recall@contained≥0.7: SAM 마스크가 OCR bbox 70%+ 포함 (의미 단위 차이 보정)

    Returns:
        (recall_iou, recall_contained, n_iou, n_contained, n_total)
    """
    if not ocr_bboxes:
        return 0.0, 0.0, 0, 0, 0

    sam_bboxes = [m.bbox for m in sam_masks]
    n_iou = 0
    n_contained = 0
    for ocr_bb in ocr_bboxes:
        best_iou = 0.0
        best_contain = 0.0
        for sam_bb in sam_bboxes:
            best_iou = max(best_iou, bbox_iou(sam_bb, ocr_bb))
            best_contain = max(best_contain, _bbox_contains_ratio(sam_bb, ocr_bb))
        if best_iou >= iou_thresh:
            n_iou += 1
        if best_contain >= containment_thresh:
            n_contained += 1
    n = len(ocr_bboxes)
    return n_iou / n, n_contained / n, n_iou, n_contained, n


def main() -> None:
    console = Console()

    priority_files = sorted(
        p
        for p in LABELS.glob("*.json")
        if json.loads(p.read_text(encoding="utf-8")).get("h1_priority")
    )

    console.print(f"[bold]H1 priority 슬라이드: {len(priority_files)}장[/]")
    console.print("[bold]SAM 2.1 hiera-large 자동 마스크 모드[/]")
    console.print()

    table = Table(title="H1 SAM 2.1 자동 마스크 결과")
    table.add_column("#", justify="right", width=3)
    table.add_column("슬라이드", style="cyan")
    table.add_column("카테고리", style="magenta")
    table.add_column("OCR", justify="right")
    table.add_column("SAM", justify="right")
    table.add_column("recall@IoU", justify="right")
    table.add_column("recall@contain", justify="right")
    table.add_column("시간(s)", justify="right")

    per_slide: list[dict] = []

    for i, label_path in enumerate(priority_files, start=1):
        label = json.loads(label_path.read_text(encoding="utf-8"))
        img_path = SAMPLES / label["image"]

        # 1. SAM 2.1 자동 마스크 생성
        t0 = time.perf_counter()
        sam_result = run_sam2_auto(img_path)
        sam_time = time.perf_counter() - t0

        # 2. OCR (텍스트 bbox → recall 측정 ground truth)
        try:
            ocr_lines = run_ocr(img_path, lang="korean")
            ocr_bboxes = [ln.bbox for ln in ocr_lines if ln.confidence >= 0.7]
        except Exception as exc:
            console.print(f"[yellow]OCR 실패 ({label['image']}): {exc}[/]")
            ocr_bboxes = []

        # 3. text recall 측정 (IoU + containment 양 방식)
        recall_iou, recall_contain, n_iou, n_contain, n_total = _text_recall(
            sam_result.masks, ocr_bboxes
        )

        # 4. 시각화 오버레이 PNG (SAM 마스크 + OCR bbox)
        pil = Image.open(img_path).convert("RGB")
        overlay_path = RESULTS / "overlays" / f"{label['image']}"
        _draw_overlay_with_ocr(pil, sam_result.masks, ocr_bboxes, overlay_path)

        # 5. 표 row
        def _color(r: float) -> str:
            return "green" if r >= 0.8 else ("yellow" if r >= 0.5 else "red")

        iou_str = f"{recall_iou:.2f}" if n_total else "N/A"
        contain_str = f"{recall_contain:.2f}" if n_total else "N/A"

        table.add_row(
            str(i),
            label["image"],
            label["category"],
            f"{n_total}",
            f"{len(sam_result.masks)}",
            f"[{_color(recall_iou)}]{iou_str}[/] ({n_iou}/{n_total})",
            f"[{_color(recall_contain)}]{contain_str}[/] ({n_contain}/{n_total})",
            f"{sam_time:.1f}",
        )

        per_slide.append(
            {
                "image": label["image"],
                "category": label["category"],
                "n_ocr_text_bboxes": n_total,
                "n_sam_masks": len(sam_result.masks),
                "text_recall_at_iou_0.5": recall_iou,
                "text_recall_at_contain_0.7": recall_contain,
                "n_matched_iou": n_iou,
                "n_matched_contain": n_contain,
                "elapsed_total_sec": sam_time,
                "device": sam_result.device,
                "overlay_path": str(overlay_path.relative_to(ROOT)),
            }
        )

    console.print(table)

    # 집계
    n = len(per_slide)
    n_with_ocr = max(1, sum(1 for r in per_slide if r["n_ocr_text_bboxes"] > 0))
    avg_iou = sum(r["text_recall_at_iou_0.5"] for r in per_slide) / n_with_ocr
    avg_contain = sum(r["text_recall_at_contain_0.7"] for r in per_slide) / n_with_ocr
    avg_time = sum(r["elapsed_total_sec"] for r in per_slide) / n
    total_masks = sum(r["n_sam_masks"] for r in per_slide)

    summary = {
        "n_slides": n,
        "model": "facebook/sam2.1-hiera-large (SAM 3 fallback — gated)",
        "avg_text_recall_at_iou_0.5": avg_iou,
        "avg_text_recall_at_contain_0.7": avg_contain,
        "avg_elapsed_sec": avg_time,
        "total_masks": total_masks,
        "device": per_slide[0]["device"] if per_slide else "?",
        "ac_target_iou": 0.8,
        "per_slide": per_slide,
    }

    out = RESULTS / "h1_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print()
    console.print(f"[bold]평균 text recall@IoU≥0.5:[/]    {avg_iou:.3f}")
    console.print(f"[bold]평균 text recall@contain≥0.7:[/] {avg_contain:.3f}")
    console.print(f"[bold]평균 처리 시간:[/] {avg_time:.1f}s/슬라이드 ({summary['device']})")
    console.print(f"[bold]총 마스크 수:[/] {total_masks}")
    console.print(f"[bold]오버레이 PNG:[/] {RESULTS / 'overlays'}")
    console.print(f"\n[dim]상세: {out}[/]")


if __name__ == "__main__":
    # SAM 3 다운로드/캐시 메시지 억제
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    main()
