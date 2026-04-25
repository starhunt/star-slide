"""Vision LLM 출력 JSON 스키마 (pydantic).

모든 요소는 슬라이드 픽셀 좌표 기준. orchestrator에서 EMU로 변환.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VisionBbox(BaseModel):
    """픽셀 좌표 bbox (x, y, w, h)."""

    x: float
    y: float
    w: float
    h: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)


class VisionElement(BaseModel):
    """슬라이드 요소 — text/shape/path/table/image."""

    type: Literal["text", "shape", "path", "table", "image"]
    bbox: VisionBbox

    # text 전용
    content: str | None = None
    color: str | None = None  # '#RRGGBB'
    font_size_pt: float | None = None
    weight: Literal["normal", "bold"] = "normal"
    italic: bool = False
    align: Literal["left", "center", "right"] = "left"
    language: Literal["ko", "en", "mixed"] = "ko"
    rotation_deg: float = 0.0

    # shape/path 전용
    subtype: str | None = None  # rectangle/ellipse/rounded_rectangle/arrow/line/polygon
    fill: str | None = None  # '#RRGGBB' or None for no fill
    stroke: str | None = None  # '#RRGGBB' or None for no stroke
    stroke_width_pt: float = 0.0
    corner_radius_pt: float = 0.0

    # path 전용
    description: str | None = None  # vtracer 입력 또는 placeholder 설명

    # table 전용
    rows: int = 0
    cols: int = 0
    cells: list[VisionTableCell] = Field(default_factory=list)
    border_color: str | None = None
    border_width_pt: float = 0.0


class VisionTableCell(BaseModel):
    row: int
    col: int
    text: str = ""
    bbox: VisionBbox | None = None
    fill: str | None = None
    color: str | None = None  # text color
    rowspan: int = 1
    colspan: int = 1


class VisionSlide(BaseModel):
    """vision LLM 출력 — 한 슬라이드."""

    image_size: tuple[int, int]  # (W, H)
    elements: list[VisionElement] = Field(default_factory=list)


# pydantic forward ref 해소
VisionElement.model_rebuild()
