"""OCR 메트릭 단위 테스트."""

from __future__ import annotations

import pytest

from star_slide.ocr.metrics import cer, levenshtein, wer


class TestLevenshtein:
    def test_identical(self) -> None:
        assert levenshtein("hello", "hello") == 0

    def test_substitution(self) -> None:
        assert levenshtein("kitten", "sitten") == 1

    def test_insertion(self) -> None:
        assert levenshtein("cat", "cats") == 1

    def test_deletion(self) -> None:
        assert levenshtein("cats", "cat") == 1

    def test_korean(self) -> None:
        assert levenshtein("안녕하세요", "안녕하세요") == 0
        assert levenshtein("안녕하세요", "안녕하세묘") == 1

    def test_empty(self) -> None:
        assert levenshtein("", "") == 0
        assert levenshtein("abc", "") == 3
        assert levenshtein("", "abc") == 3


class TestCer:
    def test_perfect(self) -> None:
        assert cer("안녕하세요", "안녕하세요") == 0.0

    def test_one_char_off(self) -> None:
        # 1/5 = 0.2
        assert abs(cer("안녕하세요", "안녕하세묘") - 0.2) < 1e-9

    def test_whitespace_ignored(self) -> None:
        assert cer("안녕\n하세요", "안녕하세요") == 0.0
        assert cer("hello world", "helloworld") == 0.0

    def test_whitespace_strict(self) -> None:
        # ignore_whitespace=False면 공백 차이가 카운트됨
        result = cer("hello world", "helloworld", ignore_whitespace=False)
        assert result > 0.0

    def test_empty_gt(self) -> None:
        assert cer("", "") == 0.0
        assert cer("predicted", "") == 1.0


class TestWer:
    def test_perfect(self) -> None:
        assert wer("hello world", "hello world") == 0.0

    def test_word_substitution(self) -> None:
        # 1/2
        assert abs(wer("hello world", "hello there") - 0.5) < 1e-9

    @pytest.mark.parametrize(
        "pred,gt,expected",
        [
            ("AI 시스템", "AI 시스템", 0.0),
            ("AI 시스템", "AI 모델", 0.5),
        ],
    )
    def test_korean_words(self, pred: str, gt: str, expected: float) -> None:
        assert abs(wer(pred, gt) - expected) < 1e-9
