# Star-Slide 상세 개발 계획서 v1.0

> 작성일: 2026-04-25
> 기반: `Star-Slide_PRD.md` v1.0, `Star-Slide_TechDecisions.md`
> 대상: 즉시 실행 가능한 수준의 Phase별 태스크, 검증 기준, 의존성

## 0. 본 문서의 사용법

1. **Phase 0부터 순차 실행** — 각 Phase는 다음 Phase의 의존성을 가지므로 순서 변경 금지
2. **각 태스크는 Atomic 검증 기준(Acceptance Criteria, AC)을 가짐** — AC가 통과하지 않으면 다음 태스크로 진행 금지 (verification-protocol 적용)
3. **Risk Checkpoint** — 각 Phase 끝의 체크포인트에서 한 가지라도 실패 시 Phase 0으로 회귀하거나 PRD 수정
4. **위임 가이드** — 태스크별로 적합한 에이전트(executor/build-fixer/test-engineer 등)를 명시. 추론/설계는 직접 수행

---

## 전체 일정 요약

| Phase | 기간 | 목표 | Exit Gate |
|---|---|---|---|
| **Phase 0: Spike** | 2주 (10 영업일) | 3개 핵심 가설 검증 + 100장 샘플셋 + custGeom PoC | 가설 3개 모두 GREEN, 또는 GO/NO-GO 결정 |
| **Phase 1: Vertical Slice MVP** | 4주 (20 영업일) | CLI end-to-end: PPTX → PPTX | MVP Exit Criteria 8개 모두 통과 |
| **Phase 2: API + 품질 강화** | 4주 (20 영업일) | REST API + 차트 C2 + QA 자동화 + 폰트 임베딩 | API 안정성 + 100장 회귀 통과 |
| **Phase 3: 웹 에디터 베타** | 6주 (30 영업일) | Next.js 에디터 + 결제 + 사용량 미터링 | 5명 베타 사용자 NPS ≥ 30 |
| **Phase 4: 고급 복원 + Enterprise** | 8주 (40 영업일) | 차트 native + VLM 자연어 편집 + VPC | 첫 Enterprise 계약 가능 상태 |

총 24주 (약 6개월) — MVP까지는 **6주**.

---

# Phase 0 — Research & Spike (2주)

## P0 목표

> **"이 프로젝트가 기술적으로 가능한지 빠르게 증명"**

다음 3개 가설 중 하나라도 **NO-GO**이면 PRD 자체를 재검토:

| 가설 | Atomic AC |
|---|---|
| **H1** SAM 3.1이 한글 슬라이드의 의미 객체를 IoU ≥ 0.8로 분리 | 50장 수동 라벨 슬라이드에서 객체별 평균 IoU ≥ 0.8, 텍스트 영역에서 글자 단위 분해율 ≤ 30% (사전 검출 후) |
| **H2** vtracer SVG → `a:custGeom` → PowerPoint에서 도형 편집 모드 진입 | 단순 도형 10종, 아이콘 20종 변환 후 PowerPoint 2019+ Microsoft 365에서 "도형 편집" 메뉴 활성화 확인, SSIM ≥ 0.85 |
| **H3** PaddleOCR PP-OCRv5 한국어 모델 슬라이드 도메인 CER ≤ 7% | 한글 슬라이드 30장 라벨 vs OCR 결과 평균 CER ≤ 7% |

## P0 태스크

### P0-T01: 프로젝트 스켈레톤 초기화 — 0.5d

**의존**: 없음
**담당**: `executor`
**산출물**: monorepo 골격, lock 파일, CI 기초

**Steps**
- [ ] `Star-Slide_Structure.md`(별도 문서)에 따라 디렉토리 생성
- [ ] `pyproject.toml` (uv 관리), Python 3.11+ pin
- [ ] `pre-commit` (ruff + mypy + black)
- [ ] GitHub Actions 기본 워크플로우 (lint + 단위 테스트)
- [ ] `.env.example`, `.gitignore`, `README.md` 골격

**AC**
- [ ] `uv sync` 성공
- [ ] `uv run ruff check .` 통과
- [ ] `uv run pytest` (빈 테스트라도) 통과
- [ ] CI 1회 GREEN

### P0-T02: 샘플셋 구축 (100장) — 2d

**의존**: P0-T01
**담당**: 직접 (사용자 + 사전 데이터 수집)
**산출물**: `data/samples/` 100장 + `data/labels/`

**Steps**
- [ ] NotebookLM 한글 슬라이드 30장 수집 (사용자 본인 콘텐츠)
- [ ] Gamma/Beautiful.ai 출력 10장
- [ ] 한국 정부/기업 공개 PDF 보고서 슬라이드 20장
- [ ] 한글 교육자료/논문 슬라이드 15장
- [ ] 인포그래픽 10장, 차트 10장, 표 5장
- [ ] 각 슬라이드별 JSON 라벨 (객체 bbox, 텍스트 내용, 분류) — 수동 또는 반자동 (CVAT 등)
- [ ] 라벨 스키마는 `Star-Slide_PRD.md` §8 Layer Schema와 일치

**AC**
- [ ] 100장 + 라벨 JSON 100개 존재
- [ ] `pytest tests/data/test_sample_integrity.py` (라벨 일관성 검사) 통과
- [ ] 데이터셋 README에 출처/라이선스 명시 (저작권 안전 확인)

### P0-T03: H1 검증 — SAM 3.1 슬라이드 객체 분리 — 2d

**의존**: P0-T01, P0-T02
**담당**: `executor` + `scientist`(분석)
**산출물**: `experiments/h1_sam31/` (notebook + report)

**Steps**
- [ ] SAM 3.1 모델 로드 (HF/공식 weights)
- [ ] `SamAutomaticMaskGenerator`로 50장 처리
- [ ] EAST/CRAFT 텍스트 검출기로 텍스트 라인 사전 검출 → SAM 마스크와 병합
- [ ] 라벨 ground truth와 IoU 계산
- [ ] 객체 평균 IoU, 텍스트 영역 글자 단위 분해율 측정

**AC**
- [ ] **IoU ≥ 0.8 평균** (목표 달성 시 GREEN)
- [ ] 텍스트 영역 글자 분해율 ≤ 30% (사전 검출 후)
- [ ] H1 검증 보고서 `experiments/h1_sam31/REPORT.md` 작성 (수치 + 시각 예시 + 실패 케이스 분석)

**Risk Branch**
- IoU < 0.8 → SAM 2 fallback 평가, 슬라이드 도메인 fine-tune 필요성 검토 → P0 연장 1주

### P0-T04: H2 검증 — vtracer + custGeom 변환 PoC — 2.5d

**의존**: P0-T01
**담당**: `executor`
**산출물**: `experiments/h2_custgeom/` + `star_slide/composer/svg2custgeom.py` PoC

**Steps**
- [ ] vtracer 바이너리/Python wrapper 설치 + 호출 wrapper
- [ ] svg-points로 SVG path d= 파싱
- [ ] EMU 좌표 변환기 (914400 EMU/inch)
- [ ] `<a:custGeom>` XML 빌더 (M/L/C/Q/Z → moveTo/lnTo/cubicBezTo/quadBezTo/close)
- [ ] python-pptx Shape에 lxml로 `_element` 직접 inject
- [ ] 단순 도형 10종(사각형/원/별/화살표/체크 등) + 아이콘 20종 변환
- [ ] PowerPoint 2019+ 또는 Microsoft 365에서 수동 검증 — "도형 편집" 메뉴 활성화 확인
- [ ] LibreOffice headless로 재렌더 → 원본 SSIM 측정

**AC**
- [ ] 30개 중 25개 이상에서 PowerPoint "도형 편집" 진입 가능
- [ ] 평균 SSIM ≥ 0.85
- [ ] arc(`A`) 명령 처리 알려진 한계 문서화
- [ ] H2 검증 보고서 `experiments/h2_custgeom/REPORT.md`

**Risk Branch**
- 진입 가능 < 25/30 → custGeom 사양 재학습, EMF fallback 비중 상향 검토
- arc 변환 비용 과다 → arc는 EMF로 우회

### P0-T05: H3 검증 — PaddleOCR 한국어 슬라이드 정확도 — 1.5d

**의존**: P0-T01, P0-T02
**담당**: `executor` + `scientist`
**산출물**: `experiments/h3_ocr/` REPORT

**Steps**
- [ ] PaddleOCR PP-OCRv5 + `korean_PP-OCRv5_mobile_rec` 설치
- [ ] 한글 슬라이드 30장에 대해 OCR 실행
- [ ] 라벨 텍스트와 CER/WER 계산
- [ ] Surya OCR로 동일 슬라이드 처리, 비교
- [ ] 신뢰도 < 0.7 텍스트의 분포 분석

**AC**
- [ ] PaddleOCR 평균 CER ≤ 7% (GREEN)
- [ ] Surya 평균 CER ≤ 5% (보조 검증)
- [ ] H3 검증 보고서

**Risk Branch**
- CER > 7% → PaddleOCR-VL-1.5 평가, 또는 슬라이드 fine-tune

### P0-T06: Layer Schema v0 확정 — 0.5d

**의존**: P0-T03, P0-T04, P0-T05
**담당**: 직접 (architect 검토)
**산출물**: `star_slide/schema/layer_v0.py` (pydantic 모델) + `docs/Star-Slide_PRD.md` §8 업데이트

**Steps**
- [ ] PRD §8 Layer Schema를 pydantic 모델로
- [ ] Phase 0 PoC 결과 반영 (실제 출력 가능한 필드만)
- [ ] JSON Schema 자동 export 설정 (스키마 버전 관리)

**AC**
- [ ] `pytest tests/schema/` 통과 (직렬화/역직렬화 round-trip)
- [ ] PRD §8 ↔ 코드 일치성 검증 (md 예제와 pydantic 모델 비교 테스트)

### P0-T07: Phase 0 Exit Gate — 0.5d

**의존**: 모든 Phase 0 태스크
**담당**: 직접 + `critic`(리뷰)
**산출물**: `docs/Star-Slide_Phase0_Report.md` + GO/NO-GO 결정

**Decision Tree**

```
H1 GREEN + H2 GREEN + H3 GREEN  → Phase 1 진입 (계획대로)
H1 RED                          → SAM 2 fallback 또는 fine-tune (1주 추가)
H2 RED                          → custGeom 사양 재검토, EMF fallback 비중 ↑
H3 RED                          → PaddleOCR-VL-1.5 또는 슬라이드 OCR fine-tune
2개 이상 RED                    → PRD 본질적 재검토 (NO-GO 가능)
```

---

# Phase 1 — Vertical Slice MVP (4주)

## P1 목표

> **"단일 PPTX 파일을 CLI 한 줄로 편집 가능 PPTX로 변환"**

```bash
$ star-slide convert deck.pptx -o deck-edited.pptx --report report.json
```

이 한 줄이 동작하면 Phase 1 완료.

## P1 스프린트 분해 (1주 단위)

### Week 1: 입력 + 래스터화 + 객체 분해

#### P1-T01: PPTX/PDF/이미지 입력 + 검증 — 1.5d

**의존**: Phase 0 완료
**담당**: `executor`
**모듈**: `star_slide/input/`

**Steps**
- [ ] 파일 검증 (확장자/MIME/크기/암호화/손상)
- [ ] PPTX → 슬라이드 단위 picture/textbox 추출 (python-pptx)
- [ ] PDF → 페이지 단위 PNG (pdf2image/Poppler)
- [ ] PNG/JPG → 단일 또는 ZIP 다중
- [ ] 슬라이드 마스터 + 본문 합성 (LibreOffice headless 호출)

**AC**
- [ ] `pytest tests/input/` 단위 테스트 모두 통과 (10+ 테스트)
- [ ] 손상 PPTX, 암호 PPTX, 빈 PPTX 각각 명확한 에러
- [ ] `star-slide validate <file>` CLI 명령 동작

#### P1-T02: 슬라이드 래스터화 + 좌표 변환 — 1d

**의존**: P1-T01
**담당**: `executor`
**모듈**: `star_slide/rasterize/`

**Steps**
- [ ] LibreOffice headless 호출 wrapper (`subprocess` + 타임아웃)
- [ ] 2x DPI 렌더링 + 썸네일 256x144
- [ ] EMU ↔ px 변환 행렬 저장
- [ ] 슬라이드 비율 보존 (16:9, 4:3, custom)

**AC**
- [ ] 20장 PPTX 래스터화 ≤ 60초 (A100 무관, LibreOffice 단독)
- [ ] EMU↔px round-trip 오차 ≤ 1px
- [ ] 단위 테스트 통과

#### P1-T03: SAM 3.1 Worker — 2d

**의존**: P1-T02, Phase 0 H1 GREEN
**담당**: `executor`
**모듈**: `star_slide/segmentation/`

**Steps**
- [ ] SAM 3.1 모델 로드 (lazy + 캐싱)
- [ ] `SamAutomaticMaskGenerator` 래퍼
- [ ] 사전 보호: 차트 디텍터(YOLO chart) + 텍스트 디텍터(EAST/CRAFT) 영역
- [ ] 마스크 후처리 (IoU/area 필터)
- [ ] 마스크 → bbox EMU 변환

**AC**
- [ ] H1 검증 샘플에서 평균 IoU ≥ 0.8 재현
- [ ] 단일 슬라이드 처리 ≤ 15초 (A100)
- [ ] OOM/CUDA 에러 시 슬라이드 단위 재시도 + skip

#### P1-T04: 객체 분류 (룰 기반) — 1d

**의존**: P1-T03
**담당**: `executor`
**모듈**: `star_slide/classify/`

**Steps**
- [ ] aspect ratio + edge density + color count + text-likeness 휴리스틱
- [ ] `{text, icon, shape, chart, table, photo, background, decoration}` 라벨링
- [ ] 신뢰도 산정
- [ ] (옵션) VLM 보조 분류 (기본 OFF, ENV로 제어)

**AC**
- [ ] H1 검증 샘플에서 분류 정확도 ≥ 80% (라벨 ground truth 대비)

### Week 2: OCR + 인페인팅 + 폰트

#### P1-T05: PaddleOCR Worker + 앙상블 — 2d

**의존**: P1-T04
**담당**: `executor`
**모듈**: `star_slide/ocr/`

**Steps**
- [ ] PaddleOCR PP-OCRv5 한국어 모델 wrapper
- [ ] Surya OCR wrapper
- [ ] 앙상블: 신뢰도 < 0.7 → Surya 재시도, 결과 비교
- [ ] 줄바꿈 재계산 (bbox 폭 + 글자 수 + 단어 경계)
- [ ] 색상 추정 (k-means 2)
- [ ] 폰트 크기 추정 (글자 높이 px → pt)

**AC**
- [ ] H3 검증 샘플 CER ≤ 7%
- [ ] 단위 테스트 (15+ 케이스, 한글/영문/숫자/혼합)

#### P1-T06: LaMa 인페인팅 Worker — 1.5d

**의존**: P1-T05
**담당**: `executor`
**모듈**: `star_slide/inpaint/`

**Steps**
- [ ] IOPaint LaMa 모델 wrapper (GPU)
- [ ] 텍스트 마스크 (OCR bbox + 4-8px padding) → 인페인팅
- [ ] 인페인팅 전후 SSIM 검증
- [ ] SSIM < 0.7 → 원본 유지 (안전 fallback)

**AC**
- [ ] 한글 슬라이드 30장 인페인팅 후 시각 검수에서 90% 이상 자연스러움 (수동 검수)
- [ ] 단위 테스트 (마스크 형태별 5+ 케이스)

#### P1-T07: 한글 폰트 매칭 (자동 + 후보 N) — 1.5d

**의존**: P1-T05
**담당**: `executor`
**모듈**: `star_slide/font/`

**Steps**
- [ ] 무료 한글 폰트 풀 30종 다운로드 + 라이선스 메타
- [ ] 글리프 렌더 + 임베딩 계산 (perceptual hash 또는 stylometric features)
- [ ] (Phase 1은 임베딩 파일로 저장, Phase 2에서 pgvector 마이그레이션)
- [ ] OCR 글리프 → 임베딩 → cosine top-5 → 픽셀 SSIM → 상위 3 후보 출력

**AC**
- [ ] 임베딩 사전 계산 build script (`uv run star-slide build-fonts`)
- [ ] 30장 한글 슬라이드에서 top-3 정확도 ≥ 70% (시각 검수)
- [ ] layer schema에 `font_candidates` 정상 기록

### Week 3: 벡터화 + 표 + PPTX 조립

#### P1-T08: vtracer + svg→custGeom 변환기 — 2d

**의존**: Phase 0 H2 GREEN, P1-T04
**담당**: `executor`
**모듈**: `star_slide/composer/svg2custgeom.py`

**Steps**
- [ ] Phase 0 PoC를 production 모듈로 승격
- [ ] path 수 임계값 + 색상 수 임계값 정책
- [ ] SVG arc → cubic bezier 근사 (또는 EMF fallback)
- [ ] 변환 후 SSIM 검증 → 미달 시 EMF fallback
- [ ] EMF fallback (Inkscape CLI 또는 LibreOffice)
- [ ] PNG fallback (최종)

**AC**
- [ ] 단위 테스트: 도형 10종, 아이콘 20종 변환 후 PowerPoint 편집 모드 진입 (수동 1회 + 자동 SSIM)
- [ ] fallback 체인 작동 확인 (path > 200, arc 다수 등)

#### P1-T09: 표 영역 감지 + 셀 OCR + T1/T2 — 2d

**의존**: P1-T05, P1-T03
**담당**: `executor`
**모듈**: `star_slide/table/`

**Steps**
- [ ] PP-StructureV3 또는 LayoutParser로 표 영역 검출
- [ ] 직선 검출 + 셀 격자 추정 (Hough transform)
- [ ] 셀 단위 OCR
- [ ] T1: 표 이미지 + overlay text box
- [ ] T2: 선/셀/텍스트를 grouped shape (python-pptx group)

**AC**
- [ ] 표 5장 샘플에서 행/열 정확도 ≥ 80%
- [ ] T1, T2 모두 PowerPoint에서 정상 표시

#### P1-T10: PPTX 조립 (Composer) — 1.5d

**의존**: P1-T07, P1-T08, P1-T09, P1-T06
**담당**: `executor`
**모듈**: `star_slide/composer/`

**Steps**
- [ ] python-pptx Presentation 생성 (슬라이드 크기, 비율 보존)
- [ ] 객체 타입별 분기 (text → textbox, shape → custGeom/auto, photo → picture, table → group/table)
- [ ] z-order 적용 + 정렬 스냅 (5% 임계 클러스터링)
- [ ] 슬라이드 background에 인페인팅 결과 적용

**AC**
- [ ] 20장 PPTX 조립 ≤ 30초
- [ ] 결과 PPTX가 PowerPoint 2019+ Microsoft 365에서 정상 열림 (수동 + LibreOffice headless 검증)

### Week 4: QA + CLI + 통합 + Exit

#### P1-T11: Visual QA 자동화 — 1.5d

**의존**: P1-T10
**담당**: `executor` + `test-engineer`
**모듈**: `star_slide/qa/`

**Steps**
- [ ] LibreOffice headless로 export PPTX 재렌더
- [ ] 원본 vs export SSIM 측정
- [ ] 누락 객체 수, 텍스트 overflow, 이미지 깨짐 검출
- [ ] fallback 객체 ID 목록 수집
- [ ] `report.json` 스키마 정의 + 출력

**AC**
- [ ] 100장 샘플셋에서 평균 SSIM ≥ 0.85
- [ ] 슬라이드 단위 실패 격리 (한 장 실패가 전체 중단 X)
- [ ] report.json 검증 테스트

#### P1-T12: CLI 인터페이스 — 1d

**의존**: P1-T11
**담당**: `executor`
**모듈**: `star_slide/cli/`

**Steps**
- [ ] `typer` 기반 CLI
- [ ] `convert` 명령: 입력/출력/리포트/옵션
- [ ] `validate` 명령: 파일 검증만
- [ ] `build-fonts` 명령: 폰트 임베딩 빌드
- [ ] 진행률 표시 (rich progress)
- [ ] 에러 메시지 (사용자 친화적)

**AC**
- [ ] `star-slide --help` 정상 출력
- [ ] 6장 PPTX 변환 데모 시나리오 통과 (E2E 테스트)

#### P1-T13: 통합 테스트 + 회귀 — 1.5d

**의존**: P1-T12
**담당**: `test-engineer`
**모듈**: `tests/e2e/`

**Steps**
- [ ] 골든 샘플 10장 (Phase 0 라벨된 것)
- [ ] 각 샘플 변환 후 메트릭 임계값 비교
- [ ] CI에 회귀 테스트 추가 (PR마다)
- [ ] 한 장씩 시각 비교 HTML 리포트 생성

**AC**
- [ ] 10장 골든 샘플 모두 임계값 통과
- [ ] CI에서 자동 실행

#### P1-T14: Phase 1 Exit Gate — 0.5d

**의존**: 모든 P1 태스크
**담당**: 직접 + `verifier`
**산출물**: `docs/Star-Slide_Phase1_Report.md`

**MVP Exit Criteria 검증** (PRD §11.3):

- [ ] 한글 OCR CER ≤ 7%
- [ ] 텍스트 객체 직접 편집 가능 비율 ≥ 80%
- [ ] 평균 편집 가능도 ≥ 60%
- [ ] 20장 PPTX A100 1대로 ≤ 10분
- [ ] export PPTX가 PowerPoint 2019+에서 정상 열림
- [ ] 슬라이드 단위 실패 격리
- [ ] 원본 대비 export SSIM ≥ 0.85
- [ ] CLI/API 양쪽 (P1은 CLI만 + API skeleton) end-to-end

---

# Phase 2 — API + 품질 강화 (4주)

## P2 목표

> **"REST API + 차트 C2 + QA 자동화 + 폰트 임베딩 pgvector"**

### Week 5-6: API 서버 + 큐

- **P2-T01** FastAPI 서버 + 인증(API key) — 2d
- **P2-T02** Celery + Redis 큐 + GPU worker 분리 — 2d
- **P2-T03** PostgreSQL 스키마 + Alembic 마이그레이션 — 1.5d
- **P2-T04** API 엔드포인트 구현 (PRD §9) — 2.5d
- **P2-T05** S3 호환 스토리지 추상화 (로컬 + MinIO 옵션) — 1d
- **P2-T06** 작업 상태 관리 (state machine) + 재시도 — 1d

### Week 7: 차트 C2 + 폰트 pgvector

- **P2-T07** 차트 영역 검출 + grouped shape 복원 (C2) — 3d
- **P2-T08** 차트 라벨 OCR (C1) — 1d
- **P2-T09** 폰트 임베딩 pgvector 마이그레이션 — 1d

### Week 8: 표 T3 + QA + 회귀

- **P2-T10** 표 native T3 (`add_table`) — 2d
- **P2-T11** export QA 시각 리포트 (HTML + 슬라이드별 SSIM) — 1.5d
- **P2-T12** 100장 회귀 테스트 셋 — 1.5d
- **P2-T13** Phase 2 Exit Gate — 0.5d

**Exit Gate**:
- [ ] API E2E 안정성 (1000회 호출 무중단)
- [ ] 100장 회귀에서 평균 편집 가능도 ≥ 70%
- [ ] 차트 C2 grouped shape 정상 동작
- [ ] 표 T3에서 row/col 정확도 ≥ 90%

---

# Phase 3 — 웹 에디터 베타 (6주)

## P3 목표

> **"5명 베타 사용자가 NPS ≥ 30 부여하는 수준의 웹 에디터"**

### Week 9-10: Editor 기반

- **P3-T01** Next.js 15 프로젝트 + tailwind + shadcn — 1d
- **P3-T02** Konva.js 캔버스 + 객체 렌더링 — 3d
- **P3-T03** 객체 선택/이동/리사이즈/삭제/복제 — 2d
- **P3-T04** undo/redo (zustand + history middleware) — 1d
- **P3-T05** 슬라이드 썸네일 좌측 패널 — 1d

### Week 11-12: 편집 기능

- **P3-T06** 텍스트 편집 (더블클릭 → contenteditable) — 2d
- **P3-T07** 폰트 후보 선택 UI (1클릭) — 1d
- **P3-T08** 색상 피커 + 속성 패널 — 2d
- **P3-T09** 레이어 패널 (z-order/lock/visibility) — 1.5d
- **P3-T10** OCR 검수 UI (원본 crop vs 인식 텍스트) — 2d
- **P3-T11** 원본/편집/diff 보기 토글 — 1d
- **P3-T12** 객체 병합/분리 (잘못 묶인 객체 사용자 보정) — 1.5d

### Week 13: 결제 + 사용량

- **P3-T13** Stripe 통합 (Pro 플랜) — 2d
- **P3-T14** 사용량 미터링 (슬라이드 수 + GPU 시간) — 1.5d
- **P3-T15** 운영 대시보드 (job queue, GPU 사용률, 실패율) — 1.5d

### Week 14: 베타 운영

- **P3-T16** 5명 베타 사용자 모집 + 온보딩 — 0.5d
- **P3-T17** 사용자 피드백 수집 (NPS, 인터뷰) — 4d
- **P3-T18** 핫픽스 사이클 — 4d
- **P3-T19** Phase 3 Exit — 0.5d

**Exit Gate**:
- [ ] NPS ≥ 30 (5명 중 promoter ≥ 2)
- [ ] 베타 기간 critical bug 0건
- [ ] Stripe 결제 동작 검증
- [ ] 사용자 1인당 평균 슬라이드 수정 시간 ≤ 2분

---

# Phase 4 — 고급 복원 + Enterprise (8주)

## P4 목표

> **"차트 native, VLM 자연어 편집, VPC 배포 가능"**

### Week 15-16: 차트 데이터 추정

- **P4-T01** DePlot worker 통합 — 2d
- **P4-T02** Claude API 후처리 (옵션, ZDR 확인) — 1.5d
- **P4-T03** 차트 데이터 검수 UI (사용자 표 수정) — 2d
- **P4-T04** native PPT chart 생성 (C4) — 2d
- **P4-T05** Track 2 반자동 (신뢰도 < 0.8 → 사용자 입력) — 1.5d

### Week 17-18: VLM 의미적 편집

- **P4-T06** VLM 슬라이드 의미 분류 (제목/목차/본문/비교/인포그래픽) — 2d
- **P4-T07** 자연어 편집 명령 ("막대 색을 회사 컬러로") — 3d
- **P4-T08** 자산 라이브러리 (CLIP 임베딩 + 검색) — 2d
- **P4-T09** 색상 팔레트 추출 + 테마 일괄 변경 — 1.5d

### Week 19-20: 다이어그램 + SmartArt

- **P4-T10** 다이어그램 디텍터 (LayoutParser fine-tune) — 3d
- **P4-T11** SmartArt 매핑 (노드+엣지 → SmartArt) — 3d
- **P4-T12** 인포그래픽 패턴 라이브러리 — 2d

### Week 21-22: Enterprise

- **P4-T13** 감사 로그 + 보존 정책 — 2d
- **P4-T14** SSO (SAML/OIDC) — 2d
- **P4-T15** VPC/On-prem 패키징 (Docker Compose + Helm) — 3d
- **P4-T16** 보안 백서 + DPA — 1.5d
- **P4-T17** Phase 4 Exit — 0.5d

**Exit Gate**:
- [ ] 차트 C4 native 생성 정확도 ≥ 70% (수동 검수)
- [ ] 자연어 편집 5종 시나리오 정상 동작
- [ ] On-prem Docker Compose로 1대 서버에 30분 내 설치
- [ ] 첫 Enterprise 견적/계약 가능 상태

---

# 운영 가이드

## 일일 워크플로우 (Phase 0-1 진행 중)

```
[09:00] 어제 진행 리뷰 + .session/CONTINUITY.md 업데이트
[09:30] 오늘 태스크 1개 in_progress 마킹 + 시작
[12:00] 중간 점검 (AC 진행률)
[15:00] 검증 (테스트/빌드/SSIM)
[17:00] PR 또는 커밋 (Tidy First — 구조/행동 분리)
[17:30] 다음날 태스크 준비 + 회고 (실패/학습 기록)
```

## 검증 프로토콜 (모든 태스크 공통)

태스크 완료 주장 시 다음 증거를 첨부:

| 주장 | 증거 |
|---|---|
| "구현 완료" | `uv run pytest tests/<module>/` 통과 + `uv run mypy star_slide/` 통과 |
| "성능 목표 달성" | 벤치마크 출력 (시간/메모리) |
| "정확도 목표 달성" | 메트릭 수치 + 샘플셋 ID |
| "PowerPoint 호환 확인" | 스크린샷 또는 LibreOffice 재렌더 SSIM |

## 위임 규칙

| 작업 유형 | 에이전트 | 비고 |
|---|---|---|
| 단일 모듈 구현 | `executor` | TDD 사이클 |
| 빌드/타입 에러 | `build-fixer` | 최소 변경 |
| 통합 테스트/회귀 | `test-engineer` | 골든 샘플 |
| 성능 분석 | `performance-reviewer` | profile + flamegraph |
| 보안 리뷰 | `security-reviewer` | OWASP Top 10 + 외부 API 호출 감사 |
| 데이터 분석 (벤치마크) | `scientist` | Python notebook |
| 디자인 (Phase 3) | `designer` | Konva 컴포넌트 |
| 복잡 자율 구현 | `deep-executor` | Phase 4 자연어 편집 |
| 계획 리뷰 | `critic` | 매 Phase Exit 전 |

## 리스크 모니터링 (주간)

매주 Phase 진행 중 다음 항목 점검:

- [ ] SAM License 변경 모니터링 (Meta blog/GitHub)
- [ ] PaddleOCR 버전 업데이트 (한국어 정확도 회귀)
- [ ] gpt-image-2 가격/정책 변경
- [ ] vtracer/python-pptx 신규 버전 (Breaking change)

## 메모리/세션 연속성

- `.session/CONTINUITY.md` 매일 업데이트 (Phase, 진행 태스크, 블로커, 다음 단계)
- Auto Memory에 범용 학습(예: SAM 라이선스 패턴, custGeom 변환 함정) 승격
- 각 Phase Exit Report는 `docs/Star-Slide_Phase{N}_Report.md`로 영구 보존

---

# 즉시 실행 가능한 첫 5일 백로그

```
Day 1 (월)
├── P0-T01 프로젝트 스켈레톤 (오전)
├── P0-T01 CI 기초 (오후)
└── 저녁: 샘플셋 수집 시작 (NotebookLM 슬라이드 10장)

Day 2 (화)
├── P0-T02 샘플셋 50장까지
└── 라벨링 도구 세팅 (CVAT 또는 단순 JSON)

Day 3 (수)
├── P0-T02 샘플셋 100장 + 라벨 완료
└── P0-T03 SAM 3.1 환경 구축 (모델 다운로드, 추론 코드)

Day 4 (목)
├── P0-T03 50장 처리 + IoU 측정
└── 결과 시각화 + 실패 케이스 분석

Day 5 (금)
├── P0-T03 H1 검증 보고서 작성
├── 주간 회고
└── 다음 주: P0-T04 vtracer + custGeom PoC
```

---

# 부록 A: 디렉토리 구조 (최소)

```
star-slide/
├── docs/
│   ├── Star-Slide_PRD.md          (통합 PRD)
│   ├── Star-Slide_TechDecisions.md (ADR)
│   ├── Star-Slide_DevPlan.md      (이 문서)
│   ├── Star-Slide_Structure.md    (별도 문서, 다음 작성)
│   ├── Star-SlideEditor.md        (Codex PRD, 원본)
│   ├── star-slidemanager-prd_claude.md
│   └── Star-SlideMaster_PRD_manus.md
│
├── star_slide/                    (Python 패키지)
│   ├── __init__.py
│   ├── cli/                       (typer CLI)
│   ├── api/                       (FastAPI, Phase 2)
│   ├── input/                     (파일 검증/추출)
│   ├── rasterize/                 (LibreOffice/Poppler)
│   ├── segmentation/              (SAM 3.1)
│   ├── classify/                  (객체 분류)
│   ├── ocr/                       (PaddleOCR + Surya)
│   ├── inpaint/                   (LaMa/IOPaint)
│   ├── font/                      (한글 폰트 매칭)
│   ├── table/                     (표 복원)
│   ├── chart/                     (차트, Phase 2)
│   ├── composer/                  (PPTX 조립 + svg2custgeom)
│   ├── qa/                        (visual QA)
│   ├── schema/                    (pydantic Layer Schema)
│   └── workers/                   (Celery tasks, Phase 2)
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── data/
│   ├── samples/                   (100장 + 라벨)
│   ├── fonts/                     (한글 폰트 풀 + 라이선스)
│   └── golden/                    (회귀 테스트 골든)
│
├── experiments/                   (Phase 0 PoC notebook + 보고서)
│   ├── h1_sam31/
│   ├── h2_custgeom/
│   └── h3_ocr/
│
├── web/                           (Phase 3 Next.js)
│
├── scripts/
├── pyproject.toml
├── uv.lock
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
└── README.md
```

(상세는 `docs/Star-Slide_Structure.md` 참조)

---

# 부록 B: 핵심 의사결정 체크리스트

Phase 0 시작 전 사용자가 결정/확인해야 할 사항:

- [ ] **GPU 환경**: A100 80GB 1대 vs RTX 4090 (개발용)
- [ ] **샘플셋 출처**: 사용자 본인 NotebookLM 슬라이드 사용 가능?
- [ ] **라이선스 우려 폰트 풀**: 무료 한글 폰트 30종 리스트 확정 (Phase 0 끝)
- [ ] **라이선스 검토**: SAM License 원문 (Meta 변호사 자문 필요?)
- [ ] **라이선스**: vtracer MIT 확인됨 (정정 완료)
- [ ] **NAS 활용 범위**: PostgreSQL:5433, Redis 그대로 사용?

---

*본 개발 계획서는 살아있는 문서로, 매 Phase Exit Gate에서 갱신된다.*
