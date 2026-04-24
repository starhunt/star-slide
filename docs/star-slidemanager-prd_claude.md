# Star-SlideManager — AI 슬라이드 레이어 분해·편집·관리 도구 개발 계획서

> **버전 0.1 / 2026-04-25**
> **대상**: NotebookLM·Gamma·기타 LLM 기반 슬라이드 생성 결과물의 "이미지 잠금" 문제를 해결하기 위한 후처리 파이프라인 설계

---

## 1. 프로젝트 개요

### 1.1 배경

NotebookLM이 PPTX 출력을 정식 지원하기 시작하면서 LLM 기반 슬라이드 자동 생성의 사용자 기반이 폭발적으로 늘었다. 그러나 다운로드된 PPTX는 사실상 **각 슬라이드가 단일 비트맵 이미지로 임베드된 형태**이며, PowerPoint·Keynote·Google Slides에서 열어도 텍스트 한 글자, 아이콘 하나조차 개별 객체로 수정할 수 없다.

사용자가 원하는 것은 단순하다.
- "이 제목 폰트만 바꾸고 싶다"
- "이 아이콘만 색을 다르게"
- "표 안의 숫자만 수정"
- "회사 로고로 교체"

이를 위해 사용자들은 현재 (1) NotebookLM 안에서 자연어로 재생성을 요청하거나, (2) PPT를 처음부터 다시 만들거나, (3) Inkscape·Illustrator로 한참을 작업한다. 어느 쪽도 만족스럽지 않다.

### 1.2 핵심 문제

> **이미지 1장으로 압축된 슬라이드를, "객체 단위로 편집 가능한" PPTX로 역변환할 수 있는가?**

### 1.3 목표

- **MVP**: 단순 슬라이드(제목 + 본문 + 아이콘 1~3개)를 90% 이상 자동으로 객체 분해
- **베타**: 차트·표·인포그래픽까지 포함한 복잡 슬라이드 처리
- **정식**: VLM 통합 자연어 편집("이 차트의 막대 색을 파란색으로") 지원

---

## 2. 핵심 가설 및 접근 방식

이미지 게시글에서 제시한 `SAM3 + vtracer + python-pptx` 조합은 다음 가설에 기반한다.

| 가설 | 검증 방법 |
|---|---|
| SAM3가 슬라이드 내 의미 단위 객체를 충분히 잘 분리한다 | 100장 샘플에 대해 IoU ≥ 0.8 객체 비율 측정 |
| vtracer가 단순 도형·아이콘을 깔끔한 SVG path로 변환한다 | 시각적 비교 + path complexity 통계 |
| python-pptx로 SVG path를 편집 가능 도형(`a:custGeom`)으로 임베드 가능하다 | PPT에서 도형 편집 모드 진입 가능 여부 |

세 가설이 모두 충족된다면 파이프라인 자체는 성립한다. 단, 실제 결과물의 **편집성**과 **시각적 충실도**의 균형은 추가 보완 모듈이 결정한다.

---

## 3. 시스템 아키텍처

### 3.1 전체 데이터 흐름

```
입력 PPTX (이미지 슬라이드)
   │
   ├─ Stage 1: Slide Image Extractor
   │     · python-pptx로 각 슬라이드의 임베드 이미지 추출
   │     · 슬라이드 좌표계 (EMU) ↔ 픽셀 매핑 보존
   │
   ├─ Stage 2: SAM3 Auto-Mask Generator
   │     · `everything mode`로 N개 마스크 생성
   │     · IoU/stability score 필터링
   │     · 너무 작은(노이즈) 마스크 제거
   │
   ├─ Stage 3: Object Classifier
   │     ① 룰 기반 휴리스틱 (aspect ratio, 색상 분산, edge density)
   │     ② VLM(GPT-4V/Claude/Gemini) 보조 분류
   │     · {text, icon, shape, chart, photo, background}
   │
   ├─ Stage 4: 분기 처리
   │     4a. Text  → OCR(PaddleOCR/TrOCR) → 폰트 매칭 → 텍스트 박스
   │     4b. Shape → vtracer → SVG path → a:custGeom
   │     4c. Chart → DePlot/ChartReader → 데이터 + 차트 타입 → python-pptx Chart
   │     4d. Photo → 비트맵 그대로 보존 (편집 X, 위치만 복원)
   │
   ├─ Stage 5: Layout Reconstructor
   │     · z-order 추정 (마스크 면적 + 겹침 관계)
   │     · 그리드 스냅 보정
   │     · 정렬 그룹 식별 (좌측 정렬, 균등 분포 등)
   │
   └─ Stage 6: PPTX Composer
         · python-pptx로 슬라이드 생성
         · 텍스트는 TextFrame, 도형은 add_shape/freeform
         · 차트는 add_chart, 사진은 add_picture
         → 출력: 편집 가능 PPTX
```

### 3.2 핵심 기술 스택

| 영역 | 선택 | 사유 |
|---|---|---|
| 세그멘테이션 | **SAM3** (Hugging Face) | 인스턴스 분리 정확도, OSS, 모델 사이즈 선택 가능 |
| 벡터화 | **vtracer** (Rust 바이너리 + Python wrapper) | 색상 클러스터 기반, 단순 도형에 강함, GPL3 |
| OCR | **PaddleOCR** (한글 우수) + 보조로 **TrOCR** | 한글 정확도, 박스 좌표 함께 제공 |
| 차트 인식 | **DePlot / Pix2Struct / UniChart** | 차트 → 표 데이터 직변환 |
| 레이아웃 | **LayoutParser / DocLayNet 모델** | 슬라이드를 문서로 취급 가능 |
| PPTX 생성 | **python-pptx** + 보조로 **LibreOffice headless** | OOXML 직접 제어 |
| VLM 보조 | **Claude Sonnet 4.x / GPT-4V / Gemini** | 의미 분류·라벨링 |
| 백엔드 | **FastAPI** (Python 3.11+) | 모델 인프라와 동거 |
| 작업 큐 | **Celery + Redis** 또는 **RQ** | GPU 작업 비동기화 |
| 프론트엔드 | **Next.js + Konva.js / Fabric.js** | 캔버스 기반 객체 편집기 |
| DB | **PostgreSQL + pgvector** | 폰트·아이콘 임베딩 검색 (사용자 NAS 인프라 활용 가능) |

---

## 4. 상세 처리 파이프라인

### 4.1 Stage 1 — 슬라이드 이미지 추출

NotebookLM PPTX의 구조는 일반적으로 다음과 같다.

- 각 슬라이드는 1개의 큰 `picture` shape으로 구성
- 또는 배경 이미지 + 일부 textbox(자동 생성된 노트)

`python-pptx`로 슬라이드를 순회하면서:
1. 슬라이드 크기(EMU 단위) 파악 → 픽셀 환산
2. `slide.shapes` 중 `MSO_SHAPE_TYPE.PICTURE` 추출
3. `image.blob`을 PIL/Pillow로 로드, DPI 기록
4. 만약 textbox가 별도로 있다면 OCR 단계 건너뛰고 그대로 보존 후보로 분리

> **주의**: 일부 PPTX는 슬라이드 마스터에 배경 이미지를, 슬라이드 본문에 또 다른 이미지를 가진다. 두 개를 합성한 최종 비주얼을 생성한 뒤 SAM3에 입력해야 한다. LibreOffice headless로 슬라이드 단위 PNG 렌더가 가장 확실하다.

```bash
soffice --headless --convert-to png --outdir ./out input.pptx
```

### 4.2 Stage 2 — SAM3 자동 세그멘테이션

`SamAutomaticMaskGenerator`(또는 SAM3 동급 API)로 슬라이드 이미지 전체에 대해 마스크를 추출한다.

핵심 파라미터:
- `points_per_side`: 32~64 (슬라이드 해상도에 따라)
- `pred_iou_thresh`: 0.86
- `stability_score_thresh`: 0.92
- `min_mask_region_area`: 슬라이드 전체 픽셀의 0.05% 이상

**후처리**:
- 마스크 간 IoU > 0.7이면 더 작은 쪽 제거(중복)
- 슬라이드 면적의 80%를 넘는 마스크는 "배경 후보"로 별도 분류
- 마스크 bounding box를 슬라이드 EMU 좌표계로 환산해 보존

**대안 검토**:
- SAM3 외에 `Mask2Former`, `OneFormer`, `SegFormer` 등도 후보. 단 SAM 계열의 zero-shot 일반성이 슬라이드 도메인에 가장 적합.
- 추후 SAM3 fine-tuning 데이터셋(슬라이드 50~100장 수동 라벨)을 만들어 정확도 향상 여지.

### 4.3 Stage 3 — 객체 분류

각 마스크 영역에 대해 `{text, icon, shape, chart, photo, background}` 라벨을 부여한다.

#### 3-1. 룰 기반 1차 분류

| 특징 | 측정 | 분류 힌트 |
|---|---|---|
| Aspect ratio | width/height | 5:1 이상 가로형 → 텍스트 가능성 |
| Edge density | Canny 평균 | 높음 → 텍스트, 낮음 → 색면 도형 |
| Color count | k-means 후 클러스터 수 | 2~3 → 단순 도형, 다수 → 사진 |
| Text-likeness | EAST detector / CRAFT | 텍스트 라인 검출 |

#### 3-2. VLM 보조 분류

각 마스크 영역을 잘라 224×224로 리사이즈 후, VLM에 다음 형태로 질의:

```
[이미지 패치]

이 이미지 영역은 슬라이드의 일부입니다. 다음 중 가장 적합한 분류를 선택하고
간단한 라벨(예: "제목 텍스트", "도형: 둥근 사각형", "막대 차트의 막대",
"인포그래픽 아이콘: 톱니바퀴")을 한 줄로 답하세요.

분류: [text | icon | shape | chart | chart_element | photo | background | decoration]
라벨: ...
```

비용 절감을 위해 **배치 호출** + **마스크 패치 그리드 합성**(한 번에 9~16개 패치 동시 분류) 전략을 쓴다.

#### 3-3. 차트 우선 검출

차트는 잘게 쪼개지면 복원 불가하므로, **세그멘테이션 전에** YOLO 기반 차트 디텍터(예: ChartDete)를 별도 실행해 차트 영역을 통째로 보호한다. 그 영역은 SAM3 결과를 무시하고 단일 객체로 처리.

### 4.4 Stage 4a — 텍스트 분기

#### OCR

PaddleOCR(한국어 모델 v4) 우선.
- 입력: 마스크 bbox + 약간의 padding
- 출력: 텍스트, 라인별 좌표, 신뢰도

신뢰도 < 0.7 텍스트는 TrOCR로 재시도(앙상블).

#### 폰트 매칭

**문제**: OCR은 글자만 뽑지 폰트 정보는 안 준다.

**접근**:
1. 텍스트 영역을 흑백 이진화
2. 글자 한 자(예: "안" 또는 "A")를 추출해 정규화
3. 한글 웹폰트 풀(Noto Sans KR, Pretendard, 나눔고딕, 나눔명조, 본명조, 에스코어드림 등) 약 30~50종에 대해 동일 글자를 동일 크기로 렌더
4. 각 후보를 입력 글리프와 픽셀 차이(SSIM 또는 perceptual hash) 비교
5. 상위 3개 후보 제시 — **최종 선택은 사용자에게**

> **구조적 한계**: 100% 정확한 폰트 식별은 거의 불가능. "비슷한 폰트 후보 + 사용자 1클릭 선택" UX가 현실적.

#### 색상·크기 추정

- 텍스트 색: 마스크 내부 픽셀의 dominant color (k-means k=2, 배경 제외)
- 폰트 크기: 글자 높이(픽셀) × (72 / 슬라이드 DPI) → pt

### 4.5 Stage 4b — 도형/아이콘 벡터화

vtracer 호출:

```bash
vtracer --input mask.png --output shape.svg \
        --colormode color \
        --hierarchical stacked \
        --filter_speckle 4 \
        --color_precision 6 \
        --gradient_step 16 \
        --corner_threshold 60 \
        --segment_length 4 \
        --splice_threshold 45
```

#### SVG → PPTX 변환의 두 갈래

| 방법 | 장점 | 단점 |
|---|---|---|
| **A. SVG path → `a:custGeom`** | PPT에서 도형 편집 가능 | path 변환 정밀도 손실, 좌표 단위(EMU) 변환 필요 |
| **B. SVG → EMF (Inkscape/LibreOffice)** | 시각 충실도 높음 | 일부 환경에서 EMF가 비트맵으로 보임 |
| **C. SVG → PNG fallback** | 항상 보임 | 편집 불가, 본 프로젝트 목적 위반 |

**권장**: 단순 path는 A로 변환(편집 가능), 복잡한 path는 B로 폴백, 그래도 안 되면 C.

A 방식의 핵심은 SVG path 명령(`M`, `L`, `C`, `Q`, `Z`)을 OOXML `<a:path>`의 `<a:moveTo>`, `<a:lnTo>`, `<a:cubicBezTo>`, `<a:close>`로 매핑하는 것. 좌표는 EMU(914400 EMU = 1 inch)로 환산하고 `a:path w/h`를 설정.

```python
# 의사코드
def svg_path_to_custgeom(svg_path_d, target_emu_w, target_emu_h):
    cmds = parse_svg_path(svg_path_d)
    bbox = compute_bbox(cmds)
    sx, sy = target_emu_w / bbox.w, target_emu_h / bbox.h
    return ooxml_path_xml(cmds, scale_x=sx, scale_y=sy)
```

### 4.6 Stage 4c — 차트/표 인식

가장 어려운 부분. 두 가지 트랙 운영.

#### Track 1 — 자동 데이터 복원
- 입력: 차트 영역 패치
- 모델: DePlot, UniChart, ChartReader
- 출력: 표 데이터 + 차트 타입(bar/line/pie/...)
- 검증: VLM에 "이 차트의 데이터를 표로 정확히 변환해줘" 재질의해 교차 검증

#### Track 2 — 반자동
- 자동 복원 신뢰도 < 0.8이면 사용자에게 표 입력 UI 제공
- 차트 타입은 자동 분류, 데이터만 사용자 입력

복원된 데이터로 `python-pptx.chart.add_chart`를 호출하면 PPT 안에서 진짜 편집 가능한 차트가 된다.

### 4.7 Stage 5 — 레이아웃 복원

#### z-order 추정
- 마스크 A가 마스크 B에 완전히 포함되면 A가 위
- 부분 겹침은 마스크 알파 분석(겹친 영역의 픽셀이 어느 객체와 더 닮았는지)
- 텍스트는 거의 항상 그래픽 위에 위치 (휴리스틱)

#### 그리드 스냅
- 객체들의 x좌표 분포를 1D 클러스터링 → 좌측 정렬 그룹 식별
- y좌표도 동일하게 → 행 정렬
- 슬라이드 폭의 5% 이내 차이는 정렬로 간주, EMU 단위로 보정

#### 그룹화
- 거리 + 의미 라벨이 비슷한 객체를 그룹으로 묶어 PPT의 그룹 도형으로 출력 → 사용자 편집성 향상

### 4.8 Stage 6 — PPTX 재구성

`python-pptx`의 핵심 호출:

```python
from pptx import Presentation
from pptx.util import Emu, Pt

prs = Presentation()
prs.slide_width  = Emu(slide_w_emu)
prs.slide_height = Emu(slide_h_emu)
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

# 텍스트
tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
tf = tb.text_frame
p = tf.paragraphs[0]
run = p.add_run()
run.text = ocr_text
run.font.name = matched_font_name
run.font.size = Pt(detected_pt)
run.font.color.rgb = RGBColor(...)

# 도형 (custGeom)
shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(x), Emu(y), Emu(w), Emu(h))
inject_custgeom_xml(shape, svg_path_d_converted)
shape.fill.solid()
shape.fill.fore_color.rgb = RGBColor(*detected_color)

# 차트
chart_data = CategoryChartData()
chart_data.categories = categories
chart_data.add_series(series_name, values)
slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, ..., chart_data)

prs.save('out.pptx')
```

---

## 5. 추가 개선 방안

### 5.1 VLM 통합 의미 이해

각 슬라이드를 통째로 VLM에 넘겨 다음 정보를 얻는다.
- 슬라이드 종류(제목, 목차, 본문, 비교표, 인포그래픽…)
- 의미적 영역 라벨("이건 핵심 메시지", "이건 보조 설명")
- 색상 테마 추출

이 정보는 `python-pptx`에서 슬라이드 마스터/레이아웃을 적절히 선택하는 데 쓰인다. 결과물이 단순 도형 모음이 아니라 "PowerPoint 다운 슬라이드"가 된다.

### 5.2 한글 폰트 매칭 강화

- 폰트 임베딩(Stylometric features)을 사전 계산해 pgvector에 저장
- 입력 글리프의 임베딩과 cosine 유사도로 후보 추출 → 픽셀 비교는 상위 5개에 대해서만

사용자가 자주 쓰는 폰트를 학습해 우선순위 부여(개인화).

### 5.3 색상 팔레트 추출 및 테마 적용

- 슬라이드 전체에서 dominant color 5~8개 추출
- python-pptx로 PPT의 ThemeColor를 해당 팔레트로 설정
- 추후 사용자가 "테마 색만 바꾸고 싶다"고 하면 한 번에 일괄 변경 가능

### 5.4 다이어그램·SmartArt 인식

순서도·계층도·벤다이어그램 등은 SAM3로 잘게 쪼개기보다 **다이어그램 디텍터**(Layout-aware)로 통째로 인식한 후, 노드+엣지 그래프로 변환해 PPT의 SmartArt로 매핑.

### 5.5 자연어 편집 명령 (Phase 4)

분해된 객체 트리에 메타데이터(라벨)가 붙어 있으면, 사용자가 "두 번째 슬라이드의 막대 색을 회사 브랜드 컬러로 바꿔줘"라고 요청 시 LLM이 객체를 식별해 변경 적용.

→ Star-CLIProxy의 OpenAI 호환 엔드포인트를 활용하면 비용 절감 가능.

### 5.6 양방향 자산 라이브러리

분해 결과로 얻은 아이콘·도형을 사용자별 자산 라이브러리에 누적. CLIP 임베딩으로 검색 가능. 다음 슬라이드 작업 시 "비슷한 아이콘 재사용" UX.

---

## 6. 기술적 도전 및 완화 방안

| 도전 | 영향 | 완화 |
|---|---|---|
| 한글 OCR 오인식 | 텍스트 품질 저하 | PaddleOCR + TrOCR 앙상블, LLM 후처리 교정 |
| 폰트 식별 불가 | 시각 충실도 손실 | 후보 N개 + 사용자 1클릭 선택 |
| 텍스트-그래픽 중첩 | 마스크 분리 실패 | 텍스트 우선 검출 후 inpainting으로 배경 분리 |
| 그라데이션·그림자 | vtracer 출력 폭증 | 효과는 별도 추론(EffectExtractor), path는 단순화 |
| custGeom 좌표 변환 오차 | 도형 모양 깨짐 | 변환 후 시각 비교(SSIM) 검증, 임계값 미만이면 EMF 폴백 |
| GPU 비용 | 운영비 부담 | A100 보유 환경 활용, 작업 큐로 배치 처리 |
| TOS 리스크 (NotebookLM 출력 처리) | 약관 위반 가능성 | 사용자가 자신의 PPTX를 업로드하는 형태이므로 본질적으로 사용자 콘텐츠 처리 — 문제 적음 |

---

## 7. 개발 로드맵

### Phase 1 — MVP (4~6주)
- 단일 슬라이드 단순 케이스(제목 + 본문 + 아이콘 1~3개)
- SAM3 + vtracer + python-pptx 기본 파이프라인
- CLI 형태, 웹 UI 최소
- **Exit criteria**: 샘플 30장에 대해 사용자가 "PPT에서 정상 편집 가능"이라고 평가하는 비율 70%↑

### Phase 2 — 차트·표 (4주)
- DePlot/UniChart 통합
- 차트 자동 복원 + 반자동 폴백
- 표 인식(테이블 디텍터 + 셀 OCR)

### Phase 3 — 복잡 레이아웃 (6주)
- 인포그래픽, 다이어그램, SmartArt 변환
- 그리드 스냅, z-order 정확도 향상
- 웹 에디터(Konva.js) 정식 출시 — 자동 분해 결과를 사용자가 추가 보정

### Phase 4 — VLM 의미적 편집 (8주)
- 자연어 편집 명령
- 자산 라이브러리, 폰트 학습
- 멀티 슬라이드 일괄 처리, 테마 일괄 변경

---

## 8. 기술 스택 상세

### 백엔드 (Python)
```
fastapi==0.115.*
python-pptx==1.0.*
paddleocr==2.9.*
torch==2.6.*
transformers (SAM3 / TrOCR / DePlot)
opencv-python
pillow
celery + redis
```

### 벡터화 도구
```
vtracer (Rust, prebuilt binary 또는 vtracerpy wrapper)
inkscape (CLI, EMF 폴백용)
libreoffice-core (headless 렌더링)
```

### 프론트엔드 (Next.js)
```
next@15
react-konva  // 객체 편집기
zustand      // 상태 관리
tailwindcss
```

### 인프라
- GPU 서버: 사용자 보유 A100 80GB (개발), MacBook M4 Max(MPS) 로컬 테스트
- DB: PostgreSQL + pgvector (사용자 NAS, port 5433 활용)
- 작업 큐: Redis on NAS
- 스토리지: 로컬 + (옵션) S3 호환

---

## 9. 사용자 워크플로우

```
1. 웹에 PPTX 업로드
2. 자동 분해 진행 (5~30초/슬라이드, GPU에 따라 다름)
3. 결과 미리보기 — 객체 단위로 하이라이트
4. 필요시 보정:
   · 잘못 묶인 객체 분할
   · OCR 텍스트 수정
   · 폰트 후보 선택
   · 차트 데이터 보정
5. "PPTX 다운로드" → 편집 가능 PPTX 생성
6. PowerPoint/Keynote에서 자유롭게 편집
```

---

## 10. 평가 지표

### 자동 평가
| 지표 | 정의 | 목표 |
|---|---|---|
| Visual Fidelity | 원본 vs 재구성 결과의 SSIM | ≥ 0.85 |
| Text Accuracy | OCR 결과의 CER (Character Error Rate) | ≤ 5% (한글) |
| Object Recall | 의미 객체 검출률 | ≥ 90% |
| Editability | PPT에서 더블클릭으로 편집 가능한 객체 비율 | ≥ 80% |

### 사용자 평가
- 5점 척도: "이 결과를 그대로 쓸 수 있는가?"
- 후처리 시간: 분해 결과를 원하는 상태로 만드는 데 걸린 분
- NPS

---

## 11. 라이선스·법적 검토

| 컴포넌트 | 라이선스 | 검토 |
|---|---|---|
| SAM3 | Meta AI 라이선스 (모델 가중치) | 상업 사용 가능 여부 확인 필요 |
| vtracer | GPL-3.0 | 별도 프로세스 호출 형태로 격리하면 우회 가능, 다만 명시 필요 |
| python-pptx | MIT | 자유 |
| PaddleOCR | Apache 2.0 | 자유 |
| DePlot | Google research, Apache 2.0 | 자유 |

vtracer GPL은 가장 신경 쓸 부분. 정적 링크가 아니라 CLI 호출이면 회피 가능하나, 안전을 위해 OSS 공개 또는 듀얼 라이선스 검토.

---

## 12. 위험·열린 질문

1. **NotebookLM 자체가 편집 가능 PPTX를 정식 지원하면 본 프로젝트 가치 급락**
   → 그래도 다른 LLM 슬라이드 도구(Gamma, Tome, Beautiful.ai)는 같은 문제를 가질 가능성 높음. 다중 소스 지원으로 헷지.

2. **SAM3가 한글 텍스트를 한 글자씩 쪼개는 경향**
   → 텍스트 영역은 SAM3 우회, EAST/CRAFT로 라인 단위 검출 후 묶음 처리.

3. **Microsoft가 PowerPoint에 동일 기능을 내장하는 가능성**
   → 그것이 표준이 되어 시장이 넓어질 수도 있음(긍정적 해석).

4. **API 비용**
   → VLM 호출은 슬라이드당 1~3회로 제한, 캐싱 적극 활용.

---

## 13. 참고 자료

- Meta AI — Segment Anything (SAM2/SAM3) 논문 및 GitHub
- visioncortex/vtracer — https://github.com/visioncortex/vtracer
- python-pptx 공식 문서 — https://python-pptx.readthedocs.io
- Google Research — DePlot: One-shot visual language reasoning by plot-to-table translation
- PaddleOCR — https://github.com/PaddlePaddle/PaddleOCR
- LayoutParser — https://layout-parser.github.io
- OOXML 사양 — `a:custGeom` 정의는 ECMA-376 Part 1, 20.1.9.10

---

## 부록 A — 최소 구현 코드 스케치

```python
# pipeline.py (의사 구현)
from pathlib import Path
import subprocess, json
from pptx import Presentation
from pptx.util import Emu, Pt
import torch
from segment_anything import SamAutomaticMaskGenerator, sam_model_registry

def decompose_slide(slide_png: Path, sam, ocr, out_pptx: Path):
    img = load_image(slide_png)

    # Stage 2
    masks = sam.generate(img)              # [{segmentation, bbox, area, ...}]
    masks = filter_masks(masks)

    # Stage 3
    objects = []
    for m in masks:
        crop = crop_by_mask(img, m)
        cls  = classify(crop)              # rule + VLM
        objects.append({"mask": m, "cls": cls, "crop": crop})

    # Stage 4
    for o in objects:
        if o["cls"] == "text":
            o["ocr"]  = ocr.run(o["crop"])
            o["font"] = match_font(o["crop"], o["ocr"])
        elif o["cls"] in ("shape", "icon"):
            o["svg"]  = vtracer_run(o["crop"])
            o["custgeom"] = svg_to_custgeom(o["svg"])
        elif o["cls"] == "chart":
            o["data"] = deplot_run(o["crop"])

    # Stage 5
    objects = reconstruct_layout(objects)

    # Stage 6
    compose_pptx(objects, out_pptx)

def vtracer_run(png_path):
    out = png_path.with_suffix(".svg")
    subprocess.run(["vtracer", "--input", str(png_path),
                    "--output", str(out), "--colormode", "color"],
                   check=True)
    return out.read_text()
```

---

*본 계획서는 살아있는 문서이며, MVP 완성 시점에서 v0.2로 갱신될 예정.*
