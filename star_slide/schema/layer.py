"""Layer Schema (중간 표현) — PRD §8 핵심 데이터 모델.

모든 파이프라인 단계가 공유하는 단일 진실 출처.
PPTX/SVG/Web Editor/JSON이 모두 이 스키마 기반.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from star_slide.schema.enums import (
    ChartLevel,
    EditableLevel,
    JobState,
    ObjectType,
    QaStatus,
    TableLevel,
)

# bbox 형식: (x, y, w, h) — px 또는 EMU


class SlideSize(BaseModel):
    """슬라이드 크기 (EMU + px)."""

    width_emu: int
    height_emu: int
    width_px: int
    height_px: int
    ratio: str = "16:9"


class FontCandidate(BaseModel):
    """한글 폰트 매칭 후보 (PRD §10.2 + ADR-008)."""

    family: str
    weight: int = 400
    score: float = Field(0.0, ge=0.0, le=1.0)


class TextPayload(BaseModel):
    """텍스트 객체 페이로드."""

    content: str
    language: str = "ko"
    font_candidates: list[FontCandidate] = Field(default_factory=list)
    font_chosen: str | None = None
    font_size_pt: float | None = None
    color: str = "#000000"  # hex RGB
    align: str = "left"  # left | center | right
    line_height: float = 1.2
    confidence: float = Field(1.0, ge=0.0, le=1.0)


class ShapePayload(BaseModel):
    """도형/아이콘 페이로드 (custGeom 또는 fallback)."""

    geom_type: str  # custGeom | preset | emf | png
    svg_path_d: str | None = None
    custgeom_xml: str | None = None
    preset_name: str | None = None  # python-pptx MSO_SHAPE 이름
    fill: str | None = None  # hex
    stroke: str | None = None  # hex
    stroke_width_pt: float = 1.0


class TableCell(BaseModel):
    """표 셀."""

    row: int
    col: int
    text: str = ""
    bbox: tuple[float, float, float, float] | None = None
    rowspan: int = 1
    colspan: int = 1


class TablePayload(BaseModel):
    """표 페이로드."""

    rows: int
    cols: int
    cells: list[TableCell] = Field(default_factory=list)
    recovery_level: TableLevel = TableLevel.T0


class ChartPayload(BaseModel):
    """차트 페이로드."""

    chart_type: str = "unknown"  # bar | line | pie | scatter | unknown
    recovery_level: ChartLevel = ChartLevel.C0
    data_inferred: list[list[str]] | None = None  # rows of cells (CSV-like)


class SourceAssets(BaseModel):
    """객체 원본 자산 경로."""

    mask_path: Path | None = None
    crop_path: Path | None = None
    detector: str = "sam2.1"
    fallback_image_path: Path | None = None


class Qa(BaseModel):
    """객체 검수 메타."""

    status: QaStatus = QaStatus.PENDING
    warnings: list[str] = Field(default_factory=list)


class Object(BaseModel):
    """슬라이드 객체 (PRD §8 단일 객체 표현)."""

    model_config = ConfigDict(use_enum_values=False)

    id: str
    type: ObjectType
    subtype: str | None = None  # title, body, caption 등
    bbox_emu: tuple[int, int, int, int] | None = None
    bbox_px: tuple[float, float, float, float]
    rotation: float = 0.0
    z_index: int = 0
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    editable_level: EditableLevel = EditableLevel.UNCERTAIN

    source: SourceAssets = Field(default_factory=SourceAssets)
    qa: Qa = Field(default_factory=Qa)

    # 타입별 페이로드 (해당 타입만 채워짐)
    text: TextPayload | None = None
    shape: ShapePayload | None = None
    table: TablePayload | None = None
    chart: ChartPayload | None = None


class Slide(BaseModel):
    """단일 슬라이드."""

    id: str
    page_no: int
    size: SlideSize
    background_path: Path | None = None  # 인페인팅 결과
    render_path: Path  # 원본 슬라이드 렌더 PNG
    thumbnail_path: Path | None = None
    objects: list[Object] = Field(default_factory=list)


class Project(BaseModel):
    """변환 프로젝트 (한 입력 파일 = 한 프로젝트)."""

    id: str
    source_file: Path
    source_kind: str  # pptx | pdf | image
    created_at: datetime = Field(default_factory=datetime.now)
    state: JobState = JobState.QUEUED
    slides: list[Slide] = Field(default_factory=list)


class QaReport(BaseModel):
    """프로젝트 단위 품질 리포트 (PRD §11.3)."""

    project_id: str
    n_slides: int
    n_objects: int
    avg_editable_ratio: float = 0.0
    avg_ssim: float | None = None
    fallback_object_ids: list[str] = Field(default_factory=list)
    text_objects_editable: int = 0
    text_objects_total: int = 0
    failed_slide_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
