"""H2 검증용 SVG path 데이터셋 — 단순 도형 10종 + 추가 아이콘.

좌표 단위는 임의(파서가 자동 정규화). PowerPoint 호환성 핵심:
- M/L/C/Q/Z만 사용 (Arc는 별도 변환 필요, PoC에서는 chord 근사)
- 음수 좌표 가능 (변환기에서 bbox 정규화)
"""

from __future__ import annotations

# (이름, SVG path d, 설명)
SIMPLE_SHAPES: list[tuple[str, str, str]] = [
    (
        "rectangle",
        "M 0 0 L 100 0 L 100 60 L 0 60 Z",
        "axis-aligned 사각형",
    ),
    (
        "rounded_rectangle",
        "M 10 0 L 90 0 Q 100 0 100 10 L 100 50 Q 100 60 90 60 L 10 60 Q 0 60 0 50 L 0 10 Q 0 0 10 0 Z",
        "라운드 사각형 (Q quadratic)",
    ),
    (
        "triangle",
        "M 50 0 L 100 100 L 0 100 Z",
        "정삼각형",
    ),
    (
        "diamond",
        "M 50 0 L 100 50 L 50 100 L 0 50 Z",
        "마름모",
    ),
    (
        "pentagon",
        "M 50 0 L 100 38 L 81 100 L 19 100 L 0 38 Z",
        "오각형",
    ),
    (
        "star_5pt",
        "M 50 0 L 61 35 L 100 35 L 69 57 L 80 91 L 50 70 L 20 91 L 31 57 L 0 35 L 39 35 Z",
        "5각 별",
    ),
    (
        "arrow_right",
        "M 0 30 L 70 30 L 70 10 L 100 50 L 70 90 L 70 70 L 0 70 Z",
        "오른쪽 화살표",
    ),
    (
        "checkmark",
        "M 10 50 L 40 80 L 90 20 L 80 10 L 40 60 L 20 40 Z",
        "체크 표시",
    ),
    (
        "speech_bubble",
        "M 10 0 L 90 0 Q 100 0 100 10 L 100 60 Q 100 70 90 70 L 50 70 L 30 90 L 30 70 L 10 70 Q 0 70 0 60 L 0 10 Q 0 0 10 0 Z",
        "말풍선 (Q + 꼬리)",
    ),
    (
        "circle_quad",
        # 원을 4개 quadratic bezier로 근사
        "M 50 0 Q 100 0 100 50 Q 100 100 50 100 Q 0 100 0 50 Q 0 0 50 0 Z",
        "원 (4 quad bezier 근사)",
    ),
]


# Cubic bezier 사용 도형 (path 복잡도 ↑ 테스트)
CUBIC_SHAPES: list[tuple[str, str, str]] = [
    (
        "heart",
        "M 50 30 C 50 0 100 0 100 30 C 100 60 50 100 50 100 C 50 100 0 60 0 30 C 0 0 50 0 50 30 Z",
        "하트 (cubic bezier)",
    ),
    (
        "leaf",
        "M 0 50 C 25 0 75 0 100 50 C 75 100 25 100 0 50 Z",
        "잎사귀 모양",
    ),
    (
        "wave",
        "M 0 50 C 25 0 50 100 75 50 C 87 25 100 50 100 50 L 100 100 L 0 100 Z",
        "웨이브 패턴",
    ),
]


def all_shapes() -> list[tuple[str, str, str]]:
    return SIMPLE_SHAPES + CUBIC_SHAPES
