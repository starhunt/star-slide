# 웹앱 UI/UX 개선 (a/b/c) 구현 계획

> 작성일: 2026-04-27
> 대상: `star_slide/api/web_app.py`, `star_slide/pipeline/notebooklm_auto.py`
> 범위: 로컬 MVP 웹앱 (CLI는 무변경)

## 목표

NotebookLM 변환 웹앱의 체감 UX를 3축으로 개선한다.
(a) 업로드 진행률 + 실시간 작업 상태 push, (b) 슬라이드별 원본/Vector/Hybrid 비교 미리보기, (c) 작업 취소 + 누락 슬라이드 재실행.

## 배경

현재 웹앱은 큰 PPTX 업로드 시 진행률이 보이지 않고(`fetch(body)` 단일 요청), 모든 작업 카드를 2.5s 폴링으로 전체 재렌더하고, 변환 결과는 `montage.png` 한 장만 보여주고, 시작된 작업을 멈출 수 없다. 변환은 슬라이드당 LLM 호출이 들어가서 1회당 수 분~십수 분 걸리므로, 잘못된 옵션으로 시작했을 때의 비용이 크다.

## 접근 방식

### (a) 업로드 진행률 + 폴링→SSE

| 방법 | 장점 | 단점 | 공수 |
|------|------|------|------|
| **A1: XHR + SSE 보완** (선택) | 의존성 0, FastAPI `StreamingResponse`로 SSE 가능, 기존 폴링 fallback 유지 | 코드 두 갈래(SSE/poll) 잠시 공존 | 중 |
| A2: WebSocket | 양방향, 추후 cancel 신호도 통합 | `websockets` 의존성 필요, 재연결 로직 복잡 | 중상 |
| A3: 폴링만 유지하고 부분 갱신 | 가장 가벼움 | UX 한계는 그대로 (지연 2.5s) | 하 |

**선택: A1**. SSE는 단방향 push만 필요하고 FastAPI로 dep 없이 구현 가능. 취소는 별도 REST(`POST /api/jobs/{id}/cancel`)로 처리하면 충돌 없음.

### (b) slide-by-slide 비교 미리보기

| 방법 | 장점 | 단점 | 공수 |
|------|------|------|------|
| **B1: 기존 QA 렌더 PNG 노출** (선택) | 추가 렌더링 없음 (qa_vector/qa_hybrid/qa_selected에 이미 PNG 존재), API만 추가 | `--keep-intermediates` 꺼지면 사라짐 → keep 정책 일부 조정 필요 | 중 |
| B2: 변환 시점에 thumbnail 별도 생성 | keep와 무관하게 항상 보존 | 디스크 사용 증가, 별도 렌더 파이프 추가 | 중상 |

**선택: B1 + 보존 정책 보강**. `qa_vector`, `qa_hybrid`, `qa_selected`의 PNG와 원본 `images/`를 작은 thumbnail(예: 480px)로 다운샘플링해 `artifacts/previews/`로 복사. 원본 keep 옵션과 무관하게 항상 보존.

### (c) 작업 취소 + 부분 재실행

| 방법 | 장점 | 단점 | 공수 |
|------|------|------|------|
| **C1: threading.Event cancel token + L1 누락 재실행** (선택) | progress 콜백처럼 단방향 신호. 기존 `workdir` 재사용으로 자연스럽게 incremental | 슬라이드별 선택 재실행은 미지원 (후속) | 중 |
| C2: subprocess 기반 + SIGTERM | 강제 종료 확실 | LLM client/I/O 중간 상태 보장 어려움, OS별 차이 | 중상 |
| C3: L2 (UI에서 슬라이드 선택 재실행) | 최고 정밀도 | `generate_layouts`/`detect_groups`에 `only_slides=[...]` 추가, 캐시 매니저 필요. 별도 PR 권장 | 상 |

**선택: C1**. `convert_notebooklm_auto`에 `cancel: Callable[[], bool] | None = None` 추가, 각 emit() 직후 폴링. 누락 재실행은 `generate_layouts`/`detect_groups`/`build_hybrid_layouts`가 이미 출력 파일 존재 시 skip 가능한지 확인 후, 가능하면 L1, 불가능하면 layout 디렉토리 mtime 비교로 처리.

---

## 태스크 (3 phase, 총 11 task)

### Phase 1: 백엔드 기반 (병렬 가능)

- [x] **T1: `cancel` 파라미터 도입 (pipeline)**
  - 파일: `star_slide/pipeline/notebooklm_auto.py`
  - 내용: `convert_notebooklm_auto`에 `cancel: Callable[[], bool] | None = None` 추가. `emit()` 헬퍼 옆에 `check_cancel()` 헬퍼 추가, 각 단계 전에 호출. 취소 시 `CancelledError` (custom: `JobCancelledError`) raise.
  - Done: 함수 시그니처 변경 + 9개 step 직전 모두에 `check_cancel()` 삽입. CLI 경로(`star_slide/cli/notebooklm.py`)는 `cancel=None` 그대로 호출 → 무영향.
  - 검증: `uv run mypy star_slide/pipeline/notebooklm_auto.py star_slide/cli/notebooklm.py` 통과. 기존 `tests/unit` 무회귀.

- [x] **T2: 진행 보존 가능한 emit() 강화**
  - 파일: 동일
  - 내용: `emit(message, percent)` → `emit(message, percent, slide_done=None, slide_total=None)` 시그니처 확장. 기본값 None으로 호출부 호환. `progress` 콜백 시그니처도 호환 유지(가변 인자 또는 별도 phase 콜백).
  - Done: 기존 호출 모두 통과. 새 정보가 web_app에서 사용 가능.
  - 검증: pytest, mypy.

- [x] **T3: SSE 엔드포인트 + 작업 이벤트 버스 (web_app)**
  - 파일: `star_slide/api/web_app.py`
  - 내용:
    - `JobState`에 `events: list[dict]` (최근 N=50) + `subscribers: set[asyncio.Queue]` 추가 (lock 보호).
    - `update_job` 호출 시 변경된 필드를 이벤트로 push.
    - `GET /api/jobs/{id}/events` → `StreamingResponse` (text/event-stream). 연결 시 현재 snapshot 1회 + 이후 변화 push. heartbeat 15s.
  - Done: curl로 SSE 스트림 수신 확인 (`curl -N http://127.0.0.1:5400/api/jobs/<id>/events`).
  - 검증: 신규 `tests/integration/test_web_app_sse.py` 1건 (FastAPI TestClient + asyncio).

- [x] **T4: 작업 취소 엔드포인트 + ThreadPool 연동**
  - 파일: `star_slide/api/web_app.py`
  - 내용:
    - `JobState`에 `cancel_event: threading.Event` 필드. `run_job`이 `cancel=lambda: state.cancel_event.is_set()` 전달.
    - `POST /api/jobs/{id}/cancel` → `cancel_event.set()` + `Future.cancel()` (큐 대기 중일 때만 효과). 상태를 `cancelling` → `cancelled`로 전환.
    - `JobCancelledError` 처리: status=`cancelled`, error 빈 값.
  - Done: 실행 중 작업에 cancel 호출 시 다음 emit 직후 종료 (최대 1단계 분량 대기).
  - 검증: 통합 테스트 1건 (mock pipeline으로 sleep 단계 가진 fake convert).

- [x] **T5: 누락 재실행 (L1) — `/api/jobs/{id}/rerun`**
  - 파일: `star_slide/api/web_app.py` + 필요시 `pipeline/notebooklm_auto.py` skip 로직 검증
  - 내용:
    - `POST /api/jobs/{id}/rerun` → 같은 input/options/workdir로 새 future 생성. 단, 기존 산출물은 그대로 (`workdir.exists()` 시 layout JSON 재사용 여부는 pipeline의 기존 동작에 의존).
    - pipeline 단계에서 출력 파일 존재 시 skip되는지 확인. **확인 결과 skip 안 되면 별도 sub-task T5b로 분기** (단, 본 계획 범위에서는 "재실행 = 같은 workdir로 처음부터" 안전한 디폴트, skip 최적화는 후속).
  - Done: 실패/취소된 작업에서 rerun 클릭 → 새 job_id 또는 같은 id로 재시작. 옵션은 그대로.
  - 검증: 수동 — 실패 케이스에서 rerun → 정상 완료.

- [x] **T6: 슬라이드 비교 preview 산출물 생성 + 영구 보존**
  - 파일: `star_slide/api/web_app.py` (`run_job` 후처리) 또는 신규 `star_slide/api/preview_assets.py`
  - 내용:
    - `run_job` 성공 후 `qa_vector/`, `qa_hybrid/`, `qa_selected/`, `images/` (원본)에서 슬라이드별 PNG를 `artifacts/previews/{slide_no:03d}_{kind}.jpg` (max width 480, JPEG q80)로 복사.
    - `kind ∈ {original, vector, hybrid, selected}`. 누락된 kind는 생략.
    - `--keep-intermediates`와 무관하게 항상 보존. `artifact_manifest.json` 갱신.
  - Done: `output/web_jobs/<id>/artifacts/previews/`에 슬라이드 × kind 매트릭스 JPEG 생성. 1슬라이드 평균 < 80KB.
  - 검증: pytest 단위 — preview 생성 함수에 fake PNG 입력, 출력 파일 수/크기 assertion.

- [x] **T7: preview API 엔드포인트**
  - 파일: `star_slide/api/web_app.py`
  - 내용:
    - `GET /api/jobs/{id}/previews` → `[{slide_no, kinds: ["original","vector","hybrid","selected"]}, ...]`
    - `GET /api/jobs/{id}/previews/{slide_no}/{kind}` → JPEG FileResponse. `Cache-Control: max-age=3600`.
  - Done: 작업 완료 후 위 두 endpoint가 200 + 정상 페이로드.
  - 검증: 통합 테스트 1건.

### Phase 2: 프론트 (T1~T7 후)

- [x] **T8: 업로드 XHR + 진행률 바**
  - 파일: `star_slide/api/web_app.py` (인라인 JS)
  - 내용: `submit()`을 `XMLHttpRequest` 기반으로 교체, `xhr.upload.onprogress`로 0~100% 표시. 시작 버튼 영역 아래 inline 진행 바. 업로드 완료 후 SSE 구독으로 자연스러운 phase 전환.
  - Done: 100MB+ 파일 업로드 시 % 가시화. 실패/취소 처리.
  - 검증: 수동 (대용량 파일 업로드).

- [x] **T9: SSE 클라이언트 + 폴링 fallback**
  - 파일: 동일
  - 내용:
    - `EventSource` 사용. 실행 중인 작업만 구독, `done`/`failed`/`cancelled` 시 자동 close.
    - `EventSource` 미지원/연결 실패 시 기존 2.5s 폴링 fallback.
    - 카드 부분 갱신: `data-job-id` 속성으로 카드 찾고, 변경 필드만 update (전체 innerHTML 재생성 금지).
  - Done: 변환 진행이 SSE로 끊김 없이 흘러옴. 모달 열어두어도 깨지지 않음.
  - 검증: 수동 — 변환 중 모달 오픈 / 다른 작업 카드 수동 액션 동시 진행.

- [x] **T10: 취소/재실행 UI**
  - 파일: 동일
  - 내용:
    - 실행 중 작업 카드에 "취소" 버튼 → `POST /api/jobs/{id}/cancel`, confirm dialog 1회.
    - 완료/실패/취소 작업에 "다시 실행" 버튼 → `POST /api/jobs/{id}/rerun`.
    - 상태 badge에 `cancelling`, `cancelled` 추가 (회색 톤).
  - Done: 실제 취소 → 카드 상태 `cancelling` → `cancelled` 전이. 재실행 시 새 작업 카드 등장.
  - 검증: 수동.

- [x] **T11: 슬라이드 비교 모달**
  - 파일: 동일
  - 내용:
    - 기존 "미리보기" 버튼 동작을 변경: montage 단일 이미지 대신 `/api/jobs/{id}/previews` 그리드.
    - 슬라이드 카드 클릭 → 큰 비교 뷰어 (좌: original, 우: selected, 토글로 vector/hybrid 표시). 키보드 ←/→로 슬라이드 이동, ESC로 닫기.
    - 폴백: previews API 404면 기존 montage 표시 유지.
    - 현재 모달 ESC/focus trap 누락 → 이번에 같이 패치(Low cost).
  - Done: 결과 검수 시간 단축. 모달 키보드 접근 가능.
  - 검증: 수동.

### Phase 3: 회귀 검증

- [x] **T12: 전체 검증**
  - 검증:
    - `uv run pytest` (전체)
    - `uv run mypy star_slide`
    - `uv run ruff check star_slide`
    - 수동: 작은 PPTX(refdata에 있는 sample) 1개로 업로드→진행률→완료→비교→재실행→취소 일주
    - 기존 CLI: `uv run star-slide notebooklm --help` 정상 + `convert_notebooklm_auto` 시그니처 변화에도 CLI 경로 통과
  - Done: 4개 전부 GREEN.

---

## 의존성 그래프

```
T1 ──┐
T2 ──┼──→ T4 ──┐
     │         ├──→ T8 ──┐
T3 ──┘         │         │
T6 ──→ T7 ─────┤         ├──→ T11 ──→ T12
               │         │
T5 ────────────┴──→ T9 ──┴──→ T10 ─→ T12
```

- 병렬 가능: {T1, T2, T3, T6}, {T4, T5}, {T7}, {T8, T9, T10, T11}
- 크리티컬 패스: T1 → T4 → T9 → T10 → T12 (취소 라인이 가장 많은 단계)

## 검증 방법

- [x] `uv run pytest` (신규 SSE/cancel/preview 통합 테스트 포함, 전부 GREEN)
- [x] `uv run mypy star_slide` (strict 유지)
- [x] `uv run ruff check star_slide`
- [x] 수동 시나리오:
  1. 작은 PPTX 업로드 → 업로드% 표시 확인
  2. 변환 시작 → SSE phase 전환이 1초 내 반영
  3. 진행 중 "취소" → `cancelled` 상태 + 워크디렉토리 보존
  4. 취소된 작업에 "다시 실행" → 정상 완료
  5. 완료 후 "미리보기" → 슬라이드 그리드 + 비교 뷰어 동작 (←/→/ESC)
  6. 기존 CLI(`uv run star-slide notebooklm run ...`) 정상

## 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| `convert_notebooklm_auto` 시그니처 변경으로 CLI 호출부/테스트 회귀 | `cancel`/확장 인자 모두 keyword-only + 기본값 None. CLI 경로 grep으로 호출처 전수 확인 |
| SSE 연결이 reverse proxy/터미널 환경에서 끊김 | heartbeat 15s + 클라이언트 자동 재연결 + 폴링 fallback 유지 |
| ThreadPool에서 cancel 신호 적용까지 1단계(최대 수 분) 지연 | UI에 `cancelling` 중간 상태 명시. 강제 종료는 본 범위 밖 |
| Pipeline이 출력 파일 존재 시 skip 안 하면 rerun이 매번 처음부터 | 본 계획 범위에서는 "처음부터 재실행"이 디폴트로 OK. skip 최적화는 별도 PR로 분리 |
| Preview JPEG 생성으로 디스크 사용 증가 | 480px JPEG q80, 슬라이드당 < 80KB 목표. 실측 후 필요 시 q70 또는 thumbnail-only |
| 인라인 단일 파일 1641줄에 추가하면 더 비대해짐 | preview/event-bus는 별도 모듈(`star_slide/api/events.py`, `preview_assets.py`)로 분리 가능한 부분만 분리. HTML/CSS/JS는 이번 범위에서 그대로 유지 |
| `EventSource`가 일부 모바일 사파리에서 백그라운드 일시정지 | 현재 사용 패턴은 데스크톱 로컬이므로 영향 미미. 폴링 fallback이 안전망 |

## 후속 (이번 범위 밖)

- L2: 슬라이드 선택형 재실행 (`generate_layouts(only_slides=...)` + UI 다중 선택)
- 단일 파일 → `templates/`+`static/` 분리
- 영구 큐 (Celery/redis 의존성은 이미 있음 → 옵션 도입)
- 인증/접근 제어
