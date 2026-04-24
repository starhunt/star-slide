# Star-Slide PRD v1.0 (통합본)

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-25 |
| 제품명 | **Star-Slide** |
| 한 줄 정의 | 이미지 기반 슬라이드(NotebookLM/Gamma 등의 출력)를 객체 단위로 분해해 PowerPoint에서 직접 편집 가능한 PPTX로 역변환하는 후처리 엔진 |
| 통합 베이스 | Star-SlideEditor(Codex) + Star-SlideManager(Claude) + Star-SlideMaster(Manus) |
| 1차 타겟 | NotebookLM/Gamma 출력물을 실무에 다듬어야 하는 개인 지식노동자/PM/기획자 |
| MVP 인터페이스 | CLI/API 우선, Phase 2에서 웹 UI |
| 외부 API 정책 | OSS-first. gpt-image-2/VLM은 옵션 |

> **이 문서의 권위**: 본 PRD는 `docs/Star-SlideEditor.md`, `docs/star-slidemanager-prd_claude.md`, `docs/Star-SlideMaster_PRD_manus.md`를 통합·정정한 결과물이다. 충돌 시 본 문서가 우선한다. 기존 3개 PRD는 히스토리/원본 자료로 보존한다.

---

## 1. Executive Summary

NotebookLM이 PPTX 출력을 정식 지원하면서 LLM 기반 슬라이드 자동 생성의 사용자 기반이 폭발적으로 늘었다. 그러나 다운로드된 PPTX는 사실상 **각 슬라이드가 단일 비트맵으로 임베드된 형태**라 텍스트 한 글자, 아이콘 하나도 개별 객체로 수정할 수 없다. Gamma·Tome·Beautiful.ai·Canva 등 다른 AI 슬라이드 도구도 동일 문제를 가진다.

Star-Slide는 (1) **SAM 3.1 segmentation + PaddleOCR PP-OCRv5 한국어 모델 + vtracer 벡터화**로 슬라이드를 객체 단위로 분해하고, (2) **python-pptx + 자체 svg→custGeom 변환기**로 PowerPoint 네이티브 객체로 재조립하며, (3) **LaMa(IOPaint)로 텍스트 자리 인페인팅**해 시각 충실도와 편집성을 양립시킨다. 핵심 가치는 "완벽한 원본 PPT 복구"가 아니라 **"AI가 만든 시각 자료를 사람이 빠르게 보정해 업무용 PPTX로 완성"** 하는 것이다.

---

## 2. 문제 정의 (Problem Statement)

### 2.1 사용자 페르소나와 잡스(JTBD)

| 페르소나 | 현재 워크플로우 | 페인 포인트 | 원하는 잡(JTBD) |
|---|---|---|---|
| **PM/기획자 (1차 타겟)** | NotebookLM으로 PRD 슬라이드 초안 → PPT로 다운로드 → 클라이언트 미팅용으로 다듬으려 함 | 텍스트 1자도 못 고침. 회사 폰트/컬러 적용 불가 | "AI가 만든 초안의 **텍스트와 컬러만** 빠르게 회사 표준으로 바꿔줘" |
| **컨설턴트** | Gamma로 비교표 슬라이드 생성 → 고객사 데이터로 표 안 숫자 수정 필요 | 표 셀 단위 수정 불가, 차트 색 못 바꿈 | "표/차트 데이터를 **수정 가능한** 객체로 분리해줘" |
| **연구자/교육자** | 논문 PDF의 다이어그램을 강의 슬라이드에 재활용 | 캡처해서 위에 텍스트 얹는 방식뿐 | "다이어그램 텍스트만 한국어로 바꿔서 PPT에 넣게 해줘" |

### 2.2 시장 신호

- AI 프레젠테이션 생성 시장: **2026년 $24.3억 → 2030년 $60억, CAGR 25.3%** (Manus PRD 출처 [3])
- 동시에 LLM 슬라이드 출력의 "이미지 잠금" 불만은 r/notebooklm, Medium 등에서 반복 보고
- 경쟁사: **Codia AI NoteSlide, PreciseDeck** — 한국어 텍스트 인식과 다채색 SVG 벡터화에서 한계

### 2.3 핵심 차별화 (Why Star-Slide?)

1. **한국어 1급**: PaddleOCR PP-OCRv5 `korean_PP-OCRv5_mobile_rec` + 한글 폰트 매칭(Pretendard/Noto Sans KR/나눔고딕 등) 풀 + 사용자 1클릭 폰트 선택 UX
2. **편집성 vs 시각 충실도 양자 중 양자**: 단순 path는 `a:custGeom`(편집 가능), 복잡 path는 EMF(시각 우선), 사진은 PNG fallback — 3단계 폴백
3. **OSS-first, Self-hostable**: gpt-image-2 등 외부 API는 옵션. 사용자 보유 A100 80GB로 자체 호스팅 가능
4. **Editable Level 5단계 표시**: native/vector/raster/uncertain/failed를 사용자에게 명확히 표시 (실패 슬라이드를 숨기지 않음)

---

## 3. 제품 비전과 목표

### 3.1 제품 비전

> "AI가 만든 시각 자료를 사람이 통제 가능한 구조화 문서로 되돌리는 **편집 복원 엔진**"

### 3.2 목표 (Goals)

**P0 (MVP)** — 사용자 결정에 따라 확정된 범위
- 입력: PPTX, PDF, PNG/JPG (단일/다중)
- **텍스트 객체**: PaddleOCR로 추출 → PowerPoint 텍스트박스로 복원, 한국어 폰트 후보 N개 + 사용자 선택
- **단순 도형/아이콘**: SAM3.1 마스크 → vtracer SVG → `a:custGeom` 변환 (편집 가능)
- **표 (Table)**: 셀 단위 OCR + native PowerPoint Table (T1-T2 레벨)
- **인페인팅**: LaMa(IOPaint)로 텍스트 자리 배경 자연스럽게 복원
- **CLI**: `star-slide convert input.pptx -o output.pptx --report report.json`
- **REST API**: `/v1/projects` 계열 비동기 작업
- **품질 리포트**: 슬라이드별 편집 가능도, fallback 객체 수, OCR 신뢰도

**P1 (Phase 2)**
- 웹 에디터 (Konva.js): 객체 선택, 텍스트/색상/위치 수정, undo/redo, 검수 상태
- 차트 데이터 추정 (DePlot + LLM 후처리, C2 레벨)
- 표 native 완전 복원 (T3)
- 배치 처리, 브랜드 템플릿 적용

**P2 (Phase 3+)**
- VLM 자연어 편집 ("이 막대 색을 회사 컬러로")
- 자산 라이브러리(아이콘/도형 임베딩 검색)
- PowerPoint Add-in
- Google Slides export, Keynote 호환
- Enterprise: VPC/On-prem, 감사 로그, SSO

### 3.3 Non-Goals (MVP 제외)

- 100% 원본 PPT 구조 완벽 복구
- 3D 차트, 지도, 수식, 손글씨의 완전 객체화
- 애니메이션·전환·테마 마스터 복원
- 저작권 보호 문서의 보호 해제 우회
- VBA, OLE 임베딩 객체 복원

---

## 4. 사용자 여정 (Core User Journey, MVP)

### 4.1 CLI 사용자 여정 (1차 타겟)

```
$ star-slide convert deck.pptx -o deck-edited.pptx --report report.json

[1/6] 파일 검증            ✓ PPTX, 12 slides, 8.4MB
[2/6] 슬라이드 래스터화    ✓ 12/12 (LibreOffice headless, 2x DPI)
[3/6] 객체 분해 (SAM 3.1)  ✓ 평균 18 객체/슬라이드, 분류 완료
[4/6] OCR + 폰트 추정      ✓ 한글 신뢰도 평균 0.94
[5/6] 벡터화 + 인페인팅    ✓ 142 객체 벡터화, 38 객체 raster fallback
[6/6] PPTX 재조립          ✓ deck-edited.pptx (3.2MB)

== 품질 리포트 ==
편집 가능도(평균):  78%
OCR 검수 필요:     3 슬라이드
raster fallback:   38 객체
slide-7 폰트 후보: Pretendard / Noto Sans KR / 나눔고딕 (사용자 선택 권장)

상세: report.json
```

### 4.2 API 사용자 여정 (개발자/통합)

```http
POST /v1/projects                          → project_id
POST /v1/projects/{id}/files (multipart)   → file_id
POST /v1/projects/{id}/analyze             → job_id
GET  /v1/jobs/{job_id}                     → status: ready
GET  /v1/projects/{id}/slides              → 슬라이드/객체 메타
PATCH /v1/objects/{obj_id}                 → 텍스트/스타일 수정
POST /v1/projects/{id}/export              → export_id (PPTX/PDF/SVG)
GET  /v1/exports/{export_id}/download      → presigned URL
```

---

## 5. 기능 요구사항 (Functional Requirements)

> 우선순위 표기: P0 = MVP 필수, P1 = Phase 2, P2 = Phase 3+

### 5.1 입력 (File Input)

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-001 | PPTX 업로드 | P0 | 이미지 기반 PPTX와 일반 PPTX 구분, 슬라이드별 처리 |
| FR-002 | PDF 업로드 | P0 | 페이지를 슬라이드 단위로 렌더링 (Poppler/pdf2image) |
| FR-003 | PNG/JPG 업로드 | P0 | 단일 또는 ZIP 다중 |
| FR-004 | 파일 유효성 검사 | P0 | 확장자/MIME/크기/암호화/손상 검사 |
| FR-005 | 대용량 파일 | P1 | 500MB 이하 비동기 처리 |
| FR-006 | 암호화 PPTX | P1 | 암호 입력 UI 또는 명확한 거부 메시지 |

### 5.2 슬라이드 래스터화

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-010 | 고해상도 렌더링 | P0 | 2x DPI 이상, EMU↔px 좌표 변환 행렬 보존 |
| FR-011 | 비율 보존 | P0 | 16:9, 4:3, custom 보존 |
| FR-012 | 썸네일 생성 | P0 | 256x144 썸네일 |
| FR-013 | 슬라이드 마스터 합성 | P0 | 마스터 배경 + 본문 이미지 합성 후 SAM 입력 (LibreOffice headless) |
| FR-014 | 렌더링 diff 계산 | P1 | export 결과 vs 원본 SSIM 측정 |

### 5.3 객체 분해 (Layer Decomposition)

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-020 | SAM 3.1 마스크 생성 | P0 | `everything mode`로 N개 마스크. IoU/stability 필터 |
| FR-021 | 차트/표 사전 보호 | P0 | YOLO 차트 디텍터로 차트 영역 사전 검출 → SAM이 쪼개지 않게 보호 |
| FR-022 | 텍스트 영역 사전 검출 | P0 | EAST/CRAFT로 텍스트 라인 검출 → SAM 결과와 병합/우회 |
| FR-023 | 마스크 병합/필터 | P0 | IoU > 0.7 중복 제거, 0.05% 미만 노이즈 제거, 80% 초과는 배경 후보 |
| FR-024 | 객체 분류 | P0 | `{text, icon, shape, chart, table, photo, background, decoration}` — 룰 기반 1차 + 옵션 VLM 보조 |
| FR-025 | z-order 추정 | P0 | 포함관계 + 마스크 알파 + 텍스트는 그래픽 위 휴리스틱 |
| FR-026 | 신뢰도 산정 | P0 | 객체별 confidence, editable_level 산출 |
| FR-027 | 레이어 잠금 | P1 | 검수 완료 객체 lock |

### 5.4 한국어 텍스트 복원

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-030 | 한국어 OCR | P0 | PaddleOCR PP-OCRv5 `korean_PP-OCRv5_mobile_rec` 1차, Surya OCR 보조 |
| FR-031 | OCR 앙상블 | P0 | 신뢰도 < 0.7이면 보조 모델 재시도 + 결과 비교 |
| FR-032 | 텍스트박스 복원 | P0 | OCR bbox → python-pptx textbox, 줄바꿈 보존 |
| FR-033 | 한글 폰트 후보 | P0 | 글리프 픽셀 비교로 상위 N개 한글 폰트 후보 제시 (Pretendard/Noto Sans KR/나눔고딕/명조 등 30+) |
| FR-034 | 폰트 임베딩 검색 | P1 | 사전 계산된 폰트 임베딩 + pgvector cosine search → 픽셀 비교는 상위 5개만 |
| FR-035 | 색상/크기 추정 | P0 | k-means 2 (배경 제외) dominant color, 글자 높이 px → pt |
| FR-036 | 줄바꿈 재계산 | P0 | bbox 폭 + 글자 수 + 단어/조사 경계 고려 |
| FR-037 | OCR 검수 UI | P1 (웹) | 원본 crop과 인식 텍스트 나란히 표시, 클릭 수정 |
| FR-038 | fallback 원본 보존 | P0 | 텍스트 복원 실패 시 원본 이미지 crop 레이어로 보존 |

### 5.5 인페인팅 (배경 복원)

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-040 | LaMa 텍스트 인페인팅 | P0 | IOPaint LaMa 모델로 텍스트 마스크 영역 자연 복원 |
| FR-041 | 인페인팅 품질 검증 | P0 | 인페인팅 전후 SSIM 측정, 임계값 미달 시 원본 사용 |
| FR-042 | gpt-image-2 옵션 | P1 | 사용자가 명시적 ON 시 호출. $/장 표시. zero-data-retention |
| FR-043 | 객체 제거 모드 | P1 | 사용자가 특정 객체 선택 후 제거 + 인페인팅 |

### 5.6 벡터화 (Shape/Icon Restoration)

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-050 | 단순 도형 감지 | P0 | 사각형/원/선/화살표/라운드 사각형 → native shape (python-pptx) |
| FR-051 | 아이콘 벡터화 | P0 | vtracer로 SVG path 생성 (color 모드, hierarchical stacked) |
| FR-052 | SVG → custGeom 변환 | P0 | 자체 변환기: M/L/C/Q/Z → moveTo/lnTo/cubicBezTo/quadBezTo/close, EMU 좌표 |
| FR-053 | EMF fallback | P0 | path 수 임계값 초과 시 Inkscape/LibreOffice EMF로 변환 |
| FR-054 | PNG fallback | P0 | EMF도 실패 시 투명 PNG (편집 불가, 시각만 보존) |
| FR-055 | 색상 편집 메타 | P0 | 복원된 도형의 fill/stroke를 사용자가 편집할 수 있는 형태로 출력 |
| FR-056 | 사진 판별 | P0 | 색상 분산도 분석 → 사진은 벡터화 우회, 투명 PNG 유지 |

### 5.7 표 복원 (Table)

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-060 | 표 영역 감지 | P0 | LayoutParser/PP-StructureV3로 표 영역 검출 |
| FR-061 | 행/열 경계 감지 | P0 | 직선 검출 + 셀 격자 추정 |
| FR-062 | 셀 OCR | P0 | 셀 단위 PaddleOCR |
| FR-063 | T1: overlay text | P0 | 표 이미지 + overlay text box (셀 텍스트만 편집 가능) |
| FR-064 | T2: grouped shapes | P0 | 선/셀/텍스트를 그룹 도형으로 복원 |
| FR-065 | T3: native PPT table | P1 | python-pptx `add_table`로 완전 복원 |

### 5.8 차트 복원 (P1, MVP 제외)

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-070 | 차트 영역 보호 | P0 (MVP는 이미지 fallback) | 차트는 단일 객체로 보호 |
| FR-071 | C0: image fallback | P0 | 차트는 통째로 PNG 유지 |
| FR-072 | C1: 라벨 OCR | P1 | 차트 라벨/축 텍스트만 편집 가능 |
| FR-073 | C2: grouped shape chart | P1 | 막대/선/마커를 그룹 도형으로 복원 |
| FR-074 | C3: 데이터 추정 | P1 | DePlot + LLM 후처리로 데이터 표 추정 (상호 검증) |
| FR-075 | C4: native chart | P2 | python-pptx `add_chart`로 PPT 차트 생성 |

### 5.9 PPTX Export

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-080 | PPTX export | P0 | PowerPoint 2019+ / Microsoft 365에서 정상 열림 |
| FR-081 | 객체 편집성 검증 | P0 | export 후 PowerPoint에서 텍스트 80%+ 직접 편집 가능 |
| FR-082 | export QA 자동화 | P0 | LibreOffice headless로 재렌더 → 원본과 SSIM 비교, 누락/overflow 검출 |
| FR-083 | fallback 리포트 | P0 | report.json에 raster fallback 객체 ID 목록 |
| FR-084 | PDF/SVG export | P1 | 슬라이드별 PDF/SVG 출력 |
| FR-085 | 브랜드 템플릿 | P1 | 사용자 지정 theme font/color 적용 |

### 5.10 프로젝트/협업 (Phase 2+)

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-090 | 프로젝트 저장 | P0 | 분석 결과 + 편집 상태 영구 저장 |
| FR-091 | 버전 히스토리 | P1 | 저장 시점 복원 |
| FR-092 | 코멘트 | P2 | 객체/슬라이드 단위 |
| FR-093 | 배치 작업 | P1 | 다중 파일 큐 + 진행률 |

---

## 6. 비기능 요구사항 (NFR)

### 6.1 Performance

| 항목 | MVP 목표 | 상용 v1 목표 | 측정 환경 |
|---|---:|---:|---|
| 단일 슬라이드 분석 | ≤ 30초 | ≤ 10초 | A100 80GB |
| 20장 PPTX 처리 | ≤ 10분 | ≤ 3분 | A100 80GB |
| 편집기 초기 로드 | ≤ 5초 | ≤ 2초 | (Phase 2) |
| 객체 선택 반응 | ≤ 100ms | ≤ 50ms | (Phase 2) |
| PPTX export (20장) | ≤ 60초 | ≤ 20초 | A100 80GB |

### 6.2 Quality

| 항목 | MVP 목표 | 상용 v1 목표 |
|---|---:|---:|
| 한글 OCR 문자 정확도 (CER) | ≤ 7% | ≤ 3% |
| 텍스트 bbox 위치 오차 | ≤ 8px | ≤ 4px |
| 일반 슬라이드 객체 분리 precision | ≥ 80% | ≥ 90% |
| 사용자가 직접 편집 가능한 객체 비율 | ≥ 60% (MVP 결정 시 텍스트는 80%+) | ≥ 80% |
| 원본 대비 export SSIM | ≥ 0.85 | ≥ 0.95 |
| 슬라이드당 사용자 보정 시간 | ≤ 2분 | ≤ 45초 |

### 6.3 Reliability

- 분석 작업 중단 후 재시작 가능 (슬라이드 단위 체크포인트)
- 동일 파일 content hash로 중복 방지
- 슬라이드 단위 실패 격리 (한 장 실패가 전체 실패로 이어지지 않음)
- worker 실패 시 슬라이드 단위 재시도 (최대 3회)
- 원본/export 양쪽 1회 이상 렌더링 검증

### 6.4 Security and Privacy

- 기본 정책: 원본 비공개 저장
- 사용자 명시 동의 없이 외부 LLM/API로 문서 이미지 전송 금지 (설정으로 강제 차단 가능)
- 저장 시 암호화 (S3 SSE-KMS 동등)
- 다운로드 URL 만료 시간 (기본 24h)
- Phase 3+: VPC/On-prem
- 감사 로그: upload/analyze/edit/export/download/delete 이벤트
- 데이터 보존 기간 plan별 설정 (Free 7일, Pro 30일, Team 90일, Enterprise 사용자 지정)

### 6.5 Compliance and Licensing

- 사용자 약관: 본인이 권한 가진 문서만 업로드
- 저작권 보호 문서 보호 해제 기능 미제공
- DPA, 데이터 삭제 SLA, 보안 백서, subprocessors 목록 (Enterprise)
- **모델/툴 라이선스 레지스트리** 유지 (`docs/Star-Slide_TechDecisions.md` 참조)
  - SAM 3 / 3.1: SAM License — 상업 사용 허용 (조항 추가 검토 필요)
  - vtracer: **MIT** (Manus PRD의 GPL-3.0 기재는 정정)
  - PaddleOCR: Apache 2.0
  - LaMa/IOPaint: 모델 가중치 라이선스 별도 확인
  - python-pptx: MIT

---

## 7. 시스템 아키텍처

### 7.1 High-Level Pipeline

```text
Input File (PPTX/PDF/PNG/JPG)
  ↓
[1] File Validation
  ↓
[2] Slide Rasterization (LibreOffice/Poppler/PIL)
  ↓
[3] Pre-detection (Chart/Text region pre-protect)
  ↓
[4] SAM 3.1 Mask Generation
  ↓
[5] Object Classification (rule + optional VLM)
  ↓
┌──── Branch by type ────┐
│ Text  → PaddleOCR + 폰트 매칭 + 색상 추정
│ Shape → vtracer → SVG → custGeom 변환
│ Icon  → vtracer → SVG → custGeom or EMF fallback
│ Chart → image fallback (MVP) / DePlot (Phase 2)
│ Table → cell OCR + grouped shapes (T2) / native (T3)
│ Photo → 투명 PNG 유지
│ BG    → 인페인팅 (LaMa/IOPaint) 후 슬라이드 배경
└────────────────────────┘
  ↓
[6] Layout Reconstruction (z-order + 정렬 스냅)
  ↓
[7] PPTX Composition (python-pptx + custGeom 인젝션)
  ↓
[8] Visual QA (재렌더 SSIM, 누락/overflow 검출)
  ↓
Output: PPTX + report.json
```

### 7.2 서비스 구성

| Service | 역할 | 후보 기술 | MVP 단일/분리 |
|---|---|---|---|
| **CLI** | 단일 파일 변환 진입점 | Python click/typer | 단일 |
| **API Server** | REST API, 작업 큐 등록 | FastAPI (Python 3.11+) | 단일 |
| **Job Queue** | 비동기 분석/export | Celery + Redis (또는 RQ) | 단일 |
| **Raster Worker** | PPTX/PDF/이미지 렌더링 | LibreOffice headless, Poppler | 분리 (소형) |
| **Segmentation Worker** | SAM 3.1 추론 (GPU) | PyTorch + SAM3 | 분리 (GPU) |
| **OCR Worker** | PaddleOCR + Surya | PaddleOCR/Surya (GPU 옵션) | 분리 (GPU 옵션) |
| **Vector Worker** | vtracer 호출, custGeom 변환 | vtracer CLI + Python | 단일/분리 |
| **Inpaint Worker** | LaMa 추론 | IOPaint (GPU) | 분리 (GPU) |
| **Compose Worker** | python-pptx 조립 | python-pptx + custom XML | 단일 |
| **Web App** | (Phase 2) 편집기 | Next.js + Konva.js | - |
| **Storage** | 원본/중간/결과 | 로컬(MVP) → S3 호환 | 로컬 |
| **Database** | 프로젝트/객체/작업 상태 | PostgreSQL + pgvector (NAS:5433) | NAS 활용 |
| **Cache** | 작업 상태/썸네일 | Redis (NAS) | NAS 활용 |

### 7.3 배포 모드 (Roadmap)

| Mode | 대상 | Phase |
|---|---|---|
| Local CLI | 개인 (자체 GPU 보유) | MVP |
| Self-hosted SaaS (1user) | 개인 NAS/로컬 서버 | MVP |
| Cloud SaaS | 일반 개인/팀 | Phase 3 |
| Dedicated VPC | 기업 | Phase 4 |
| On-Prem | 보안 조직 | Phase 4 |
| Desktop App | 고급 개인 | Phase 4 |

---

## 8. 중간 데이터 모델 (Layer Schema)

PPTX/SVG/Web Editor/JSON이 모두 공유하는 중간 표현. **이 스키마가 아키텍처의 핵심**이다.

```json
{
  "project_id": "prj_001",
  "slide_id": "sld_001",
  "slide_size": { "width_emu": 9144000, "height_emu": 6858000, "ratio": "16:9" },
  "render": { "px_per_emu": 0.0001, "dpi": 192 },

  "object": {
    "id": "obj_001",
    "type": "text",
    "subtype": "title",
    "bbox_emu": [Emu, Emu, Emu, Emu],
    "bbox_px": [x, y, w, h],
    "rotation": 0,
    "z_index": 12,
    "confidence": 0.92,
    "editable_level": "native | vector | raster | uncertain | failed",

    "source": {
      "mask_path": "masks/obj_001.png",
      "crop_path": "crops/obj_001.png",
      "detector": "sam3.1+ocr",
      "fallback_image_path": "fallback/obj_001.png"
    },

    "text": {
      "content": "AI 슬라이드 분해",
      "language": "ko",
      "font_candidates": [
        { "family": "Pretendard", "weight": 700, "score": 0.92 },
        { "family": "Noto Sans KR", "weight": 700, "score": 0.88 }
      ],
      "font_chosen": "Pretendard",
      "font_size_pt": 42,
      "color": "#111111",
      "align": "left",
      "line_height": 1.2
    },

    "shape": {
      "geom_type": "custGeom | preset | emf | png",
      "svg_path_d": "M 100 100 L ...",
      "custgeom_xml": "<a:custGeom>...</a:custGeom>",
      "fill": "#FF6B35",
      "stroke": null
    },

    "table": {
      "rows": 4, "cols": 3,
      "cells": [[ {"text": "...", "bbox": [...]}, ... ]],
      "recovery_level": "T1 | T2 | T3"
    },

    "chart": {
      "chart_type": "bar | line | pie | unknown",
      "recovery_level": "C0 | C1 | C2 | C3 | C4",
      "data_inferred": null
    },

    "qa": {
      "status": "pending | reviewed | accepted | rejected",
      "warnings": ["low_ocr_confidence", "font_uncertain"]
    }
  }
}
```

### 8.1 Object Types

| Type | 설명 | MVP Export 매핑 |
|---|---|---|
| background | 슬라이드 배경 | 슬라이드 background fill (이미지 또는 색) |
| text | OCR 복원 텍스트 | PPT TextBox |
| shape | 사각형/원/선/화살표 | PPT auto shape |
| icon | 벡터 아이콘 | PPT custGeom or EMF or PNG |
| photo | 사진/복잡 이미지 | PPT picture (PNG) |
| table | 표 | PPT table (T1/T2/T3) |
| chart | 차트 | PPT picture (MVP), PPT chart (Phase 2+) |
| equation | 수식 | PNG fallback |
| unknown | 분류 실패 | PNG fallback |

### 8.2 Editable Level

| Level | 의미 | UI 색 | export |
|---|---|---|---|
| native | PowerPoint 객체 직접 편집 | 녹색 | textbox/shape/table/chart |
| vector | SVG/path 편집 가능 | 파랑 | custGeom |
| raster | 이미지만 편집 가능 | 회색 | PNG (위치/크기만) |
| uncertain | 신뢰도 낮음, 검수 필요 | 노랑 | (사용자 결정) |
| failed | 분석 실패 | 빨강 | 원본 crop만 표시 |

---

## 9. API 설계 (MVP)

### 9.1 Core Endpoints

```http
POST   /v1/projects                        프로젝트 생성
POST   /v1/projects/{id}/files             파일 업로드 (multipart)
POST   /v1/projects/{id}/analyze           분석 시작 (옵션 body)
GET    /v1/projects/{id}                   프로젝트 메타
GET    /v1/projects/{id}/slides            슬라이드 목록
GET    /v1/slides/{slide_id}/objects       객체 목록
PATCH  /v1/objects/{obj_id}                객체 수정 (text/style/qa)
POST   /v1/projects/{id}/export            export 시작
GET    /v1/jobs/{job_id}                   작업 상태
GET    /v1/exports/{export_id}/download    presigned URL
```

### 9.2 Analyze Options

```json
POST /v1/projects/{id}/analyze
{
  "use_external_api": false,         // gpt-image-2 등
  "ocr_models": ["paddleocr", "surya"],
  "vector_threshold": { "max_paths": 200, "max_colors": 8 },
  "table_recovery_level": "T2",
  "chart_recovery_level": "C0",
  "inpaint": true,
  "report_format": "json"
}
```

### 9.3 Job State

```text
queued → rasterizing → detecting → reconstructing → ready
                                                   ↘ failed (slide-level)
ready → exporting → exported
                  ↘ export_failed
```

---

## 10. 데이터 모델 (DB)

### 10.1 Tables (PostgreSQL)

| Table | 주요 필드 |
|---|---|
| users | id, email, plan |
| organizations | id, name (Phase 3) |
| projects | id, owner_id, name, status, created_at |
| files | id, project_id, original_name, content_hash, size, mime |
| slides | id, project_id, page_no, width_emu, height_emu, render_path |
| slide_renders | id, slide_id, kind (original/edited/exported), path, ssim |
| objects | id, slide_id, type, subtype, bbox_emu, z_index, confidence, editable_level, payload (jsonb) |
| object_assets | id, object_id, kind (mask/crop/svg/fallback), path |
| jobs | id, project_id, kind, state, retry_count, error |
| exports | id, project_id, format, path, expires_at |
| audit_logs | id, user_id, project_id, event, payload, ts |
| qa_metrics | id, project_id, slide_id, kind, value |
| font_embeddings | font_family, weight, glyph (e.g. "안"), embedding (vector(512)) |

### 10.2 Storage Layout

```text
/var/star-slide/storage/
  org/{org_id}/project/{project_id}/
    original/
    renders/
    thumbnails/
    masks/
    crops/
    vectors/
    inpainted/
    exports/
    qa/
```

(MVP는 로컬 파일시스템, Phase 3 이후 S3 호환)

---

## 11. MVP Scope 확정

### 11.1 MVP 포함 (사용자 결정 반영)

- [x] 입력: PPTX, PDF, PNG/JPG (단일/ZIP 다중)
- [x] 슬라이드 래스터화 + 마스터 합성
- [x] SAM 3.1 마스크 생성 + 차트/텍스트 사전 보호
- [x] 객체 분류 (룰 기반, VLM 옵션)
- [x] **텍스트 복원** (PaddleOCR + 폰트 후보 + 색상)
- [x] **단순 도형/아이콘** (vtracer + custGeom)
- [x] **표 복원 T1-T2** (셀 OCR + grouped shapes)
- [x] **인페인팅** (LaMa/IOPaint)
- [x] PPTX export + visual QA
- [x] CLI + REST API (인증은 단순 API key)
- [x] 품질 리포트 (JSON)

### 11.2 MVP 제외 (Phase 2 이후)

- 웹 에디터 (Konva.js)
- 차트 데이터 추정 (DePlot)
- 표 native T3
- gpt-image-2 inpainting (옵션 플러그로만)
- 다중 사용자/팀
- 결제/플랜
- VLM 의미적 편집

### 11.3 MVP Exit Criteria

샘플셋 기준 (실제 NotebookLM/Gamma/PDF 보고서/한글 교육자료 100장):

- [ ] 한글 OCR CER ≤ 7%
- [ ] 텍스트 객체 직접 편집 가능 비율 ≥ 80%
- [ ] 평균 편집 가능도 ≥ 60%
- [ ] 20장 PPTX를 A100 1대로 10분 이내 분석
- [ ] export PPTX가 PowerPoint 2019+에서 정상 열림
- [ ] 슬라이드 단위 실패 격리 (전체 작업 중단 없음)
- [ ] 원본 대비 export SSIM ≥ 0.85
- [ ] CLI/API 양쪽으로 end-to-end 검증

---

## 12. Roadmap

### Phase 0: Research & Spike (2주)

목표: **3개 핵심 가설을 작은 코드로 검증**
- H1. SAM 3.1이 한글 슬라이드의 의미 객체를 IoU ≥ 0.8로 분리하는가
- H2. vtracer 출력을 `a:custGeom`으로 변환했을 때 PowerPoint에서 도형 편집 모드 진입 가능한가
- H3. PaddleOCR PP-OCRv5 한국어 모델의 슬라이드 도메인 CER이 7% 이하인가

산출물: 100장 샘플셋, benchmark report, layer schema v0, custGeom 변환기 PoC

### Phase 1: Vertical Slice MVP (4주)

목표: **CLI end-to-end 단일 파일 → 편집 가능 PPTX**

- 파이프라인 단계별 구현 + 슬라이드 단위 격리
- 텍스트/단순도형/아이콘/표(T1-T2)/인페인팅
- 품질 리포트 JSON
- pytest로 골든 샘플 회귀 테스트

### Phase 2: API + 품질 강화 (4주)

목표: **REST API + 차트 C2 + QA 자동화**

- FastAPI + Celery + Redis
- 폰트 임베딩 검색 (pgvector)
- 차트 grouped shape (C2)
- 표 native T3
- export QA 리포트 시각화

### Phase 3: 웹 에디터 베타 (6주)

목표: **사용자 보정 UI + 베타 운영**

- Next.js + Konva.js 에디터
- OCR 검수, 폰트 후보 1클릭 선택, 객체 병합/분리
- 결제(Stripe), 플랜, 사용량 미터링
- 운영 대시보드

### Phase 4: 고급 복원 + Enterprise (8주)

- 차트 native (C4), DePlot + LLM 후처리
- 자연어 편집 명령 (VLM)
- VPC/On-prem 패키징
- 감사 로그, SSO
- 자산 라이브러리

---

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 이미지에서 원본 구조 완전 복원 불가 | 사용자 기대 어긋남 | editable level + fallback 명시, "복원" 아닌 "편집 가능 초안" 메시지 |
| SAM 3 라이선스 조항 변경 또는 임계치 | 상용 배포 리스크 | 라이선스 레지스트리 + SAM2/Mask2Former fallback 대비, 프로덕션 배포 전 원문 확인 |
| 한글 OCR 오류 | 텍스트 신뢰도 저하 | PaddleOCR + Surya 앙상블, LLM 후처리 옵션, 검수 UI |
| 폰트 100% 식별 불가 | 시각 차이 | 후보 N개 + 사용자 1클릭 선택 UX (절대 자동 1개로 강제 X) |
| 차트 데이터 추정 실패 | native chart 복원 불가 | C0 fallback 보장, 사용자 데이터 입력 UI |
| custGeom 좌표 변환 오차 | 도형 깨짐 | 변환 후 SSIM 검증 → 미달 시 EMF/PNG fallback |
| **vtracer GPL 오해** | 라이선스 차단 우려 | **MIT 라이선스 확정** (정정), 문서에 명시 |
| GPU 비용 | SaaS 원가 상승 | 객체 사전 분류로 필요 모델만 실행, 개인 SaaS는 사용자 GPU 활용 |
| NotebookLM이 자체 편집 PPTX 지원 시 가치 급락 | 시장 위축 | Gamma/Tome/Beautiful.ai 등 다중 소스 지원으로 헷지 |
| MS PowerPoint가 동등 기능 내장 | 시장 경쟁 | 한국어 최적화 + on-prem + 자산 라이브러리로 차별화 |
| 모델 라이선스 변경 (SAM/PaddleOCR 등) | 상용 사용 리스크 | 모델별 라이선스 레지스트리 + fallback 모델 |
| 외부 API(gpt-image-2) 데이터 정책 변경 | 신뢰 훼손 | 기본 OFF, 사용자 명시 동의, zero-data-retention 확인 |

---

## 14. Quality Benchmark Plan

### 14.1 Dataset

샘플셋 구성 (Phase 0에서 100장, Phase 2까지 1000장):
- NotebookLM 생성 PPTX (한국어 30%, 영문 10%)
- Gamma/Beautiful.ai 출력 (10%)
- 일반 PDF 보고서 (한국어 정부/기업, 20%)
- 한글 교육자료/논문 슬라이드 (15%)
- 인포그래픽 중심 (10%)
- 차트 중심 (10%)
- 표 중심 (10%)

각 슬라이드에 **수동 라벨 ground truth**: 객체 bbox, 텍스트 내용, 폰트 추정, 분류.

### 14.2 Metrics

객체 단위:
- detection precision/recall, IoU
- OCR CER/WER (한국어)
- font top-3 accuracy
- editable_level 분포

슬라이드 단위:
- visual similarity (SSIM, perceptual)
- export success rate
- user correction count
- edit completion time

비즈니스 단위:
- upload→export conversion
- export per active user
- cost per slide (GPU 시간)
- support ticket rate

### 14.3 자동 회귀 테스트

- 매 PR마다 골든 샘플 10장 자동 변환 → 품질 메트릭이 임계 미만이면 차단
- 매주 전체 샘플셋 회귀 (Phase 1+)

---

## 15. 비즈니스 모델 (참고, MVP 이후)

| Plan | 대상 | 제한 | 가격 방향 |
|---|---|---|---|
| Free | 체험 | 월 10슬라이드, watermark | 무료 |
| Pro | 개인 | 월 500슬라이드, PPTX export | 구독 |
| Team | 소규모 팀 | 공유 프로젝트, 배치, 브랜드 템플릿 | 좌석 + 사용량 |
| Enterprise | 기업 | VPC/On-prem, 감사, SSO | 계약 |

과금 단위: **슬라이드 수** (사용자 이해 우선), 내부 원가는 GPU 시간 추적.

---

## 16. Open Questions (우선순위 의사결정 필요)

| # | 질문 | 결정 시점 | 영향 |
|---|---|---|---|
| 1 | SAM License 2.0 원문에서 재배포/임계치 조항 정확한가 | Phase 0 | 상용 배포 |
| 2 | A100 외에 어떤 GPU에서 운영할 것인가 (RTX 4090 충분?) | Phase 1 | 인프라 비용 |
| 3 | Phase 2 웹 에디터를 자체 구축 vs Tldraw/Excalidraw fork | Phase 1 말 | 개발 속도 |
| 4 | 한글 폰트 라이선스 풀 (상용 폰트는 추정만, 기본 매핑 정책) | Phase 1 | UX |
| 5 | Free 플랜의 데이터 보존 기간 (기본 7일?) | Phase 3 | 정책 |
| 6 | NotebookLM 최적화를 첫 타깃으로 고정할 것인가 (Gamma/Tome 동등 지원?) | Phase 0 끝 | 데이터셋 |

---

## 17. Definition of Done (v1 Commercial)

- [ ] Pro 사용자가 가입 후 5분 안에 첫 PPTX export 완료
- [ ] 한글 AI 슬라이드 텍스트 수정 가능률 ≥ 80%
- [ ] 실패 객체는 숨겨지지 않고 명확한 fallback 표시
- [ ] export PPTX가 Microsoft PowerPoint 최신 버전에서 정상 열림 + 주요 객체 편집 가능
- [ ] 원본/중간 산출물 삭제 기능 제공
- [ ] 운영자가 실패 작업과 GPU 비용 추적 가능
- [ ] 약관에 업로드 권한/보존/외부 모델 사용 명시
- [ ] 장애 시 프로젝트 단위 데이터 손실 없이 재시도

---

## 18. References (3개 PRD 통합 출처)

### 통합 베이스 PRD
- `docs/Star-SlideEditor.md` (Codex, 2026-04-25) — 가장 포괄적, 본 PRD의 골격
- `docs/star-slidemanager-prd_claude.md` (Claude, 2026-04-25) — 기술 구현 깊이, custGeom 변환, 폰트 매칭
- `docs/Star-SlideMaster_PRD_manus.md` (Manus, 2026-04-25) — 시장 분석, 경쟁사

### 핵심 기술 (정정 반영)
- Meta SAM 3 / 3.1: https://github.com/facebookresearch/sam3, https://ai.meta.com/blog/segment-anything-model-3/
- vtracer: https://github.com/visioncortex/vtracer (**MIT License** — Manus PRD의 GPL-3.0 기재 정정)
- PaddleOCR PP-OCRv5: https://github.com/PaddlePaddle/PaddleOCR
- python-pptx: https://python-pptx.readthedocs.io/
- IOPaint (LaMa): https://github.com/Sanster/IOPaint
- DePlot (Phase 2): https://arxiv.org/abs/2212.10505
- Surya OCR (앙상블): https://github.com/VikParuchuri/surya

### 추가 검토 필요 (Open Questions 참조)
- SAM License 원문 (재배포 조항)
- gpt-image-2 zero-data-retention 약관 정확 확인
- 한국어 OCR 학술 벤치마크 (KORIE 등) 추가 비교

---

## 부록 A: 3개 원본 PRD 통합 결정 매트릭스

| 영역 | Codex 안 | Claude 안 | Manus 안 | **Star-Slide 채택** |
|---|---|---|---|---|
| 제품명 | Star-SlideEditor | Star-SlideManager | Star-SlideMaster | **Star-Slide** (사용자 결정) |
| Segmentation | SAM3/3.1 + fallback | SAM3 | SAM 3 | **SAM 3.1 + SAM 2 fallback** |
| OCR | PaddleOCR PP-OCRv5 | PaddleOCR + TrOCR | gpt-image-2 | **PaddleOCR PP-OCRv5 1차 + Surya 보조** (gpt-image-2는 옵션) |
| 인페인팅 | (배경 분리만) | (텍스트 inpainting 언급) | gpt-image-2 mask-based | **LaMa/IOPaint 1차 + gpt-image-2 옵션** |
| 차트 | C0~C4 단계 | DePlot/UniChart/ChartReader | (Phase 3 향후) | **MVP는 C0(이미지), Phase 2부터 C2(grouped) + C3(DePlot+LLM)** |
| 폰트 | 추정 | pgvector 임베딩 + 후보 N | 고딕/명조 매핑 | **pgvector 임베딩 + 후보 N + 사용자 1클릭 (Claude안)** |
| 벡터화 | vtracer | vtracer (GPL3 우려) | VTracer (GPL3 우려) | **vtracer (MIT 확정 — 정정)** |
| PPTX 생성 | python-pptx + OpenXML | python-pptx + custGeom 변환기 | python-pptx | **python-pptx + 자체 svg→custGeom 변환기 + EMF fallback + PNG fallback** |
| MVP 인터페이스 | 웹 편집기 우선 | CLI 우선 (Phase 1) | 모호 | **CLI/API 우선 (사용자 결정)** |
| 표 | T0~T3 단계 | 셀 OCR + grouped | (없음) | **T1-T2 (MVP), T3 (Phase 2)** |
| 외부 API 정책 | 옵션 | 일부 | 적극 사용 | **OSS-first, 옵션 (사용자 결정)** |
| 1차 타겟 | 개인 Pro | 개인 | 지식노동자 | **개인 PM/기획자 (사용자 결정)** |
| 보안/엔터프라이즈 | 매우 상세 | 일부 | 없음 | **MVP 외, Phase 4 본격** |
| API 설계 | 상세 | 없음 | 없음 | **Codex안 채택, MVP는 단순화** |
| DB 모델 | 상세 | 일부 | 없음 | **Codex안 + 폰트 임베딩(Claude안)** |

---

*본 PRD는 살아있는 문서로, Phase 0 결과에 따라 v1.1로 갱신된다.*
