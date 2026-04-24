# NotebookLM 샘플셋 라벨링 가이드

## 입력
- `data/samples/notebooklm/sample{1,2}_slide{NN}.png` — 27장
- `data/labels/notebooklm/sample{1,2}_slide{NN}.json` — 라벨 골격 (이 가이드에 따라 채움)

## 라벨링 우선순위
Phase 0 H1/H2/H3 검증에 필요한 최소 정보부터 채운다.

### 1차 필수 (모든 27장)
- `category`: 슬라이드 종류 — `title | diagram | process | comparison | infographic | chart | table | text-heavy`
- `ground_truth_text`: 슬라이드의 모든 한글 텍스트를 사람이 정확히 입력 (OCR CER 측정용, H3 핵심)
- `labeler`: 작업자 이름

### 2차 (대표 슬라이드 10장만, H1 검증용)
각 슬라이드당 5-15개 객체:
- `objects[]`:
  - `id`: "obj_001" 형식
  - `type`: text | icon | shape | chart | table | photo | background
  - `bbox_px`: [x, y, w, h] (px 단위)
  - `text_content`: 텍스트 객체일 때 정답 텍스트
  - `notes`: (선택) 검수자 코멘트

### 3차 (Phase 0 끝까지)
- 폰트 추정 (`Pretendard | Noto Sans KR | 나눔고딕 | 명조 계열 | 기타`)
- 색상(주요 fill/stroke)

## 라벨링 도구
- 1차: 텍스트 에디터로 직접 JSON 편집
- 2차: CVAT 또는 LabelMe 사용 권장 (bbox 시각 라벨)

## 검증
`uv run pytest tests/data/test_label_integrity.py` (Phase 0 P0-T06에서 작성)
