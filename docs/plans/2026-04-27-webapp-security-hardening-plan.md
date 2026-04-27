# 웹앱 보안 하드닝 (Top 5) 구현 계획

> 작성일: 2026-04-27
> 대상: `star_slide/api/web_app.py`, `star_slide/cli/web.py`, `tests/integration/test_web_app.py`
> 입력: Red Team(security/code/api 3-agent) 검토 결과 합의된 Top 5 fix

## 목표

Red Team이 합의한 Critical/High 5건을 수정해 데이터 손실 위험과 SSRF/CSRF/OOM 공격 표면을 제거한다.

## 배경

직전 commit `712292b`에 대해 보안 검토 3건 병렬 실행. 결과:
- **Critical 1 / High 5 / Medium 6 / Low 4** (중복 제거)
- 사용자 결정: **A — Top 5 모두 진행**
- 5건 모두 동일한 두 파일에 집중되어 분리 PR로 가지 않고 단일 변경 묶음으로 충분

## 접근 방식

| 방법 | 장점 | 단점 | 공수 |
|------|------|------|------|
| **A: Top 5 단일 PR로 묶음 처리** (선택) | 모두 같은 두 파일, 통합 테스트 패턴 동일, 한번의 재시작으로 검증 | PR 크기 ↑ | 4~5h |
| B: 5개 분리 PR | 리뷰 단위 작음 | 같은 파일에 5번 충돌, 재시작/검증 5배 | 6~7h |

**선택: A**. Phase 단위로 커밋 분리는 가능 — Phase 1(데이터 손실 차단) → Phase 2(상태/CSRF) → Phase 3(SSRF/Upload).

---

## 태스크 (3 phase, 총 10 task)

### Phase 1: 데이터 손실 / 상태 무결성 (백엔드 + 프론트)

- [x] **T1: 백엔드 `update_job` terminal-state guard**
  - 파일: `star_slide/api/web_app.py`
  - 내용: `update_job(job_id, *, force=False, **changes)` 시그니처 확장. 현재 status가 `TERMINAL_STATUSES`에 있으면, force=True가 아니거나 새 status도 terminal이 아니면 변경 거부 (early return). `run_job`의 done/failed/cancelled emit은 `force=True`로 호출.
  - Done: cancel 후 도착하는 progress 콜백이 status를 "running"으로 되돌리지 못함.
  - 검증: 신규 통합 테스트 `test_cancelled_job_resists_late_progress` — fake convert가 cancel 후 progress 콜백 발생 → 최종 status `cancelled` 유지.

- [x] **T2: 프론트 `decryptApiKey` null 센티넬 + 안전 import**
  - 파일: `star_slide/api/web_app.py` 인라인 JS
  - 내용:
    - `decryptApiKey`: 실패 시 `null` 반환 (이전: `""`).
    - `importSettingsFromStorage`: 결과 `null`이면 provider의 `apiKey` 필드 **설정 안 함** (undefined로 둠) + `apiKeyEnc`는 그대로 보존.
    - 글로벌 플래그 `_decryptFailed: boolean`. import 중 한 번이라도 null 발생 시 true.
    - `init`에서 `_decryptFailed`가 true면 마이그레이션 `exportSettingsToStorage` 호출 **건너뜀** + 상단 경고 배너 표시.
    - 신규 `setKeystoreWarning(message)` 헬퍼 — 헤더 아래 회색 배너에 표시.
  - Done: IndexedDB 강제 삭제(또는 시크릿 모드) 후 재로드 → 콘솔 경고 + UI 배너 + `apiKeyEnc` 보존 + 빈 키 export 안 됨.
  - 검증: 수동 (Chrome DevTools → Application → IndexedDB → starSlideKeystore 삭제 후 reload). 자동화 안 함.

### Phase 2: CSRF + non-loopback 경고

- [x] **T3: `/cancel` `/rerun`에 Content-Type 강제**
  - 파일: `web_app.py`
  - 내용: 두 핸들러 입구에 `if request.headers.get("content-type", "").split(";")[0].strip() != "application/json": raise HTTPException(415, ...)`. UI fetch에는 이미 application/json 사용중인지 확인 → 없으면 추가.
  - Done: cross-origin `<form>` POST가 415로 차단. UI 정상 동작.
  - 검증: 신규 통합 테스트 `test_cancel_requires_json_content_type` — Content-Type 없이 POST → 415.

- [x] **T4: 프론트 `cancelJob`/`rerunJob`에 명시적 헤더**
  - 파일: 동일 (인라인 JS)
  - 내용: 기존 `fetch(..., {method: "POST"})` → `fetch(..., {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"})`. 빈 객체 바디.
  - Done: 자체 UI는 정상.
  - 검증: T7(전체 통합) 통과.

- [x] **T5: CLI startup non-loopback 경고**
  - 파일: `star_slide/cli/web.py`
  - 내용: `WEB_PORT` 옆에 `LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}`. `run` 함수 console.print 직전에 host가 그 집합에 없으면 노란 경고 출력 (`[yellow]⚠️ ...[/]`). 메시지: "인증 없는 LAN/외부 노출 — 신뢰된 네트워크에서만 사용하세요."
  - Done: `--host 0.0.0.0` 등 시 명시적 경고 1줄 출력.
  - 검증: 수동 (`--host 0.0.0.0`로 실행해서 경고 확인) + 향후 자동화는 비대상.

### Phase 3: SSRF + Upload streaming

- [x] **T6: SSRF 가드 `_validate_outbound_url`**
  - 파일: `web_app.py`
  - 내용: 신규 헬퍼 (module-level):
    ```python
    def _validate_outbound_url(url: str) -> tuple[bool, str]:
        # urllib.parse.urlparse → scheme http/https only
        # ipaddress.ip_address(socket.gethostbyname(host)) → loopback/private/link-local/multicast/reserved 거부
        # 단, hostname이 localhost/127.0.0.1/::1 리터럴이면 명시적 허용
        # return (ok, error_msg)
    ```
  - `probe_llm_endpoint`, `_list_models` 양쪽 진입부에서 호출 → 실패 시 `{"ok": False, "error": ...}` 즉시 반환.
  - Done: `file://`, `gopher://`, `http://169.254.169.254`, `http://192.168.x.x` 등 거부.
  - 검증: 신규 단위 테스트 `tests/unit/test_ssrf_guard.py` — scheme/IP 분기 6개 케이스.

- [x] **T7: SSRF — `follow_redirects=False` + 응답 본문 미반사**
  - 파일: `web_app.py` `_probe_chat_completions`, `_list_models`
  - 내용:
    - `httpx.Client(... , follow_redirects=False)` 양쪽 다 변경.
    - `_probe_chat_completions`의 4xx/5xx 분기에서 `response.text[:300]`을 **응답에 포함하지 않음**. 대신 status code와 hint만 + 사용자가 직접 확인할 수 있도록 응답 헤더 `WWW-Authenticate` 등 한정 메타데이터만 (없거나 안전하면 생략).
    - 30x 응답이면 별도 에러 (`"리다이렉트는 보안상 허용되지 않습니다"`).
    - sanitize_error 패턴에 `Bearer\s+\S+`, `AIza[0-9A-Za-z\-_]{35}`, `https?://[^@\s]+:[^@\s]+@` 추가.
  - Done: 외부 endpoint 응답 본문이 클라이언트에 반사되지 않음.
  - 검증: 신규 단위 테스트 `test_probe_does_not_reflect_response_body` (mock httpx로 4xx 응답 시 result.error에 응답 본문 substring 없음 확인).

- [x] **T8: Upload streaming + 부분 파일 정리**
  - 파일: `web_app.py` `submit_job`
  - 내용:
    - `await request.body()` 제거. `safe_name` 검증 강화: `if not safe_name or safe_name in {".", ".."}: raise HTTPException(400)`.
    - 임시 파일에 `async for chunk in request.stream():`로 청크 누적, 누적 size > MAX_UPLOAD_BYTES이면 부분 파일 unlink + `raise HTTPException(413)`.
    - 빈 입력(0 byte)도 거부.
    - 정상 종료 시 `input_path` 그대로 사용.
  - Done: GB+ 스트림으로 OOM 안 남, 한도 초과 시 디스크에 부분 파일 안 남음.
  - 검증: 신규 통합 테스트 `test_upload_oversize_streamed_rejected` — TestClient는 한 번에 보내지만 MAX를 작게 monkeypatch해서 size 초과 케이스 + 부분 파일 정리 확인.

### Phase 4: 회귀 검증

- [x] **T9: 전체 검증**
  - 검증:
    - `uv run pytest` (전체 + 신규 보안 테스트)
    - `uv run mypy star_slide` (베이스라인 11 유지, 신규 0)
    - `uv run ruff check star_slide` (clean)
    - 수동: 웹앱 재시작 → 변환 시작 → 진행 중 cancel → status `cancelled` 유지 (resurrect 안 됨)
    - 수동: Test 버튼으로 `http://169.254.169.254/v1` 입력 → "차단됨" 메시지
  - Done: 4개 GREEN.

- [x] **T10: 커밋 + 푸시**
  - 커밋: Phase 단위 분리 가능 — `fix(web): guard terminal state and protect encrypted key store` / `fix(web): SSRF & CSRF defenses` / `fix(web): stream uploads to disk` 3개로 또는 단일 `fix(web): security hardening (Top 5)` 1개.
  - 결정: **단일 커밋**. Top 5가 같은 파일이고 함께 검증되어 분리 시 중간 commit이 빌드는 통과해도 의미가 약함.

---

## 의존성 그래프

```
T1 ──┐                                 ┐
T2 ──┤        (병렬)                    │
T3 ──┼──→ T4 ──┐                       ├──→ T9 ──→ T10
T5 ──┤         │                        │
T6 ──→ T7 ─────┤                        │
T8 ────────────┘                        ┘
```

병렬 가능 그룹: {T1, T2, T3, T5, T6, T8}, {T4, T7}
크리티컬 패스: T6 → T7 → T9 → T10 (SSRF 라인이 가장 길다)

## 검증 방법

- [x] `uv run pytest` (전체) — 기존 92 + 신규 4~5 통과
- [x] `uv run mypy star_slide` — 11 errors 유지 (베이스라인)
- [x] `uv run ruff check star_slide` — clean
- [x] 수동 시나리오:
  1. `--host 0.0.0.0` 시작 시 노란 경고 출력
  2. Chrome DevTools에서 IndexedDB `starSlideKeystore` 삭제 후 reload → 빨간 배너 표시 + apiKey input은 빈 칸이지만 localStorage `apiKeyEnc` 보존
  3. Test 버튼 → `http://169.254.169.254/v1` 입력 → 거부 메시지
  4. 변환 시작 → 진행률 50% 시점에 cancel → cancelled 유지, 이후 phase 메시지 들어와도 running 안 됨
  5. cURL로 Content-Type 없이 `/cancel` POST → 415
  6. 큰 파일 업로드 (300MB+) 시 한도 초과로 거부 + `output/web_jobs/<id>/`에 부분 파일 없음

## 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| `socket.getaddrinfo`가 외부 호스트 lookup으로 startup 지연 | probe 호출 시점에서만 실행. 타임아웃 짧게(2초) 설정 |
| `follow_redirects=False`로 정상 OpenAI 호환 endpoint도 실패할 수 있음 | OpenAI/Gemini/Ollama 모두 직접 응답하지 redirect 없음 — 회귀 가능성 낮음. test 버튼으로 즉시 검증 |
| Content-Type 강제로 외부 클라이언트 깨짐 | 자체 UI만 호출 — 영향 없음. 외부 통합 발생 시 별도 토큰 인증 도입 검토 |
| 스트리밍 업로드 도중 disk full → 부분 파일 정리 실패 | finally + best-effort unlink. 실패해도 워크디렉토리에만 영향 |
| `_decryptFailed` 배너가 첫 사용자에게 노이즈로 보일 수 있음 | 진짜 decrypt 실패 시에만 표시 (apiKeyEnc 존재 + decrypt null 조합) — 신규 사용자는 apiKeyEnc 자체가 없어 트리거 안 됨 |
| terminal-state guard로 합법적인 retry 시나리오 막힘 | force=True로 의도된 경로(run_job 자체 종료)만 통과. 외부에서 unstuck 필요 시 별도 admin endpoint 도입(미포함) |

## 후속 (이번 범위 밖)

- Bearer 토큰 인증 (--host 0.0.0.0 운영 모드)
- SSE asyncio.Queue maxsize 도입 (현재 50 history만 cap)
- `future.cancel()` 데드 코드 제거
- Magic-byte 검증 (PK\x03\x04 / %PDF-)
- writeStoredSettings write race serialize
