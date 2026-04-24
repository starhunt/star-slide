# H1 검증 우선 10장 라벨링 — 사용자 워크플로우

> Phase 0 P0-T03(SAM 3.1 IoU 검증)을 위해 27장 중 10장 우선 라벨링.
> 라벨링은 두 가지 방식 중 편한 것 사용. **예시 2장(`sample1_slide01`, `sample2_slide01`)이 미리 채워져 있으니 참고**.

---

## 워크플로우 — 3가지 옵션

### 옵션 A: CLI 헬퍼 (가장 빠름, 추천)

```bash
# 1. 진행 상태 확인
uv run star-slide label list

# 2. 다음 슬라이드 이미지 열기 (macOS Preview)
uv run star-slide label open sample1_slide02

# 3. 텍스트 입력 (EDITOR=code 또는 nano로 자동 열림)
uv run star-slide label text sample1_slide02

# 에디터에서 # 줄을 무시하고 한글 텍스트만 입력 → 저장 → 닫기
# → 자동으로 라벨 JSON에 반영됨

# 4. 다시 list로 확인
uv run star-slide label list
```

EDITOR 환경변수로 원하는 에디터 선택 가능:
```bash
export EDITOR="code --wait"   # VSCode (저장 후 닫을 때까지 대기)
export EDITOR="nvim"          # Vim
export EDITOR="nano"          # 기본
```

### 옵션 B: VSCode 직접 편집 (자유도 높음)

1. VSCode에서 `data/labels/notebooklm/sample1_slide02.json` 열기
2. 같은 화면에 `data/samples/notebooklm/sample1_slide02.png` 미리보기 열기
3. 다음 필드 채움:
   - `labeled_at`: 현재 ISO 시간 (예: `"2026-04-25T10:30:00"`)
   - `labeler`: 작업자 이름
   - `ground_truth_text`: 슬라이드의 모든 한글 텍스트 (시각 줄바꿈 그대로, `\n`)
4. 저장

**예시 형식**: `sample1_slide01.json`, `sample2_slide01.json` 참조 (이미 채워져 있음).

### 옵션 C: macOS Preview + VSCode 분할 화면

1. Finder에서 `data/samples/notebooklm/` 열고 `sample1_slide02.png` 더블클릭 → Preview에 표시
2. VSCode 한쪽에 라벨 JSON 열기
3. 옵션 B와 동일하게 편집

---

## 선정 10장

| # | 파일 | 카테고리 | 패턴 | 상태 |
|---|------|----------|------|------|
| 1 | `sample1_slide01` | title | 표지: 대형 헤드라인 + 서브타이틀 + 일러스트 | ✅ **예시 (claude-example)** |
| 2 | `sample1_slide02` | comparison | Early/Late Stage 다이어그램 + AI 아이콘 + 화살표 | ⬜ |
| 3 | `sample1_slide05` | process | HUMAN/AI swim lane, 4단계 박스 | ⬜ |
| 4 | `sample1_slide08` | diagram | Focusing 흐름도, Step1/2/3 박스 | ⬜ |
| 5 | `sample1_slide12` | process | Main/Forked Session 분기 다이어그램 | ⬜ |
| 6 | `sample1_slide17` | infographic | 헥사곤 6개 AGENT 인포그래픽 | ⬜ |
| 7 | `sample2_slide01` | title | 표지: CONFIDENTIAL 배지 + 헤드라인 | ✅ **예시 (claude-example)** |
| 8 | `sample2_slide03` | table | **격자 표**: Pro vs Flash 매트릭스 | ⬜ |
| 9 | `sample2_slide05` | comparison | 3카드 메트릭 + 도넛 차트 아이콘 | ⬜ |
| 10 | `sample2_slide09` | comparison | 2컬럼 + 큰 아이콘 2개 | ⬜ |

**남은 작업**: 8장 (예시 2장 제외)

---

## 1차 필수 작업 (Phase 0 H3 OCR 검증에 직접 영향)

각 슬라이드에 대해 **`ground_truth_text`만 채우면 됩니다**.

### 텍스트 입력 규칙
- **시각 줄바꿈 그대로**: 슬라이드에서 줄이 바뀌는 위치마다 `\n` 입력
- **빈 줄로 의미 단위 구분**: 제목/부제목/캡션 사이 등
- **워터마크 무시**: NotebookLM 우측 하단 워터마크는 자동 인식되므로 입력 X
- **영문/숫자 그대로**: "1.6T", "AI", "Step 1" 등은 원본 그대로
- **특수기호 그대로**: `[CONFIDENTIAL]`, `:`, `-` 등

### 예시 (`sample1_slide01`)
```
하네스 엔지니어링:
AI 에이전트의 완벽한
자율주행을 위한
시스템 설계

10배의 생산성을 만드는
'통제된 자율성' 구축 가이드
```

### 시간 예상
- 슬라이드당 3-7분 (텍스트 양에 따라)
- 8장 합계 30-50분

---

## 2차 작업 (선택, 시간 여유 시)

H1 SAM 분리 IoU 측정을 더 정밀하게 하려면 `objects[]` 배열에 의미 객체별 bbox를 추가.
**필수는 아님** — Phase 0에서는 사용자가 직접 검토 가능한 텍스트 라벨만으로 시작.

```json
"objects": [
  {
    "id": "obj_001",
    "type": "text",
    "bbox_px": [40, 60, 480, 280],
    "text_content": "하네스 엔지니어링: AI 에이전트의 완벽한 자율주행을 위한 시스템 설계",
    "notes": ""
  },
  {
    "id": "obj_002",
    "type": "icon",
    "bbox_px": [800, 50, 500, 600],
    "text_content": null,
    "notes": "엔지니어 도시 풍경 일러스트"
  }
]
```

bbox 측정 도구:
- macOS Preview: 도구 > 사각 선택 → 보기 > 인스펙터 (선택 영역 px 표시)
- VSCode 확장 "Image Preview"
- 또는 Phase 0에서 SAM 추론 결과를 라벨로 변환하는 자동 도구 작성 가능

---

## 진행 모니터링

```bash
uv run star-slide label list
```

---

## 완료 후

10장 모두 `ground_truth_text`가 채워지면:
1. SAM 3.1 가중치 다운로드 (사용자 GPU 서버)
2. P0-T03 H1 IoU 측정 실행
3. P0-T05 H3 PaddleOCR CER 측정 실행
