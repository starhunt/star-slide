# Star-Slide Tech Decisions (ADR)

> Architecture Decision Records — 기술 스택별 채택 이유, 대안, 라이선스, 리스크 정리.
> 본 문서는 `docs/Star-Slide_PRD.md`의 §6.5(Compliance) 및 §7.2(서비스 구성)와 짝을 이룬다.

작성일: 2026-04-25
기반 리서치: 2026-04-25 (researcher 에이전트, 7개 컴포넌트 검증)

---

## 정정 사항 요약 (3개 원본 PRD 대비)

| # | 항목 | 원본 PRD 기재 | 검증 결과 | 영향 |
|---|---|---|---|---|
| C-1 | vtracer 라이선스 | Claude/Manus PRD 모두 GPL-3.0 | **MIT** (LICENSE 파일 직접 확인) | 우려 무효, 라이브러리 링크/CLI 호출 자유 |
| C-2 | gpt-image-2 한국어 정확도 | Manus: 99% glyph accuracy | 95% 정도가 보도 수치 (마케팅 매체) | MVP 기본 OFF 권장 유지 |
| C-3 | ChartGemma 채택 | (검토 후보) | **인스트럭션 데이터가 proprietary LLM 생성** → 상업 사용 위험 명시 | DePlot 우선 |
| C-4 | python-pptx custGeom | (지원 가정) | **SVG path 직접 임포트 미지원**, 자체 변환기 필요 | 별도 모듈 개발 필수 |

---

## ADR-001: Segmentation 모델 — SAM 3.1

**Status**: Accepted (2026-04-25)

**Context**
- 슬라이드 도메인 객체 감지가 필요 (텍스트 영역, 도형, 아이콘, 차트, 사진)
- 슬라이드 객체는 일반 사진 객체와 다름 (단순 색면, 텍스트 박스 다수)
- zero-shot 일반성과 라이선스 명확성 필요

**Decision**: **SAM 3.1** (2026-03-27 출시) 채택, SAM 2 fallback 유지

**Rationale**
- H100 16→32 FPS, RTX 4090(24GB) PoC 충분, 보유 A100 80GB 활용
- 학습 데이터 SA-Co에 document 도메인 포함 (Meta 공식)
- Object Multiplexing으로 다객체 동시 추적 (비디오 기능, 슬라이드엔 무관하나 정확도 향상 효과 기대)

**Alternatives Considered**

| 대안 | 평가 | 비채택 이유 |
|---|---|---|
| SAM 3 (2025-11) | 기능 충분 | SAM 3.1이 동등 라이선스로 출시된 상태 |
| Mask2Former / OneFormer | 성능 양호 | zero-shot 일반성 부족, 슬라이드 fine-tuning 필요 |
| SegFormer | 경량 | 정확도 한계 |

**License**
- SAM License (2025-11-19 갱신)
- 상업 사용 **허용**, 군사·ITAR·핵·무기 용도 금지
- **확인 필요**: 재배포/파생 모델/MAU 임계 조항 (프로덕션 배포 전 LICENSE 원문 직접 검토 — Open Question #1)

**Risks**
- 라이선스 조항 변경 가능성 → SAM 2 fallback 코드 경로 유지
- 텍스트 박스를 한 글자씩 쪼개는 경향 → EAST/CRAFT로 텍스트 라인 사전 검출 후 SAM 결과와 병합 (Claude PRD 12장 #2 참조)

**Implementation Notes**
- 추론은 별도 GPU worker (`segmentation-worker`)로 격리
- `points_per_side=32~64`, `pred_iou_thresh=0.86`, `stability_score_thresh=0.92`
- 마스크 후처리: 슬라이드 면적 80%+ → 배경, 0.05% 미만 → 노이즈 제거

**Refs**
- https://ai.meta.com/blog/segment-anything-model-3/
- https://github.com/facebookresearch/sam3
- https://arxiv.org/abs/2511.16719

---

## ADR-002: OCR — PaddleOCR PP-OCRv5 (1차) + Surya OCR (보조)

**Status**: Accepted

**Context**
- 1차 타겟이 한국어 사용자 (사용자 결정)
- "한국어 1급 품질"이 핵심 차별화
- OSS-first, 자체 호스팅 필요

**Decision**: **PaddleOCR PP-OCRv5 `korean_PP-OCRv5_mobile_rec` 1차, Surya OCR 보조 앙상블**

**Rationale**
- PaddleOCR PP-OCRv5: 106개 언어, PP-OCRv3 대비 30%+ 정확도 향상
- 한국어 mobile_rec 모델 별도 제공 (HF 등록)
- Apache 2.0 라이선스 (자유)
- KORIE 한국어 영수증 벤치마크에서 EasyOCR/Tesseract 대비 최저 오류율

**Ensemble 전략**
- 1차: PaddleOCR
- 신뢰도 < 0.7 또는 한국어 비율 비정상 → Surya OCR 재시도
- 두 결과 비교 → 일치 시 채택, 불일치 시 둘 다 사용자에 표시 (검수 UI)

**Alternatives Considered**

| 대안 | 점수 (한국어) | 비채택 이유 |
|---|---|---|
| Surya OCR | 97.41% (종합) | 1차로 쓸 수도 있으나 PaddleOCR이 KORIE에서 더 안정적 → 보조로 |
| TrOCR | 95.92% | 박스 좌표 별도, 박스+텍스트 동시 제공하는 PaddleOCR이 우수 |
| Tesseract | 92.38% (CER 25%) | 한국어 정확도 부족 |
| EasyOCR | CER 17.36% | PaddleOCR 대비 부정확 |
| gpt-image-2 OCR | 95% (보도) | $0.21/이미지, 데이터 보안 우려, 옵션으로만 |
| PaddleOCR-VL-1.5 (2026-01) | OmniDocBench 94.5% | 신규 모델, 안정성 검증 후 Phase 2에서 평가 |

**License**: Apache 2.0

**Implementation Notes**
- OCR worker는 GPU 옵션 (CPU도 동작하나 느림)
- 한글/영문/숫자 혼합 처리
- 라인별 좌표 + 신뢰도 반환
- 후처리: 줄바꿈 재계산 (bbox 폭 + 글자 수 + 단어 경계)

**Refs**
- https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md
- https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec
- https://www.mdpi.com/2227-7390/14/1/187 (KORIE 벤치마크)

---

## ADR-003: 벡터화 — vtracer (정정: MIT)

**Status**: Accepted (2026-04-25 정정)

**Context**
- 단순 도형/아이콘을 SVG path로 변환해야 함
- 슬라이드 아이콘은 다채색이 흔함

**Decision**: **vtracer 채택**

**중요 정정**
- Claude PRD/Manus PRD 모두 vtracer를 **GPL-3.0**으로 기재했으나, 실제 라이선스는 **MIT** (Copyright 2024 TSANG, Hao Fung).
- LICENSE 파일 직접 확인 (https://raw.githubusercontent.com/visioncortex/vtracer/master/LICENSE).
- 따라서 CLI 호출/라이브러리 링크 모두 자유.
- Manus PRD의 GPL 우려 및 Claude PRD의 "별도 프로세스 호출 격리" 권장은 **불필요**하나, 안전을 위해 CLI 호출 패턴은 유지 (디버깅/병렬화 이점).

**Rationale**
- **다채색(color mode)** 직접 처리 가능 → 슬라이드 아이콘에 적합
- 색상 클러스터링 기반 → 단순 도형 path 수 적음
- Rust 바이너리 + Python wrapper (`vtracer-py`) 모두 제공

**Alternatives Considered**

| 대안 | 라이선스 | 비채택 이유 |
|---|---|---|
| Potrace | GPL-2.0+ | 흑백만, 상용 시 Potrace Professional 별도 라이선스 |
| autotrace | LGPL | 오래된 코드, 유지보수 부진 |
| SVG-Path-Trace 직접 구현 | - | 비용/시간 |

**Implementation Notes**
- 호출: `vtracer --input mask.png --output shape.svg --colormode color --hierarchical stacked --filter_speckle 4 --color_precision 6 --gradient_step 16 --corner_threshold 60 --segment_length 4 --splice_threshold 45`
- 출력 SVG path를 svg-points로 파싱 → `a:custGeom` 변환기에 입력
- path 수 임계값 초과 시 EMF fallback

**Refs**
- https://github.com/visioncortex/vtracer
- https://raw.githubusercontent.com/visioncortex/vtracer/master/LICENSE

---

## ADR-004: 인페인팅 — LaMa(IOPaint) 1차 + gpt-image-2 옵션

**Status**: Accepted

**Context**
- 텍스트가 OCR로 추출된 후 원본 이미지에서 텍스트를 자연스럽게 제거해야 함 (배경 복원)
- 텍스트 객체와 배경 객체의 분리가 시각 충실도의 핵심

**Decision**: **LaMa (IOPaint) 1차, gpt-image-2 옵션**

**Rationale**
- LaMa (WACV 2022): 텍스트 제거 분야 OSS 표준, 여전히 SOTA 수준 (2026 기준)
- IOPaint (구 lama-cleaner): LaMa + Stable Diffusion 통합, 자체 호스팅 가능
- 무료, A100에서 빠름, 데이터 외부 전송 없음

**gpt-image-2 옵션 조건**
- 사용자가 명시적 ON 토글 (기본 OFF)
- $0.21/이미지 비용 표시
- Zero Data Retention 확인 (OpenAI 공식)
- 텍스트 재배치까지 필요한 슬라이드(예: 영문→한글)에서만 사용 가치

**Alternatives Considered**

| 대안 | 평가 | 비채택 이유 |
|---|---|---|
| MAT (Mask-Aware Transformer) | 양호 | LaMa로 충분, 통합 도구(IOPaint) 부재 |
| ZITS | 양호 | 동일 |
| SD Inpaint (Stable Diffusion) | 우수 | 비용 OSS이나 GPU 부담, IOPaint 안에 포함 |

**Implementation Notes**
- `inpaint-worker` GPU 노드
- 텍스트 마스크는 OCR bbox + 약간의 padding (4-8px)
- 인페인팅 전후 SSIM 측정 → 임계값 0.7 미달 시 원본 그대로 사용 (안전 fallback)
- gpt-image-2 호출 시: `images.edit` API, mask 흰색 영역만 수정

**Refs**
- https://github.com/advimman/lama
- https://github.com/Sanster/IOPaint
- https://developers.openai.com/api/docs/models/gpt-image-2

---

## ADR-005: PPTX 생성 — python-pptx + 자체 svg→custGeom 변환기

**Status**: Accepted

**Context**
- vtracer가 출력한 SVG path를 PowerPoint **편집 가능 도형**(custGeom)으로 변환해야 함
- python-pptx는 SVG path 직접 임포트 미지원

**Decision**: **python-pptx + 자체 svg→custGeom 변환기 + EMF/PNG 다단계 fallback**

**Rationale**
- python-pptx는 PPT 슬라이드/텍스트박스/표/차트 생성에 가장 안정적인 OSS (MIT)
- custGeom XML은 OOXML(ECMA-376 Part 1, 20.1.9.10) 사양에 따라 직접 생성 가능
- SVG `M/L/C/Q/Z` → OOXML `<a:moveTo>/<a:lnTo>/<a:cubicBezTo>/<a:quadBezTo>/<a:close>` 매핑

**Conversion Pipeline**

```text
SVG path (d="M ...")
  → svg-points 파싱
  → bbox 계산
  → EMU 좌표 스케일 (914400 EMU = 1 inch, 12700 = 1pt)
  → <a:custGeom> XML 생성 (a:pathLst > a:path with w/h)
  → python-pptx Shape에 inject (lxml로 _element 직접 조작)
  → 변환 후 SSIM 검증 (원본 PNG vs PowerPoint 재렌더 PNG)
  → SSIM < 0.85 → EMF fallback
  → EMF 변환 실패 → 투명 PNG fallback
```

**Alternatives Considered**

| 대안 | 평가 | 비채택 이유 |
|---|---|---|
| **PptxGenJS** (JS) | custGeom 완전 지원 (PR #872) | Python 백엔드와 분리 부담, MVP에서 불필요 |
| Aspose.Slides (.NET, 상용) | `AddFromSVGAsShapes()` 직접 변환 | $1000+/년 라이선스 비용, OSS 우선 정책 위반 |
| Spire.Presentation (상용) | 동일 기능 | 동일 |
| OpenXML SDK (.NET) 후처리 | 가능 | Python 단일 스택 유지가 우선 |

**Implementation Notes**
- 변환기 모듈: `star_slide/composer/svg2custgeom.py`
- 주의: SVG arc(`A` 명령) ↔ OOXML arc 파라미터 변환은 별도 처리 (회귀 테스트 핵심)
- Phase 2에 PptxGenJS 마이크로서비스 분리 옵션 검토 (현재로선 불필요)

**Refs**
- https://python-pptx.readthedocs.io/
- https://github.com/scanny/python-pptx/blob/master/docs/dev/analysis/shp-freeform.rst
- https://github.com/gitbrent/PptxGenJS/pull/872

---

## ADR-006: 차트 인식 — DePlot + LLM 후처리 (Phase 2)

**Status**: Accepted (Phase 2부터 적용, MVP는 C0 image fallback)

**Context**
- 차트는 의미 단위 객체 (쪼개면 복원 불가)
- MVP는 차트 영역을 PNG으로 보호만 함 (C0)
- Phase 2부터 데이터 추출 → native PPT chart 생성 시도

**Decision**: **MVP: C0 image fallback. Phase 2: DePlot + LLM 후처리 (C2-C3)**

**Rationale**
- DePlot (Google, Apache 2.0): chart-image → table 직변환, 라이선스 안전
- LLM 후처리(예: Claude/GPT-4)로 표 검증 + 차트 타입 분류
- 신뢰도 < 0.8 → 사용자 입력 UI (Track 2)

**ChartGemma 비채택 이유 (정정)**
- 정확도 SOTA이나, 인스트럭션 튜닝 데이터가 **proprietary LLM(Gemini 등)으로 생성**
- ChartGemma 논문 자체가 "상업 환경 제약 가능" 명시
- 상용 제품에 적용 시 잠재적 라이선스 리스크

**Alternatives Considered**

| 대안 | 평가 | 비채택 이유 |
|---|---|---|
| DePlot | Apache 2.0, 안정 | **채택** (Phase 2) |
| UniChart | 140M 경량 | 정확도 낮음, 한국어 미지원 |
| ChartReader | 양호 | 유지보수 비활성 |
| ChartGemma | SOTA | 라이선스 리스크 (상기) |
| MatCha | Pre-train만 | DePlot이 fine-tune 버전 |

**Implementation Notes**
- MVP: 차트 영역 검출 후 통째로 PNG 임베드, 라벨 OCR도 별도 진행하지 않음 (단순화)
- Phase 2: `chart-worker`로 분리, DePlot 추론 + Claude API(옵션) 후처리

**Refs**
- https://arxiv.org/abs/2212.10505 (DePlot)
- https://arxiv.org/html/2407.04172v1 (ChartGemma — 라이선스 위험 명시)

---

## ADR-007: VLM 보조 분류 — 옵션 (기본 OFF)

**Status**: Accepted

**Context**
- 객체 분류(text/icon/shape/chart/table/photo)에서 룰 기반만으로 한계
- VLM(Claude Sonnet, GPT-4V, Gemini)이 의미 분류에 강함
- OSS-first 정책

**Decision**: **룰 기반 분류 1차, VLM은 옵션 (기본 OFF)**

**Rationale**
- 룰 기반(aspect ratio + edge density + color count + text-likeness)이 슬라이드 도메인에서 80%+ 정확도 가능
- VLM 호출은 슬라이드당 1-3회 + 배치 패치(9~16개 동시)로 비용 절감
- 사용자가 명시적 ON 시에만 호출
- Star-CLIProxy(사용자 보유 인프라) 활용 시 비용 추가 절감 가능

**Implementation Notes**
- VLM 옵션 활성화 시 호출 모델 우선순위: Claude Sonnet 4.x > GPT-4V > Gemini
- 결과 캐싱: (이미지 해시, 프롬프트 해시) → 동일 입력 재호출 방지

---

## ADR-008: 한글 폰트 매칭 — pgvector 임베딩 + 후보 N + 사용자 선택

**Status**: Accepted

**Context**
- OCR이 텍스트 내용은 추출하나 폰트는 안 줌
- 폰트 100% 자동 식별은 거의 불가능
- 시각 충실도와 사용자 통제의 균형

**Decision**: **글리프 임베딩 사전 계산(pgvector) + cosine 검색 → 상위 5 후보 픽셀 비교 → 상위 N개를 사용자에게 제시**

**Rationale**
- Claude PRD의 5.2 폰트 매칭 강화 안 채택
- 사용자 NAS 보유 PostgreSQL + pgvector(port 5433) 활용
- 사용자가 자주 쓰는 폰트 학습으로 우선순위 부여 가능 (개인화)

**Pipeline**

```
한글 폰트 풀 (Pretendard, Noto Sans KR, 나눔고딕, 나눔명조, 본명조, 에스코어드림 등 30~50종)
  → 동일 글리프(예: "안") 동일 크기로 렌더 → 512차원 임베딩(perceptual hash 또는 stylometric features)
  → pgvector에 저장
  
[추론]
OCR 결과 텍스트의 글리프 1자 추출 → 임베딩
  → cosine 유사도 상위 5 후보
  → 픽셀 SSIM/perceptual hash 비교
  → 상위 N개를 score와 함께 layer schema에 기록
  → 사용자가 1클릭 선택 (UX), 자동 1개 강제 X
```

**Implementation Notes**
- 폰트 임베딩 사전 계산은 build-time (CI에 추가)
- `font_embeddings` 테이블 (PRD §10.1)
- MVP는 자동 추정 + report에 후보 N개 노출
- Phase 2 웹 UI에서 1클릭 선택

---

## ADR-009: 백엔드 스택 — Python (FastAPI + Celery + Redis)

**Status**: Accepted

**Context**
- AI 모델(SAM/PaddleOCR/LaMa/DePlot) 대부분 PyTorch/Python 기반
- python-pptx도 Python
- 단일 언어 스택의 운영 단순성

**Decision**: **Python 3.11+, FastAPI (API), Celery + Redis (큐), PostgreSQL + pgvector (DB)**

**Rationale**
- 모델 인프라와 동거 → 데이터 전송 오버헤드 최소
- FastAPI: async, OpenAPI 자동 생성, 검증 강력
- Celery: 성숙, GPU worker 분리 운영 검증됨
- Redis: NAS 보유 인프라 활용
- PostgreSQL + pgvector: 사용자 NAS port 5433 보유

**Alternatives Considered**

| 대안 | 비채택 이유 |
|---|---|
| NestJS (TS) | AI 모델 인프라 분리 부담 |
| Go | 모델 호출 시 Python 별도 프로세스 → 단순성 손실 |
| RQ (Redis Queue) | Celery보다 가볍지만 GPU worker 우선순위/재시도 정책 부족 |
| Temporal | 강력하나 MVP 오버킬 |

---

## ADR-010: 프론트엔드 스택 — Next.js + Konva.js (Phase 2)

**Status**: Accepted (Phase 2)

**Context**
- 캔버스 기반 객체 편집기 필요
- MVP는 CLI/API만, 웹은 Phase 2

**Decision**: **Next.js 15 + react-konva + zustand + tailwindcss**

**Rationale**
- react-konva: Canvas 객체 편집(선택/이동/리사이즈/z-order)에 검증된 OSS
- zustand: 간단한 상태 관리, undo/redo 패턴 친화적
- Next.js: SSR + API routes로 BFF 가능

**Alternatives Considered**

| 대안 | 비채택 이유 |
|---|---|
| Fabric.js | 성숙하나 React 통합 ecosystem이 Konva보다 약함 |
| Tldraw fork | 강력하나 슬라이드 도메인에 과한 추상화 |
| Excalidraw fork | 손그림 중심, 슬라이드 편집과 결이 다름 |
| 자체 Canvas 엔진 | 비용/시간 |

**Implementation Notes**
- 객체 편집은 Konva, 폼/사이드바는 일반 React
- 실시간 협업은 Phase 3+ (Yjs 검토)

---

## ADR-011: 인프라 — 로컬 개발 (사용자 NAS) → Phase 3 클라우드

**Status**: Accepted

**Context**
- 사용자 보유 자원: A100 80GB GPU 서버 (개발), MacBook M4 Max(MPS) 로컬, NAS PostgreSQL(:5433) + Redis
- MVP는 단일 사용자 사용 시나리오

**Decision**: **MVP는 사용자 GPU 서버 + NAS 활용. Phase 3부터 클라우드 (S3 호환 + GPU worker 풀)**

**Rationale**
- MVP에서 클라우드 비용 발생 X
- NAS PostgreSQL + Redis 재사용
- A100 활용으로 SAM/PaddleOCR/LaMa 빠른 추론 검증 가능

**Phase 3 클라우드 마이그레이션**
- S3 호환 (AWS S3 또는 MinIO 자체 호스팅)
- GPU worker는 Modal / RunPod / 자체 K8s + GPU 노드 검토
- DB는 RDS Postgres 또는 자체 Postgres 클러스터

---

## ADR-012: 라이선스 레지스트리

본 프로젝트가 의존하는 모든 모델/툴의 라이선스 추적표. **상용 배포 전 확인 필수**.

| 컴포넌트 | 라이선스 | 상업 사용 | 검증 상태 | 비고 |
|---|---|---|---|---|
| SAM 3.1 (모델 가중치) | SAM License | 가능 (제한 조항) | ⚠️ 원문 재확인 필요 | Open Question #1 |
| PaddleOCR | Apache 2.0 | 자유 | ✅ | |
| Surya OCR | Apache 2.0 (확인 필요) | 자유 | ⚠️ 확인 필요 | |
| **vtracer** | **MIT** | **자유** | ✅ | **Manus/Claude PRD 정정** |
| python-pptx | MIT | 자유 | ✅ | |
| LaMa (모델 가중치) | Apache 2.0 (코드) | 가능 | ⚠️ 가중치 별도 확인 | |
| IOPaint | Apache 2.0 | 자유 | ✅ | |
| DePlot | Apache 2.0 | 자유 | ✅ | Phase 2 |
| ChartGemma | 가중치 Gemma 라이선스 | **위험** | ❌ 비채택 | 인스트럭션 데이터가 proprietary LLM 산출 |
| FastAPI | MIT | 자유 | ✅ | |
| Celery | BSD-3 | 자유 | ✅ | |
| PostgreSQL | PostgreSQL License | 자유 | ✅ | |
| Next.js | MIT | 자유 | ✅ | Phase 2 |
| react-konva | MIT | 자유 | ✅ | Phase 2 |
| gpt-image-2 (옵션) | OpenAI API ToS | 가능 (출력물 사용자 귀속) | ✅ | Zero Data Retention 호환 |
| Claude API (옵션) | Anthropic API ToS | 가능 | ✅ | |

**Action Items (Phase 0)**:
- [ ] SAM License 원문 재배포/임계치 조항 확인
- [ ] Surya OCR LICENSE 파일 확인
- [ ] LaMa 모델 가중치(big-lama 등) 라이선스 명시 확인

---

## ADR-013: 한글 폰트 풀 정책

**Status**: Draft (Phase 0에서 확정)

**Context**
- 폰트 매칭에 사용할 한글 폰트 풀 구성
- 상용 폰트(애플 SD 산돌고딕, 윤고딕 등) 라이선스 우려

**Decision (Draft)**: 무료 사용 가능 한글 폰트만 풀에 포함, 상용 폰트는 추정 결과로만 표시 (실제 임베딩 없음)

**무료 한글 폰트 후보 풀 (30+)**:
- Pretendard (OFL) — 모던 산세리프
- Noto Sans KR / Noto Serif KR (OFL)
- 나눔고딕, 나눔명조, 나눔스퀘어 (OFL)
- 본고딕 / 본명조 (OFL)
- 에스코어드림 (개인/상업 무료, 재배포 제한 있음 — 확인 필요)
- 카페24 시리즈, 배달의민족 시리즈 (개인/상업 무료, 재배포 제한)
- ...

**Phase 0 작업**:
- 라이선스별로 풀 분류 (자유 재배포 / 사용 자유 / 추정만)
- 사용자가 시스템에 설치된 폰트는 자체 인식 옵션

---

## ADR-014: 외부 API 데이터 정책

**Status**: Accepted

**Context**
- gpt-image-2, Claude/GPT-4V 등 외부 호출 옵션
- 사용자 데이터 보안

**Decision**:
1. 모든 외부 API 호출은 **사용자 명시 동의(opt-in)** 필요
2. 기본 OFF
3. UI/CLI에서 호출 직전 비용 표시 ($/이미지 또는 토큰)
4. 호출 로그에 어떤 데이터가 어디로 갔는지 기록
5. Zero Data Retention 가능 모델만 등록 (gpt-image-2, Claude API 확인됨)
6. Enterprise 플랜은 외부 API 전체 차단 가능 옵션

**Implementation Notes**
- 환경 변수 `STAR_SLIDE_DISABLE_EXTERNAL_API=1`로 강제 차단
- 호출 시 `audit_logs`에 `event=external_api_call, model=..., bytes_sent=...`

---

## 결정 요약 매트릭스

| 영역 | 결정 | ADR |
|---|---|---|
| Segmentation | SAM 3.1 + SAM 2 fallback | 001 |
| OCR | PaddleOCR PP-OCRv5 한국어 + Surya 보조 | 002 |
| 벡터화 | vtracer (MIT 확정) | 003 |
| 인페인팅 | LaMa(IOPaint) 1차 + gpt-image-2 옵션 | 004 |
| PPTX 생성 | python-pptx + 자체 svg→custGeom + EMF/PNG fallback | 005 |
| 차트 | C0(MVP) → DePlot+LLM(Phase 2) | 006 |
| VLM 보조 분류 | 옵션, 기본 OFF | 007 |
| 한글 폰트 매칭 | pgvector 임베딩 + 후보 N + 사용자 선택 | 008 |
| 백엔드 | Python + FastAPI + Celery + Redis + PG/pgvector | 009 |
| 프론트엔드 (P2) | Next.js + react-konva + zustand | 010 |
| 인프라 (MVP) | 사용자 NAS + GPU 서버 | 011 |
| 라이선스 정책 | 레지스트리 유지 + 정기 검토 | 012 |
| 한글 폰트 풀 | 무료 폰트 우선, 상용은 추정만 | 013 |
| 외부 API | opt-in 기본 OFF, ZDR 확인된 것만 | 014 |
