"""coords 변환 단위 테스트."""

from __future__ import annotations

from star_slide.rasterize.coords import EMU_PER_INCH, CoordTransform


class TestCoordTransform:
    def test_basic_round_trip(self) -> None:
        t = CoordTransform(
            slide_width_emu=9_144_000,
            slide_height_emu=6_858_000,
            image_width_px=1920,
            image_height_px=1080,
        )
        # 픽셀 (960, 540) — 슬라이드 중앙 → EMU 중앙
        x_emu, y_emu = t.px_to_emu(960, 540)
        assert abs(x_emu - 9_144_000 // 2) < 10
        assert abs(y_emu - 6_858_000 // 2) < 10

        # 역변환 round-trip
        x_px, y_px = t.emu_to_px(x_emu, y_emu)
        assert abs(x_px - 960) < 1
        assert abs(y_px - 540) < 1

    def test_bbox_conversion(self) -> None:
        t = CoordTransform(
            slide_width_emu=9_144_000,
            slide_height_emu=6_858_000,
            image_width_px=1920,
            image_height_px=1080,
        )
        # px (100, 50, 200, 100) — 좌상단 박스
        bbox_emu = t.px_bbox_to_emu((100, 50, 200, 100))
        assert bbox_emu[0] > 0 and bbox_emu[1] > 0
        assert bbox_emu[2] > 0 and bbox_emu[3] > 0

    def test_emu_per_inch_constant(self) -> None:
        # 1 inch = 914400 EMU
        assert EMU_PER_INCH == 914400
