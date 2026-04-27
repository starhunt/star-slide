# Star-Slide — Agent Usage Guide

This document is for AI coding agents (Claude Code, Codex CLI, Cursor, Aider, etc.)
that need to invoke Star-Slide as a one-shot conversion tool from a shell.

The companion human-facing docs are [README.md](README.md) (Korean) and
[Readme_en.md](Readme_en.md) (English).

## What this tool does

Converts a NotebookLM image-locked PPTX or PDF into an editable PPTX. Returns
the path to the new PPTX plus a JSON report describing what was selected
(`vector` vs `hybrid`) per slide.

Input types: `.pptx`, `.pdf`. Output: `.pptx`.

Pipeline calls a Vision LLM through an OpenAI-compatible `/v1/chat/completions`
endpoint (default: a local proxy at `http://localhost:8300/v1`). The LLM is
the only required external dependency for the conversion itself; LibreOffice
and Poppler are needed for the QA / auto-selection step.

## One-shot invocation (recommended for agents)

```bash
uv run star-slide notebooklm run INPUT.{pptx,pdf} \
  -o OUTPUT.pptx \
  --quiet --json
```

- `--quiet` suppresses the rich progress bar (no TTY required).
- `--json` prints a single-line JSON object to stdout on success.
- Exit code: `0` on success, `1` on failure (JSON error object on stdout in
  `--json` mode).

### Example output (success)

```json
{"ok": true, "elapsed_sec": 162.4, "output": "out.pptx", "workdir": "out", "report": "out/notebooklm_auto_report.json", "vector_pptx": "out/vector.pptx", "hybrid_pptx": "out/hybrid.pptx", "artifact_dir": "out/../artifacts", "montage": "out/qa_selected/montage.png", "selected_layout_dir": "out/layouts_selected"}
```

### Example output (failure)

```json
{"ok": false, "error": "no slide images extracted from input.pptx"}
```

## Environment variables

CLI flags take precedence; otherwise these are picked up automatically:

| Variable | Purpose | Default |
|---|---|---|
| `STAR_SLIDE_API_KEY` (alias: `VISION_PROXY_API_KEY`) | Bearer token sent to the LLM endpoint. Empty for local proxies (Ollama, star-cliproxy). | `""` |
| `STAR_SLIDE_BASE_URL` | OpenAI-compatible endpoint base | `http://localhost:8300/v1` |
| `STAR_SLIDE_MODEL` | LLM model name | `gpt-5.5` |
| `STAR_SLIDE_TIMEOUT` | Per-call timeout in seconds | `600` |
| `STAR_SLIDE_RETRIES` | Retry count for malformed JSON | `1` |
| `STAR_SLIDE_LLM_PARALLEL` | Concurrent LLM calls | `5` |
| `STAR_SLIDE_SAM3` | `1`/`true` to enable SAM3 bbox refinement | `0` |

## Common patterns

### Convert with a remote OpenAI key

```bash
STAR_SLIDE_API_KEY=sk-... \
STAR_SLIDE_BASE_URL=https://api.openai.com/v1 \
STAR_SLIDE_MODEL=gpt-4.1 \
uv run star-slide notebooklm run input.pptx -o out.pptx --quiet --json
```

### Use Ollama (no key)

```bash
STAR_SLIDE_BASE_URL=http://localhost:11434/v1 \
STAR_SLIDE_MODEL=gpt-oss:20b \
uv run star-slide notebooklm run input.pptx -o out.pptx --quiet --json
```

### Capture only the output path

```bash
out_path=$(uv run star-slide notebooklm run input.pptx -o out.pptx --quiet --json | jq -r .output)
```

### Inspect per-slide selections after the run

```bash
report=$(uv run star-slide notebooklm run input.pptx -o out.pptx --quiet --json | jq -r .report)
jq '.selection_report[] | {slide_no, chosen, vector_mean_abs_diff, hybrid_mean_abs_diff}' "$report"
```

## What you should *not* do

- **Do not invoke the web app** (`star-slide web run`) from an agent. It is an
  interactive local UI bound to port `5400` and is not designed for
  programmatic use. Use the CLI above instead.
- **Do not pass `--keep-intermediates` by default.** It produces gigabytes of
  QA renders. Only enable when explicitly debugging.
- **Do not retry blindly on failure.** Inspect `error` first — common causes
  are LLM endpoint unreachable, model name typo, or LibreOffice not installed.

## System dependencies the agent should verify before running

Run these once and bail out early if any are missing:

```bash
command -v soffice >/dev/null || echo "WARN: LibreOffice (soffice) not on PATH — QA selection will degrade"
command -v pdftoppm >/dev/null || echo "WARN: Poppler (pdftoppm) not on PATH — PDF input may fail"
uv run python -c "import star_slide"  # confirms the package is installed
```

## Output directory layout (after `--clean-intermediates` default)

```
OUTPUT.pptx                              # final editable PPTX
OUTPUT/                                  # workdir (= output stem)
  notebooklm_auto_report.json            # full report (selection + QA diffs)
  qa_selected/montage.png                # comparison preview
artifacts/                               # next to OUTPUT (or workdir parent)
  candidate_vector.pptx
  candidate_hybrid.pptx
  layout_json.zip
  artifact_manifest.json
```

## Reading the report programmatically

`notebooklm_auto_report.json` schema (top-level keys):
- `selection_report`: `[{slide_no, chosen: "vector"|"hybrid", vector_mean_abs_diff, hybrid_mean_abs_diff, ...}]`
- `selected_qa`: per-slide QA after final selection
- `vector_qa`, `hybrid_qa`: per-slide QA for each candidate

Lower `mean_abs_diff` is better (smaller pixel delta against the original
slide image).

## Failure exit codes

| Exit | Meaning | What to do |
|---|---|---|
| `0` | success | proceed |
| `1` | conversion failed (see `error` in `--json` mode, or stderr otherwise) | inspect; do not retry blindly |
| other | typer/uvicorn argument error | re-check command syntax |

## Out of scope for the CLI agent path

- Watermark-only mode is currently a backlog item; not yet a CLI flag.
- The web app's slide compare preview, cancel/rerun, and SSE event stream
  are UI features only. The CLI runs to completion (or failure) in one go.
