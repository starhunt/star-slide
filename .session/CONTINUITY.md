# Star-Slide Session Continuity

> 매 세션 종료 전 갱신. 새 세션 시작 시 가장 먼저 읽기.

---

## 현재 상태 (2026-04-25)

- **Phase**: Phase 0 (Spike) — Day 1
- **진행 태스크**: P0-T02 샘플셋 수집 — 27/100장 + 라벨 골격 (in progress, 라벨 작성 대기)
- **블로커**: 추가 73장 출처 결정 + 27장 라벨링 누가 할지 결정

## 완료된 작업

- ✅ 3개 원본 PRD(Codex/Claude/Manus) 검토 + 통합 PRD 작성
- ✅ 최신 기술 검증 리서치 (researcher 에이전트, 2026-04-25)
- ✅ ADR 14건 작성 (`docs/Star-Slide_TechDecisions.md`)
- ✅ 상세 개발계획 6개월 분 작성 (`docs/Star-Slide_DevPlan.md`)
- ✅ 프로젝트 구조 가이드 (`docs/Star-Slide_Structure.md`)
- ✅ P0-T01: git init, 디렉토리, pyproject.toml, pre-commit, CI 골격 + 첫 커밋 `179d976`
- ✅ refdata 분석: sample1.pptx(17장) + sample2.pptx(10장) 모두 100% 이미지-잠금 확인 (PRD §2 가정 실증)
- ✅ 27장 슬라이드 이미지 추출 → `data/samples/notebooklm/`
- ✅ 27장 라벨 골격 JSON 생성 → `data/labels/notebooklm/`
- ✅ 라벨링 가이드 작성 → `data/labels/notebooklm/LABELING_GUIDE.md`

## 핵심 결정 (사용자 답변)

- **MVP 범위**: 텍스트 + 단순도형/아이콘 + 표(T1-T2) + 인페인팅
- **외부 API**: OSS-first, 유료 API는 옵션 (기본 OFF)
- **인터페이스**: CLI/API 우선, 웹은 Phase 3
- **타깃**: 개인 PM/기획자 (NotebookLM/Gamma 사용자)

## 리서치 정정 사항 (반영 완료)

1. **vtracer는 MIT** (Claude/Manus PRD GPL-3.0 기재 정정)
2. gpt-image-2 한국어 정확도 95% (Manus PRD 99% 주장은 마케팅 수치)
3. ChartGemma 라이선스 위험 → DePlot 채택
4. python-pptx custGeom 직접 임포트 미지원 → 자체 변환기 필수

## 다음 단계 (즉시)

1. **사용자 라벨링 작업** (10장, `data/labels/notebooklm/H1_PRIORITY_TRACKING.md` 참조)
   - 1차 필수: ground_truth_text (정답 한글 텍스트 입력)
   - 2차: objects[] 배열 (bbox + 텍스트 객체 분류)
2. **사용자 GPU 환경에서 SAM 3.1 가중치 다운로드**
3. P0-T03 SAM 3.1 추론 코드 완성 (현재 loader.py placeholder, 라벨/모델 준비 후 채움)
4. P0-T04/T05 (H2 custGeom + H3 OCR) 병렬 진행 가능

## 관찰 사항 (Phase 0 데이터셋 분석)

- **이미지 다운샘플**: NotebookLM 임베드 이미지 1376x768 (슬라이드 EMU 좌표 1707x960px @ 96DPI 대비 ~80%) → P1-T02 래스터화는 LibreOffice 슬라이드 합성 우선이 임베드 이미지 추출보다 정확
- **NotebookLM 워터마크**: 모든 슬라이드 우측 하단 고정 → background_decoration 사전 분류 정책 확정 (label 골격에 반영됨)
- **샘플 범주 다양성** (27장 관찰):
  - 표지(타이틀+서브+일러스트): sample1_slide01, sample2_slide01
  - 비교 다이어그램(Early/Late): sample1_slide02
  - 프로세스 흐름도(swim lane + 4단계): sample1_slide05
  - 카드형 비교(3열 메트릭+도넛): sample2_slide05
- **표 1장 발견** (정정): sample2_slide03 = Pro vs Flash 매트릭스(5행x3열) → MVP 표 복원 검증에 직접 사용 가능
- **H1 priority 10장 선정 완료**: 4가지 패턴(title/comparison/process/diagram/infographic) + 표 1 + 인포그래픽 1
  - 추적 파일: `data/labels/notebooklm/H1_PRIORITY_TRACKING.md`
- **H1 priority 10장 ground_truth_text 입력 완료** (2026-04-25, claude-vision)
  - 평균 217자/슬라이드, 총 2,082자
  - 큰 텍스트 정확, 작은 텍스트는 1376x768 해상도에서 보이는 만큼
  - 사용자 검수는 H3 측정 전 권장 (필수는 아님)

## Phase 0 가설 검증 일정

- Day 1 (오늘): P0-T01 스켈레톤
- Day 2-3: P0-T02 샘플셋 + 라벨링
- Day 4-5: P0-T03 H1 SAM 3.1 IoU 검증
- Week 2: P0-T04 H2 custGeom + P0-T05 H3 OCR + Phase 0 Exit Gate

## 사용자 결정 대기 중

- [ ] GPU 환경: A100 80GB 1대 vs RTX 4090 (개발용) 혹은 MacBook M4 Max(MPS)
- [ ] 무료 한글 폰트 풀 30종 리스트 확정 (Phase 0 끝)
- [ ] SAM License 원문 재배포/임계치 조항 확인 (변호사 자문 필요?)

## Mistakes & Learnings

| 시점 | 실수/관찰 | 원인 | 해결책 | 재발 방지 |
|---|---|---|---|---|
| 2026-04-25 | Manus PRD가 vtracer를 GPL-3.0으로 기재 | LICENSE 미확인 | researcher 에이전트로 LICENSE 직접 확인 → MIT 확정 | 외부 의존성 도입 전 LICENSE 파일 직접 검증 (CLAUDE.md 외부 라이브러리 규칙 적용) |
| 2026-04-25 | Manus PRD의 99% glyph accuracy 주장 | 마케팅 수치 인용 | 독립 학술 벤치마크 부재 명시, 95% 보수치 사용 | 정확도 주장은 반드시 출처 신뢰도 등급(HIGH/MED/LOW) 표기 |

## 참조

- 통합 PRD: `docs/Star-Slide_PRD.md`
- ADR: `docs/Star-Slide_TechDecisions.md`
- 개발계획: `docs/Star-Slide_DevPlan.md`
- 구조: `docs/Star-Slide_Structure.md`
