"""라벨링 헬퍼 CLI.

`star-slide label list` — H1 priority 라벨 진행 상태 표시
`star-slide label show <slide>` — 특정 슬라이드의 라벨 JSON 출력
`star-slide label text <slide>` — ground_truth_text 인터랙티브 입력 (외부 에디터 호출)
`star-slide label open <slide>` — 시스템 기본 이미지 뷰어로 슬라이드 이미지 열기
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

LABELS_DIR = Path("data/labels/notebooklm")
SAMPLES_DIR = Path("data/samples/notebooklm")

app = typer.Typer(help="H1 우선 10장 라벨링 헬퍼.", no_args_is_help=True)
console = Console()


def _load(slide_stem: str) -> tuple[Path, dict[str, Any]]:
    """slide_stem(예: 'sample1_slide01')의 라벨 JSON 로드. 없으면 typer.Exit."""
    p = LABELS_DIR / f"{slide_stem}.json"
    if not p.exists():
        console.print(f"[red]라벨 파일 없음: {p}[/]")
        raise typer.Exit(1)
    return p, json.loads(p.read_text(encoding="utf-8"))


def _save(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_priority_done(label: dict[str, Any]) -> bool:
    return bool(
        label.get("h1_priority") and label.get("ground_truth_text") and label.get("labeler")
    )


@app.command("list")
def list_priority() -> None:
    """H1 priority 10장의 라벨 진행 상태."""
    table = Table(title="H1 Priority 라벨 진행 상태", show_lines=False)
    table.add_column("#", justify="right", width=3)
    table.add_column("슬라이드", style="cyan")
    table.add_column("카테고리", style="magenta")
    table.add_column("패턴", overflow="fold")
    table.add_column("텍스트", justify="right")
    table.add_column("Objects", justify="right")
    table.add_column("상태", justify="center")

    priority_files = sorted(
        p
        for p in LABELS_DIR.glob("*.json")
        if json.loads(p.read_text(encoding="utf-8")).get("h1_priority")
    )

    done = 0
    for idx, p in enumerate(priority_files, start=1):
        label = json.loads(p.read_text(encoding="utf-8"))
        text_len = len(label.get("ground_truth_text") or "")
        obj_count = len(label.get("objects") or [])
        is_done = _is_priority_done(label)
        if is_done:
            done += 1
        status = "[green]✓[/]" if is_done else "[yellow]⬜[/]"
        pattern = (label.get("pattern_note") or "")[:50]
        table.add_row(
            str(idx),
            p.stem,
            label.get("category") or "-",
            pattern,
            f"{text_len}자",
            str(obj_count),
            status,
        )

    console.print(table)
    console.print(f"\n진행: [bold]{done}/{len(priority_files)}[/]")
    if done < len(priority_files):
        next_target = next(
            (
                p.stem
                for p in priority_files
                if not _is_priority_done(json.loads(p.read_text(encoding="utf-8")))
            ),
            None,
        )
        if next_target:
            console.print(f"\n다음 작업: [cyan]uv run star-slide label text {next_target}[/]")


@app.command("show")
def show(slide: str) -> None:
    """라벨 JSON 내용 출력."""
    path, label = _load(slide)
    console.print(f"[dim]{path}[/]")
    console.print_json(json.dumps(label, ensure_ascii=False))


@app.command("open")
def open_image(slide: str) -> None:
    """OS 기본 뷰어로 슬라이드 이미지 열기 (참고용)."""
    img = SAMPLES_DIR / f"{slide}.png"
    if not img.exists():
        console.print(f"[red]이미지 없음: {img}[/]")
        raise typer.Exit(1)
    if sys.platform == "darwin":
        subprocess.run(["open", str(img)], check=False)
    elif sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", str(img)], check=False)
    elif sys.platform == "win32":
        os.startfile(str(img))  # type: ignore[attr-defined]
    console.print(f"[green]열림:[/] {img}")


@app.command("text")
def text(slide: str, labeler: str = "starhunter") -> None:
    """ground_truth_text를 외부 에디터(EDITOR 환경변수)로 입력.

    저장 후 라벨 JSON 자동 갱신.
    """
    path, label = _load(slide)
    image = SAMPLES_DIR / f"{slide}.png"

    console.print(f"[bold]슬라이드:[/] {slide}")
    console.print(f"[bold]카테고리:[/] {label.get('category')}")
    console.print(f"[bold]패턴:[/] {label.get('pattern_note')}")
    console.print(f"[bold]이미지:[/] {image}")
    console.print()

    # 임시 파일에 현재 텍스트 + 안내 + 이미지 경로 표시
    current = label.get("ground_truth_text") or ""
    tmp = path.parent / f".{slide}.tmp.txt"
    header = (
        f"# {slide}\n"
        f"# 이 줄을 포함한 # 으로 시작하는 줄은 무시됩니다.\n"
        f"# 이미지를 보면서 슬라이드의 모든 한글 텍스트를 정확히 입력하세요.\n"
        f"# 줄바꿈은 의미 단위로 (기본은 시각 줄바꿈 그대로).\n"
        f"# 이미지: {image.absolute()}\n"
        f"# (저장 후 닫으면 라벨 JSON에 반영됩니다.)\n\n"
    )
    tmp.write_text(header + current, encoding="utf-8")

    editor = os.environ.get("EDITOR") or shutil.which("code") or "nano"
    if editor.endswith("code") or editor.endswith("code.exe"):
        subprocess.run([editor, "--wait", str(tmp)], check=False)
    else:
        subprocess.run([editor, str(tmp)], check=False)

    raw = tmp.read_text(encoding="utf-8")
    tmp.unlink(missing_ok=True)
    new_text = "\n".join(line for line in raw.splitlines() if not line.startswith("#")).strip()

    if not new_text:
        console.print("[yellow]입력 없음 — 변경하지 않음[/]")
        return

    label["ground_truth_text"] = new_text
    label["labeler"] = labeler
    label["labeled_at"] = datetime.now().isoformat(timespec="seconds")
    _save(path, label)

    console.print(f"[green]저장됨[/]: {len(new_text)}자, labeler={labeler}")


@app.command("set-category")
def set_category(slide: str, category: str) -> None:
    """category 값 설정 (title|diagram|process|comparison|infographic|chart|table|text-heavy)."""
    valid = {
        "title",
        "diagram",
        "process",
        "comparison",
        "infographic",
        "chart",
        "table",
        "text-heavy",
    }
    if category not in valid:
        console.print(f"[red]유효하지 않은 카테고리. 허용: {sorted(valid)}[/]")
        raise typer.Exit(1)
    path, label = _load(slide)
    label["category"] = category
    _save(path, label)
    console.print(f"[green]저장됨[/]: {slide}.category = {category}")
