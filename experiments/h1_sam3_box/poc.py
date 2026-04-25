"""SAM 3 box-prompt PoC — OCR bbox를 SAM 3에 주면 정밀 글자 마스크가 나오는가?

핵심 가설: SAM 3 box prompt = OCR bbox → SAM이 박스 안의 글자 ink만 segment.
잘 되면 인페인팅 마스크 quality가 글자 윤곽까지 정확해짐 (잔재 해소).

산출물:
  - slide5_orig.png        원본 렌더
  - slide5_ocr_overlay.png OCR bbox 사각형 표시
  - slide5_sam3_masks.png  SAM 3 정밀 글자 마스크 union
  - slide5_inpaint_test.png 정밀 마스크로 LaMa 인페인팅
  - report.md              관찰 + 결정
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from star_slide.inpaint.lama import inpaint_with_mask
from star_slide.ocr.paddleocr_worker import run_ocr

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_PATH = REPO_ROOT / "output/sample2/_workdir_sample2_edited/renders/slide_005.png"
OUT_DIR = Path(__file__).resolve().parent / "out"


def _device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== SAM 3 Box Prompt PoC ===")
    print(f"render: {RENDER_PATH}")
    if not RENDER_PATH.exists():
        raise SystemExit(f"renders/slide_005.png 없음 — 먼저 sample2 변환을 한 번 실행하세요")

    pil = Image.open(RENDER_PATH).convert("RGB")
    pil.save(OUT_DIR / "slide5_orig.png")
    w, h = pil.size
    print(f"image size: {w}x{h}")

    # 1) OCR
    print("\n[1] OCR...")
    t0 = time.perf_counter()
    lines = run_ocr(RENDER_PATH, lang="korean")
    t_ocr = time.perf_counter() - t0
    accepted = [ln for ln in lines if ln.confidence >= 0.3]
    print(f"  {len(accepted)} lines (conf>=0.3) in {t_ocr:.1f}s")

    # OCR overlay
    overlay = pil.copy()
    draw = ImageDraw.Draw(overlay)
    for ln in accepted:
        x, y, bw, bh = ln.bbox
        draw.rectangle([x, y, x + bw, y + bh], outline="red", width=2)
    overlay.save(OUT_DIR / "slide5_ocr_overlay.png")

    # 2) SAM 3 box prompt: 각 OCR bbox → 정밀 글자 마스크
    print("\n[2] SAM 3 (box prompt mode) ...")
    from transformers import Sam3Model, Sam3Processor

    dev = _device()
    print(f"  device: {dev}")
    t1 = time.perf_counter()
    model = Sam3Model.from_pretrained("facebook/sam3").to(dev)  # type: ignore[arg-type]
    processor = Sam3Processor.from_pretrained("facebook/sam3")
    print(f"  load: {time.perf_counter() - t1:.1f}s")

    # OCR bbox(x,y,w,h) → xyxy
    boxes_xyxy = [
        [float(ln.bbox[0]), float(ln.bbox[1]),
         float(ln.bbox[0] + ln.bbox[2]), float(ln.bbox[1] + ln.bbox[3])]
        for ln in accepted
    ]
    if not boxes_xyxy:
        print("  no OCR boxes; abort")
        return

    # 한 번의 forward로 모든 box를 prompt로 (positive=1)
    input_boxes = [boxes_xyxy]                 # batch=1
    input_boxes_labels = [[1] * len(boxes_xyxy)]

    t2 = time.perf_counter()
    inputs = processor(
        images=pil,
        input_boxes=input_boxes,
        input_boxes_labels=input_boxes_labels,
        return_tensors="pt",
    ).to(dev)
    with torch.no_grad():
        outputs = model(**inputs)
    results = processor.post_process_instance_segmentation(
        outputs,
        threshold=0.5,
        mask_threshold=0.5,
        target_sizes=inputs.get("original_sizes").tolist(),
    )[0]
    t_sam3 = time.perf_counter() - t2
    print(f"  inference: {t_sam3:.1f}s, masks={len(results['masks'])}")

    # 3) Union 마스크 시각화
    masks_t = results["masks"]
    if hasattr(masks_t, "cpu"):
        masks_np = masks_t.cpu().numpy().astype(bool)
    else:
        masks_np = np.asarray(masks_t).astype(bool)

    union = np.zeros((h, w), dtype=np.uint8)
    for m in masks_np:
        if m.shape == (h, w):
            union[m] = 255
        else:
            # 후처리 size 보존됐으나 안전장치
            from PIL.Image import fromarray
            resized = np.asarray(
                fromarray(m.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)
            )
            union[resized > 0] = 255

    Image.fromarray(union, mode="L").save(OUT_DIR / "slide5_sam3_masks.png")

    # 4) 인페인팅 비교: SAM 3 정밀 마스크 + 작은 dilate
    print("\n[3] LaMa inpaint with SAM 3 masks...")
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    union_dil = cv2.dilate(union, kernel, iterations=1).astype(np.uint8)
    mask_pil = Image.fromarray(union_dil, mode="L")
    mask_pil.save(OUT_DIR / "slide5_sam3_masks_dilated.png")

    t3 = time.perf_counter()
    inpainted = inpaint_with_mask(pil, mask_pil)
    t_inp = time.perf_counter() - t3
    inpainted.save(OUT_DIR / "slide5_inpaint_test.png")
    print(f"  inpaint: {t_inp:.1f}s")

    # 5) 보고서
    report = OUT_DIR / "report.md"
    report.write_text(
        f"""# SAM 3 Box Prompt PoC — slide 5

## 환경
- device: {dev}
- image: {w}x{h}
- OCR lines (conf>=0.3): {len(accepted)}

## 타이밍
- OCR: {t_ocr:.1f}s
- SAM 3 inference: {t_sam3:.1f}s ({len(boxes_xyxy)} box prompts)
- LaMa inpaint: {t_inp:.1f}s

## 산출물
- slide5_orig.png         원본 렌더
- slide5_ocr_overlay.png  OCR bbox 시각화
- slide5_sam3_masks.png   SAM 3 정밀 마스크 union
- slide5_sam3_masks_dilated.png  +5px dilate
- slide5_inpaint_test.png 정밀 마스크 LaMa 인페인팅 결과

## 평가 기준 (사용자 결정)
- 텍스트 잔재(글자 외곽선)가 사라졌는가?
- 게이지 그래픽이 보존됐는가?
- 시간 비용이 받아들일 만한가?

## 다음 단계
- 결과 좋으면 → orchestrator에서 sam2_auto → sam3 box-prompt 모드로 전환
- 결과 미흡하면 → text prompt 모드 ("text", "korean letter") 시도
""",
        encoding="utf-8",
    )
    print(f"\nreport: {report}")
    print("done")


if __name__ == "__main__":
    main()
