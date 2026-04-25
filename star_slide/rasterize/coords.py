"""EMU ↔ pixel 좌표 변환 (PRD §6.2 FR-010).

EMU(English Metric Unit): 914,400 EMU = 1 inch.
"""

from __future__ import annotations

from dataclasses import dataclass

EMU_PER_INCH = 914400
EMU_PER_PT = 12700


@dataclass(frozen=True)
class CoordTransform:
    """슬라이드 EMU 좌표계와 렌더 PNG px 좌표계 사이의 매핑."""

    slide_width_emu: int
    slide_height_emu: int
    image_width_px: int
    image_height_px: int

    @property
    def emu_per_px_x(self) -> float:
        return self.slide_width_emu / self.image_width_px

    @property
    def emu_per_px_y(self) -> float:
        return self.slide_height_emu / self.image_height_px

    def px_to_emu(self, x: float, y: float) -> tuple[int, int]:
        return (
            round(x * self.emu_per_px_x),
            round(y * self.emu_per_px_y),
        )

    def emu_to_px(self, x_emu: int, y_emu: int) -> tuple[float, float]:
        return (
            x_emu / self.emu_per_px_x,
            y_emu / self.emu_per_px_y,
        )

    def px_bbox_to_emu(self, bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        x, y, w, h = bbox
        x_emu, y_emu = self.px_to_emu(x, y)
        x2_emu, y2_emu = self.px_to_emu(x + w, y + h)
        return (x_emu, y_emu, x2_emu - x_emu, y2_emu - y_emu)
