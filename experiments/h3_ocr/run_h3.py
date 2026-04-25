"""H3 검증: PaddleOCR PP-OCRv5 한국어 모델의 슬라이드 도메인 CER 측정.

10장 H1 priority 슬라이드 OCR → ground_truth_text와 CER 계산 → AC ≤7% 검증.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from star_slide.ocr.metrics import cer, wer
from star_slide.ocr.paddleocr_worker import lines_to_text, run_ocr

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples" / "notebooklm"
LABELS = ROOT / "data" / "labels" / "notebooklm"
RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)


def main() -> None:
    console = Console()

    # H1 priority 라벨된 10장 수집
    priority = []
    for label_path in sorted(LABELS.glob("*.json")):
        label = json.loads(label_path.read_text(encoding="utf-8"))
        if label.get("h1_priority") and label.get("ground_truth_text"):
            priority.append(label)

    console.print(f"[bold]H1 priority 라벨 완료 슬라이드: {len(priority)}장[/]")

    table = Table(title="H3 PaddleOCR CER 측정 (raw + conf≥0.8 필터)")
    table.add_column("#", justify="right", width=3)
    table.add_column("슬라이드", style="cyan")
    table.add_column("카테고리", style="magenta")
    table.add_column("GT 글자", justify="right")
    table.add_column("OCR(raw)", justify="right")
    table.add_column("OCR(≥0.8)", justify="right")
    table.add_column("CER raw", justify="right")
    table.add_column("CER ≥0.8", justify="right")
    table.add_column("시간(s)", justify="right")

    CONF_THRESHOLD = 0.8

    per_slide_results: list[dict] = []

    for i, label in enumerate(priority, start=1):
        img_path = SAMPLES / label["image"]
        gt = label["ground_truth_text"]

        t0 = time.perf_counter()
        lines = run_ocr(img_path, lang="korean")
        elapsed = time.perf_counter() - t0

        pred_raw = lines_to_text(lines)
        filtered = [ln for ln in lines if ln.confidence >= CONF_THRESHOLD]
        pred_filtered = lines_to_text(filtered)

        cer_raw = cer(pred_raw, gt)
        cer_filtered = cer(pred_filtered, gt)
        wer_filtered = wer(pred_filtered, gt)

        gt_chars = len(gt.replace("\n", "").replace(" ", ""))
        pred_raw_chars = len(pred_raw.replace("\n", "").replace(" ", ""))
        pred_filt_chars = len(pred_filtered.replace("\n", "").replace(" ", ""))

        def _color(c: float) -> str:
            return "green" if c <= 0.07 else ("yellow" if c <= 0.15 else "red")

        table.add_row(
            str(i),
            label["image"],
            label["category"],
            str(gt_chars),
            str(pred_raw_chars),
            str(pred_filt_chars),
            f"[{_color(cer_raw)}]{cer_raw:.3f}[/]",
            f"[{_color(cer_filtered)}]{cer_filtered:.3f}[/]",
            f"{elapsed:.1f}",
        )

        per_slide_results.append(
            {
                "image": label["image"],
                "category": label["category"],
                "gt_chars": gt_chars,
                "pred_raw_chars": pred_raw_chars,
                "pred_filt_chars": pred_filt_chars,
                "ocr_lines_raw": len(lines),
                "ocr_lines_filtered": len(filtered),
                "cer_raw": cer_raw,
                "cer_filtered": cer_filtered,
                "wer_filtered": wer_filtered,
                "elapsed_sec": elapsed,
                "predicted_text_raw": pred_raw,
                "predicted_text_filtered": pred_filtered,
                "predicted_lines": [
                    {"text": ln.text, "confidence": ln.confidence, "bbox": list(ln.bbox)}
                    for ln in lines
                ],
            }
        )

    console.print(table)

    # 집계
    n = len(per_slide_results)
    avg_cer_raw = sum(r["cer_raw"] for r in per_slide_results) / n
    avg_cer_filt = sum(r["cer_filtered"] for r in per_slide_results) / n
    total_time = sum(r["elapsed_sec"] for r in per_slide_results)

    summary = {
        "n_slides": n,
        "conf_threshold": CONF_THRESHOLD,
        "avg_cer_raw": avg_cer_raw,
        "avg_cer_filtered": avg_cer_filt,
        "median_cer_filtered": sorted(r["cer_filtered"] for r in per_slide_results)[n // 2],
        "max_cer_filtered": max(r["cer_filtered"] for r in per_slide_results),
        "min_cer_filtered": min(r["cer_filtered"] for r in per_slide_results),
        "total_time_sec": total_time,
        "ac_target_cer": 0.07,
        "ac_pass_filtered": avg_cer_filt <= 0.07,
        "ac_pass_raw": avg_cer_raw <= 0.07,
        "per_slide": per_slide_results,
    }

    out = RESULTS / "h3_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print()
    console.print(f"[bold]평균 CER (raw):[/]      {avg_cer_raw:.3f}")
    console.print(f"[bold]평균 CER (conf≥0.8):[/] {avg_cer_filt:.3f}")
    console.print(
        f"[bold]conf≥0.8 분포:[/] "
        f"min {summary['min_cer_filtered']:.3f}, "
        f"median {summary['median_cer_filtered']:.3f}, "
        f"max {summary['max_cer_filtered']:.3f}"
    )
    console.print(f"[bold]총 시간:[/] {total_time:.1f}s ({total_time / n:.1f}s/슬라이드)")

    if summary["ac_pass_filtered"]:
        console.print(
            f"\n[bold green]✅ H3 GREEN (conf≥0.8): 평균 CER {avg_cer_filt:.3f} ≤ 0.07[/]"
        )
    else:
        console.print(f"\n[bold yellow]⚠️  H3 YELLOW (conf≥0.8): 평균 CER {avg_cer_filt:.3f}[/]")
        console.print(
            "[yellow]GT 라벨에 일러스트 안 영문 텍스트가 누락된 슬라이드 가능. "
            "사용자 검수 또는 슬라이드별 CER 분석 권장.[/]"
        )

    console.print(f"\n[dim]상세: {out}[/]")


if __name__ == "__main__":
    main()
