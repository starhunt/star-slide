"""Layer Schema enum 정의 (PRD §8.1, §8.2)."""

from __future__ import annotations

from enum import StrEnum


class ObjectType(StrEnum):
    """슬라이드 객체 타입 (PRD §8.1)."""

    BACKGROUND = "background"
    TEXT = "text"
    SHAPE = "shape"
    ICON = "icon"
    PHOTO = "photo"
    TABLE = "table"
    CHART = "chart"
    EQUATION = "equation"
    DECORATION = "decoration"
    UNKNOWN = "unknown"


class EditableLevel(StrEnum):
    """편집 가능도 (PRD §8.2)."""

    NATIVE = "native"  # PowerPoint 객체로 직접 편집 (녹색)
    VECTOR = "vector"  # SVG/path 편집 (파랑)
    RASTER = "raster"  # 이미지만 편집 (회색)
    UNCERTAIN = "uncertain"  # 신뢰도 낮음 (노랑)
    FAILED = "failed"  # 분석 실패 (빨강)


class QaStatus(StrEnum):
    """객체 검수 상태."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class JobState(StrEnum):
    """작업 상태 머신 (PRD §13.3)."""

    QUEUED = "queued"
    RASTERIZING = "rasterizing"
    DETECTING = "detecting"
    RECONSTRUCTING = "reconstructing"
    READY = "ready"
    FAILED = "failed"
    EXPORTING = "exporting"
    EXPORTED = "exported"
    EXPORT_FAILED = "export_failed"


class TableLevel(StrEnum):
    """표 복원 레벨 (PRD §10.4)."""

    T0 = "T0"  # image fallback
    T1 = "T1"  # overlay text
    T2 = "T2"  # grouped shapes
    T3 = "T3"  # native PPT table


class ChartLevel(StrEnum):
    """차트 복원 레벨 (PRD §10.4)."""

    C0 = "C0"  # image fallback
    C1 = "C1"  # 라벨 OCR
    C2 = "C2"  # grouped shape chart
    C3 = "C3"  # 추정 데이터 테이블
    C4 = "C4"  # native PowerPoint chart
