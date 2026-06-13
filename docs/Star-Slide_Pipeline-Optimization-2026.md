# Star-Slide 파이프라인 최적화 설계서 (Codex image_gen 채택안)

> 작성일: 2026-06-13
> 전제: **사용자 실측 결과 "Codex Vision + image_gen 2.0 기반 접근(`image_split`/`diagram_split` 경로)"이 한글 처리·이미지 생성에서 가장 우월**하다는 결론을 채택. 본 문서는 *다른 방법으로의 교체*가 아니라, **채택된 방법 안에서의 개선/최적화**를 다룬다.
> 대상 경로: `star_slide/pipeline/codex_image_split.py` + `experiments/diagram_split` (v7~v9 모듈화) 계열.
> 비채택 일반론(마스크 inpainting 우선 등)은 본 설계의 권고가 아님 — 단, 그 기법들을 *codex 경로의 보조 단계*로 흡수하는 방안만 채택.

---

## 0. 한 줄 요약

채택된 codex 접근법의 4단계 골격(① Vision 분석 → ② image_gen 텍스트 제거 → ③ 레이어 추출 → ④ 재조립)은 유지한다. 핵심 최적화는 **②단계가 일으키는 dimension drift를 "생성 이미지를 좌표 기준으로 신뢰하지 않는다"는 원칙으로 차단**하고, ③의 **계층(nested) 구조를 SAM이 아니라 Vision LLM이 직접 출력**하게 하며, **codex 호출을 슬라이드당 1회로 묶어 비용/지연을 통제**하는 것이다.

---

## 1. 채택 근거 (실측 기반, 변경하지 않음)

| 근거 | 출처 |
|------|------|
| gpt-image-2 한국어 정확도 ≈95% (실측, Manus PRD의 99%는 마케팅 수치로 정정됨) | `.session/CONTINUITY.md` 리서치 정정 #2 |
| 일러스트/도식이 많은 슬라이드는 OSS(SAM+LaMa) 경로보다 codex 생성형이 시각 충실도 우수 | `experiments/diagram_split` v1~v9 진화 |
| codex는 별도 `OPENAI_API_KEY` 없이 ChatGPT 로그인으로 image_gen 2.0 사용 가능 | `duct-cli` (Star-CLIProxy 어댑터) |

→ 따라서 **textless basis 생성과 한글 텍스트 판독의 주 엔진은 codex(image_gen 2.0 / Vision)** 로 고정한다. OSS 도구(SAM2.1, LaMa, PaddleOCR)는 **보조·검증·fallback**으로만 둔다.

---

## 2. 현재 아키텍처의 실증된 한계 (개선 대상)

`star-slide`에 이미 남아 있는 한계 기록을 개선 대상으로 정리한다. (출처: CONTINUITY.md, experiments/*, docs/TechDecisions)

| # | 한계 | 증상 | 현재 상태 |
|---|------|------|----------|
| L1 | **Dimension drift** | image_gen은 고정 해상도(1024²/1024×1536/1536×1024)로 출력 → 16:9 원본과 종횡비·픽셀격자 불일치. `coords.py`는 `image_size` JSON을 신뢰만 함 | 구조적 미해결 |
| L2 | **Text ghost(잔상)** | 생성형/LaMa 후 한글 획 외곽선·제목바 배경 잔재 (slide 2·6) | padding 12px+dilate 7px로 완화, SSIM<0.7시 원본 fallback |
| L3 | **Nested objects** | 박스 안의 박스/아이콘, 화살표+라벨 계층을 SAM이 의미적으로 분리 못 함 | SAM "everything mode"는 계층 무지 |
| L4 | **한글 폰트 매칭** | `font_size_pt`만 있고 `font_family` 부재 → 고딕/명조 구분 손실 | P1-T07 미구현 |
| L5 | **Vector/Hybrid 선택** | `mean_abs_diff`(MAE)만으로 후보 선택 — 텍스트 미세 위치 오차에 과민, 편집성 미반영 | `select_best_layout()` MAE+delta |
| L6 | **작은 배지/아이콘 손실** | OCR 미검출 소형 라벨이 편집 불가 래스터로 잔류 | `child_object_max_area_ratio=0.25` 보존 정책 |
| L7 | **비용/지연** | image_gen ≈$0.21/img·≈80s/slide, codex rate limit(`max_concurrent:1`) | 슬라이드당 1회 미보장, 자동 라우팅 부재 |

---

## 3. 최적화 설계

### 3.1 [L1·최우선] Dimension Drift 차단 — "생성 이미지는 좌표 기준이 아니다"

> **⚠️ 2026-06-13 정정**: 본 절의 "옵션 A(마스크 편집으로 drift 원천 차단)"는 후속 조사로 **부분적으로만 유효**함이 확인됨. ① codex builtin/duct-cli 경유로는 마스크를 넘길 수 없고(Issue #19136 open), ② gpt-image는 마스크 밖 영역 픽셀 보존을 보장하지 않으며, ③ 복잡 배경(격자/사진)의 텍스트 제거는 원리적 환각이라 품질 한계가 있음. 따라서 **마스크 편집보다 "배경 보존 + composite back"이 더 견고**하다. 상세·정정안: [Star-Slide_Codex-ImageGen-TextRemoval-Findings-2026.md](./Star-Slide_Codex-ImageGen-TextRemoval-Findings-2026.md).

**원칙: 원본 슬라이드 픽셀 격자를 유일한 좌표 진실(source of truth)로 고정한다. codex 출력은 *배경 텍스처 소스*로만 쓴다.**

세 가지 구현 옵션 중 안전도 순:

**옵션 A (권장) — 마스크 편집 모드로 codex 호출 (전체 재생성 금지)**
- image_gen 2.0이 mask/edit(인페인팅) 입력을 지원하면, **텍스트 bbox 영역만 마스크로 지정**해 codex에 "이 영역의 텍스트만 지우고 배경 이어그리기"를 요청.
- 출력은 원본과 동일 해상도·종횡비 유지 → drift 원천 제거. codex의 한글 배경 복원 우월성은 그대로 활용.
- duct-cli `openai:images`에 `image`/`mask` 입력 경로를 추가해야 함(현재 prompt-only). → **duct-cli 개선 항목 #1**.

**옵션 B — 전체 재생성 + 강제 재정합(registration)**
- codex가 전체 textless를 새로 생성하면(해상도 다름), 결과를 원본에 정합:
  1. 원본 해상도 `(W0,H0)`를 고정.
  2. codex 출력을 원본에 **특징점 정합**(ORB/AKAZE → homography) 또는, 구조 보존 가정 시 **letterbox 역변환 + resize**로 `(W0,H0)` 격자에 워핑.
  3. 정합 실패(inlier 부족) 시 옵션 C로 강등.
- `coords.py`에 "render PNG 해상도 ≠ Vision image_size" 케이스의 명시적 재스케일 추가(현재 image_size 신뢰만 하는 미해결 지점 보완).

**옵션 C — 결정적 fallback (solid/LaMa)**
- 텍스트 밀도 높고 배경 단순한 슬라이드는 codex 생성 없이 `bbox 주변색 solid fill` 또는 LaMa로 처리(이미 구현됨). drift·비용 0.

**라우팅 규칙**: 배경이 사진/그라데이션/일러스트 → A(또는 B). 단색/단순 → C.

**검증**: 정합 후 `원본 vs textless의 비텍스트 영역` SSIM ≥ 0.97을 게이트로. 미달 시 fallback.

---

### 3.2 [L3·고가치] Nested 레이어를 Vision LLM이 직접 출력

SAM은 의미 계층을 모른다(실험 h1: "process 슬라이드를 큰 frame 마스크로 덮음"). 계층은 **Vision LLM 책임**으로 이동.

- `VisionElement` 스키마에 계층 필드 추가:
  ```jsonc
  {
    "id": "el_007",
    "parent_id": "el_003",        // 컨테이너 박스 id (없으면 null)
    "z_hint": 3,                   // z-order 정수
    "role": "container|card|icon|label|connector",
    "type": "...", "bbox": {...}, ...
  }
  ```
- Vision 프롬프트에 "각 요소의 parent_id와 z_hint를 반드시 출력. 박스 안의 박스는 child로 표기" 규칙 추가(`vision_llm/extractor.py` SYSTEM_PROMPT 확장).
- **SAM은 강등**: 의미 분리 주 엔진이 아니라, *Vision이 지정한 parent bbox의 경계 정밀화*(box-prompt refine)에만 사용 — 이미 `--sam3` 옵션이 이 역할. 기본 OFF 유지.
- 재조립(`reconstruct_from_layout.py`)에서 `parent_id`로 그룹화 → z_hint 정렬 후 배치. python-pptx group 미지원이므로 z-order 순차 배치 + 메타데이터로 그룹 기록.

---

### 3.3 [L4] 한글 폰트 매칭 — 경량 룰 우선, pgvector는 보류

P1-T07을 pgvector 임베딩 없이 80% 달성:

- Vision 스키마에 `font_category: "sans|serif|mono|handwriting"` + `weight` + `is_korean` 추가.
- 로컬 폰트 매핑 테이블(결정적):
  | category + ko | 매핑 폰트 |
  |---|---|
  | sans + ko | Pretendard / Noto Sans KR |
  | serif + ko | Noto Serif KR |
  | sans + en | Inter / Arial |
  | mono | D2Coding / JetBrains Mono |
- `font_scale`(현재 0.93)은 렌더 QA 결과로 슬라이드별 자동 미세조정(overflow 감지 시 0.02씩 축소, 1회 재렌더).
- pgvector 유사도 검색은 폰트 라이선스/번들 확보 후 Phase 3로 이연.

---

### 3.4 [L5] Vector/Hybrid 선택 기준 고도화

MAE 단독 → **perceptual + 편집성 결합 점수**:

```
score = w1·(1 - SSIM)            # 시각 충실도 (낮을수록 좋음)
      + w2·LPIPS                  # 지각적 차이 (선택, 무거우면 생략)
      + w3·(1 - editable_ratio)   # 편집 가능 객체 비율 (높을수록 좋음)
```
- `editable_ratio` = (native text + native shape 면적) / 전체. hybrid가 래스터 보존으로 시각점수는 좋아도 편집성이 낮으면 감점.
- 기존 `--hybrid-allowed-delta`는 `score` 기준으로 재정의. 기본값에 근거(샘플 골든셋 튜닝) 부여 — 현재 "근거 없음" 문제 해소.
- MAE는 보조 지표로 report에만 유지(회귀 추적용).

---

### 3.5 [L2] Text Ghost 국소화

- **합성 전략**: codex/LaMa textless 전체를 쓰지 말고, **OCR/Vision 텍스트 bbox 영역만 textless로 교체, 나머지는 원본 픽셀 유지**(alpha 합성). 잔상이 텍스트 영역에 국한 → 비텍스트 영역 오염 0.
- 2단 정리: codex 배경 복원 후 잔상 의심 영역(텍스트 bbox ∩ 고주파 잔차)만 LaMa 재처리.
- 마스크 padding은 한글 받침/외곽선 고려 12px 유지하되, 작은 영문 라벨 누락(L6) 방지 위해 **OCR 신뢰도와 무관하게 Vision이 text로 판정한 모든 bbox를 마스크에 포함**(현재 OCR 임계 0.3/inpaint 0.7 분리가 누락 유발).

---

### 3.6 [L7] 비용·지연 통제

- **슬라이드당 codex image_gen 1회 보장**: 텍스트 제거를 영역별로 쪼개 여러 번 호출하지 말 것(rate limit·비용). 한 번에 전체 마스크 처리.
- **자동 라우팅(3경로 통합)**: 단일 오케스트레이터가 슬라이드 유형으로 분기
  | 슬라이드 유형 | 경로 |
  |---|---|
  | 텍스트 위주(목차/본문) | vector (codex 미사용, 빠름·무료) |
  | 일러스트/도식 위주 | image_split (codex image_gen) |
  | 혼합 | notebooklm hybrid + 필요한 슬라이드만 codex |
- **캐싱**: 입력 이미지 해시 → codex 결과 캐시(`cache_buster` 확장). 재실행 시 호출 0.
- **병렬**: codex는 `max_concurrent:1`(계정 한도) 유지하되, OSS 단계(SAM/LaMa/vtracer)는 슬라이드별 병렬 5 유지. codex만 직렬 큐.
- 목표: codex 미사용 슬라이드 17s → 유지, codex 슬라이드 80s → 캐시 적중 시 ~5s.

---

## 4. duct-cli 측 필요 개선 (codex 어댑터)

본 파이프라인을 위해 `duct-cli`(`/Users/starhunter/StudyProj/aiporj/duct-cli`)에 추가해야 할 기능:

| # | 항목 | 이유 | 현재 |
|---|------|------|------|
| 1 | **image+mask 편집 입력** (`--image`, `--mask`) | 3.1 옵션 A(마스크 편집)의 전제. drift 차단의 핵심 | prompt-only |
| 2 | `size`/종횡비 전달 | 옵션 B에서 원본 종횡비 요청 | `size`·`n` 무시(코드 미전달) |
| 3 | 샌드박스 권한 최소화 | `--dangerously-bypass-approvals-and-sandbox` 위험 | 전체 우회 |
| 4 | 응답 `file://` 일관화 + 캐시 키 | 3.6 캐싱 연동 | 절대경로 반환 |

→ duct-cli 개선은 별도 이슈/PR로 분리(SCOPED). 본 설계의 3.1 옵션 A는 #1에 의존.

---

## 5. 우선순위 로드맵

| 순위 | 작업 | 근거 | 의존 |
|------|------|------|------|
| P0 | 3.1 dimension drift 차단(옵션 A 우선, 불가 시 B) | 채택 방법의 최대 리스크 | duct-cli #1 |
| P0 | 3.5 text ghost 국소 합성 + 마스크 포함 규칙 | L2·L6 동시 완화, 저비용 | - |
| P1 | 3.2 Vision 계층 출력(parent_id/z_hint) | 레이어 재조립 정확도 | 스키마 확장 |
| P1 | 3.6 자동 라우팅 + codex 1회/캐싱 | 비용·지연 | - |
| P2 | 3.4 폰트 룰 매칭(P1-T07) | 편집 품질 | - |
| P2 | 3.3 Vector/Hybrid score 고도화 | 선택 신뢰도 | 골든셋 |
| P3 | duct-cli #2~#4, pgvector 폰트 | 부가 | - |

---

## 6. 검증 전략 (flip-centered)

- **골든셋**: `refdata/sample2.pptx`(10장, 369객체) + 일러스트 위주 샘플 1개 추가 고정.
- **회귀 게이트**: 각 변경 전 baseline 산출(편집가능비율, SSIM, 슬라이드별 처리시간) → 변경 후 비교. **이전 통과 슬라이드가 깨지면(flip) 총점 향상과 무관하게 차단**.
- **단계별 증거**:
  - 3.1: 비텍스트 영역 SSIM ≥ 0.97, 좌표 오차 ≤ 2px.
  - 3.2: nested 샘플에서 parent-child 관계 정확도(수동 라벨 대비).
  - 3.3: overflow 발생 0건(자동 font_scale 후).
  - 3.6: codex 호출 횟수 = codex 라우팅 슬라이드 수(1:1).
- **렌더 QA**: LibreOffice → PNG → contact sheet 육안 검수(기존 파이프라인 재사용).

---

## 7. 비채택/이연 결정 기록

| 항목 | 결정 | 사유 |
|------|------|------|
| 마스크 inpainting을 *주* textless 엔진으로 | 비채택 | 사용자 실측상 codex 한글/생성 우월. 단 3.5 잔상 정리의 *보조*로만 흡수 |
| 순수 VLM→SVG(image→code) 전면 전환 | 이연 | fine-tune 비용·한글 OCR 보강 필요. 현 codex+추출 하이브리드가 실측 우위 |
| pgvector 폰트 임베딩 | Phase 3 | 룰 매핑으로 80% 달성, 라이선스 선결 필요 |
| SAM3 주 엔진화 | 비채택 | gated repo + 의미계층 무지. box-refine 보조만 |
