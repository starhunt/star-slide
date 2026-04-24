"""스모크 테스트: 기본 import와 CLI 진입점이 동작하는지 확인."""

from __future__ import annotations

from typer.testing import CliRunner


def test_package_import() -> None:
    """패키지 import + 버전 노출 확인."""
    import star_slide

    assert star_slide.__version__ == "0.1.0"


def test_settings_default_safe() -> None:
    """기본 Settings는 외부 API 차단 상태(안전 기본값)여야 한다."""
    from star_slide.config import get_settings

    settings = get_settings()
    assert settings.disable_external_api is True
    assert settings.enable_vlm_classify is False
    assert settings.enable_gpt_inpaint is False


def test_cli_version() -> None:
    """CLI version 명령이 정상 출력."""
    from star_slide.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_cli_status() -> None:
    """CLI status 명령이 정상 출력."""
    from star_slide.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Phase 0" in result.stdout
