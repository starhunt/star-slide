# H1 검증 보고서: SAM 3.1 슬라이드 객체 분리 IoU

> 작성: P0-T03 진행 중. 라벨 완료 후 자동 갱신.

## 가설 (PRD §Phase 0)

> SAM 3.1이 한글 슬라이드의 의미 객체를 IoU ≥ 0.8로 분리하는가

## Acceptance Criteria

- [ ] 50장 수동 라벨 슬라이드 평균 IoU ≥ 0.8
  - **현재 계획**: 27장 NotebookLM 샘플 중 H1 priority 10장 우선 측정 → 시그널 보고 25-30장 보강 결정
- [ ] 텍스트 영역 글자 단위 분해율 ≤ 30% (사전 검출 후)

## 실험 설계

### 입력
- `data/samples/notebooklm/` 27장 (1차: priority 10장만)
- `data/labels/notebooklm/*.json` (h1_priority=true 슬라이드)

### 파이프라인
1. 이미지 로드 (PIL)
2. 사전 보호: EAST/CRAFT 텍스트 영역 검출, 차트 디텍터(YOLO chart, 옵션)
3. SAM 3.1 `SamAutomaticMaskGenerator` (`points_per_side=32`, `pred_iou_thresh=0.86`)
4. 후처리: IoU > 0.7 중복 제거, 0.05% 미만 노이즈 제거, 80%+ 배경 분리
5. 라벨 ground truth 객체별 best match IoU 계산

### 출력
- `experiments/h1_sam31/results/per_slide_iou.json` — 슬라이드별 IoU 분포
- `experiments/h1_sam31/results/visualization/*.png` — 마스크 오버레이
- 본 보고서 갱신 (평균 IoU, 실패 케이스, 텍스트 분해율)

## 진행 상태

| 단계 | 상태 |
|------|------|
| IoU 헬퍼 모듈 | ✅ `star_slide/segmentation/iou.py` + 단위 테스트 |
| SAM 로더 인터페이스 | ✅ `star_slide/segmentation/loader.py` (placeholder) |
| SAM 3.1 가중치 다운로드 | ⏳ 사용자 GPU 서버 작업 필요 |
| EAST/CRAFT 사전 검출기 | ⏳ |
| H1 priority 10장 라벨 | ⏳ 사용자 라벨링 대기 |
| Notebook 실행 + 결과 | ⏳ |

## 결과 (라벨/추론 완료 후 채움)

### 평균 IoU
TBD

### 분포 히스토그램
TBD

### 실패 케이스 분석
TBD

### Decision (GO/NO-GO)
TBD — H1 GREEN(IoU≥0.8) → P1 진입, RED → SAM 2 fallback 또는 fine-tune
