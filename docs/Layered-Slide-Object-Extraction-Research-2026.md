# 이미지 기반 슬라이드의 계층적 객체 추출 리서치 노트

작성일: 2026-05-16
대상: `star-slide` 이미지 기반 슬라이드 → 편집 가능한 PPTX 변환 품질 개선

## 문제 정의

Flattened slide image에서 다음 구조를 복원하고 싶다.

- 배경
- 도표/차트/table/diagram 영역
- 큰 그룹 도형/카드/패널
- 그룹 내부의 작은 객체/text/icon/line/arrow
- 큰 객체는 작은 객체를 제외한 “빈 레이어/배경 레이어”로 분리
- 작은 객체는 개별 editable object 또는 replaceable object로 분리
- PowerPoint의 z-order/grouping에 가까운 hierarchy 복원

이 문제는 원본 PPTX/PSD/Figma layer metadata가 사라진 상태라 완전 복원은 원리적으로 underdetermined이다. 그러나 최근 2025–2026 논문과 실용 파이프라인을 결합하면 현재 star-slide의 Vision LLM + raster group 방식보다 더 체계적인 근사 복원이 가능하다.

---

## 1. 가장 직접적으로 관련 있는 최신 연구

### LayerD: Decomposing Raster Graphic Designs into Layers

- arXiv: https://arxiv.org/abs/2509.25134
- 공개: 2025-09
- 핵심: flattened raster graphic design을 editable layer로 분해한다.
- 적용성: 매우 높음. 슬라이드/포스터/카드형 디자인과 문제 정의가 거의 같다.
- star-slide 적용 아이디어:
  - 기존 `raster_groups`를 “1개 crop”으로만 다루지 말고, group crop 내부에서 LayerD류 layer peeling을 수행한다.
  - 결과 RGBA layer를 `image object`로 두고, OCR text는 별도 editable text로 올린다.
  - 큰 패널은 background layer, 내부 icon/text는 child layer로 둔다.

### CreatiParser: Generative Image Parsing of Raster Graphic Designs into Editable Layers

- arXiv: https://arxiv.org/abs/2604.19632
- 공개: 2026-04
- 핵심: graphic design image를 text/background/sticker 등의 editable layer로 parsing한다.
- 적용성: 매우 높음. 특히 “텍스트/배경/장식 레이어” 분리가 목표와 일치한다.
- star-slide 적용 아이디어:
  - Vision LLM이 현재 layout JSON을 직접 만들게 하는 대신, VLM parser stage를 `scene graph + layer candidates` 생성기로 사용한다.
  - sticker/decorative layer는 SVG/vectorization 후보로 보낸다.
  - text layer는 OCR/LLM transcription + text fit loop로 보정한다.

### Illustrator's Depth: Monocular Layer Index Prediction for Image Decomposition

- arXiv: https://arxiv.org/abs/2511.17454
- 공개: 2025-11
- 핵심: flat image의 각 pixel/object에 “illustrator depth”, 즉 layer index를 예측한다.
- 적용성: 높음. PowerPoint z-order 복원에 직접 대응된다.
- star-slide 적용 아이디어:
  - object mask별 z-index 추정 stage 추가.
  - rule 기반 z-order: background < cards < images/icons < text < watermark.
  - 향후 모델 기반 layer index predictor로 대체 가능.

### AmodalSVG: Amodal Image Vectorization via Semantic Layer Peeling

- arXiv: https://arxiv.org/abs/2604.10940
- 공개: 2026-04
- 핵심: 보이는 부분만 tracing하지 않고 occluded 부분까지 보완해 semantic SVG layer를 만든다.
- 적용성: 높음. 아이콘/도형/도식 vector 복원에 유용.
- star-slide 적용 아이디어:
  - group 내부의 작은 icon/shape mask를 AmodalSVG/vtracer/OpenCV contour로 SVG화.
  - PPTX에서는 freeform/custGeom 또는 SVG image로 삽입.

### Vector Scaffolding: Inter-Scale Orchestration for Differentiable Image Vectorization

- arXiv: https://arxiv.org/abs/2605.11913
- 공개: 2026-05
- 핵심: polygon soup이 아닌 계층적/스케일별 vectorization.
- 적용성: 중상. star-slide의 `vtracer` 보완 후보.
- 적용 아이디어:
  - 작은 아이콘/로고/flat shape의 vector 품질 개선 실험 후보.

### LICA / synthetic layered design datasets

- LICA: https://arxiv.org/abs/2603.16098
- Synthetic layered design data: https://arxiv.org/abs/2605.15167
- 핵심: layered design decomposition 학습/평가용 데이터.
- 적용성: 장기적으로 매우 높음.
- 적용 아이디어:
  - PPTX를 synthetic source로 사용한다.
  - python-pptx/PptxGenJS로 레이어 tree가 알려진 synthetic slide를 만들고 PNG로 render.
  - 모델/휴리스틱이 원본 layer tree를 얼마나 복원하는지 평가한다.

---

## 2. 차트/도표/문서/UI 영역별 적용 후보

### Chart extraction

- DePlot: https://arxiv.org/abs/2212.10505
- MatCha: https://arxiv.org/abs/2212.09662
- UniChart: https://arxiv.org/abs/2305.14761

적용:

- full slide가 아니라 chart crop에만 적용한다.
- chart detector → crop upscale → chart-to-table → editable chart 재생성 또는 fallback image.
- 초기에 native PowerPoint chart 재생성까지 욕심내기보다, 데이터 table + chart image + metadata를 남기는 것이 현실적이다.

### Document/layout detection

- DocLayout-YOLO: https://arxiv.org/abs/2410.12628
- LayoutParser: https://arxiv.org/abs/2103.15348
- DocLayNet: https://arxiv.org/abs/2206.01062

적용:

- slide 전체를 title/body/figure/table/chart/footer 같은 high-level region으로 먼저 나눈다.
- region별 specialized parser를 적용한다.
- 현재 star-slide의 one-pass VLM layout JSON보다 deterministic routing에 유리하다.

### UI/screenshot parser

- OmniParser: https://github.com/microsoft/OmniParser
- OmniParser 논문: https://arxiv.org/abs/2408.00203, V2 https://arxiv.org/abs/2502.16161
- UIED: https://github.com/MulongXie/UIED
- ScreenAI: https://arxiv.org/abs/2402.04615

적용:

- 앱 화면/다이어그램/아이콘이 많은 슬라이드에서 작은 객체 탐지에 유리하다.
- UIED류 OpenCV+OCR+component merging은 star-slide에 빠르게 실험 가능하다.

### Small object detection

- SAHI: https://arxiv.org/abs/2202.06934
- GroundingDINO: https://arxiv.org/abs/2303.05499
- SAM: https://arxiv.org/abs/2304.02643

적용:

- 큰 group crop 내부를 tile로 쪼개서 작은 객체 recall을 올린다.
- GroundingDINO/SAM은 “arrow, icon, logo, circle, chart bar, legend, card, button” 같은 prompt로 candidate mask를 얻는 데 유용하다.

---

## 3. star-slide에 권장하는 새 파이프라인: Hierarchical Layer Peeling

### 핵심 개념

현재 star-slide는 대략 다음 구조다.

```text
slide image
  -> VLM layout JSON
  -> vector PPTX
  -> raster group detection
  -> hybrid PPTX
  -> QA select
```

새로운 옵션은 다음처럼 바꾼다.

```text
slide image
  -> high-level region detection
  -> text/OCR mask extraction
  -> region별 object proposal
  -> parent group detection
  -> child object detection inside groups
  -> parent background layer = group crop - child masks
  -> child layers = text/icon/shape/chart/table objects
  -> z-order / hierarchy inference
  -> PPTX object tree + QA
```

### 큰 그룹 안의 작은 객체 분리 방법

예: 큰 카드/도표/패널 안에 작은 아이콘, 라벨, 선, 도형이 있을 때.

1. parent group 후보 탐지
   - 큰 contour/rect/card/frame
   - VLM이 말한 `raster_group`
   - DocLayout/OmniParser high-level region
2. child object 후보 탐지
   - OCR boxes
   - OpenCV connected components
   - SAM/Grounded-SAM masks
   - SAHI tiled detection
3. child mask union 생성
   - text mask + icon mask + line mask + shape mask
4. parent background layer 생성
   - parent crop에서 child mask 부분을 제거/inpaint/solid-fill
   - 이 레이어는 `group_background`로 PPTX에 삽입
5. child layer를 위에 올림
   - text → editable text
   - simple shape/line → native PPT shape
   - icon/logo → SVG or raster PNG with alpha
   - chart/table → specialized reconstruction or fallback image
6. hierarchy metadata 저장
   - PowerPoint group shape 자체는 python-pptx에서 제한적이므로, 우선 naming/z-order/metadata로 group을 표시한다.

---

## 4. 속도/품질 면에서 가장 현실적인 MVP

최신 연구 모델을 바로 붙이기 전에, star-slide에는 다음 MVP가 가장 빠르고 효과적이다.

### MVP-A: Classical + OCR + current VLM hybrid

- OpenCV connected components/contours
- OCR text boxes
- VLM high-level group boxes
- SAHI-style tiled small-object proposals
- 기존 `apply_raster_groups_to_layout.py` 확장

장점:

- 빠름
- 로컬 실행 가능
- 현 코드에 바로 붙이기 쉬움
- LLM 호출 수를 줄일 수 있음

단점:

- semantic labeling은 약함
- 복잡한 일러스트는 여전히 raster fallback 필요

### MVP-B: GroundingDINO/SAM optional high-quality mode

- parent group crop 단위로만 GroundingDINO+SAM 실행
- prompt set: `text, icon, arrow, chart, legend, axis, bar, line, circle, rectangle, logo, card, button, image`
- small object는 SAHI/tile로 처리

장점:

- 작은 객체 recall 향상
- 복잡한 group 내부를 더 잘 쪼갤 수 있음

단점:

- 느림
- 모델 설치/메모리 부담
- false positive 후처리 필요

### MVP-C: LayerD/CreatiParser research adapter

- 해당 코드/모델이 사용 가능하면 adapter로 붙인다.
- 출력이 RGBA layer라면 `layout image object`로 매핑한다.
- text는 별도 OCR로 editable화한다.

장점:

- 문제 정의와 가장 가까움

단점:

- 최신 논문이라 코드 성숙도/라이선스/속도 확인 필요
- PPT native object까지는 추가 변환 필요

---

## 5. 추천 실험 우선순위

1. **빠른 로컬 실험**: parent group 내부에서 child masks를 제외한 `group_background` 생성
   - 기존 `apply_raster_groups_to_layout.py`에 가장 잘 맞음.
2. **Small object recall 실험**: SAHI-style tiling + OpenCV components
   - 작은 객체 누락을 줄임.
3. **UIED/OmniParser 비교 실험**
   - icon/card/text가 많은 슬라이드에 적합한지 확인.
4. **GroundingDINO+SAM optional mode**
   - high quality but slower mode.
5. **LayerD/CreatiParser 코드 사용성 확인**
   - 가능하면 research-grade layer parser로 adapter 작성.
6. **Synthetic PPT benchmark 생성**
   - 원본 layer tree가 알려진 synthetic slide로 객관 평가.

---

## 6. 구현 시 schema 확장안

```json
{
  "id": "slide_001",
  "objects": [
    {
      "type": "group",
      "name": "process_diagram_group",
      "bbox": [100, 160, 760, 420],
      "children": ["step_icon_1", "step_label_1", "arrow_1"],
      "background_object": "process_diagram_group_bg",
      "z_index": 10
    },
    {
      "type": "image",
      "name": "process_diagram_group_bg",
      "path": "assets/slide_001/process_diagram_group_bg.png",
      "bbox": [100, 160, 760, 420],
      "source": "parent_layer_minus_children",
      "replaceable": true,
      "z_index": 11
    },
    {
      "type": "text",
      "name": "step_label_1",
      "text": "수집",
      "bbox": [140, 210, 80, 28],
      "parent": "process_diagram_group",
      "z_index": 20
    }
  ]
}
```

python-pptx에서 실제 PowerPoint grouping이 어렵다면 초기에는 다음으로 대체한다.

- object name prefix: `group/process_diagram_group/step_label_1`
- z-order 순서 보존
- report에 hierarchy 저장
- 나중에 OOXML 직접 편집으로 group shape 지원 검토

---

## 7. 결론

“이미지 편집 프로그램이나 PowerPoint가 다룰 만한 문제라 방법이 있을 것”이라는 직감은 맞다. 다만 원본 layer metadata 없이 완전 복원하는 범용 해법은 아직 없다. 대신 2025–2026 연구는 `graphic design layer decomposition` 쪽으로 빠르게 발전 중이며, 특히 LayerD/CreatiParser/AmodalSVG/Illustrator's Depth는 star-slide가 가야 할 방향과 매우 가깝다.

현실적인 단기 개선은 다음이다.

- 큰 group을 통째로 crop하는 대신, **group crop 내부 child object를 먼저 찾고 제거한 parent background layer를 만든다.**
- child는 text/shape/icon/chart/table로 분류해 editable 또는 replaceable object로 올린다.
- SAHI-style tiling + OpenCV component + OCR를 먼저 붙이면 속도 대비 효과가 좋다.
- GroundingDINO/SAM/LayerD류는 high-quality option으로 실험한다.

추천 신규 모드명:

```text
--reconstruction-mode hierarchical-overlay
```

추천 내부 단계명:

```text
region_detect -> child_propose -> group_peel -> object_classify -> layer_emit -> qa_select
```
