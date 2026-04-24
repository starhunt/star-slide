"""환경 변수 기반 설정.

Pydantic Settings로 .env 자동 로드. 모든 설정의 단일 출처.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DeviceType = Literal["cuda", "mps", "cpu"]
EnvType = Literal["development", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STAR_SLIDE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: EnvType = "development"
    log_level: str = "INFO"
    data_dir: Path = Field(default=Path("./data"))
    storage_dir: Path = Field(default=Path("./storage"))

    device: DeviceType = "cpu"
    gpu_index: int = 0

    sam_model: str = "sam3.1"
    sam_weights: Path | None = None
    ocr_model: str = "paddleocr_ppocrv5_korean"
    inpaint_model: str = "lama"

    disable_external_api: bool = True
    enable_vlm_classify: bool = False
    enable_gpt_inpaint: bool = False

    db_url: str | None = None
    redis_url: str | None = None


def get_settings() -> Settings:
    """싱글톤 설정 인스턴스."""
    return _settings


_settings = Settings()
