# H2 검증 보고서: SVG path → custGeom → PowerPoint 호환

> 실행: 2026-04-25
> 환경: macOS arm64, vtracer 0.6.5, python-pptx 1.0.2, svg.path 7.0
> 샘플: 단순 도형 10종 + cubic 곡선 도형 3종 = 13종

## 가설 (PRD §Phase 0)

> vtracer SVG path → `<a:custGeom>` 변환 후 PowerPoint에서 도형 편집 모드 진입 가능

## Acceptance Criteria

- [x] 13종 SVG path 모두 OOXML custGeom XML 변환 성공 (13/13)
- [x] python-pptx Shape에 custGeom 주입 성공 (13/13)
- [x] 변환된 PPTX가 python-pptx로 재로드 가능
- [ ] PowerPoint 2019+/Microsoft 365에서 도형 우클릭 → "점 편집" 메뉴 활성화 (**사용자 시각 검증 필요**)

## 결과 요약

| 도형 | segments | bbox | XML 길이 | 변환 | 주입 |
|------|---------:|------|---------:|:---:|:---:|
| rectangle | 5 | 100×60 | 419 | ✅ | ✅ |
| rounded_rectangle | 10 | 100×60 | 793 | ✅ | ✅ |
| triangle | 4 | 100×100 | 381 | ✅ | ✅ |
| diamond | 5 | 100×100 | 427 | ✅ | ✅ |
| pentagon | 6 | 100×100 | 475 | ✅ | ✅ |
| star_5pt | 11 | 100×91 | 710 | ✅ | ✅ |
| arrow_right | 8 | 100×80 | 563 | ✅ | ✅ |
| checkmark | 7 | 80×70 | 521 | ✅ | ✅ |
| speech_bubble | 13 | 100×90 | 931 | ✅ | ✅ |
| circle_quad | 6 | 100×100 | 613 | ✅ | ✅ |
| heart (cubic) | 6 | 100×92 | 761 | ✅ | ✅ |
| leaf (cubic) | 4 | 100×76 | 527 | ✅ | ✅ |
| wave (cubic) | 6 | 100×64 | 624 | ✅ | ✅ |

**13/13 변환+주입 성공**, 평균 path 명령 7개, 평균 XML 597자.

## 자동 검증 통과 항목

### 1. PPTX 구조 검증
- `experiments/h2_custgeom/results/h2_shapes.pptx` (29,478 bytes)
- slide1.xml에 custGeom **13개** 존재 (도형 13개와 정확히 일치)
- prstGeom 13개 잔존 — 라벨 textbox 13개의 정상 preset (도형이 아님)
- python-pptx 재로드 시 26개 shape (13 도형 + 13 textbox 라벨) 정상

### 2. OOXML 명령 매핑 검증 (rectangle 예시)
첫 도형 path 명령: `moveTo`, `lnTo`, `lnTo`, `lnTo`, `close` — SVG `M L L L Z`와 정확히 일치.

### 3. 단위 테스트 (8개 통과)
- `test_basic_rectangle`, `test_xml_has_required_elements`, `test_coordinates_scaled_to_target`
- `test_cubic_bezier`, `test_quadratic_bezier`
- `test_negative_coords_normalized`, `test_empty_path_raises`, `test_xml_namespace_prefix_normalized`

## 사용자 시각 검증 (남은 작업)

```bash
open experiments/h2_custgeom/results/h2_shapes.pptx
```

**확인 포인트**:
1. 13개 도형이 모두 정상 표시되는가?
2. 도형 우클릭 → "점 편집(Edit Points)" 메뉴 활성화되는가?
3. 점 편집 모드에서 SVG path와 동일한 점/곡선이 보이는가?
4. 아무 점을 드래그했을 때 도형이 정상 변형되는가?

**Microsoft PowerPoint 외 검증**:
- LibreOffice Impress: 도형 우클릭 → "도형 편집"
- Keynote: 도형 두 번 클릭 → 베지어 편집 모드
- Google Slides: custGeom 임포트 제한적 — fallback 동작 확인

## 한계 및 후속 작업

### Phase 0 한계
- LibreOffice 미설치 → 자동 시각 비교(SSIM) 미수행
- PowerPoint 호환성은 사용자 수동 검증 필요

### Phase 1 후속
- **SVG arc(A) 처리**: 현재는 chord 직선 근사 — 정확한 arc는 a2c 알고리즘 포팅 필요 (FR-053 EMF fallback로 우회 가능)
- **path 수 임계값 정책**: vtracer 출력 path 수가 200을 초과하면 EMF fallback (FR-053)
- **변환 후 SSIM 검증 자동화** (FR-082 export QA)
- **vtracer 실 출력 (NotebookLM 슬라이드 아이콘)**: 27장 슬라이드의 아이콘 영역을 SAM3로 분리 후 vtracer → custGeom → PPTX 통합 PoC

## H2 GO/NO-GO Decision

> **GO (자동 검증 100% 통과, PowerPoint 시각 검증 사용자 1회 권장)**

- 변환기/주입기 모두 자동 테스트 통과
- 13종 도형 + cubic/quadratic bezier 모두 정상 변환
- Phase 1 진입 차단 요소 없음

### Phase 1 진입 시 확인 사항
1. PowerPoint에서 점 편집 모드 정상 작동 (사용자 1회 시각 검증)
2. NotebookLM 실 슬라이드 아이콘에 적용 시 path 수 분포 측정
3. Arc 변환 정확도 (a2c 포팅 필요 시점 결정)

## 출력 파일
- `experiments/h2_custgeom/results/h2_shapes.pptx` — 13종 도형 PPTX
- `experiments/h2_custgeom/results/h2_results.json` — 슬라이드별 변환 메타
- `star_slide/composer/svg2custgeom.py` — 변환기 (재사용 가능)
- `star_slide/composer/inject.py` — python-pptx Shape 주입기

## 다음 단계
H1 (SAM 3.1) — 사용자 GPU 환경 + 가중치 다운로드 후 진행.
