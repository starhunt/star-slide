# Star-Slide

[Korean](README.md) | [English](Readme_en.md)

Star-Slide is a post-processing engine that converts image-locked AI slide decks back into editable PowerPoint files.

Tools such as NotebookLM can export something that looks like a normal PPTX, but each slide is often just one large image. In that state, you cannot edit text, select icons, move objects, or delete unwanted elements.

Star-Slide analyzes those slide images and reconstructs text, shapes, lines, and large image groups as PowerPoint objects. The goal is not simply to OCR text on top of the original image, but to preserve the original content and design as much as possible while producing a PPTX that is practical to edit.

## Core Features

- Automatic conversion for NotebookLM image-locked PPTX/PDF files
- Vision LLM-based `layout.json` generation for each slide
- Large illustration/diagram regions preserved as selectable image objects
- Titles, body text, and key labels restored as editable PowerPoint text
- Optional SAM3 bbox refinement for large image groups
- NotebookLM watermark removal
- Vector and hybrid candidates rendered and automatically selected by QA diff
- Parallel LLM calls, default `5`
- Inpaint artifact reduction when removing text from colored backgrounds
- Small badges, icon labels, and dimension labels can remain rasterized when that preserves visual quality

## Conversion Flow

The main workflow is the `notebooklm run` command.

```text
PPTX/PDF input
  -> extract slide images
  -> generate slide_XXX.layout.json with a Vision LLM
  -> build vector PPTX and render QA
  -> detect large raster group candidates with a Vision LLM
  -> optionally refine raster group bboxes with SAM3
  -> replace large diagrams/illustrations with selectable image objects
  -> keep extracted key text as editable text
  -> build hybrid PPTX and render QA
  -> automatically choose the safer layout between vector/hybrid
  -> generate the final editable PPTX
```

SAM3 is not the primary semantic segmentation engine. It is a helper used to tighten large image-group boundaries found by the Vision LLM. It is disabled by default to keep installation and runtime simpler. Enable it only when large image crops look visibly awkward. See [SAM3 Policy](#sam3-policy) for details.

## Installation

Python 3.11+ and `uv` are required.

```bash
git clone https://github.com/starhunt/star-slide.git
cd star-slide
uv sync --extra api
```

For development and verification tools:

```bash
uv sync --group dev
```

> ⚠️ **Required system dependency — LibreOffice**
>
> **LibreOffice is mandatory, not optional.** When an automated agent installs this project, it must install LibreOffice **in addition to** `uv sync` — finishing without LibreOffice leaves the project in a broken state.
>
> - The vector/hybrid layout auto-selection QA compares PNGs rendered by LibreOffice. Without it the conversion pipeline either fails outright or degrades severely.
> - After installation, verify `soffice --version` works in a fresh shell. If the command is missing or empty, **do not start a conversion** — fix the install/PATH first.

LibreOffice is required for PPTX render QA.

macOS:

```bash
brew install libreoffice poppler
```

LibreOffice is a free and open-source office suite. See [LibreOffice Licenses](https://www.libreoffice.org/licenses/) for official license details. Star-Slide does not bundle LibreOffice; it calls the locally installed `soffice`/`libreoffice` executable to render PPTX files to PNG for QA. Automatic layout selection depends on LibreOffice-rendered output, so **LibreOffice is a required dependency** (not optional).

Windows:

```powershell
winget install TheDocumentFoundation.LibreOffice
winget install oschwartz10612.Poppler
```

On Windows, `soffice.exe` and Poppler's `pdftoppm.exe`/`pdfinfo.exe` must be available on PATH. Open a new terminal and verify that `soffice --version` and `pdftoppm -v` work.

Poppler may be needed for PDF input and PDF-to-image rendering. The web app shows the detected status for LibreOffice, Poppler, and optional SAM3 readiness on the first screen.

To use SAM3 high-quality bbox refinement:

```bash
uv sync --extra api --extra gpu-segmentation
```

The `facebook/sam3` model may require HuggingFace access permission. Normal conversion works without SAM3; SAM3 is an optional quality mode for improving large image object boundaries.

## Vision LLM Provider

The `notebooklm` workflow uses an OpenAI-compatible `/v1/chat/completions` Vision endpoint. The Vision LLM looks at each slide image and turns it into structured `layout.json` data containing text, shapes, tables, and large image groups.

Default:

```text
base-url: http://localhost:8300/v1
model: gpt-5.5
```

Recommended local proxy:

- [Star-CliProxy](https://github.com/starhunt/Star-CliProxy)

Star-CliProxy is a local OpenAI-compatible API proxy for safely calling LLM CLI tools that you already subscribe to. From Star-Slide's point of view, it only calls a local endpoint such as `http://localhost:8300/v1`, so you can use a subscribed CLI-based LLM without adding a separate usage-based API key just for Star-Slide. The proxy handles authentication and actual CLI execution; Star-Slide only needs the OpenAI-compatible URL and model name.

Notes:

- Follow the model provider's terms of service and subscription policy.
- Star-CliProxy is intended to run locally.
- A high parallel setting (`--llm-parallel`, default 5) can hit CLI session or provider rate limits.
- For remote deployment, use dedicated secret storage instead of browser `localStorage`.

API keys can be passed through CLI options or environment variables.

```bash
export VISION_PROXY_API_KEY="..."
```

Or:

```bash
--api-key "..."
```

Star-CliProxy requires its own internally issued API key (an authentication token minted by the proxy itself, not an external pay-per-use LLM key), so you must enter that key in Star-Slide as well. Local LLMs that need no authentication, such as Ollama, can be used with the API key field left blank.

## Quick Start

```bash
uv run star-slide notebooklm run refdata/sample5.pptx \
  -o output/notebooklm_layout/sample5_auto_cli/sample5_auto_cli.pptx \
  --workdir output/notebooklm_layout/sample5_auto_cli/work \
  --timeout 600 \
  --retries 2 \
  --llm-parallel 5
```

Typical outputs:

```text
output/.../sample5_auto_cli.pptx
output/.../work/notebooklm_auto_report.json
output/.../work/qa_selected/montage.png
output/.../work/qa_selected/qa_report.json
```

## Using from AI agents (Claude Code, Codex CLI, ...)

The CLI is non-interactive, exposes a JSON output mode, and reads the same
options from environment variables, so coding agents can invoke it directly.

```bash
STAR_SLIDE_API_KEY=sk-... \
STAR_SLIDE_BASE_URL=https://api.openai.com/v1 \
STAR_SLIDE_MODEL=gpt-4.1 \
uv run star-slide notebooklm run input.pptx -o out.pptx --quiet --json
```

- `--quiet`: suppress the progress UI (no TTY required)
- `--json`: print the result metadata as a single-line JSON object to stdout
- exit code: `0` on success, `1` on failure

Supported environment variables: `STAR_SLIDE_API_KEY` (alias
`VISION_PROXY_API_KEY`), `STAR_SLIDE_BASE_URL`, `STAR_SLIDE_MODEL`,
`STAR_SLIDE_TIMEOUT`, `STAR_SLIDE_RETRIES`, `STAR_SLIDE_LLM_PARALLEL`,
`STAR_SLIDE_SAM3`.

See [AGENTS.md](AGENTS.md) for the full agent guide (output schema, common
patterns, anti-patterns).

## Web App

The web app runs the same conversion pipeline as the CLI. It is currently a local MVP. Uploaded files and outputs are stored under `output/web_jobs/`.

```bash
uv run --extra api star-slide web run --host 127.0.0.1
```

The web app always runs on port `5400` (fixed). Open:

```text
http://127.0.0.1:5400
```

Web app features:

- Drag-and-drop PPTX/PDF upload
- OpenAI, Gemini, Local Proxy, and multiple custom OpenAI-compatible providers (left sidebar)
- Top-right ⚙ **Settings modal** (System status / LLM Provider / Conversion options tabs) for persistently saving provider name, Base URL, model, API key, and conversion-option defaults
- Sidebar Provider/Model and conversion options are **session-scoped** — changes apply to that run only and the saved defaults are preserved
- Configure timeout, retries, LLM parallelism, font scale, SAM3 usage, embedded-text handling, intermediate artifact retention, and a **watermark-only mode (off / fast / detail)**
- Start asynchronous conversion jobs with SSE-based phase progress
- Job list: first-slide thumbnails, checkbox-based **bulk / individual deletion** (permanent or move to `_trash`), numeric-page pagination
- Dark/light mode (dark by default)
- Download completed PPTX and preview slides (including side-by-side compare against the original, rendered client-side via pptx-preview)
- Conversion report modal and raw JSON download
- Layout JSON summary modal and layout JSON zip download

The Gemini preset uses Google's OpenAI-compatible endpoint format: `https://generativelanguage.googleapis.com/v1beta/openai/`. See [Gemini API OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai) for details.

Provider settings and API keys are stored in browser `localStorage`. This is convenient for local development, but remote or shared deployments should use proper server-side secret storage.

### LAN / private-network LLM policy (SSRF guard)

The web app applies a host-aware SSRF policy to the LLM base URL the user enters.

| Web app bound to | Private IPs (10.x / 172.16-31.x / 192.168.x) | Always blocked |
| --- | --- | --- |
| `127.0.0.1` (default) | **Allowed** — internal GPU servers etc. work | link-local (169.254.x cloud IMDS), multicast, unspecified, file:// ... |
| `0.0.0.0` / LAN IP | **Blocked** — prevents the server being used as an SSRF proxy | same |

Because the default loopback bind cannot be reached by an external caller in
the first place, calling a corporate LLM on `http://192.168.1.100:8000/v1`
just works. If the web app is exposed to a network (`--host 0.0.0.0`), the
private-network gate flips on automatically and a yellow warning is printed
at startup. The literals `localhost`, `127.0.0.1`, `::1` are always allowed
regardless of policy (Ollama, star-cliproxy, and similar local proxies).

The web app does not edit PPTX files directly in the browser. Full PowerPoint-level editing and saving would require integration with a separate document editor such as Microsoft Office Online, OnlyOffice, or Collabora Online.

## CLI Options

```bash
uv run star-slide notebooklm run INPUT.pptx -o OUTPUT.pptx [options]
# or
uv run star-slide notebooklm run INPUT.pdf -o OUTPUT.pptx [options]
```

| Option | Default | Description |
| --- | --- | --- |
| `--workdir` | derived from output path | Directory for intermediate artifacts |
| `--base-url` | `http://localhost:8300/v1` | OpenAI-compatible Vision LLM endpoint |
| `--model` | `gpt-5.5` | Vision LLM model name |
| `--api-key` | empty string | Proxy API key |
| `--timeout` | `600` | LLM timeout in seconds |
| `--retries` | `2` | Retry count for broken JSON, missing layouts, or transient LLM failures |
| `--llm-parallel` | `5` | Parallel LLM calls for layout/raster-group analysis |
| `--layout-failure-mode` | `image_fallback` | Use a full-slide image fallback after exhausted retries, or set `fail` to stop the job |
| `--sam3 / --no-sam3` | `--no-sam3` | Use SAM3 bbox refinement (off by default — opt-in quality mode) |
| `--hybrid-allowed-delta` | `0.0` | Allow hybrid even if its diff is worse than vector by this amount |
| `--editable-embedded-text / --rasterize-embedded-text` | `--editable-embedded-text` | Keep text inside large image groups editable when possible |
| `--font-scale` | `0.93` | Global text size multiplier for PPTX rendering |
| `--keep-intermediates / --clean-intermediates` | `--clean-intermediates` | Keep large QA renders/assets after completion |

## Output Directory

By default, large intermediate files are cleaned up in product mode. Example web job structure:

```text
output/web_jobs/{job_id}/
  {uploaded}.pptx|.pdf      # original uploaded file
  result.pptx               # final converted PPTX
  artifacts/
    candidate_vector.pptx   # vector candidate
    candidate_hybrid.pptx   # hybrid candidate
    layout_json.zip         # LLM layout JSON and selection result JSON
    report.json             # conversion report
    montage.png             # final QA preview
    artifact_manifest.json  # retained artifact list and sizes
```

If `--keep-intermediates` is enabled, extracted images, QA renders, SAM3 crops, overlays, and other debugging files remain under `work/`.

`qa_report.json` records per-slide object counts, image object counts, and average render difference from the source image.

## SAM3 Policy

SAM3 is not Star-Slide's default conversion engine. Baseline quality comes from Vision LLM-generated `layout.json`, large raster group preservation, text/image preservation policy, and LibreOffice render-QA-based automatic selection. SAM3 only refines the boundary of large image groups.

Default is `--no-sam3` because:

- The `facebook/sam3` model may require access permission.
- Heavy dependencies such as `torch` and `transformers` are required.
- It can be slow on CPU and still adds time on GPU/MPS for large decks.
- Most NotebookLM slides contain large rectangular diagrams or panels where Vision LLM bboxes are often sufficient.

Enable SAM3 when:

- Large illustration or generated-image crops look visibly awkward.
- You need only the inner image inside a panel, but surrounding lines, margins, or backgrounds are being included.
- Final visual quality matters more than runtime.
- The web app system status shows SAM3 as `OK`.

SAM3 is usually less helpful when:

- The main problem is text extraction or editability.
- Slides are mostly tables, boxes, and simple lines.
- The hybrid result already preserves the large original image naturally.
- You need quick setup and batch conversion on a new machine.

Install:

```bash
uv sync --extra api --extra gpu-segmentation
```

Run:

```bash
uv run star-slide notebooklm run INPUT.pptx -o OUTPUT.pptx --sam3
```

In the web app, enable `SAM3 bbox refinement` under conversion options. The system status checks whether `torch` and `transformers` are installed, but it does not fully guarantee HuggingFace access to `facebook/sam3`. The first SAM3 run may still fail if model download or access permission is missing.

## Editability Policy

Star-Slide does not blindly vectorize every pixel.

Full vectorization can create too many PowerPoint objects and produce worse visual fidelity. The current policy is:

- Titles, body text, and key labels: editable text objects
- Tables, boxes, lines, and simple shapes: PowerPoint shapes/lines when practical
- Complex illustrations, generated images, and large diagrams: selectable image objects
- Small English badges, icon labels, and dimension labels: may remain in the original raster image
- NotebookLM watermark: removed

This approach is more stable in real use than trying to make every pixel editable. The goal is to balance text editability with visual fidelity.

## Prompt-Based Infographics

If only a finished image is available, reverse reconstruction is required. But if source structure exists, such as a YouTube summary or a detailed image-generation prompt, there is a better path:

```text
prompt/summary
  -> structured layout.json
  -> editable PPTX from the beginning
```

This avoids OCR and image-reasoning errors, so it is better for Korean text-heavy infographics. This path is currently experimental and may become a dedicated CLI mode later.

## Legacy `convert` Command

The older general conversion command remains available:

```bash
uv run star-slide convert run INPUT.pptx \
  -o output/converted.pptx \
  --vision-llm \
  --vision-base-url http://localhost:8300/v1 \
  --vision-model gpt-5.5
```

For NotebookLM image-locked decks, the `notebooklm run` path is the actively maintained workflow.

## Development

```bash
uv run star-slide --help
uv run star-slide notebooklm --help
uv run ruff check scripts/apply_raster_groups_to_layout.py star_slide/pipeline/notebooklm_auto.py star_slide/cli/notebooklm.py
uv run pytest
```

## Git Policy

The following directories are treated as generated output or large local input data and are ignored by default:

```text
output/
data/
experiments/
```

`refdata/` is a local place for test input files. Track only the samples that should intentionally be part of the repository.

## Current Limitations

- Small text may be missed depending on Vision LLM output quality.
- LLM responses can contain broken JSON, so retries are needed.
- Making every piece of text inside complex diagrams editable can reduce visual quality.
- PowerPoint and LibreOffice rendering can differ slightly, causing line-wrap differences.
- Fully automated production deployment still needs stronger missing-text QA, an automatic correction loop, and a proper job queue/API server.

## Project Docs

- [Integrated PRD](docs/Star-Slide_PRD.md)
- [Technical Decisions](docs/Star-Slide_TechDecisions.md)
- [Development Plan](docs/Star-Slide_DevPlan.md)
- [Project Structure](docs/Star-Slide_Structure.md)

## License

MIT.

External models and tools follow their own licenses and terms.
