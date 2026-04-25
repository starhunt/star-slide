# Star-Slide Session Continuity

> 매 세션 종료 전 갱신. 새 세션 시작 시 가장 먼저 읽기.
> 마지막 갱신: 2026-04-25 (Phase 1 P1-T06 완료 시점)

---

## 현재 상태

- **Phase**: Phase 1 (Vertical Slice MVP)
- **GitHub**: https://github.com/starhunt/star-slide (private), main 브랜치, 11 커밋
- **마지막 커밋**: `2227860 feat(inpaint): integrate LaMa text removal into pipeline`
- **블로커**: 없음 (계속 진행 가능)

## End-to-End 작동 검증

```bash
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  uv run star-slide convert run refdata/sample2.pptx \
  -o output/sample2/sample2_edited.pptx \
  --no-libreoffice
# → 105초, 10장, 193 textbox, 100% editable, LaMa 인페인팅 적용됨
```

결과 파일: `output/sample2/sample2_edited.pptx` (사용자 시각 확인 완료, 텍스트 추출 정상)

## 핵심 결정 (사용자 답변 반영)

- **MVP 범위**: 텍스트 + 단순도형/아이콘 + 표(T1-T2) + 인페인팅
- **외부 API**: OSS-first, 유료 API는 옵션 (기본 OFF)
- **인터페이스**: CLI/API 우선, 웹은 Phase 3
- **타깃**: 개인 PM/기획자 (NotebookLM/Gamma 사용자)
- **출력 디렉토리**: `output/<project>/` 규약 (`.gitignore`로 산출물 비추적)

## 리서치 정정 사항 (반영 완료)

1. **vtracer는 MIT** (Claude/Manus PRD GPL-3.0 기재 정정)
2. gpt-image-2 한국어 정확도 95% (Manus PRD 99% 주장은 마케팅 수치)
3. ChartGemma 라이선스 위험 → DePlot 채택
4. python-pptx custGeom 직접 임포트 미지원 → 자체 변환기 필수
5. **SAM 3는 gated repo** (`facebook/sam3`) → SAM 2.1 hiera-large fallback (ADR-001 fallback 경로)

## Phase 0 (Spike) 결과 — 모두 GO

| 가설 | 결과 | 핵심 수치 | 보고서 |
|---|---|---|---|
| H1 SAM 객체 분리 | ✅ GO (SAM 2.1) | recall@contain 0.719, 4.9s/slide MPS | `experiments/h1_sam31/REPORT.md` |
| H2 custGeom 변환 | ✅ GO | 13/13 변환+주입, PowerPoint 호환 | `experiments/h2_custgeom/REPORT.md` |
| H3 PaddleOCR Korean | ✅ GO with caveat | slide5 CER 0.026, slide7 0.067 | `experiments/h3_ocr/REPORT.md` |

## Phase 1 (Vertical Slice MVP) 진행 상황

| Task | 상태 | 비고 |
|---|---|---|
| P1-T01 입력 검증 | ✅ | `star_slide/input/` |
| P1-T02 래스터화 | ✅ | LibreOffice + 임베드 fallback, EMU↔px |
| P1-T03 SAM Worker | ⏳ | 모듈 완성(`sam2_auto.py`), 파이프라인 미통합 |
| P1-T04 객체 분류 | ⏳ | 후속 |
| P1-T05 OCR Worker | ✅ | (Phase 0에서 완성) |
| P1-T06 LaMa 인페인팅 | ✅ | 파이프라인 통합 완료, 잔재 거의 없음 |
| P1-T07 폰트 매칭 | ⏳ | 후속 |
| P1-T08 vtracer/custGeom | ✅ | (Phase 0 H2에서 완성) — 파이프라인 미통합 |
| P1-T09 표 복원 | ⏳ | 후속 |
| P1-T10 Composer | ✅ | 텍스트박스 + 배경 PNG 합성 |
| P1-T11 Visual QA | ⏳ | 후속 |
| P1-T12 CLI convert | ✅ | `star-slide convert run` 동작 |
| P1-T13 통합 테스트 | ⏳ | 후속 |
| P1-T14 Exit Gate | ⏳ | 후속 |

## 다음 단계 (즉시)

추천 우선순위 — PRD MVP exit criteria(편집 가능 비율 80%+) 빠르게 도달:

1. **SAM 객체 분리 통합** (P1-T03/T04) — 도형/아이콘을 별도 객체로 분리
2. **vtracer 통합** (P1-T08) — 도형/아이콘 → native PowerPoint shape (custGeom)
3. **표 native 복원** (P1-T09 T2 레벨) — sample2_slide03 같은 표
4. **Visual QA** (P1-T11) — SSIM 측정 + report.json 강화
5. **회귀 테스트** (P1-T13) — pytest tests/e2e/ 골든 샘플

후속 후보:
- 한글 폰트 매칭 (P1-T07, pgvector 임베딩)
- LibreOffice 설치 후 슬라이드 마스터 합성 정확도 검증
- SAM 3 access 획득 시 sam2_auto → sam3 교체 (PCS 패러다임)

## 코드베이스 현황

- **Python 패키지**: 41 source files, mypy strict GREEN, ruff GREEN
- **테스트**: 54 unit tests passing (smoke 4, iou 14, metrics 15, svg2custgeom 8, input 8, coords 3, rest 2)
- **모듈**:
  - `star_slide/schema/` — Layer Schema (pydantic)
  - `star_slide/input/` — 검증 + PPTX 추출
  - `star_slide/rasterize/` — 좌표 변환 + LibreOffice/fallback
  - `star_slide/segmentation/` — IoU + SAM 2.1 + SAM 3 stub
  - `star_slide/ocr/` — PaddleOCR + 메트릭
  - `star_slide/inpaint/` — LaMa wrapper
  - `star_slide/composer/` — svg2custgeom + inject
  - `star_slide/pipeline/orchestrator.py` — convert() end-to-end
  - `star_slide/cli/` — convert + label + main

## 외부 의존성 (설치됨)

```
torch 2.11.0 (MPS), transformers 5.5.4, paddleocr 3.4.1, paddlepaddle 3.3.1
simple-lama-inpainting 0.1.2 (big-lama 가중치 자동 다운로드 ~196MB)
opencv-python 4.11, pillow 9.5
python-pptx 1.0.2, pdf2image 1.17, pydantic 2.6+
vtracer 0.6.5 (cargo install, ~/.cargo/bin/vtracer)
```

## 사용자 결정 대기 중

- [ ] LibreOffice 설치 여부 (현재 `--no-libreoffice` fallback 사용)
- [ ] SAM 3 HuggingFace access 요청 (선택)
- [ ] PowerPoint H2 시각 검증 (1회): 13 도형 점 편집 메뉴 확인
- [ ] sample2_edited.pptx 직접 검증 (텍스트 편집 가능 여부)

## Mistakes & Learnings

| 시점 | 실수/관찰 | 원인 | 해결책 | 재발 방지 |
|---|---|---|---|---|
| 2026-04-25 | Manus PRD가 vtracer를 GPL-3.0으로 기재 | LICENSE 미확인 | researcher로 LICENSE 직접 확인 → MIT | 외부 의존성 도입 전 LICENSE 직접 검증 |
| 2026-04-25 | Manus PRD 99% glyph accuracy 주장 | 마케팅 수치 인용 | 95% 보수치 사용, 출처 신뢰도 등급 표기 | 정확도 주장은 HIGH/MED/LOW 라벨 |
| 2026-04-25 | SAM 3 access 차단 | gated repo 미인지 | SAM 2.1 fallback 즉시 적용 (ADR-001 약속대로) | 모델 도입 전 access 정책 확인 |
| 2026-04-25 | 인페인팅 첫 시도 잔재 | padding 6 + dilate 0 | padding 12 + dilate 7 + conf 0.3 마스크 임계 | 한글 폰트는 잔재 방지 위해 큰 padding 필요 |
| 2026-04-25 | 인페인팅과 textbox 임계 동일 | 작은 영문 라벨 마스킹 누락 | inpaint_min_confidence(0.3) ≠ ocr_min_confidence(0.7) 분리 | 동일 데이터의 다른 용도 임계 분리 |

## 참조

- 통합 PRD: `docs/Star-Slide_PRD.md`
- ADR (14건): `docs/Star-Slide_TechDecisions.md`
- 개발계획: `docs/Star-Slide_DevPlan.md`
- 프로젝트 구조: `docs/Star-Slide_Structure.md`
- 출력 규약: `output/README.md`
- 라벨링 가이드: `data/labels/notebooklm/H1_PRIORITY_TRACKING.md`

## 새 세션 시작 시 진행 명령

```bash
# 1. 컨텍스트 확인
cat .session/CONTINUITY.md

# 2. 코드베이스 상태 확인
git log --oneline | head -15
uv run pytest tests/ 2>&1 | tail -3

# 3. 최신 변환 결과 확인
ls -la output/sample2/

# 4. 다음 작업 진입 — SAM 객체 분리 통합 (추천 1순위)
# star_slide/segmentation/sam2_auto.py를 pipeline/orchestrator.py에 통합
```
