"""정리된 워크디렉토리 때문에 썸네일이 빠진 기존 잡 디렉토리 일괄 백필.

각 output/web_jobs/<id>/ 에 대해:
  - result.pptx 가 있으면 preview_cache/result/page_*.png 생성
  - render_pptx_pages(job, "result") 가 fingerprint 체크 → 이미 캐시 있으면 즉시 skip

실행:
    uv run --extra api python scripts/backfill_thumbnails.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from star_slide.api.web_app import (
    JobState,
    WEB_ROOT,
    render_pptx_pages,
)


def backfill(job_dir: Path) -> str:
    result_pptx = job_dir / "result.pptx"
    if not result_pptx.exists():
        return "skip (no result.pptx)"

    job = JobState(
        id=job_dir.name,
        filename=result_pptx.name,
        output=str(result_pptx),
        report=str(job_dir / "artifacts" / "report.json"),
    )
    try:
        pages = render_pptx_pages(job, "result")
    except FileNotFoundError as exc:
        return f"skip ({exc})"
    except RuntimeError as exc:
        return f"fail ({exc})"
    return f"ok ({len(pages)} pages)"


def main() -> int:
    if not WEB_ROOT.exists():
        print(f"WEB_ROOT not found: {WEB_ROOT}")
        return 1
    job_dirs = sorted(p for p in WEB_ROOT.iterdir() if p.is_dir())
    if not job_dirs:
        print("no jobs to backfill")
        return 0

    total = len(job_dirs)
    print(f"[backfill] {total} job dirs under {WEB_ROOT}")
    counts = {"ok": 0, "skip": 0, "fail": 0}
    for idx, job_dir in enumerate(job_dirs, start=1):
        status = backfill(job_dir)
        bucket = status.split(" ", 1)[0]
        counts[bucket if bucket in counts else "fail"] += 1
        print(f"  [{idx:>2}/{total}] {job_dir.name[:8]} {status}", flush=True)
    print(f"[backfill] done: {counts}")
    return 0 if counts["fail"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
