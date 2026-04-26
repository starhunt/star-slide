# Star-Slide

AI가 만든 이미지 잠금 슬라이드를 PowerPoint에서 다시 편집할 수 있는 PPTX로 변환하는 후처리 엔진입니다.

NotebookLM 같은 생성형 슬라이드 도구는 보기에는 PPTX처럼 보이지만, 실제로는 각 슬라이드가 한 장의 이미지로 들어간 경우가 많습니다. 이 상태에서는 텍스트 수정, 도형 선택, 아이콘 이동, 불필요한 객체 삭제가 불가능합니다.

Star-Slide는 이런 슬라이드를 분석해 텍스트, 도형, 선, 큰 이미지 그룹을 다시 PowerPoint 객체로 재구성합니다. 목표는 단순한 OCR 덮어쓰기가 아니라, 원본 디자인을 최대한 유지하면서 실무적으로 수정 가능한 PPTX를 만드는 것입니다.

## 현재 핵심 기능

- NotebookLM 이미지 잠금 PPTX/PDF 자동 변환
- 슬라이드별 Vision LLM 기반 `layout.json` 생성
- 큰 일러스트/도식 영역을 선택 가능한 이미지 객체로 보존
- 제목, 본문, 주요 라벨을 편집 가능한 PowerPoint 텍스트로 복원
- SAM3 bbox refinement를 통한 큰 이미지 그룹 추출 보정
- NotebookLM 하단 워터마크 제거
- vector/hybrid 결과를 모두 렌더링한 뒤 QA diff 기준으로 자동 선택
- LLM 호출 병렬 처리, 기본 `5`개
- 색 배경 위 텍스트 제거 시 inpaint 얼룩 완화
- 작은 배지/아이콘 라벨은 필요 시 래스터에 그대로 남겨 시각 품질 보존

## 변환 방식

현재 주력 파이프라인은 `notebooklm run` 명령입니다.

```text
PPTX/PDF 입력
  -> 슬라이드 이미지 추출
  -> Vision LLM으로 slide_XXX.layout.json 생성
  -> vector PPTX 생성 및 렌더 QA
  -> Vision LLM으로 큰 raster group 후보 탐지
  -> SAM3로 raster group bbox 보정
  -> 큰 도식/일러스트는 이미지 객체로 치환
  -> 추출된 주요 텍스트는 editable text로 유지
  -> hybrid PPTX 생성 및 렌더 QA
  -> vector/hybrid 중 더 안전한 layout 자동 선택
  -> 최종 editable PPTX 생성
```

SAM3는 모든 요소를 직접 의미 분리하는 주 엔진이 아니라, Vision LLM이 찾은 큰 이미지 그룹을 더 정확히 잘라내는 보조 엔진으로 사용합니다.

## 설치

Python 3.11 이상과 `uv`가 필요합니다.

```bash
uv sync
```

개발/검증용 도구까지 설치하려면 다음을 사용합니다.

```bash
uv sync --group dev
```

PPTX 렌더 QA에는 LibreOffice가 필요합니다.

macOS:

```bash
brew install libreoffice
```

LibreOffice는 무료 오픈소스 오피스 제품군입니다. 공식 라이선스 안내는 [LibreOffice Licenses](https://www.libreoffice.org/licenses/)를 참고하세요. Star-Slide는 LibreOffice를 번들로 재배포하지 않고 로컬/서버에 설치된 실행 파일을 호출해 PPTX를 PNG로 렌더링합니다. 현재 자동 선택 QA가 LibreOffice 렌더 결과를 사용하므로, 안정적인 배치 변환에는 LibreOffice 설치가 사실상 필수입니다.

PDF 입력 렌더링, PPTX 렌더링, 이미지 추출 흐름에 따라 `poppler`, `inkscape`가 추가로 필요할 수 있습니다.

```bash
brew install poppler inkscape
```

## Vision LLM 프록시

`notebooklm` 자동 변환은 OpenAI 호환 `/v1/chat/completions` Vision endpoint를 사용합니다.

기본값:

```text
base-url: http://localhost:8300/v1
model: gpt-5.5
```

API key는 CLI 옵션 또는 환경변수로 전달할 수 있습니다.

```bash
export VISION_PROXY_API_KEY="..."
```

또는 실행 시:

```bash
--api-key "..."
```

## 빠른 실행

```bash
uv run star-slide notebooklm run refdata/sample5.pptx \
  -o output/notebooklm_layout/sample5_auto_cli/sample5_auto_cli.pptx \
  --workdir output/notebooklm_layout/sample5_auto_cli/work \
  --timeout 600 \
  --retries 1 \
  --llm-parallel 5
```

실행이 끝나면 다음 파일들이 생성됩니다.

```text
output/.../sample5_auto_cli.pptx
output/.../work/notebooklm_auto_report.json
output/.../work/qa_selected/montage.png
output/.../work/qa_selected/qa_report.json
```

## 웹앱 실행

CLI와 같은 변환 파이프라인을 웹에서 사용할 수 있습니다. 현재 웹앱은 로컬 MVP이며, 업로드한 파일과 산출물은 `output/web_jobs/` 아래에 저장됩니다.

```bash
uv run --extra api star-slide web run \
  --host 127.0.0.1 \
  --port 8787
```

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:8787
```

웹앱에서 가능한 작업:

- PPTX/PDF 드래그 앤 드롭 업로드
- OpenAI, Gemini, Local Proxy, 여러 Custom OpenAI-compatible provider 선택
- provider별 이름, Base URL, 모델명, API key 저장 및 자동 불러오기
- timeout, retry, LLM 병렬 수, 폰트 배율, SAM3 사용 여부, embedded text 처리, 중간 산출물 보존 여부 조정
- 비동기 변환 작업 시작
- 단계별 진행 상태 확인 및 작업 목록 페이징
- 다크/라이트 모드 전환, 기본 다크 모드
- 완료 후 PPTX 다운로드
- QA montage 모달 미리보기
- 변환 리포트 모달 확인 및 원본 JSON 다운로드
- Layout JSON 요약 모달 확인 및 layout JSON zip 다운로드

Gemini preset은 Google의 OpenAI compatibility endpoint 형식(`https://generativelanguage.googleapis.com/v1beta/openai/`)을 기준으로 합니다. 자세한 내용은 [Gemini API OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)를 참고하세요.

웹앱의 provider 설정과 API key는 브라우저 `localStorage`에 저장됩니다. 로컬 개발 환경에서 반복 입력을 줄이기 위한 기능이며, 여러 사람이 함께 쓰는 브라우저나 원격 배포 환경에서는 별도 secret storage를 붙이는 것을 권장합니다.

현재 웹앱은 PPTX 파일 자체를 브라우저에서 직접 편집하지는 않습니다. 웹에서 PowerPoint 수준의 편집과 저장까지 제공하려면 Microsoft Office Online, OnlyOffice, Collabora Online 같은 별도 문서 편집 서버 연동이 필요합니다.

## 주요 CLI 옵션

```bash
uv run star-slide notebooklm run INPUT.pptx -o OUTPUT.pptx [options]
# 또는
uv run star-slide notebooklm run INPUT.pdf -o OUTPUT.pptx [options]
```

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--workdir` | 출력 경로 기반 자동 생성 | 중간 산출물 저장 디렉터리 |
| `--base-url` | `http://localhost:8300/v1` | OpenAI 호환 Vision LLM endpoint |
| `--model` | `gpt-5.5` | 사용할 Vision LLM 모델명 |
| `--api-key` | 빈 문자열 | 프록시 API key |
| `--timeout` | `600` | LLM 호출 타임아웃 초 |
| `--retries` | `1` | 깨진 JSON 등 실패 시 재시도 횟수 |
| `--llm-parallel` | `5` | layout/raster group LLM 병렬 호출 수 |
| `--sam3 / --no-sam3` | `--sam3` | SAM3 bbox refinement 사용 여부 |
| `--hybrid-allowed-delta` | `0.0` | hybrid가 vector보다 이 값만큼 나빠도 hybrid 선택 허용 |
| `--editable-embedded-text / --rasterize-embedded-text` | `--editable-embedded-text` | 큰 이미지 그룹 내부 텍스트를 편집 가능 객체로 유지할지 여부 |
| `--font-scale` | `0.93` | PPTX 렌더링 시 텍스트 크기 배율 |
| `--keep-intermediates / --clean-intermediates` | `--clean-intermediates` | 완료 후 큰 QA 렌더/asset 중간 산출물 보존 여부 |

## 출력 디렉터리 구조

기본값은 제품 모드에 가깝게 큰 중간 산출물을 정리합니다. 웹 작업 기준 예시:

```text
output/web_jobs/{job_id}/
  {uploaded}.pptx|.pdf      # 사용자가 업로드한 원본 파일명 그대로 저장
  result.pptx               # 최종 변환 PPTX
  artifacts/
    candidate_vector.pptx   # vector 후보 결과
    candidate_hybrid.pptx   # hybrid 후보 결과
    layout_json.zip         # LLM layout JSON 및 선택 결과 JSON
    report.json             # 작업 결과 리포트
    montage.png             # 최종 QA 미리보기
    artifact_manifest.json  # 보존 산출물 목록과 크기
```

`--keep-intermediates`를 켜면 기존처럼 `work/` 아래에 추출 이미지, QA 렌더, SAM3 crop, overlay 등 디버깅용 파일을 모두 남깁니다.

`qa_report.json`에는 슬라이드별 객체 수, 이미지 객체 수, 원본 대비 렌더 평균 차이값이 기록됩니다.

## 편집 가능성 정책

Star-Slide는 모든 픽셀을 무조건 벡터화하지 않습니다.

무조건 벡터화하면 PowerPoint 객체 수가 과도하게 늘고, 원본 디자인과 다른 결과가 나올 수 있습니다. 그래서 현재 기본 정책은 다음과 같습니다.

- 제목, 본문, 주요 라벨: 편집 가능한 텍스트 객체
- 표, 박스, 선, 단순 도형: 가능한 한 PowerPoint 도형/선 객체
- 복잡한 일러스트, 생성 이미지, 큰 도식: 선택 가능한 이미지 객체
- 작은 영문 배지, 아이콘 라벨, 치수 라벨: 원본 이미지에 그대로 보존할 수 있음
- NotebookLM 워터마크: 제거

이 방식은 “전부 editable”보다 실사용 품질이 안정적입니다. 텍스트 수정 가능성과 시각 충실도 사이의 균형을 맞추는 것이 목표입니다.

## 프롬프트 기반 인포그래픽

이미 완성된 이미지밖에 없는 경우에는 이미지 역변환이 필요합니다. 하지만 유튜브 요약이나 상세 프롬프트처럼 원천 구조 정보가 있는 경우에는 더 좋은 방법이 있습니다.

```text
프롬프트/요약문
  -> 구조화된 layout.json 생성
  -> 처음부터 편집 가능한 PPTX 생성
```

이 경로는 OCR과 이미지 역추정 오류가 없기 때문에 한글 텍스트가 많은 인포그래픽에 더 적합합니다. 현재는 실험 스크립트 수준이며, 향후 정식 CLI 모드로 분리할 수 있습니다.

## 기존 convert 명령

일반 변환 명령도 남아 있습니다.

```bash
uv run star-slide convert run INPUT.pptx \
  -o output/converted.pptx \
  --vision-llm \
  --vision-base-url http://localhost:8300/v1 \
  --vision-model gpt-5.5
```

다만 현재 NotebookLM 이미지 잠금 PPTX에는 `notebooklm run` 경로가 더 적극적으로 관리되고 있습니다.

## 개발 명령

```bash
uv run star-slide --help
uv run star-slide notebooklm --help
uv run ruff check scripts/apply_raster_groups_to_layout.py star_slide/pipeline/notebooklm_auto.py star_slide/cli/notebooklm.py
uv run pytest
```

## Git 관리 규칙

다음 디렉터리는 산출물 또는 대용량 입력 데이터로 보고 기본적으로 Git에서 제외합니다.

```text
output/
data/
experiments/
```

`refdata/`는 테스트 입력 파일을 둘 수 있는 작업용 위치입니다. 저장소 정책에 따라 필요한 샘플만 별도로 관리합니다.

## 현재 한계

- Vision LLM 출력 품질에 따라 작은 텍스트가 누락될 수 있습니다.
- 깨진 JSON이 반환될 수 있어 재시도 옵션이 필요합니다.
- 복잡한 도식 내부 텍스트를 전부 editable로 만들면 시각 품질이 떨어질 수 있습니다.
- PowerPoint와 LibreOffice 렌더링 차이로 실제 PowerPoint에서 미세한 줄바꿈 차이가 있을 수 있습니다.
- 완전 자동 배치/업로드 제품화를 위해서는 누락 텍스트 QA, 자동 보정 루프, 작업 큐/API 서버가 추가로 필요합니다.

## 프로젝트 문서

- [통합 PRD](docs/Star-Slide_PRD.md)
- [기술 결정](docs/Star-Slide_TechDecisions.md)
- [개발 계획](docs/Star-Slide_DevPlan.md)
- [프로젝트 구조](docs/Star-Slide_Structure.md)

## 라이선스

MIT.

외부 모델과 도구의 라이선스는 각 프로젝트 정책을 따릅니다.
