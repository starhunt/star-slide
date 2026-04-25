"""text_attributes 단위 테스트."""

from __future__ import annotations

import numpy as np
from PIL import Image

from star_slide.ocr.text_attributes import (
    detect_korean,
    estimate_font_color,
    estimate_font_size_pt,
)


class TestKoreanDetection:
    def test_korean_syllable(self) -> None:
        assert detect_korean("안녕")
        assert detect_korean("안 녕 hello")

    def test_korean_jamo(self) -> None:
        assert detect_korean("가")

    def test_no_korean(self) -> None:
        assert not detect_korean("hello world 123")
        assert not detect_korean("$0.15")


class TestFontSizeEstimate:
    def test_korean_default(self) -> None:
        # 30px 마스크 → ~26.5 pt (em=30/0.85=35.3, pt=35.3*72/96=26.4)
        pt = estimate_font_size_pt(30, is_korean=True)
        assert 25.0 < pt < 28.0

    def test_latin_smaller_ratio(self) -> None:
        pt_kr = estimate_font_size_pt(30, is_korean=True)
        pt_en = estimate_font_size_pt(30, is_korean=False)
        # 영문 ratio가 더 작음 → em 더 큼 → pt 더 큼
        assert pt_en > pt_kr

    def test_zero_height(self) -> None:
        assert estimate_font_size_pt(0) == 0.0


class TestFontColor:
    def _img(self, fill: tuple[int, int, int], size: tuple[int, int] = (40, 40)) -> Image.Image:
        return Image.new("RGB", size, fill)

    def _mask(self, size: tuple[int, int] = (40, 40)) -> np.ndarray:
        m = np.zeros((size[1], size[0]), dtype=bool)
        m[10:30, 10:30] = True  # 중앙 20x20
        return m

    def test_dark_text(self) -> None:
        img = self._img((20, 20, 20))  # 거의 검정
        mask = self._mask()
        color = estimate_font_color(img, mask)
        assert color is not None
        assert color.startswith("#")
        # 양자화로 #181818 또는 비슷
        assert color in ("#101010", "#303030", "#202020", "#181818")

    def test_no_mask(self) -> None:
        img = self._img((100, 100, 100))
        mask = np.zeros((40, 40), dtype=bool)
        assert estimate_font_color(img, mask) is None

    def test_blue_text_on_white(self) -> None:
        # 파란 글자 영역 + 흰 배경. mask는 글자만 가리킴 (위에서 모두 dark blue)
        img = Image.new("RGB", (40, 40), (255, 255, 255))
        arr = np.asarray(img).copy()
        arr[10:30, 10:30] = (10, 30, 200)  # dark blue
        img = Image.fromarray(arr)
        mask = self._mask()
        color = estimate_font_color(img, mask)
        assert color is not None
        # 양자화로 비슷한 dark blue 영역
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        assert b > 150 and r < 64 and g < 64
