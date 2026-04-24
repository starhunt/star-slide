# H1 검증 우선 10장 라벨링 추적

> Phase 0 P0-T03(SAM 3.1 IoU 검증)을 위해 27장 중 10장을 다양성 + 표 포함으로 우선 선별.
> 라벨링 완료 시 `labeled_at` 와 `labeler` 필드를 채우면 자동 진행 가능.

## 선정 10장

| # | 파일 | 카테고리 | 패턴 | 라벨 상태 |
|---|------|----------|------|-----------|
| 1 | `sample1_slide01.png` | title | 표지: 대형 헤드라인 + 서브타이틀 + 일러스트(엔지니어 도시 풍경) | ⬜ |
| 2 | `sample1_slide02.png` | comparison | Early Stage vs Late Stage 다이어그램, AI 아이콘 + 화살표 | ⬜ |
| 3 | `sample1_slide05.png` | process | HUMAN/AI swim lane, 4단계 박스(기획→설계→개발→검증) | ⬜ |
| 4 | `sample1_slide08.png` | diagram | Focusing 흐름도, 좌측 문서 스택 + 우측 Step1/2/3 박스 | ⬜ |
| 5 | `sample1_slide12.png` | process | Main Session/Forked Session 분기 다이어그램 + 캡션 박스 | ⬜ |
| 6 | `sample1_slide17.png` | infographic | 헥사곤 다중 에이전트 인포그래픽 (6개 AGENT 라벨) | ⬜ |
| 7 | `sample2_slide01.png` | title | 표지: CONFIDENTIAL 배지 + 한글 헤드라인 | ⬜ |
| 8 | `sample2_slide03.png` | table | 실제 격자 표: Pro vs Flash 매트릭스 (5행 x 3열) | ⬜ |
| 9 | `sample2_slide05.png` | comparison | 3카드 메트릭 + 도넛 차트 아이콘 (Cache Hit/Miss/Output) | ⬜ |
| 10 | `sample2_slide09.png` | comparison | 2컬럼: 학습 환경 블랙박스 + NPU 검증 (큰 아이콘 2개) | ⬜ |


## 라벨링 워크플로우 (1장당 5-10분)

각 priority=true 라벨 JSON에 다음을 채운다:

### 1차 필수 (먼저 채움)
- `labeled_at`: ISO 8601 (예: "2026-04-25T10:30:00")
- `labeler`: 작업자 이름
- `ground_truth_text`: 슬라이드의 모든 한글 텍스트 (줄바꿈 \n으로 구분, OCR CER 측정 기준)

### 2차 (objects[] 배열, H1 IoU 측정용)
각 의미 객체 1개당 1개 항목:
```json
{
  "id": "obj_001",
  "type": "text",
  "bbox_px": [x, y, w, h],
  "text_content": "AI 에이전트의 완벽한 자율주행을 위한 시스템 설계",
  "notes": ""
}
```

객체 타입: `text | icon | shape | chart | table | photo | background`

### 우선순위 가이드
- 텍스트 객체부터 (H3 OCR 검증 직접 영향)
- 큰 아이콘/일러스트 (H1 SAM 분리 검증 직접 영향)
- NotebookLM 워터마크는 이미 자동 인식 → 재라벨 불필요

## 진행 모니터링

```bash
uv run python -c "
import json, glob
done = sum(1 for p in glob.glob('data/labels/notebooklm/*.json')
           if json.loads(open(p, encoding='utf-8').read()).get('h1_priority')
           and json.loads(open(p, encoding='utf-8').read()).get('labeled_at'))
print(f'H1 priority 라벨 완료: {done}/10')
"
```
