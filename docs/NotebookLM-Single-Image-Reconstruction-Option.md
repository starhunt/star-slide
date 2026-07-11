# NotebookLM 단일 이미지 재구성 옵션 적용 지침

작성일: 2026-05-16
대상 프로젝트: `star-slide`
목적: 기존 `notebooklm run` 파이프라인을 대체하지 않고, 최근 검증한 **단일 슬라이드 이미지 → 편집 가능 PPTX** 접근을 옵션/부가기능으로 통합하기 위한 지침.

---

## 1. 현재 스킬화/프로세스화 수준

개별 이미지 한 장 기준으로는 **실험 단계가 아니라 재사용 가능한 프로세스 초안 수준**까지 정리되었다고 볼 수 있다.

다만 상태를 정확히 나누면 다음과 같다.

- **프로세스 안정도**: 중상
  - 입력 이미지 1장에 대해 장면 JSON을 만들고, 텍스트/도형/이미지 레이어를 분리한 뒤, PPTX로 조립하고 렌더 QA를 보는 절차는 명확하다.
- **자동화 수준**: 중간
  - `star-slide`에는 이미 `generate_layout_json.py`, `generate_layout_batch.py`, `reconstruct_from_layout.py`, `layout_qa.py`, `apply_raster_groups_to_layout.py`가 있어 큰 틀은 들어와 있다.
  - 아직 “NotebookLM 마크를 삭제하지 않고 별도 removable object로 유지”, “solid-fill 우선 텍스트 제거”, “텍스트 fit loop”는 명시 옵션으로 완전히 고정되어 있지 않다.
- **품질 기대치**: 실무 보조 가능
  - 완전한 원본 복제보다는 `보기에는 원본에 충분히 가깝고, 주요 텍스트/객체를 수정 가능하게 만드는` 쪽에 적합하다.
  - 복잡한 일러스트/도식은 세부 요소로 쪼개기보다 **replaceable raster group**으로 유지하는 편이 현재 품질이 좋다.
- **권장 통합 방식**: 기존 자동 변환의 기본값을 바꾸기보다 `mode`/옵션으로 추가
  - 기존 로직: NotebookLM 워터마크 제거, vector/hybrid 자동 선택, deck 단위 batch 처리.
  - 신규 옵션: 단일 이미지 또는 슬라이드별 처리에서 `stable text overlay + removable mark + conservative raster groups`를 선택 가능하게 함.

요약하면: **개별 이미지 1장 처리는 “옵션화 가능한 recipe” 단계**이며, star-slide에서는 기존 파이프라인의 fallback/고품질 모드/디버그 모드로 붙이는 것이 적절하다.

---

## 2. 새 접근의 핵심 원칙

### 2.1 원본 이미지를 통째로 배경으로 쓰지 않는 것을 기본 목표로 한다

최종 PPTX의 목표는 다음 순서다.

1. 편집 가능한 텍스트
2. 편집 가능한 단순 도형/선/카드 프레임
3. 복잡한 그림/도식은 교체 가능한 이미지 객체
4. 실패 시에만 원본 전체 이미지 fallback

단, 모든 요소를 억지로 벡터화하지 않는다. 작은 아이콘, 복잡한 생성형 일러스트, 텍스트가 박힌 미세 라벨은 raster group으로 유지하는 편이 낫다.

### 2.2 NotebookLM 마크는 삭제/배경 병합이 아니라 별도 객체 옵션을 둔다

현재 프로젝트에는 다음 로직이 있다.

- `scripts/generate_layout_json.py`
  - system prompt에서 “NotebookLM watermark/logo를 포함하지 말라”고 지시
  - `_drop_notebooklm_watermark(layout)`로 이름/텍스트에 `notebooklm`이 들어간 객체를 제거
- `scripts/apply_raster_groups_to_layout.py`
  - `is_notebooklm_watermark()`로 워터마크 텍스트 객체 제거
- `star_slide/input/watermark_remover.py`
  - `fast`/`detail` 워터마크 제거 모드 제공

신규 옵션에서는 이 동작을 다음처럼 확장한다.

- 기본 기존 동작은 유지: `remove` 또는 `drop`
- 신규 동작 추가: `separate_object`
  - NotebookLM 마크를 **별도 image object** 또는 작은 shape/text group으로 보존
  - 객체 이름 예: `notebooklm_mark_removable`
  - metadata 예: `{"removable": true, "source": "notebooklm_mark"}`
  - clean background에는 절대 병합하지 않음
  - 사용자가 PowerPoint에서 선택 후 삭제할 수 있어야 함

권장 옵션명:

```text
--notebooklm-mark-policy remove|separate_object|keep_in_raster
```

초기 기본값은 기존 호환성을 위해 `remove`가 안전하다. 사용자가 “마크를 나중에 지울 수 있게 분리”를 원할 때 `separate_object`를 켠다.

### 2.3 텍스트 제거는 diffusion/inpaint보다 solid-fill 우선

NotebookLM 스타일 슬라이드는 흰색/옅은 회색/단색 카드 배경이 많다. 이런 경우 텍스트를 지울 때 인페인팅을 기본으로 쓰면 오히려 얼룩, 수평 smear, 흐릿한 잔상이 생긴다.

권장 규칙:

- 텍스트 bbox 주변이 단색/저분산이면 `solid` fill
- 카드/노트 박스 내부는 Vision annotation의 `background_color`를 우선 사용
- 배경색이 없으면 bbox 외곽 ring sampling으로 추정
- 그라디언트/사진/복잡한 도식 위 텍스트만 `inpaint` 또는 `alpha punchout`

권장 옵션명:

```text
--text-erase-mode auto|solid|inpaint|alpha|none
```

초기 구현은 `auto`를 추가하고 내부 규칙은 단순하게 시작한다.

```python
if explicit_background_color:
    mode = "solid"
elif local_variance < threshold and not overlaps_image_group:
    mode = "solid"
else:
    mode = "inpaint"
```

### 2.4 텍스트 크기는 반드시 render-driven fit loop로 보정한다

Vision LLM이 추정한 `font_size`는 PowerPoint/LibreOffice에서 그대로 맞지 않는 경우가 많다.

권장 흐름:

1. layout JSON 생성
2. PPTX 생성
3. LibreOffice로 PNG 렌더
4. 원본 이미지와 비교 + 텍스트 overflow 검사
5. bbox 안에 맞지 않는 text object만 font size 조정
6. 1~2회 반복

초기에는 전체 `font_scale`만 적용해도 되지만, 장기적으로는 object별 fit이 필요하다.

현재 관련 위치:

- `scripts/reconstruct_from_layout.py`
  - `LayoutRenderer._add_text()`에서 `font_scale` 적용
- `scripts/layout_qa.py`
  - `run_qa(..., font_scale=...)`로 QA 렌더 수행
- `star_slide/pipeline/notebooklm_auto.py`
  - `NotebookLmAutoOptions.font_scale` 기본값 0.93

신규 옵션은 전체 scale + 객체별 fit으로 확장한다.

```text
--fit-text off|global|per-object
```

초기 기본값 후보: `global`

---

## 3. star-slide 현 구조와 매핑

현재 프로젝트에는 이미 신규 접근의 주요 부품이 있다.

### 3.1 입력 정규화

관련 파일:

- `star_slide/input/pptx_extractor.py`
  - `extract_embedded_images()`
  - `extract_pdf_pages()`
  - `is_image_locked()`
- `star_slide/pipeline/notebooklm_auto.py`
  - PPTX/PDF 입력을 `workdir/images/slide_XXX.png` 계열로 정규화

적용 방향:

- 단일 이미지 파일 입력도 같은 `images/slide_001.png` 구조로 normalize한다.
- PDF/PPTX deck 입력은 기존처럼 slide별 이미지로 normalize한다.
- 신규 옵션도 deck 전체가 아니라 **slide job 단위**로 독립 처리 가능해야 한다.

### 3.2 장면/layout JSON 생성

관련 파일:

- `scripts/generate_layout_json.py`
- `scripts/generate_layout_batch.py`
- `star_slide/vision_llm/schema.py`

현재 특징:

- Vision LLM으로 `layout.json` 생성
- text/shape/line/polyline 위주
- image object는 strict mode에서 제한적
- NotebookLM watermark는 제거 방향

적용 방향:

- prompt에 `notebooklm_mark_policy`를 주입할 수 있게 한다.
- schema에 다음 필드를 허용하는 것을 고려한다.

```json
{
  "type": "image",
  "name": "notebooklm_mark_removable",
  "path": "assets/slide_001/notebooklm_mark.png",
  "bbox": [1230, 704, 120, 34],
  "replaceable": true,
  "removable": true,
  "source": "notebooklm_mark"
}
```

주의: `validate_layout()`는 이미 `image` 객체를 지원하지만 strict mode에서는 image를 금지한다. `separate_object` 옵션에서는 `--allow-images` 또는 별도 예외가 필요하다.

### 3.3 복잡한 도식/일러스트 처리

관련 파일:

- `scripts/detect_raster_groups.py`
- `scripts/apply_raster_groups_to_layout.py`
- `scripts/apply_sam3_box_to_raster_groups.py`
- `star_slide/pipeline/notebooklm_auto.py`

현재 특징:

- Vision LLM으로 raster group 후보 탐지
- 선택적으로 SAM3 bbox refinement
- raster group 안의 텍스트는 editable로 유지하거나 punchout/inpaint
- 작은 embedded label은 raster에 남기는 휴리스틱 존재

적용 방향:

- 신규 옵션은 “maximum vectorization”이 아니라 “stable hybrid overlay”를 목표로 한다.
- 도식 전체를 replaceable image로 유지하면서 주요 제목/본문만 editable로 올리는 정책을 강화한다.
- `rasterize_embedded_labels`는 케이스별 선택 가능하게 유지한다.

### 3.4 PPTX 조립과 QA

관련 파일:

- `scripts/reconstruct_from_layout.py`
- `scripts/layout_qa.py`
- `star_slide/rasterize/libreoffice.py`
- `star_slide/api/preview_assets.py`

현재 특징:

- layout JSON → PPTX 생성
- LibreOffice 렌더 → 원본 대비 diff/montage 생성
- vector/hybrid 결과 자동 선택

적용 방향:

- 단일 이미지 옵션에서도 반드시 `layout_qa.py`를 실행한다.
- QA 산출물은 web preview에서 볼 수 있게 기존 `qa_vector`, `qa_hybrid`, `qa_selected` 구조와 호환시킨다.
- 신규 mode 이름 후보:

```text
qa_stable_overlay/
qa_layered_debug/
qa_selected/
```

---

## 4. 권장 신규 모드: `stable_overlay`

기존 모드와 충돌하지 않도록 신규 옵션을 다음처럼 정의한다.

```text
star-slide notebooklm run input.pptx \
  -o output.pptx \
  --reconstruction-mode auto|vector|hybrid|stable-overlay \
  --notebooklm-mark-policy remove|separate_object|keep_in_raster \
  --text-erase-mode auto|solid|inpaint|alpha|none \
  --fit-text off|global|per-object
```

### 4.1 `stable-overlay`의 의미

`stable-overlay`는 다음 원칙을 따른다.

- 배경: 가능한 한 재구성된 solid/decorated background 사용
- 텍스트: 주요 텍스트는 editable text box로 복원
- 카드/선/프레임: 단순 도형이면 editable shape/line
- 복잡한 도식: replaceable raster group
- NotebookLM 마크: 옵션에 따라 제거 또는 별도 removable object
- 실패한 슬라이드: 원본 이미지 fallback + QA report에 명시

### 4.2 기존 `hybrid`와의 차이

- `hybrid`: vector layout과 raster group replacement를 만들고 QA diff로 선택하는 현재 주력 경로
- `stable-overlay`: 처음부터 “시각 안정성”을 더 우선한다. 복잡한 내부 요소를 덜 쪼개고, 주요 수정 대상만 editable로 올린다.

즉 `stable-overlay`는 `hybrid`의 보수적 preset으로 구현해도 된다.

---

## 5. 구현 제안

### Step 1. 옵션 모델 확장

파일: `star_slide/pipeline/notebooklm_auto.py`

`NotebookLmAutoOptions`에 필드를 추가한다.

```python
reconstruction_mode: str = "auto"  # auto|vector|hybrid|stable_overlay
notebooklm_mark_policy: str = "remove"  # remove|separate_object|keep_in_raster
text_erase_mode: str = "auto"  # auto|solid|inpaint|alpha|none
fit_text: str = "global"  # off|global|per_object
```

### Step 2. CLI/API 옵션 연결

관련 파일:

- `star_slide/cli/notebooklm.py`
- `star_slide/api/web_app.py`

CLI와 웹 설정에 동일 옵션을 노출한다. 기존 사용자 호환성을 위해 기본값은 현 동작과 최대한 같게 둔다.

권장 기본값:

```text
reconstruction_mode=auto
notebooklm_mark_policy=remove
text_erase_mode=auto
fit_text=global
```

### Step 3. layout generation에 mark policy 전달

파일:

- `scripts/generate_layout_json.py`
- `scripts/generate_layout_batch.py`
- `star_slide/pipeline/notebooklm_auto.py::generate_layouts()`

변경 방향:

- `--notebooklm-mark-policy` 인자 추가
- system prompt를 policy별로 분기
- `_drop_notebooklm_watermark(layout)`는 `policy == "remove"`일 때만 실행

정책별 prompt 예:

```text
remove: Do NOT include the NotebookLM watermark/logo.
separate_object: If a NotebookLM mark is visible, represent it as a separate removable image object named notebooklm_mark_removable. Do not merge it into the background.
keep_in_raster: Leave the mark only if it is part of a full raster fallback image.
```

### Step 4. NotebookLM 마크 crop 생성

처음부터 LLM이 mark asset을 만들 수는 없으므로 후처리에서 crop을 생성한다.

추가 유틸 후보:

```text
star_slide/input/notebooklm_mark.py
```

역할:

- 우측 하단 후보 bbox 계산
- 필요 시 OCR/텍스트 탐지로 `NotebookLM` 위치 확인
- crop PNG 저장: `workdir/assets/slide_001/notebooklm_mark.png`
- layout object에 image object 삽입

초기 단순 bbox는 `watermark_remover.py`의 `_watermark_box()`를 재사용할 수 있다.

### Step 5. text erase mode를 raster group 적용에 연결

파일: `scripts/apply_raster_groups_to_layout.py`

현재 `--erase-mode inpaint|alpha|none`이 있다. 여기에 `solid` 또는 `auto`를 추가한다.

- `solid`: punchout 대상 텍스트 bbox를 주변/명시 색으로 채움
- `auto`: 저분산/명시 배경색이면 solid, 아니면 inpaint

장기적으로는 layout text object에 `background_color` 필드를 추가한다.

예:

```json
{
  "type": "text",
  "name": "card_body_1",
  "text": "...",
  "bbox": [100, 200, 420, 80],
  "font_size": 17,
  "color": "#222222",
  "background_color": "#F8F7F2"
}
```

### Step 6. 단일 이미지 fast path 추가

현재 `notebooklm run`은 PPTX/PDF 중심이다. 단일 이미지 파일을 직접 받을 수 있게 하면 이번 프로세스와 잘 맞는다.

권장 동작:

```text
star-slide notebooklm run slide.png -o slide_rebuilt.pptx --reconstruction-mode stable-overlay
```

내부 처리:

1. `workdir/images/slide_001.png`로 복사
2. 이후 deck과 동일한 slide list pipeline 사용
3. 최종 PPTX는 1-slide deck으로 저장

---

## 6. 슬라이드별 artifact 구조

신규 옵션을 디버깅하기 쉽게 하려면 한 장 처리에도 artifact를 명확히 남긴다.

```text
work/
  images/
    slide_001.png
  layouts_vector/
    slide_001.layout.json
  raster_groups/
    slide_001_raster_groups.json
  layouts_stable_overlay/
    slide_001.layout.json
    assets/
      slide_001/
        01_diagram.png
        notebooklm_mark.png
  qa_stable_overlay/
    slide-1.png
    montage.png
    qa_report.json
    qa_pairs/
      slide_01_orig_vs_render.png
  qa_selected/
    ...
  notebooklm_auto_report.json
```

이 구조는 batch deck에도 그대로 확장된다.

---

## 7. QA 기준

단일 이미지 옵션은 산출물만 보고 성공 판단하지 말고 다음을 체크한다.

- 원본 이미지 크기와 PPTX 슬라이드 비율이 일치한다.
- 제목/본문/주요 라벨은 선택 가능한 텍스트 박스다.
- 텍스트가 bbox 밖으로 넘치거나 잘리지 않는다.
- 도식/일러스트는 너무 잘게 쪼개지지 않고 교체 가능한 이미지 객체로 유지된다.
- NotebookLM 마크 정책이 지켜진다.
  - `remove`: 최종 렌더에 보이지 않음
  - `separate_object`: 최종 렌더에는 보이되 PowerPoint에서 별도 선택/삭제 가능
  - `keep_in_raster`: fallback 또는 원본 raster에 남아 있음을 report에 명시
- `qa_report.json`에 object count, picture count, diff가 남는다.
- `qa_pairs/` 원본-vs-렌더 비교 이미지에서 큰 레이아웃 어긋남이 없다.

---

## 8. 권장 개발 순서

1. **문서/옵션만 먼저 추가**
   - CLI/API schema에 옵션을 추가하되 기본 동작은 바꾸지 않는다.
2. **mark policy 분기 구현**
   - `_drop_notebooklm_watermark()`를 조건부로 바꾸고 `separate_object` crop 삽입을 구현한다.
3. **단일 이미지 입력 fast path**
   - `.png/.jpg/.jpeg`를 직접 `notebooklm run`에 넣을 수 있게 한다.
4. **stable-overlay preset 추가**
   - 기존 hybrid 생성 로직을 재사용하되 conservative preset을 둔다.
5. **text erase auto/solid 추가**
   - inpaint smear가 줄어드는지 `qa_pairs`로 비교한다.
6. **per-object text fit은 마지막에**
   - 먼저 global `font_scale` + QA를 안정화한 뒤 object-level fit을 붙인다.

---

## 9. 최소 구현 체크리스트

- [ ] `NotebookLmAutoOptions`에 `reconstruction_mode`, `notebooklm_mark_policy`, `text_erase_mode`, `fit_text` 추가
- [ ] CLI `star-slide notebooklm run --help`에 신규 옵션 노출
- [ ] 웹앱 설정 모달에 신규 옵션 추가 또는 advanced section에 숨김 옵션으로 추가
- [ ] `generate_layout_json.py`에 `--notebooklm-mark-policy` 추가
- [ ] `_drop_notebooklm_watermark()` 조건부 실행
- [ ] `separate_object`일 때 mark crop asset 생성 + layout image object 삽입
- [ ] 단일 이미지 입력 지원
- [ ] stable-overlay artifact dir 생성
- [ ] `layout_qa.py`로 렌더 QA 수행
- [ ] README에는 “고급 옵션”으로 짧게만 소개하고, 상세는 이 문서로 링크

---

## 10. 당장 적용 시 주의할 점

- 현재 `generate_layout_json.py`의 prompt는 “image object는 real photo/screenshot에만 사용”이라고 되어 있다. `separate_object` 마크 정책을 쓰려면 이 문구에 예외를 둬야 한다.
- 현재 `validate_layout(strict_editable=True)`는 image object를 error로 본다. stable-overlay는 image object가 정상 요소이므로 `--allow-images` 또는 policy-aware validation이 필요하다.
- 현재 fallback layout은 `slide_size_emu`를 16:9 고정 `[16_256_000, 9_144_000]`으로 쓴다. 입력 이미지 비율이 16:9가 아닐 경우 slide size 계산 정책이 필요하다.
- 기존 `watermark_mode=fast/detail`은 “제거” 기능이고, 신규 `notebooklm_mark_policy=separate_object`는 “분리 보존” 기능이다. 둘은 동시에 켜지면 충돌하므로 우선순위를 정해야 한다.
  - 권장: `watermark_mode != off`이면 제거 모드가 우선, mark policy는 `remove`로 강제하거나 warning을 낸다.
- 신규 옵션은 기존 사용자의 기대 결과를 바꾸지 않도록 기본값을 보수적으로 둔다.

---

## 11. 결론

단일 이미지 한 장 처리 방식은 이제 star-slide에 다음 형태로 적용할 수 있다.

- 기존 NotebookLM deck 자동 변환의 **대체재가 아니라 보수적 고품질 옵션**
- 복잡한 도식은 raster group으로 안정 보존하고, 주요 텍스트만 editable로 올리는 **stable-overlay preset**
- NotebookLM 마크는 `remove` 외에 `separate_object`를 제공해 사용자가 PowerPoint에서 직접 삭제 가능하게 하는 부가기능
- `solid/auto text erase`와 `render-driven text fit`을 통해 현재 품질 병목인 얼룩/글자 넘침을 줄이는 방향

즉, 지금 단계에서 가장 현실적인 적용은 **`--reconstruction-mode stable-overlay` + `--notebooklm-mark-policy separate_object` + `--text-erase-mode auto`** 조합을 고급 옵션으로 추가하는 것이다.
