"""pytest 공유 fixture.

Phase 0에서는 최소한의 골격만 — Phase 1부터 샘플셋 fixture 추가.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project_root() -> Path:
    """프로젝트 루트 경로."""
    return PROJECT_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    """테스트 fixture 디렉토리."""
    return PROJECT_ROOT / "tests" / "fixtures"
