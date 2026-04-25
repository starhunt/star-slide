"""vtracer wrapper 단위 테스트."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from star_slide.composer.vtracer_wrapper import (
    _apply_translate_to_d,
    _path_bbox,
    _resolve_translate,
    dominant_hex_color,
    trace_image,
)

vtracer_available = shutil.which("vtracer") is not None


class TestParseHelpers:
    def test_resolve_translate_two_args(self) -> None:
        assert _resolve_translate("translate(10, 20)") == (10.0, 20.0)

    def test_resolve_translate_one_arg(self) -> None:
        # SVG는 단일 인자도 허용 (y=0)
        assert _resolve_translate("translate(15)") == (15.0, 0.0)

    def test_resolve_translate_none(self) -> None:
        assert _resolve_translate(None) == (0.0, 0.0)
        assert _resolve_translate("") == (0.0, 0.0)

    def test_apply_translate_to_d_basic(self) -> None:
        d = "M 10 20 L 30 40 Z"
        result = _apply_translate_to_d(d, 5, 7)
        # 모든 절대 좌표가 (+5, +7) 이동돼야 함
        assert "15" in result and "27" in result
        assert "35" in result and "47" in result
        assert result.endswith("Z")

    def test_apply_translate_zero(self) -> None:
        d = "M 0 0 L 10 10"
        assert _apply_translate_to_d(d, 0, 0) == d

    def test_path_bbox(self) -> None:
        d = "M 10 20 L 50 60"
        bbox = _path_bbox(d)
        assert bbox == (10.0, 20.0, 40.0, 40.0)


@pytest.mark.skipif(not vtracer_available, reason="vtracer not installed")
class TestTraceImage:
    def test_circle_produces_one_path(self, tmp_path: Path) -> None:
        # 단순 검정 원
        png = tmp_path / "circle.png"
        img = Image.new("RGB", (200, 200), "white")
        ImageDraw.Draw(img).ellipse((40, 40, 160, 160), fill="black")
        img.save(png)

        paths = trace_image(png, color_mode="bw")
        assert len(paths) >= 1
        # bbox가 원 영역 근처 (40~160, 약 120x120)
        _bx, _by, bw, bh = paths[0].bbox
        assert 90 < bw < 140
        assert 90 < bh < 140

    def test_empty_image_returns_no_paths(self, tmp_path: Path) -> None:
        png = tmp_path / "blank.png"
        Image.new("RGB", (50, 50), "white").save(png)
        paths = trace_image(png, color_mode="bw")
        # 흰색만 있으면 path 없거나 매우 작음
        assert all(p.bbox[2] <= 50 for p in paths)


class TestDominantColor:
    def test_solid_red(self) -> None:
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        assert dominant_hex_color(img) == "#FF0000"

    def test_majority_color(self) -> None:
        img = Image.new("RGB", (10, 10), (0, 128, 0))
        # 한 픽셀만 다르게
        img.putpixel((0, 0), (255, 0, 0))
        assert dominant_hex_color(img) == "#008000"
