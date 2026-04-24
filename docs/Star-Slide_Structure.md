# Star-Slide 프로젝트 구조 + 초기화 가이드

> 작성일: 2026-04-25
> 목적: Day 1부터 바로 실행 가능한 디렉토리 구조 + 초기화 명령

---

## 1. 디렉토리 구조 (전체)

```
star-slide/
├── docs/                           # PRD, ADR, 개발계획 (이미 존재)
│   ├── Star-Slide_PRD.md
│   ├── Star-Slide_TechDecisions.md
│   ├── Star-Slide_DevPlan.md
│   ├── Star-Slide_Structure.md     # 이 문서
│   ├── Star-Slide_Phase0_Report.md # (Phase 0 끝에 생성)
│   ├── Star-SlideEditor.md         # 원본 PRD (보존)
│   ├── star-slidemanager-prd_claude.md
│   └── Star-SlideMaster_PRD_manus.md
│
├── star_slide/                     # Python 메인 패키지
│   ├── __init__.py
│   ├── _version.py
│   │
│   ├── schema/                     # 중간 레이어 표현 (PRD §8)
│   │   ├── __init__.py
│   │   ├── layer.py                # pydantic models
│   │   ├── enums.py                # ObjectType, EditableLevel
│   │   └── jobs.py                 # Job state machine
│   │
│   ├── input/                      # 파일 입력 + 검증
│   │   ├── __init__.py
│   │   ├── validator.py            # 확장자/MIME/크기/암호화
│   │   ├── pptx_extractor.py       # PPTX 슬라이드 추출
│   │   ├── pdf_extractor.py        # PDF → 페이지
│   │   └── image_extractor.py      # PNG/JPG/ZIP
│   │
│   ├── rasterize/                  # 슬라이드 → 이미지
│   │   ├── __init__.py
│   │   ├── libreoffice.py          # headless renderer
│   │   ├── poppler.py              # PDF
│   │   └── coords.py               # EMU↔px 변환
│   │
│   ├── segmentation/               # SAM 3.1
│   │   ├── __init__.py
│   │   ├── sam31.py                # SAM 3.1 wrapper
│   │   ├── sam2_fallback.py        # SAM 2 fallback
│   │   ├── pre_protect.py          # 차트/텍스트 사전 검출
│   │   ├── east_craft.py           # 텍스트 디텍터
│   │   └── postprocess.py          # IoU/area 필터
│   │
│   ├── classify/                   # 객체 분류
│   │   ├── __init__.py
│   │   ├── rule_based.py           # aspect/edge/color/text-likeness
│   │   └── vlm_assist.py           # 옵션, 기본 OFF
│   │
│   ├── ocr/                        # OCR 앙상블
│   │   ├── __init__.py
│   │   ├── paddleocr.py            # PP-OCRv5 한국어
│   │   ├── surya.py                # 보조
│   │   ├── ensemble.py             # 신뢰도 기반 앙상블
│   │   └── postprocess.py          # 줄바꿈/색상/폰트크기
│   │
│   ├── inpaint/                    # 인페인팅
│   │   ├── __init__.py
│   │   ├── lama.py                 # IOPaint LaMa
│   │   ├── gpt_image2.py           # 옵션
│   │   └── ssim_guard.py           # 안전 fallback
│   │
│   ├── font/                       # 한글 폰트 매칭
│   │   ├── __init__.py
│   │   ├── pool.py                 # 폰트 풀 정의
│   │   ├── embedding.py            # 글리프 임베딩
│   │   ├── matcher.py              # cosine + 픽셀 비교
│   │   └── build.py                # 사전 임베딩 빌드 스크립트
│   │
│   ├── table/                      # 표 복원
│   │   ├── __init__.py
│   │   ├── detector.py             # PP-StructureV3
│   │   ├── grid.py                 # 직선 + 셀 격자
│   │   ├── t1_overlay.py           # 이미지 + overlay text
│   │   └── t2_grouped.py           # grouped shape
│   │
│   ├── chart/                      # 차트 (Phase 2)
│   │   ├── __init__.py
│   │   ├── detector.py
│   │   ├── deplot.py               # Phase 2
│   │   └── grouped.py              # C2
│   │
│   ├── composer/                   # PPTX 조립
│   │   ├── __init__.py
│   │   ├── presentation.py         # python-pptx wrapper
│   │   ├── svg2custgeom.py         # 핵심 변환기
│   │   ├── emf_fallback.py         # Inkscape/LibreOffice
│   │   ├── png_fallback.py
│   │   ├── layout.py               # z-order + 정렬 스냅
│   │   └── group.py                # group shape
│   │
│   ├── qa/                         # Visual QA
│   │   ├── __init__.py
│   │   ├── ssim.py
│   │   ├── overflow.py             # 텍스트 overflow 검출
│   │   └── report.py               # report.json 빌더
│   │
│   ├── pipeline/                   # 전체 파이프라인 오케스트레이션
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # Phase 1: 단일 프로세스
│   │   ├── checkpoint.py           # 슬라이드 단위 재시도
│   │   └── isolation.py            # 슬라이드 실패 격리
│   │
│   ├── api/                        # FastAPI (Phase 2)
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── routes/
│   │   ├── auth.py
│   │   └── deps.py
│   │
│   ├── workers/                    # Celery (Phase 2)
│   │   ├── __init__.py
│   │   ├── tasks.py
│   │   └── celery_app.py
│   │
│   ├── storage/                    # 파일 스토리지 추상화
│   │   ├── __init__.py
│   │   ├── local.py                # MVP
│   │   └── s3_compat.py            # Phase 3
│   │
│   ├── db/                         # DB (Phase 2)
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy
│   │   ├── session.py
│   │   └── migrations/             # Alembic
│   │
│   ├── audit/                      # 감사 로그 (Phase 4)
│   │   └── __init__.py
│   │
│   ├── cli/                        # typer CLI
│   │   ├── __init__.py
│   │   ├── main.py                 # entrypoint
│   │   ├── convert.py
│   │   ├── validate.py
│   │   └── build_fonts.py
│   │
│   └── config.py                   # 환경 변수 + Pydantic Settings
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_input/
│   │   ├── test_rasterize/
│   │   ├── test_segmentation/
│   │   ├── test_classify/
│   │   ├── test_ocr/
│   │   ├── test_inpaint/
│   │   ├── test_font/
│   │   ├── test_table/
│   │   ├── test_composer/          # svg2custgeom 회귀 핵심
│   │   ├── test_qa/
│   │   └── test_schema/
│   ├── integration/
│   │   ├── test_pipeline.py
│   │   └── test_e2e_cli.py
│   ├── e2e/
│   │   └── test_golden_samples.py  # 골든 10장 회귀
│   └── fixtures/
│       ├── pptx/
│       ├── pdf/
│       ├── images/
│       └── expected/
│
├── data/
│   ├── samples/                    # 100장 (Phase 0)
│   │   ├── notebooklm/             # 30장
│   │   ├── gamma/                  # 10장
│   │   ├── pdf_reports/            # 20장
│   │   ├── educational/            # 15장
│   │   ├── infographics/           # 10장
│   │   ├── charts/                 # 10장
│   │   └── tables/                 # 5장
│   ├── labels/                     # ground truth JSON 100개
│   ├── fonts/                      # 한글 폰트 풀
│   │   ├── manifest.json           # 폰트별 라이선스/메타
│   │   ├── pretendard/
│   │   ├── noto-sans-kr/
│   │   ├── nanum-gothic/
│   │   └── ...
│   ├── font_embeddings/            # 사전 계산 임베딩 (build script 출력)
│   └── golden/                     # 회귀 테스트 골든
│       ├── input/
│       └── expected/
│
├── experiments/                    # Phase 0 PoC + 보고서
│   ├── h1_sam31/
│   │   ├── notebook.ipynb
│   │   ├── REPORT.md
│   │   └── results/
│   ├── h2_custgeom/
│   │   ├── poc.py
│   │   ├── REPORT.md
│   │   └── samples/
│   └── h3_ocr/
│       ├── notebook.ipynb
│       ├── REPORT.md
│       └── results/
│
├── web/                            # Phase 3 Next.js
│   └── (Phase 3에 초기화)
│
├── scripts/
│   ├── setup-dev.sh                # uv venv + pre-commit
│   ├── download-models.sh          # SAM/PaddleOCR/LaMa 사전 다운로드
│   ├── build-fonts.sh              # 폰트 임베딩 사전 계산
│   ├── run-libreoffice.sh          # docker 옵션
│   └── benchmark.py                # 100장 회귀 벤치마크
│
├── deploy/                         # 배포 설정 (Phase 2+)
│   ├── docker/
│   │   ├── Dockerfile.api
│   │   ├── Dockerfile.worker-cpu
│   │   └── Dockerfile.worker-gpu
│   ├── docker-compose.yml          # 로컬 통합
│   └── k8s/                        # Phase 4
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # lint + unit + golden
│   │   ├── benchmark.yml           # 매주 100장 회귀
│   │   └── docker.yml              # 이미지 빌드
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
│
├── .session/                       # 세션 연속성
│   └── CONTINUITY.md
│
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .python-version                 # 3.11
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE                         # MIT 또는 사용자 결정
└── CONTRIBUTING.md                 # (Phase 3+)
```

---

## 2. 의존성 격리 전략

### 2.1 GPU vs CPU 분리

GPU가 필요한 모듈과 CPU만 필요한 모듈을 분리해 worker 노드 비용 최적화.

| 모듈 | GPU 필요 | 분리 패키지(extra) |
|---|---|---|
| `input`, `rasterize`, `composer`, `qa`, `cli`, `api` | ❌ | `[base]` |
| `segmentation` (SAM) | ✅ | `[gpu-segmentation]` |
| `ocr` (PaddleOCR/Surya) | 옵션 | `[ocr]` |
| `inpaint` (LaMa) | ✅ | `[gpu-inpaint]` |
| `font/embedding` 빌드 | ❌ | `[base]` |
| `chart/deplot` (Phase 2) | ✅ | `[gpu-chart]` |

### 2.2 pyproject.toml 핵심

```toml
[project]
name = "star-slide"
version = "0.1.0"
description = "AI 슬라이드 이미지를 편집 가능 PPTX로 역변환하는 후처리 엔진"
requires-python = ">=3.11"
dependencies = [
    "python-pptx>=1.0",
    "pdf2image>=1.17",
    "pillow>=10",
    "numpy>=1.26",
    "lxml>=5",
    "svg.path>=6.3",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "typer>=0.12",
    "rich>=13",
    "scikit-image>=0.22",  # SSIM
]

[project.optional-dependencies]
gpu-segmentation = [
    "torch>=2.6",
    "torchvision",
    "transformers>=4.40",
    # SAM 3.1 패키지 (출시 후 정확한 이름 확정)
]
ocr = [
    "paddleocr>=2.9",
    "paddlepaddle-gpu",  # CPU 환경은 paddlepaddle
    # surya OCR
]
gpu-inpaint = [
    "iopaint",
    "torch>=2.6",
]
api = [
    "fastapi>=0.115",
    "uvicorn[standard]",
    "celery[redis]",
    "sqlalchemy>=2",
    "alembic",
    "psycopg[binary]",
    "pgvector",
]
dev = [
    "pytest>=8",
    "pytest-cov",
    "pytest-asyncio",
    "ruff>=0.4",
    "mypy>=1.10",
    "black",
    "pre-commit",
    "ipykernel",
    "jupyterlab",
]

[project.scripts]
star-slide = "star_slide.cli.main:app"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "gpu: tests requiring GPU",
    "slow: tests > 5s",
    "e2e: end-to-end tests",
]
```

### 2.3 외부 시스템 의존성

다음은 OS 레벨 또는 별도 바이너리:

| 의존성 | 설치 방법 | 사용처 |
|---|---|---|
| LibreOffice (headless) | `brew install libreoffice` 또는 docker | `rasterize`, `composer/emf_fallback` |
| Poppler (pdftoppm) | `brew install poppler` | `rasterize/poppler` |
| vtracer | `cargo install vtracer` 또는 prebuilt binary | `composer` (CLI 호출) |
| Inkscape (옵션) | `brew install inkscape` | `composer/emf_fallback` 보조 |
| Redis | NAS 보유 인프라 활용 | Phase 2 큐 |
| PostgreSQL + pgvector | NAS:5433 | Phase 2 DB |

`scripts/setup-dev.sh`로 macOS 환경 자동화.

---

## 3. 환경 변수 (.env.example)

```env
# === Core ===
STAR_SLIDE_ENV=development          # development | production
STAR_SLIDE_LOG_LEVEL=INFO
STAR_SLIDE_DATA_DIR=./data
STAR_SLIDE_STORAGE_DIR=./storage

# === GPU ===
STAR_SLIDE_DEVICE=cuda              # cuda | mps | cpu
STAR_SLIDE_GPU_INDEX=0

# === Models ===
STAR_SLIDE_SAM_MODEL=sam3.1
STAR_SLIDE_SAM_WEIGHTS=./models/sam3.1.pt
STAR_SLIDE_OCR_MODEL=paddleocr_ppocrv5_korean
STAR_SLIDE_INPAINT_MODEL=lama

# === External APIs (옵션, 기본 OFF) ===
STAR_SLIDE_DISABLE_EXTERNAL_API=1   # 1로 두면 모든 외부 호출 강제 차단
OPENAI_API_KEY=                     # gpt-image-2 옵션
ANTHROPIC_API_KEY=                  # Claude API 옵션 (VLM 보조)

# === DB (Phase 2) ===
STAR_SLIDE_DB_URL=postgresql+psycopg://user:pass@nas:5433/star_slide
STAR_SLIDE_REDIS_URL=redis://nas:6379/0

# === Storage (Phase 3) ===
STAR_SLIDE_S3_ENDPOINT=
STAR_SLIDE_S3_BUCKET=
STAR_SLIDE_S3_ACCESS_KEY=
STAR_SLIDE_S3_SECRET_KEY=

# === Feature Flags ===
STAR_SLIDE_ENABLE_VLM_CLASSIFY=0
STAR_SLIDE_ENABLE_GPT_INPAINT=0
```

---

## 4. Day 1 초기화 명령 (실행 순서)

```bash
# 1. 작업 디렉토리 진입
cd /Users/starhunter/StudyProj/aiporj/star-slide

# 2. Python 버전 고정
echo "3.11" > .python-version

# 3. uv로 가상환경 + 의존성
uv venv
uv pip install --upgrade pip

# 4. pyproject.toml 작성 (위 §2.2 참조)
# (직접 편집)

# 5. 기본 의존성 설치
uv sync

# 6. dev 도구
uv pip install --group dev

# 7. pre-commit 설정
cat > .pre-commit-config.yaml <<'EOF'
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, types-requests]
EOF
uv run pre-commit install

# 8. 초기 패키지 골격
mkdir -p star_slide/{schema,input,rasterize,segmentation,classify,ocr,inpaint,font,table,chart,composer,qa,pipeline,api,workers,storage,db,audit,cli}
touch star_slide/__init__.py star_slide/_version.py star_slide/config.py
for d in schema input rasterize segmentation classify ocr inpaint font table chart composer qa pipeline api workers storage db audit cli; do
  touch star_slide/$d/__init__.py
done

# 9. 테스트 골격
mkdir -p tests/{unit,integration,e2e,fixtures}
touch tests/__init__.py tests/conftest.py

# 10. 데이터/실험 디렉토리
mkdir -p data/{samples,labels,fonts,font_embeddings,golden}
mkdir -p experiments/{h1_sam31,h2_custgeom,h3_ocr}

# 11. 외부 바이너리 (macOS)
brew install libreoffice poppler inkscape || echo "이미 설치됨"

# 12. vtracer (Rust 또는 prebuilt)
# Option A: cargo
# cargo install vtracer
# Option B: prebuilt (https://github.com/visioncortex/vtracer/releases)

# 13. .env 작성
cp .env.example .env
# (편집)

# 14. .gitignore
cat > .gitignore <<'EOF'
__pycache__/
*.py[cod]
.venv/
.env
storage/
models/
data/font_embeddings/
data/samples/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
.DS_Store
.session/
experiments/*/results/
EOF

# 15. README 골격
cat > README.md <<'EOF'
# Star-Slide

AI 슬라이드 이미지를 편집 가능 PPTX로 역변환하는 후처리 엔진.

## 문서
- [통합 PRD](docs/Star-Slide_PRD.md)
- [기술 결정 (ADR)](docs/Star-Slide_TechDecisions.md)
- [상세 개발 계획](docs/Star-Slide_DevPlan.md)
- [프로젝트 구조](docs/Star-Slide_Structure.md)

## 개발 시작
```bash
uv sync
uv run pre-commit install
uv run pytest
uv run star-slide --help
```
EOF

# 16. 첫 커밋
git init
git add .
git commit -m "chore: Initialize Star-Slide project structure"
```

---

## 5. CI 기본 워크플로우 (.github/workflows/ci.yml)

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v2
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy star_slide/

  test-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v2
      - run: uv sync --all-extras
      - run: uv run pytest tests/unit -v --cov=star_slide --cov-report=xml
      - uses: codecov/codecov-action@v4

  test-golden:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v2
      - run: |
          sudo apt-get install -y libreoffice poppler-utils
          curl -L -o vtracer.tar.gz https://github.com/visioncortex/vtracer/releases/download/0.6.4/vtracer-x86_64-unknown-linux-musl.tar.gz
          tar xzf vtracer.tar.gz && sudo mv vtracer /usr/local/bin/
      - run: uv sync --all-extras
      - run: uv run pytest tests/e2e/test_golden_samples.py -v
```

---

## 6. 모듈별 Owner와 의존성 그래프

```
[input] ────► [rasterize] ──────► [segmentation] ──┐
                                                    │
                                  [classify] ◄──────┘
                                       │
                ┌──────────────────────┼──────────────────────┐
                ▼                      ▼                      ▼
              [ocr] ───► [font]   [composer/svg2custgeom]   [table]
                │                       │                      │
                ▼                       ▼                      │
            [inpaint]           [composer/emf_fallback]        │
                │                       │                      │
                └────► [composer/presentation] ◄───────────────┘
                              │
                              ▼
                            [qa]
                              │
                              ▼
                  [pipeline/orchestrator]
                              │
                              ▼
                           [cli] / [api+workers]
```

이 의존성 그래프대로 구현하면 모듈 간 결합 최소화. 각 모듈은 자체 테스트 가능.

---

## 7. 개발 환경 검증 체크리스트

Day 1 끝나기 전 다음 모두 통과 확인:

```bash
# Python 환경
uv run python -c "import sys; assert sys.version_info >= (3,11)"

# 핵심 라이브러리
uv run python -c "import pptx; import pdf2image; import lxml; print('OK')"

# 외부 바이너리
which soffice libreoffice  # 둘 중 하나
which pdftoppm
which vtracer

# Linting/Typing
uv run ruff check .
uv run mypy star_slide/

# 테스트 실행
uv run pytest --collect-only

# CLI entrypoint
uv run star-slide --help

# pre-commit
uv run pre-commit run --all-files

# Git
git status  # 첫 커밋 완료 확인
```

모든 항목 ✅이면 **Phase 0 P0-T01 완료** → P0-T02 (샘플셋 수집) 진입.

---

## 8. 모듈 작성 컨벤션

### 8.1 파일 헤더 템플릿

```python
"""
{모듈 짧은 설명}

본 모듈은 Star-Slide 파이프라인의 [Phase X] 단계를 담당한다.

Refs:
  - PRD §X.Y
  - ADR-NNN
"""
```

### 8.2 함수 시그니처 컨벤션

- 입력/출력 타입은 항상 명시 (mypy strict)
- pydantic 모델은 `schema` 모듈에만 정의, 다른 모듈은 import
- 외부 I/O(파일/모델/API)는 `_` 접두 private 함수에서 격리
- 부수 효과 있는 함수는 동사로 시작 (`render_slide`, `extract_text`)
- 순수 함수는 명사로 (`bbox_iou`, `glyph_embedding`)

### 8.3 테스트 명명

```
tests/unit/test_<module>/test_<function>.py
tests/integration/test_<feature>.py
tests/e2e/test_<scenario>.py
```

### 8.4 커밋 메시지

`~/.claude/rules/workflow.md` 적용:
- `feat:` 새 기능
- `fix:` 버그 수정
- `refactor:` 구조 변경 (행동 변화 X)
- `test:` 테스트
- `docs:` 문서
- `chore:` 빌드/설정
- `perf:` 성능

학습 태그(footer): `[insight]`, `[gotcha]`, `[decision]`, `[followup]`

---

## 9. 다음 단계

이 문서대로 디렉토리/스켈레톤을 초기화하면 Phase 0 P0-T01이 완료된다.

다음:
1. `Star-Slide_DevPlan.md` §"즉시 실행 가능한 첫 5일 백로그" 따라가기
2. P0-T02 샘플셋 수집 시작
3. 사용자 결정 필요 항목(부록 B 체크리스트) 확정

---

*본 문서는 Phase 0 진행 중에도 갱신 가능. 디렉토리/의존성 변경 시 즉시 반영.*
