# Star-Slide

> AI 슬라이드 이미지를 객체 단위로 분해해 PowerPoint에서 직접 편집 가능한 PPTX로 역변환하는 후처리 엔진.

NotebookLM, Gamma, Tome 등 LLM 기반 슬라이드 생성 도구의 출력은 사실상 각 슬라이드가 단일 비트맵으로 임베드된 형태라 텍스트 한 글자도 수정할 수 없다. Star-Slide는 SAM 3.1 segmentation + PaddleOCR PP-OCRv5(한국어) + vtracer 벡터화 + python-pptx 재조립을 통해 이를 **편집 가능한 객체 트리**로 복원한다.

## 핵심 가치

- **한국어 1급**: PaddleOCR 한국어 모델 + 한글 폰트 후보 매칭 + 사용자 1클릭 폰트 선택
- **편집성 vs 시각 충실도 양자**: custGeom(편집 가능) → EMF → PNG 3단계 폴백
- **OSS-first, Self-hostable**: 외부 API 옵션, 사용자 GPU로 자체 호스팅 가능
- **Editable Level 표시**: native/vector/raster/uncertain/failed 5단계로 사용자에게 명시

## 문서

- [통합 PRD](docs/Star-Slide_PRD.md) — 제품 요구사항, 기능/비기능 요구사항, MVP scope
- [기술 결정 (ADR)](docs/Star-Slide_TechDecisions.md) — 기술 스택 채택 이유, 라이선스 레지스트리
- [상세 개발 계획](docs/Star-Slide_DevPlan.md) — Phase 0~4 태스크 + Acceptance Criteria
- [프로젝트 구조](docs/Star-Slide_Structure.md) — 디렉토리 + 초기화 가이드

## 빠른 시작 (개발자)

```bash
# 1. 의존성 설치 (uv 필요)
uv sync --extra ocr

# 2. pre-commit 훅
uv run pre-commit install

# 3. 테스트
uv run pytest

# 4. CLI
uv run star-slide --help
```

## 변환 사용 예

NotebookLM/Gamma 출력 PPTX를 편집 가능 PPTX로 변환:

```bash
# refdata/에 입력 PPTX 두고 실행
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  uv run star-slide convert run refdata/sample2.pptx \
  -o output/sample2/sample2_edited.pptx \
  --no-libreoffice

# PowerPoint로 결과 열기
open output/sample2/sample2_edited.pptx
```

출력 규약: [`output/README.md`](output/README.md) 참조.

### 외부 바이너리 (OS 레벨)

macOS:
```bash
brew install libreoffice poppler inkscape
# vtracer는 prebuilt binary 또는 cargo install vtracer
```

## 현재 상태

**Phase 0 (Spike)** — 진행 중

3개 핵심 가설 검증:
- H1: SAM 3.1이 한글 슬라이드 의미 객체 IoU ≥ 0.8
- H2: vtracer SVG → custGeom → PowerPoint 도형 편집 가능
- H3: PaddleOCR PP-OCRv5 한국어 슬라이드 CER ≤ 7%

상세는 [DevPlan §Phase 0](docs/Star-Slide_DevPlan.md#phase-0--research--spike-2주) 참조.

## 라이선스

MIT (잠정). Phase 0 끝에 최종 확정.

본 프로젝트가 의존하는 모델/툴의 라이선스는 [TechDecisions §ADR-012 라이선스 레지스트리](docs/Star-Slide_TechDecisions.md#adr-012-라이선스-레지스트리) 참조.
