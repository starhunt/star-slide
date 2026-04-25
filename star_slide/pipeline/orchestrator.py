"""파이프라인 오케스트레이터 — Phase 1 단일 프로세스 실행.

CLI `star-slide convert input.pptx -o output.pptx --report report.json` end-to-end.

단계 (PRD §7.1):
  1. 파일 검증
  2. 슬라이드 추출 (PPTX/PDF/이미지)
  3. (옵션) SAM 마스크 생성
  4. OCR (텍스트 객체 추출)
  5. PPTX 조립 (현재는 텍스트 + 원본 배경 합성)
  6. 품질 리포트 JSON 출력

Phase 1 MVP 범위:
- 텍스트 객체 → PowerPoint 텍스트박스 (편집 가능)
- 슬라이드 배경 = 원본 PNG (인페인팅은 P1-T06에서 추가)
- 도형/아이콘 → vtracer + custGeom (P1-T08에서 추가, 현재는 스킵)
- 표/차트 → 이미지 fallback
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

from star_slide.composer.inject import replace_geometry_with_custgeom
from star_slide.composer.vectorize import VectorizedShape, vectorize_shape
from star_slide.inpaint.lama import (
    _bboxes_to_mask,
    inpaint_background,
    inpaint_with_mask,
)
from star_slide.input.pptx_extractor import inspect_pptx
from star_slide.input.validator import validate
from star_slide.ocr.metrics import cer
from star_slide.ocr.paddleocr_worker import OcrLine, run_ocr
from star_slide.rasterize.coords import CoordTransform
from star_slide.rasterize.libreoffice import (
    LibreOfficeNotFoundError,
    fallback_render_from_embedded,
    render_pptx_to_pngs,
)
from star_slide.schema import (
    EditableLevel,
    JobState,
    Object,
    ObjectType,
    Project,
    Qa,
    QaReport,
    Slide,
    SlideSize,
    SourceAssets,
    TextPayload,
)
from star_slide.segmentation.classify import (
    ClassificationResult,
    MaskClass,
    classify_masks,
)
from star_slide.segmentation.sam2_auto import Sam2Result, run_sam2_auto


@dataclass(frozen=True)
class ConvertOptions:
    """convert 명령 옵션."""

    use_libreoffice: bool = True  # False면 임베드 이미지 직접 추출
    ocr_min_confidence: float = 0.7  # textbox 생성 임계 (보수적)
    inpaint: bool = True  # P1-T06: LaMa로 텍스트 자리 배경 복원
    inpaint_padding_px: int = 12
    inpaint_dilate_px: int = 7
    inpaint_min_confidence: float = 0.3  # 마스크에 포함할 OCR 임계 (관대)
    vectorize_shapes: bool = True  # P1-T08: vtracer로 native shape (custGeom) 변환
    use_sam: bool = True  # P1-T03/T04: SAM 객체 분리 + SAM 마스크 기반 인페인팅
    sam_text_dilate_px: int = 3  # SAM TEXT 마스크용 dilate (정밀해서 작게)
    sam_pred_iou_thresh: float = 0.86
    sam_stability_thresh: float = 0.92
    sam_points_per_side: int = 32
    sam_max_masks: int = 200
    vectorize_shape_min_area_ratio: float = 0.001  # vtracer 입력 최소 면적 (0.1%)
    vectorize_shape_max_area_ratio: float = 0.15  # 너무 큰 SHAPE은 카드 배경 → vector 부적합


def convert(
    input_path: Path,
    output_path: Path,
    *,
    workdir: Path | None = None,
    options: ConvertOptions | None = None,
    progress: object = None,
) -> tuple[Project, QaReport]:
    """input PPTX/PDF/이미지 → 편집 가능 PPTX + QaReport.

    Args:
        input_path: 입력 파일
        output_path: 출력 PPTX 경로
        workdir: 중간 산출물(렌더 PNG, 마스크 등) 저장 위치. None이면 output 옆에 자동.
        options: 변환 옵션
        progress: rich.progress 또는 None (단순 print)
    """
    options = options or ConvertOptions()
    workdir = workdir or output_path.parent / f"_workdir_{output_path.stem}"
    workdir.mkdir(parents=True, exist_ok=True)

    project = Project(
        id=f"prj_{uuid.uuid4().hex[:8]}",
        source_file=input_path,
        source_kind=validate(input_path),
        state=JobState.QUEUED,
    )

    # Phase 1은 PPTX만 지원, PDF/이미지는 후속
    if project.source_kind != "pptx":
        raise NotImplementedError(
            f"Phase 1 MVP는 PPTX만 지원. PDF/이미지는 후속 phase. (kind={project.source_kind})"
        )

    project.state = JobState.RASTERIZING

    # 1. 슬라이드 추출 + 렌더링
    slide_w_emu, slide_h_emu, infos = inspect_pptx(input_path)

    render_dir = workdir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)

    if options.use_libreoffice:
        try:
            png_paths = render_pptx_to_pngs(input_path, render_dir)
        except LibreOfficeNotFoundError:
            png_paths = fallback_render_from_embedded(input_path, render_dir)
    else:
        png_paths = fallback_render_from_embedded(input_path, render_dir)

    if len(png_paths) != len(infos):
        # 렌더 슬라이드 수와 PPTX 슬라이드 수 다름 → 짧은 쪽 기준
        n = min(len(png_paths), len(infos))
        png_paths = png_paths[:n]
        infos = infos[:n]

    # 2. 슬라이드별 OCR + 객체 생성
    project.state = JobState.DETECTING

    qa_warnings: list[str] = []
    n_text_total = 0
    n_text_editable = 0
    failed_slide_ids: list[str] = []

    for idx, (_info, png_path) in enumerate(zip(infos, png_paths, strict=False), start=1):
        try:
            with Image.open(png_path) as im:
                im_w, im_h = im.size
        except Exception as exc:
            failed_slide_ids.append(f"sld_{idx:03d}")
            qa_warnings.append(f"slide {idx} 이미지 로드 실패: {exc}")
            continue

        coord = CoordTransform(
            slide_width_emu=slide_w_emu,
            slide_height_emu=slide_h_emu,
            image_width_px=im_w,
            image_height_px=im_h,
        )

        slide_size = SlideSize(
            width_emu=slide_w_emu,
            height_emu=slide_h_emu,
            width_px=im_w,
            height_px=im_h,
            ratio=_ratio_str(slide_w_emu, slide_h_emu),
        )

        # OCR
        try:
            ocr_lines = run_ocr(png_path, lang="korean")
        except Exception as exc:
            qa_warnings.append(f"slide {idx} OCR 실패: {exc}")
            ocr_lines = []

        accepted_lines = [ln for ln in ocr_lines if ln.confidence >= options.ocr_min_confidence]
        # 인페인팅용은 더 관대한 임계 (작은 영문 라벨까지 지움)
        mask_lines = [
            ln for ln in ocr_lines if ln.confidence >= options.inpaint_min_confidence
        ]

        # SAM 객체 분리 (옵션). 실패해도 인페인팅은 계속 (OCR bbox fallback).
        sam_result: Sam2Result | None = None
        classification: ClassificationResult | None = None
        if options.use_sam:
            try:
                sam_result = run_sam2_auto(
                    png_path,
                    pred_iou_thresh=options.sam_pred_iou_thresh,
                    stability_score_thresh=options.sam_stability_thresh,
                    points_per_side=options.sam_points_per_side,
                    max_masks=options.sam_max_masks,
                )
                classification = classify_masks(
                    sam_result.masks,
                    mask_lines,
                    image_size=(im_w, im_h),
                )
            except Exception as exc:
                qa_warnings.append(f"slide {idx} SAM 실패 (OCR bbox fallback): {exc}")
                sam_result = None
                classification = None

        # 인페인팅: SAM TEXT 마스크 우선 + (SAM이 못 잡은) OCR fallback
        background_path = png_path
        if options.inpaint and mask_lines:
            try:
                inpainted = _inpaint_slide(
                    png_path=png_path,
                    image_size=(im_w, im_h),
                    mask_lines=mask_lines,
                    classification=classification,
                    options=options,
                )
                inpaint_dir = workdir / "inpainted"
                inpaint_dir.mkdir(parents=True, exist_ok=True)
                background_path = inpaint_dir / png_path.name
                inpainted.save(background_path)
            except Exception as exc:
                qa_warnings.append(f"slide {idx} 인페인팅 실패 (원본 사용): {exc}")
                background_path = png_path

        slide = Slide(
            id=f"sld_{idx:03d}",
            page_no=idx,
            size=slide_size,
            render_path=png_path,
            background_path=background_path,
        )

        for k, line in enumerate(accepted_lines):
            n_text_total += 1
            n_text_editable += 1

            bbox_px = line.bbox
            bbox_emu = coord.px_bbox_to_emu(bbox_px)

            obj = Object(
                id=f"{slide.id}_obj_{k:03d}",
                type=ObjectType.TEXT,
                bbox_px=bbox_px,
                bbox_emu=bbox_emu,
                confidence=line.confidence,
                editable_level=EditableLevel.NATIVE,
                source=SourceAssets(crop_path=None, detector="paddleocr_ppocrv5"),
                qa=Qa(),
                text=TextPayload(
                    content=line.text,
                    confidence=line.confidence,
                ),
            )
            slide.objects.append(obj)

        # SAM SHAPE → vtracer → custGeom (P1-T08)
        if classification is not None:
            shape_offset = len(slide.objects)
            slide_pil_for_vec: Image.Image | None = None
            shape_min_px = options.vectorize_shape_min_area_ratio * im_w * im_h
            shape_max_px = options.vectorize_shape_max_area_ratio * im_w * im_h
            for j, cm in enumerate(classification.classified):
                if cm.cls != MaskClass.SHAPE:
                    continue

                vec: VectorizedShape | None = None
                if (
                    options.vectorize_shapes
                    and shape_min_px <= cm.mask.area <= shape_max_px
                ):
                    if slide_pil_for_vec is None:
                        slide_pil_for_vec = Image.open(png_path).convert("RGB")
                    try:
                        vec = vectorize_shape(slide_pil_for_vec, cm.mask.segmentation)
                    except Exception as exc:
                        qa_warnings.append(
                            f"slide {idx} shape {j} vectorize 실패: {exc}"
                        )
                        vec = None

                bbox_px = vec.bbox if vec is not None else cm.mask.bbox
                bbox_emu = coord.px_bbox_to_emu(bbox_px)
                shape_obj = Object(
                    id=f"{slide.id}_shape_{shape_offset + j:03d}",
                    type=ObjectType.SHAPE,
                    bbox_px=bbox_px,
                    bbox_emu=bbox_emu,
                    confidence=cm.mask.score,
                    editable_level=(
                        EditableLevel.VECTOR if vec is not None else EditableLevel.RASTER
                    ),
                    source=SourceAssets(detector="sam2.1_hiera_large"),
                    qa=Qa(),
                    shape=vec.payload if vec is not None else None,
                )
                slide.objects.append(shape_obj)

        project.slides.append(slide)

    # 3. PPTX 조립
    project.state = JobState.RECONSTRUCTING
    _compose_pptx(project, output_path)

    # 4. 품질 리포트 — NATIVE(텍스트박스) + VECTOR(custGeom 도형) 모두 편집 가능으로 카운트
    project.state = JobState.READY
    n_objects = sum(len(s.objects) for s in project.slides)
    editable_levels = {EditableLevel.NATIVE, EditableLevel.VECTOR}
    avg_editable = sum(
        1 for s in project.slides for o in s.objects if o.editable_level in editable_levels
    ) / max(1, n_objects)
    report = QaReport(
        project_id=project.id,
        n_slides=len(project.slides),
        n_objects=n_objects,
        avg_editable_ratio=avg_editable,
        text_objects_editable=n_text_editable,
        text_objects_total=n_text_total,
        failed_slide_ids=failed_slide_ids,
        warnings=qa_warnings,
    )

    return project, report


def _ratio_str(w_emu: int, h_emu: int) -> str:
    if h_emu == 0:
        return "?"
    r = w_emu / h_emu
    if abs(r - 16 / 9) < 0.01:
        return "16:9"
    if abs(r - 4 / 3) < 0.01:
        return "4:3"
    return f"{r:.2f}"


def _compose_pptx(project: Project, output_path: Path) -> None:
    """python-pptx로 결과 PPTX 조립.

    각 슬라이드에 대해:
    - 슬라이드 배경 = 원본 PNG (전체 슬라이드 영역)
    - 텍스트 객체 → 투명 텍스트박스 (편집 가능)

    Phase 1 단순화: 모든 텍스트박스는 흰 배경 텍스트 위에 덮어 그리지 않고,
    원본 PNG를 배경으로 두고 그 위에 OCR 텍스트박스를 투명하게 배치.
    Phase 2에서 인페인팅 + 텍스트박스로 교체.
    """
    if not project.slides:
        raise ValueError("프로젝트에 슬라이드가 없습니다")

    first = project.slides[0]
    prs = Presentation()
    prs.slide_width = Emu(first.size.width_emu)
    prs.slide_height = Emu(first.size.height_emu)

    blank_layout = prs.slide_layouts[6]

    for slide_data in project.slides:
        slide = prs.slides.add_slide(blank_layout)

        # 배경 이미지 (인페인팅된 게 있으면 우선, 없으면 원본)
        bg_path = slide_data.background_path or slide_data.render_path
        slide.shapes.add_picture(
            str(bg_path),
            Emu(0),
            Emu(0),
            width=Emu(slide_data.size.width_emu),
            height=Emu(slide_data.size.height_emu),
        )

        # 도형 (SHAPE) — vtracer custGeom 변환된 native shape
        for obj in slide_data.objects:
            if (
                obj.type != ObjectType.SHAPE
                or obj.shape is None
                or obj.bbox_emu is None
                or obj.shape.custgeom_xml is None
            ):
                continue
            x, y, w, h = obj.bbox_emu
            if w <= 0 or h <= 0:
                continue
            sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(x), Emu(y), Emu(w), Emu(h))
            try:
                replace_geometry_with_custgeom(sh, obj.shape.custgeom_xml)
            except Exception:
                continue
            if obj.shape.fill:
                with contextlib.suppress(Exception):
                    rgb = obj.shape.fill.lstrip("#")
                    sh.fill.solid()
                    sh.fill.fore_color.rgb = RGBColor.from_string(rgb)  # type: ignore[no-untyped-call]
            with contextlib.suppress(Exception):
                sh.line.fill.background()

        # 텍스트 객체
        for obj in slide_data.objects:
            if obj.type != ObjectType.TEXT or obj.text is None or obj.bbox_emu is None:
                continue
            x, y, w, h = obj.bbox_emu
            tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
            tf = tb.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = obj.text.content
            if obj.text.font_size_pt:
                run.font.size = Pt(obj.text.font_size_pt)
            # 배경 PNG와 겹치지 않도록 텍스트박스 자체는 채움 없음 (기본)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))


def _inpaint_slide(
    *,
    png_path: Path,
    image_size: tuple[int, int],
    mask_lines: list[OcrLine],
    classification: ClassificationResult | None,
    options: ConvertOptions,
) -> Image.Image:
    """슬라이드 1장 인페인팅.

    전략:
      - 인페인팅 영역은 OCR 사각 bbox + padding (이미 잘 작동, proven).
      - SAM의 가치는 *도형 보호*: SHAPE 마스크 영역은 인페인팅 대상에서 제외.
        → 게이지/아이콘이 OCR bbox와 겹쳐도 지워지지 않음.
      - SAM TEXT 마스크는 안티앨리어싱 가장자리가 남는 문제로 인페인팅에 직접 쓰지 않음.
    """
    bboxes = [ln.bbox for ln in mask_lines]
    if classification is None:
        # SAM 미사용 → 기존 경로
        result = inpaint_background(
            png_path,
            bboxes,
            padding=options.inpaint_padding_px,
            dilate_kernel=options.inpaint_dilate_px,
        )
        if isinstance(result, tuple):
            result = result[0]
        return result

    pil = Image.open(png_path).convert("RGB")

    # 1. OCR 기반 인페인팅 마스크 (기존 방식, 잘 작동)
    ocr_mask_pil = _bboxes_to_mask(
        bboxes,
        image_size=image_size,
        padding=options.inpaint_padding_px,
        dilate_kernel=options.inpaint_dilate_px,
    )
    ocr_mask_arr = np.asarray(ocr_mask_pil.convert("L"), dtype=np.uint8)

    # 2. SHAPE 보호 마스크: SAM이 "도형"으로 분류한 픽셀 중,
    #    OCR과 (실질적으로) 겹치지 않는 것만 보호한다.
    #    → 게이지/아이콘은 살리지만, OCR bbox 내부의 글자 획 잔재는 보호 X.
    shape_segs: list[NDArray[np.bool_]] = []
    w, h = image_size
    slide_area = float(w * h) if w > 0 and h > 0 else 1.0
    shape_max_area_ratio = 0.15
    shape_overlap_with_ocr_max = 0.05  # OCR과의 픽셀 겹침이 5% 이상이면 텍스트 잔재로 의심 → 보호 X

    for c in classification.classified:
        if c.cls != MaskClass.SHAPE:
            continue
        if c.mask.area / slide_area > shape_max_area_ratio:
            continue
        seg = c.mask.segmentation
        if seg.shape != (h, w):
            continue
        overlap = int(np.logical_and(seg, ocr_mask_arr > 0).sum())
        if c.mask.area > 0 and overlap / c.mask.area > shape_overlap_with_ocr_max:
            continue
        shape_segs.append(seg)

    if shape_segs:
        shape_arr = np.zeros((h, w), dtype=np.uint8)
        for seg in shape_segs:
            shape_arr[seg] = 255
        final_arr = ocr_mask_arr.copy()
        final_arr[shape_arr > 0] = 0
    else:
        final_arr = ocr_mask_arr

    final_mask = Image.fromarray(final_arr.astype(np.uint8), mode="L")
    return inpaint_with_mask(pil, final_mask)


def quick_self_check_cer(predicted: str, ground_truth: str) -> float:
    """간단한 CER 측정 헬퍼 (CLI report 출력용)."""
    return cer(predicted, ground_truth)
