"""환경 변수 기반 설정.

Pydantic Settings로 .env 자동 로드. 모든 설정의 단일 출처.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DeviceType = Literal["cuda", "mps", "cpu"]
EnvType = Literal["development", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STAR_SLIDE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
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

    # === Vision LLM (cliproxy/OpenAI 호환 endpoint) ===
    # 우선순위: 호출 시 인자 > 사용자 UI/CLI 입력 > 아래 환경설정 default
    vision_base_url: str = Field(
        default="http://localhost:8300/v1",
        validation_alias=AliasChoices("STAR_SLIDE_BASE_URL", "STAR_SLIDE_VISION_BASE_URL"),
    )
    """STAR_SLIDE_BASE_URL 또는 STAR_SLIDE_VISION_BASE_URL endpoint."""

    vision_model: str = Field(
        default="gpt-5.5",
        validation_alias=AliasChoices("STAR_SLIDE_MODEL", "STAR_SLIDE_VISION_MODEL"),
    )
    """STAR_SLIDE_MODEL 또는 STAR_SLIDE_VISION_MODEL의 모델 alias/이름.

    cliproxy 가 multiplex 하는 모델 alias 또는
    실제 모델명. 사용자 환경의 cliproxy 라우팅 설정에 맞춰 .env 로 override."""

    vision_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "STAR_SLIDE_API_KEY",
            "VISION_PROXY_API_KEY",
            "STAR_SLIDE_VISION_API_KEY",
            "LOCAL_CLAUDE_API_KEY",
        ),
    )
    """문서화된 API key 이름과 기존 vision/cliproxy alias를 모두 지원."""

    image_gen_model: str = ""
    """STAR_SLIDE_IMAGE_GEN_MODEL — text_erase_mode='codex_imagegen' 일 때 codex
    CLI builtin image_gen 도구 호출에 전달할 모델. 빈 문자열이면 codex 기본 사용."""

    db_url: str | None = None
    redis_url: str | None = None


def get_settings() -> Settings:
    """싱글톤 설정 인스턴스."""
    return _settings


_settings = Settings()
