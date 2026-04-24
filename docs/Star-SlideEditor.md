# Star-SlideEditor PRD v1.0

작성일: 2026-04-25  
제품명: Star-SlideEditor  
문서 목적: 이미지 기반 슬라이드/PDF를 사람이 직접 편집 가능한 PPTX와 웹 편집 프로젝트로 변환하는 상용 제품 요구사항 정의  
핵심 접근: AI 레이어 분해 + OCR/레이아웃 분석 + 벡터화 + 네이티브 PPTX 재구성 + 사람이 보정 가능한 편집 UI

---

## 1. Executive Summary

NotebookLM, Gamma, Canva, 이미지 생성형 AI, PDF 기반 리포트 도구 등은 빠르게 슬라이드를 생성하지만, 결과물이 이미지 기반이거나 객체 구조가 망가진 PPTX인 경우가 많다. 사용자는 LLM에게 다시 수정 요청을 할 수는 있지만, 실제 업무에서는 PowerPoint, Keynote, Google Slides 또는 웹 편집기에서 직접 텍스트, 아이콘, 도표, 차트, 레이아웃을 수정하길 원한다.

Star-SlideEditor는 이미지 기반 슬라이드를 분석하여 텍스트, 아이콘, 도형, 차트, 표, 사진, 배경을 레이어 단위로 분해하고, 가능한 객체는 PowerPoint 네이티브 객체로 복원한다. 복원이 불확실한 객체는 SVG 또는 이미지 레이어로 fallback 처리하여 시각적 재현도를 유지한다.

제품의 핵심 가치는 "완벽한 원본 PPT 복구"가 아니라 "AI가 편집 가능한 초안을 만들고, 사용자가 빠르게 보정하여 업무용 PPTX로 완성하는 것"이다.

---

## 2. Problem Statement

### 2.1 사용자 문제

이미지 기반 슬라이드를 받은 사용자는 다음 문제를 겪는다.

| 문제 | 설명 | 현재 대안의 한계 |
|---|---|---|
| 텍스트 직접 수정 불가 | 한글 텍스트가 이미지로 박혀 있어 오타, 표현, 숫자를 고칠 수 없다 | OCR 후 수동 재작성 필요 |
| 아이콘/도형 수정 불가 | 아이콘 색상, 위치, 크기, 선 두께를 바꿀 수 없다 | 원본 디자인 재작업 필요 |
| 차트/표 수정 불가 | 데이터 값, 라벨, 색상, 축을 수정하기 어렵다 | 차트를 처음부터 다시 만들어야 함 |
| 레이아웃 재사용 불가 | 슬라이드 템플릿처럼 재활용하기 어렵다 | 캡처 이미지 위에 새 객체를 얹는 방식으로 처리 |
| LLM 수정 의존 | NotebookLM 내부 명령으로 수정할 수 있어도 사용자가 직접 통제하기 어렵다 | 반복 요청 비용과 품질 편차 발생 |
| 한국어 품질 문제 | OCR, 줄바꿈, 폰트, 자간, 조사/띄어쓰기 오류가 생긴다 | 글로벌 도구의 한글 최적화 부족 |

### 2.2 대표 사용자

Primary user:
- AI 도구로 초안을 만들고 PowerPoint에서 최종 산출물을 다듬는 기획자, PM, 컨설턴트, 연구자, 강사, 마케터

Secondary user:
- 내부 보고서, 교육자료, 세일즈덱, 제안서를 대량 변환해야 하는 디자인/문서 운영팀
- PDF/이미지 자료를 재활용해야 하는 학생, 지식노동자, 콘텐츠 제작자

Enterprise user:
- 회사 내부 문서 변환, 브랜드 템플릿 적용, 민감 자료 사내 처리, 감사 로그가 필요한 조직

---

## 3. Product Vision

Star-SlideEditor는 다음 3단계 경험을 제공한다.

1. 사용자가 이미지 기반 PPTX/PDF/PNG를 업로드한다.
2. 시스템이 슬라이드 객체를 자동 분해하고 편집 가능한 레이어 모델로 변환한다.
3. 사용자는 웹 편집기 또는 PPTX에서 텍스트/도형/아이콘/차트/표를 직접 수정하고 내보낸다.

제품의 장기 비전은 "AI가 만든 시각 자료를 사람이 통제 가능한 구조화 문서로 되돌리는 편집 복원 엔진"이다.

---

## 4. Goals and Non-Goals

### 4.1 Goals

P0 목표:
- 이미지 기반 PPTX, PDF, PNG/JPG 슬라이드 입력 지원
- 슬라이드별 객체 자동 분해
- 한글 OCR 텍스트를 편집 가능한 텍스트박스로 복원
- 단순 도형, 선, 화살표, 아이콘을 가능한 범위에서 벡터/PPT 객체로 복원
- 웹 편집기에서 객체 선택, 이동, 삭제, 텍스트 수정, 색상 변경, 이미지 교체 지원
- PPTX export 시 PowerPoint에서 주요 객체 편집 가능
- 복원 신뢰도와 fallback 상태를 사용자에게 명확히 표시

P1 목표:
- 표 구조를 PowerPoint native table로 복원
- 차트 영역을 데이터 기반 chart 또는 editable shape chart로 복원
- 브랜드 템플릿 적용
- 배경 inpainting 및 object removal
- 배치 처리와 팀 협업 기능

P2 목표:
- PowerPoint add-in
- Google Slides export
- Keynote 호환 export
- 사내 설치형/on-prem 배포
- NotebookLM/Gamma/Canva 출력물별 최적화 preset

### 4.2 Non-Goals

MVP에서 제외:
- 모든 슬라이드를 100% 원본 PPT 구조로 복구
- 복잡한 3D 차트, 지도, 수식, 손글씨의 완전 편집 객체화
- 원본에 존재하지 않는 차트 데이터를 완벽히 추정
- PowerPoint VBA, animation, transition, theme master 완전 복원
- 불법 복제 방지 우회 또는 저작권 보호 문서의 제한 해제

---

## 5. Core User Journeys

### 5.1 개인 사용자: 이미지 기반 PPTX를 직접 수정

1. 사용자가 NotebookLM에서 받은 PPTX를 업로드한다.
2. 시스템이 슬라이드를 이미지 기반으로 감지하고 분석 작업을 시작한다.
3. 사용자는 슬라이드별 "편집 가능도" 점수를 확인한다.
4. 첫 번째 슬라이드를 열어 제목 텍스트를 수정한다.
5. 아이콘 색상을 브랜드 컬러로 변경한다.
6. 불확실한 차트는 이미지 레이어로 유지하고, 라벨 텍스트만 수정한다.
7. PPTX로 내보내 PowerPoint에서 최종 수정한다.

### 5.2 팀 사용자: 대량 보고서 변환

1. 운영자가 PDF 보고서 50개를 업로드한다.
2. 시스템이 배치 작업 큐에 넣고 진행률을 표시한다.
3. 결과 프로젝트별로 변환 품질, 실패 슬라이드, OCR 이슈를 표시한다.
4. 팀원이 웹 편집기에서 검수한다.
5. 브랜드 템플릿을 적용해 PPTX를 일괄 생성한다.

### 5.3 Enterprise: 보안 문서 변환

1. 관리자가 사내 설치형 환경을 구성한다.
2. 외부 LLM/API 전송 없이 로컬 모델로 OCR, segmentation, vectorization을 수행한다.
3. 감사 로그에 파일 업로드, 변환, 다운로드, 삭제 이벤트가 기록된다.
4. 보존 정책에 따라 원본과 중간 산출물이 자동 삭제된다.

---

## 6. Functional Requirements

### 6.1 File Input

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-001 | PPTX 업로드 지원 | P0 | 이미지 기반 슬라이드와 일반 PPTX를 구분한다 |
| FR-002 | PDF 업로드 지원 | P0 | 페이지를 슬라이드 단위로 렌더링한다 |
| FR-003 | PNG/JPG 업로드 지원 | P0 | 단일 이미지 또는 다중 이미지 ZIP을 처리한다 |
| FR-004 | 파일 유효성 검사 | P0 | 확장자, MIME, 크기, 암호화 여부, 손상 여부를 검사한다 |
| FR-005 | 대용량 파일 처리 | P1 | 500MB 이하 파일을 비동기 처리한다 |
| FR-006 | 암호화 문서 감지 | P1 | 암호 필요 문서는 사용자에게 해제 요청을 표시한다 |

### 6.2 Slide Rasterization

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-010 | 슬라이드 고해상도 렌더링 | P0 | 2x 이상 해상도로 렌더링하고 좌표 변환 행렬을 저장한다 |
| FR-011 | 원본 비율 유지 | P0 | 16:9, 4:3, custom size를 보존한다 |
| FR-012 | 썸네일 생성 | P0 | 프로젝트/슬라이드 목록에서 빠르게 표시된다 |
| FR-013 | 렌더링 diff 계산 | P1 | export 결과와 원본 렌더링의 시각 차이를 측정한다 |

### 6.3 Layer Decomposition

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-020 | 객체 후보 감지 | P0 | 텍스트, 도형, 아이콘, 이미지, 차트, 표, 배경 후보를 분류한다 |
| FR-021 | SAM 기반 마스크 생성 | P0 | 주요 객체의 bbox와 mask를 생성한다 |
| FR-022 | 마스크 병합/분리 | P0 | 겹치는 마스크를 IoU, OCR, 색상 정보를 기준으로 정리한다 |
| FR-023 | z-order 추정 | P0 | 객체 겹침 순서를 추정하고 사용자가 수정할 수 있다 |
| FR-024 | 배경 레이어 분리 | P0 | 선택 가능한 전경 객체와 고정 배경을 분리한다 |
| FR-025 | 신뢰도 산정 | P0 | 객체별 confidence와 editable_level을 계산한다 |
| FR-026 | 레이어 잠금 | P1 | 배경/검수 완료 객체를 잠글 수 있다 |

### 6.4 Korean Text Restoration

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-030 | 한글 OCR | P0 | 한글, 영어, 숫자 혼합 텍스트를 인식한다 |
| FR-031 | 텍스트 블록 복원 | P0 | OCR 결과를 PPT 텍스트박스로 생성한다 |
| FR-032 | 줄바꿈 보존 | P0 | 원본 bbox 안에서 시각적으로 유사한 줄바꿈을 생성한다 |
| FR-033 | 글꼴 추정 | P1 | 산세리프/명조/고정폭, 굵기, 크기를 추정한다 |
| FR-034 | 색상 추정 | P0 | 텍스트 fill color를 원본과 유사하게 복원한다 |
| FR-035 | OCR 검수 UI | P0 | 원본 텍스트 이미지와 인식 텍스트를 비교해 수정할 수 있다 |
| FR-036 | fallback 원본 보존 | P0 | 텍스트 복원이 실패해도 원본 이미지 레이어를 보존한다 |

### 6.5 Vector and Shape Restoration

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-040 | 단순 도형 감지 | P0 | 사각형, 원, 선, 화살표, 라운드 사각형을 native shape로 변환한다 |
| FR-041 | 아이콘 벡터화 | P0 | 단색/저색상 아이콘을 SVG 또는 PPT shape로 변환한다 |
| FR-042 | 색상 편집 | P0 | 복원된 도형/아이콘의 fill/stroke를 변경할 수 있다 |
| FR-043 | 복잡 이미지 fallback | P0 | 사진/복잡 일러스트는 이미지 레이어로 유지한다 |
| FR-044 | SVG 최적화 | P1 | path 수, 색상 수, 파일 크기를 제한한다 |
| FR-045 | native PPT 변환 | P1 | 주요 SVG path를 DrawingML shape로 변환한다 |

### 6.6 Table and Chart Restoration

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-050 | 표 영역 감지 | P1 | 행/열/셀 경계를 감지한다 |
| FR-051 | 표 텍스트 OCR | P1 | 셀 단위 텍스트를 수정 가능하게 복원한다 |
| FR-052 | native table export | P1 | PowerPoint table로 내보낸다 |
| FR-053 | 차트 영역 감지 | P1 | 막대/선/파이/축/범례/라벨 후보를 분류한다 |
| FR-054 | editable shape chart | P1 | 데이터 추정 실패 시 도형 기반 차트로 복원한다 |
| FR-055 | native chart export | P2 | 추정 데이터와 라벨로 PowerPoint chart를 생성한다 |
| FR-056 | 차트 데이터 검수 UI | P2 | 사용자가 추정 데이터 테이블을 수정할 수 있다 |

### 6.7 Web Editor

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-060 | 슬라이드 목록 | P0 | 좌측 썸네일에서 슬라이드를 전환한다 |
| FR-061 | 캔버스 편집 | P0 | 객체 선택, 이동, 크기 조절, 삭제, 복제를 지원한다 |
| FR-062 | 텍스트 편집 | P0 | 더블클릭 또는 속성 패널에서 텍스트를 수정한다 |
| FR-063 | 속성 패널 | P0 | 위치, 크기, 색상, 폰트, opacity, layer type을 수정한다 |
| FR-064 | 레이어 패널 | P0 | 객체명, 타입, 신뢰도, lock, visibility, z-order를 표시한다 |
| FR-065 | 원본/편집/차이 보기 | P0 | original, editable, diff view를 전환한다 |
| FR-066 | 실행 취소/다시 실행 | P0 | 주요 편집 작업을 undo/redo할 수 있다 |
| FR-067 | 키보드 조작 | P1 | delete, arrow move, copy/paste, group/ungroup을 지원한다 |
| FR-068 | 검수 상태 | P1 | 객체/슬라이드별 pending, reviewed, accepted 상태를 저장한다 |

### 6.8 Export

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-070 | PPTX export | P0 | PowerPoint에서 열리고 주요 객체가 편집 가능하다 |
| FR-071 | PDF export | P1 | 최종 결과를 PDF로 출력한다 |
| FR-072 | SVG export | P1 | 슬라이드별 SVG를 출력한다 |
| FR-073 | 원본 대비 preview | P0 | export 전 시각 비교 preview를 제공한다 |
| FR-074 | fallback 표시 | P0 | PPTX 내부 또는 리포트에서 raster fallback 객체를 식별할 수 있다 |
| FR-075 | 브랜드 템플릿 export | P1 | 지정한 theme font/color/master를 적용한다 |

### 6.9 Project and Collaboration

| ID | 요구사항 | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-080 | 프로젝트 저장 | P0 | 분석 결과와 편집 상태가 저장된다 |
| FR-081 | 버전 히스토리 | P1 | 주요 저장 시점으로 복원할 수 있다 |
| FR-082 | 사용자 초대 | P1 | 팀원이 프로젝트를 함께 검수한다 |
| FR-083 | 코멘트 | P2 | 객체 또는 슬라이드 단위 코멘트를 남긴다 |
| FR-084 | 배치 작업 | P1 | 여러 파일을 큐로 처리하고 결과를 묶어 다운로드한다 |

---

## 7. Non-Functional Requirements

### 7.1 Performance

| 항목 | MVP 목표 | 상용 목표 |
|---|---:|---:|
| 단일 슬라이드 분석 시간 | 30초 이하 | 10초 이하 |
| 20장 PPTX 처리 시간 | 10분 이하 | 3분 이하 |
| 편집기 초기 로드 | 5초 이하 | 2초 이하 |
| 객체 선택 반응 | 100ms 이하 | 50ms 이하 |
| PPTX export | 20장 기준 60초 이하 | 20장 기준 20초 이하 |

### 7.2 Quality

| 항목 | MVP 목표 | 상용 목표 |
|---|---:|---:|
| 한글 OCR 문자 정확도 | 93% 이상 | 97% 이상 |
| 텍스트 bbox 위치 오차 | 8px 이하 | 4px 이하 |
| 일반 슬라이드 객체 분리 precision | 80% 이상 | 90% 이상 |
| 사용자가 직접 편집 가능한 객체 비율 | 60% 이상 | 80% 이상 |
| 원본 대비 export 시각 유사도 | 0.90 이상 | 0.96 이상 |
| 사용자가 수동 보정하는 시간 | 슬라이드당 2분 이하 | 슬라이드당 45초 이하 |

### 7.3 Reliability

- 분석 작업은 중단 후 재시작 가능해야 한다.
- 동일 파일 재업로드 시 중복 저장을 피하기 위해 content hash를 사용한다.
- worker 실패 시 슬라이드 단위로 재시도한다.
- 특정 슬라이드 분석 실패가 전체 프로젝트 실패로 이어지면 안 된다.
- 원본 파일과 export 결과를 최소 1회 이상 렌더링 검증한다.

### 7.4 Security and Privacy

- 기본 정책은 원본 파일 비공개 저장이다.
- 사용자가 명시적으로 허용하지 않으면 외부 LLM API로 문서 이미지를 보내지 않는다.
- 파일은 저장 시 암호화한다.
- 다운로드 URL은 만료 시간을 둔다.
- Enterprise 버전은 on-prem 또는 VPC 배포를 지원한다.
- 감사 로그에는 업로드, 분석 시작/종료, 편집 저장, export, 다운로드, 삭제 이벤트를 기록한다.
- 데이터 보존 기간은 plan별로 설정한다.

### 7.5 Compliance

- 저작권 보호 문서의 제한 해제를 목적으로 한 기능은 제공하지 않는다.
- 사용자가 업로드 권한을 가진 문서만 처리한다는 약관을 명시한다.
- 기업 고객을 위해 DPA, 데이터 삭제 SLA, 보안 백서, subprocessors 목록을 제공한다.

---

## 8. System Architecture

### 8.1 High-Level Pipeline

```text
Input File
  -> File validation
  -> Slide/page rasterization
  -> Layout detection
  -> OCR
  -> Segmentation mask generation
  -> Object classification
  -> Vectorization / native shape reconstruction
  -> Layer graph assembly
  -> Web editor project
  -> PPTX/PDF/SVG export
  -> Visual QA report
```

### 8.2 Services

| Service | 역할 | 후보 기술 |
|---|---|---|
| Web App | 편집기, 프로젝트 UI | React, TypeScript, Canvas/SVG engine |
| API Server | 인증, 파일, 프로젝트, export API | FastAPI 또는 NestJS |
| Job Queue | 분석/변환 비동기 처리 | Redis Queue, Celery, Temporal |
| Raster Worker | PPTX/PDF/image 렌더링 | LibreOffice headless, Poppler, Playwright |
| Segmentation Worker | 객체 마스크 생성 | SAM3/SAM3.1, fallback SAM2 또는 YOLO-seg |
| OCR Worker | 한글 OCR, 레이아웃 분석 | PaddleOCR PP-OCRv5, PP-StructureV3 |
| Vector Worker | 아이콘/도형 벡터화 | vtracer, Potrace, custom simplifier |
| Reconstruction Worker | native shape/text/table/chart 생성 | python-pptx, OpenXML SDK style postprocessor |
| Storage | 원본/중간/결과 파일 저장 | S3 compatible storage |
| Database | 프로젝트/객체/작업 상태 | PostgreSQL |
| Cache | 작업 상태, 썸네일 cache | Redis |

### 8.3 Deployment Modes

| Mode | 대상 | 특징 |
|---|---|---|
| Cloud SaaS | 개인/팀 | 빠른 가입, GPU worker 공유 |
| Dedicated VPC | 기업 | 고객별 격리, private storage |
| On-Prem | 보안 조직 | 외부 전송 없음, 로컬 GPU 사용 |
| Desktop Companion | 개인 고급 사용자 | 로컬 파일 직접 처리, cloud sync optional |

---

## 9. Intermediate Layer Model

Star-SlideEditor의 핵심은 PPTX, SVG, 웹 편집기, PDF가 모두 공유하는 중간 표현이다.

```json
{
  "project_id": "prj_001",
  "slide_id": "sld_001",
  "slide_size": {
    "width": 1920,
    "height": 1080,
    "unit": "px"
  },
  "object": {
    "id": "obj_001",
    "type": "text",
    "subtype": "title",
    "bbox": [120, 80, 720, 160],
    "rotation": 0,
    "z_index": 12,
    "confidence": 0.92,
    "editable_level": "native",
    "source": {
      "mask_path": "masks/obj_001.png",
      "crop_path": "crops/obj_001.png",
      "detector": "ocr+sam",
      "fallback_image_path": "fallback/obj_001.png"
    },
    "text": {
      "content": "AI 이미지 레이어 분해",
      "language": "ko",
      "font_family": "Pretendard",
      "font_size": 42,
      "font_weight": 700,
      "color": "#111111",
      "align": "left",
      "line_height": 1.2
    },
    "style": {
      "fill": null,
      "stroke": null,
      "opacity": 1
    },
    "qa": {
      "status": "pending",
      "warnings": []
    }
  }
}
```

### 9.1 Object Types

| Type | 설명 | Export 우선순위 |
|---|---|---|
| background | 고정 배경 | image 또는 native fill |
| text | OCR 복원 텍스트 | PPT text box |
| shape | 사각형, 원, 선, 화살표 | PPT auto shape |
| icon | 벡터 아이콘 | PPT shape 또는 SVG |
| photo | 사진/복잡 이미지 | PNG/JPEG |
| table | 표 | PPT table 또는 grouped shapes |
| chart | 차트 | PPT chart, grouped shapes, image fallback |
| equation | 수식 | image fallback, P2 MathML |
| unknown | 분류 실패 | image fallback |

### 9.2 Editable Level

| Level | 의미 | 사용자 표시 |
|---|---|---|
| native | PowerPoint 객체로 직접 편집 가능 | 녹색 |
| vector | SVG/path 수준 편집 가능 | 파란색 |
| raster | 이미지 레이어로만 편집 가능 | 회색 |
| uncertain | 인식 신뢰도 낮음 | 노란색 |
| failed | 분석 실패 | 빨간색 |

---

## 10. AI and CV Strategy

### 10.1 Segmentation

기본 전략:
- SAM3/SAM3.1을 우선 검토한다.
- 모델/라이선스/운영비/속도 이슈가 있으면 SAM2, YOLO segmentation, Detectron2 기반 fallback을 둔다.
- 슬라이드 객체는 일반 사진 객체와 다르므로 도메인 특화 후처리가 필수다.

프롬프트/감지 클래스:
- text block
- icon
- logo
- chart
- table
- line
- arrow
- diagram
- photo
- background decoration

후처리:
- OCR bbox와 겹치는 마스크는 text 후보로 우선 분류한다.
- 색상 수가 적고 edge가 명확한 객체는 vectorization 후보로 분류한다.
- 면적이 크고 다른 객체 뒤에 있는 마스크는 background 후보로 분류한다.
- 작은 마스크가 다수 모인 경우 icon group 또는 chart group으로 병합한다.

### 10.2 OCR and Text Reconstruction

한글 OCR은 제품 품질의 핵심이다.

요구사항:
- 한글/영어/숫자 혼합 인식
- 줄바꿈 보정
- 글꼴 크기 추정
- 색상 추정
- 원본 crop과 인식 텍스트를 함께 보여주는 검수 UI

후보 모델:
- PaddleOCR PP-OCRv5 multilingual
- PaddleOCR PP-StructureV3
- CLOVA OCR 또는 Google Vision은 cloud option으로만 검토
- Enterprise/on-prem은 로컬 OCR 우선

텍스트 복원 규칙:
- OCR 결과를 그대로 이미지 위에 덮지 않는다.
- 원본 텍스트 이미지는 숨김 fallback으로 보존한다.
- 사용자가 OCR 텍스트를 승인하면 fallback 텍스트 crop은 제거하거나 비활성화한다.
- 한글 문장 줄바꿈은 bbox 폭, 글자 수, 단어 경계, 조사/어절을 고려해 재계산한다.

### 10.3 Vectorization

vtracer는 아이콘, 단순 로고, 플랫 일러스트 복원에 사용한다.

적용 조건:
- 색상 수가 제한적이다.
- edge가 명확하다.
- 사진/복잡 텍스처가 아니다.
- path 수가 제한 임계값 이하로 유지된다.

실패 조건:
- path 수 과다
- 원본 대비 시각 차이 큼
- gradient/shadow/filter가 많음
- 텍스트를 path로 잘못 변환함

fallback:
- SVG로 유지
- PNG 레이어로 유지
- 사용자가 수동 trace 또는 단순 도형 변환 선택

### 10.4 Chart/Table Recovery

차트/표는 상용 품질에서 가장 어려운 영역이다. 단계적 복원을 적용한다.

Chart recovery levels:
- C0: chart image fallback
- C1: 라벨 텍스트만 OCR로 편집 가능
- C2: 막대/선/마커를 grouped shape로 복원
- C3: 추정 데이터 테이블 생성
- C4: native PowerPoint chart 생성

Table recovery levels:
- T0: table image fallback
- T1: 셀 텍스트만 overlay text로 복원
- T2: 선/셀/텍스트를 grouped shape로 복원
- T3: native PowerPoint table 생성

MVP는 C1/T1까지, 상용 v1은 C2/T2, v2는 C4/T3을 목표로 한다.

---

## 11. PPTX Export Design

### 11.1 Export Priority

객체별 export 우선순위:

1. PowerPoint native object
2. SVG/vector object
3. Cropped raster image
4. Full-slide raster fallback

### 11.2 PPTX Mapping

| Layer Model | PPTX Object | 구현 방식 |
|---|---|---|
| text | text box | python-pptx |
| rectangle/ellipse | auto shape | python-pptx |
| line/arrow | connector/line | python-pptx 또는 OpenXML |
| icon path | freeform/custom geometry | OpenXML postprocess |
| SVG | picture or converted shape | SVG insert + optional ungroup guide |
| photo | picture | python-pptx |
| table | table | python-pptx |
| chart | chart | python-pptx chart API |
| grouped object | group shape | OpenXML postprocess |

### 11.3 Export QA

PPTX 생성 후 다음 검증을 자동 수행한다.

- PowerPoint/LibreOffice headless로 다시 렌더링
- 원본 렌더링과 export 렌더링 비교
- 누락 객체 수 확인
- 텍스트 overflow 감지
- 이미지 깨짐 감지
- 객체 수/path 수 과다 경고
- fallback 객체 목록 리포트 생성

---

## 12. Web Editor UX Requirements

### 12.1 Layout

기본 화면:

```text
+---------------------------------------------------------------+
| Top Toolbar: select text shape image export view mode          |
+------------+------------------------------------+-------------+
| Slides     | Canvas                             | Properties  |
| thumbnails | original/editable/diff             | Layer info   |
|            |                                    | Text/style   |
+------------+------------------------------------+-------------+
| Status: analysis quality, warnings, save state                 |
+---------------------------------------------------------------+
```

### 12.2 Key Interactions

- 객체 클릭: 선택
- 더블클릭 text: 텍스트 편집
- 드래그: 이동
- 핸들 드래그: 크기 조정
- 레이어 패널 drag: z-order 변경
- eye icon: visibility toggle
- lock icon: lock toggle
- confidence badge click: 원본 crop과 분석 근거 표시
- diff toggle: 원본 대비 차이 표시
- export button: PPTX/PDF/SVG 선택

### 12.3 Quality Feedback UI

슬라이드별 표시:
- 편집 가능도 점수
- OCR 검수 필요 텍스트 수
- raster fallback 객체 수
- export 시각 차이 점수
- 실패/경고 목록

객체별 표시:
- type badge
- editable level
- confidence
- source crop
- suggested action

---

## 13. API Requirements

### 13.1 Core APIs

```http
POST /v1/projects
POST /v1/projects/{project_id}/files
POST /v1/projects/{project_id}/analyze
GET  /v1/projects/{project_id}
GET  /v1/projects/{project_id}/slides
GET  /v1/slides/{slide_id}/objects
PATCH /v1/objects/{object_id}
POST /v1/projects/{project_id}/export
GET  /v1/jobs/{job_id}
GET  /v1/exports/{export_id}/download
```

### 13.2 Object Patch Example

```json
{
  "bbox": [130, 90, 760, 170],
  "text": {
    "content": "수정된 한글 제목",
    "font_size": 40,
    "color": "#222222"
  },
  "style": {
    "opacity": 1
  },
  "qa": {
    "status": "reviewed"
  }
}
```

### 13.3 Job State

```text
queued -> rasterizing -> detecting -> reconstructing -> ready
queued -> rasterizing -> failed
ready -> exporting -> exported
ready -> exporting -> export_failed
```

---

## 14. Data Model

### 14.1 Tables

| Table | 설명 |
|---|---|
| users | 사용자 |
| organizations | 팀/기업 |
| projects | 변환 프로젝트 |
| files | 원본 파일 |
| slides | 슬라이드/페이지 |
| slide_renders | 원본/편집/export 렌더링 |
| objects | 레이어 객체 |
| object_assets | mask, crop, svg, fallback image |
| jobs | 분석/export 작업 |
| exports | 다운로드 가능한 결과물 |
| audit_logs | 보안/운영 이벤트 |
| qa_metrics | 품질 측정 결과 |

### 14.2 Storage Layout

```text
s3://bucket/org/{org_id}/project/{project_id}/
  original/
  renders/
  thumbnails/
  masks/
  crops/
  vectors/
  exports/
  qa/
```

---

## 15. Admin and Operations

### 15.1 Admin Dashboard

필수 항목:
- 작업 큐 상태
- GPU worker 사용률
- 실패 작업 목록
- 평균 처리 시간
- 파일 저장 용량
- OCR/segmentation/export 오류율
- 고객별 사용량
- 보안 이벤트 로그

### 15.2 Observability

로그:
- request_id, project_id, slide_id, job_id 포함
- 원본 문서 내용은 로그에 저장하지 않는다.

메트릭:
- job duration
- worker memory/GPU usage
- slide processing time
- export failure rate
- OCR confidence distribution
- fallback ratio

트레이싱:
- upload -> raster -> AI analysis -> reconstruction -> export 전체 span 추적

---

## 16. Business Model

### 16.1 Pricing Draft

| Plan | 대상 | 제한 | 가격 방향 |
|---|---|---|---|
| Free | 체험 | 월 10슬라이드, watermark, 낮은 priority | 무료 |
| Pro | 개인 | 월 500슬라이드, PPTX export | 구독 |
| Team | 소규모 팀 | 공유 프로젝트, 배치 처리, 브랜드 템플릿 | 좌석 + 사용량 |
| Enterprise | 기업 | VPC/on-prem, 감사 로그, SSO, SLA | 계약 |

### 16.2 Usage Metering

과금 단위 후보:
- 분석 슬라이드 수
- export 슬라이드 수
- GPU 처리 시간
- 저장 용량
- 팀 좌석 수

권장:
- 사용자에게 이해하기 쉬운 "슬라이드 수" 기반 과금
- 내부 원가 관리는 GPU 처리 시간으로 추적

---

## 17. MVP Scope

### 17.1 MVP 포함

- 파일 업로드: PPTX, PDF, PNG/JPG
- 슬라이드 래스터화
- OCR 기반 텍스트 복원
- SAM 기반 객체 마스크 생성
- 단순 도형/아이콘 벡터화
- 레이어 JSON 생성
- 웹 편집기 기본 기능
- PPTX export
- 분석 품질 리포트

### 17.2 MVP 제외

- native chart 완전 복원
- native table 완전 복원
- 협업 코멘트
- PowerPoint add-in
- Google Slides export
- on-prem installer

### 17.3 MVP Exit Criteria

- 30개 실제 AI 생성 슬라이드 샘플셋에서 평균 편집 가능도 60% 이상
- 한글 OCR 문자 정확도 93% 이상
- 20장 PPTX를 10분 이내 분석
- PPTX export 결과가 PowerPoint에서 정상 열림
- 텍스트 객체는 80% 이상 직접 수정 가능
- 실패 슬라이드는 전체 작업을 중단하지 않고 fallback 처리

---

## 18. Roadmap

### Phase 0: Research and Benchmark, 2 weeks

목표:
- 실제 샘플셋 100장 구축
- SAM3/SAM3.1, PaddleOCR, vtracer, python-pptx, OpenXML 변환 검증
- 객체별 복원 성공률 측정

산출물:
- benchmark report
- sample dataset
- layer model schema v0
- PPTX export prototype

### Phase 1: Vertical Slice MVP, 4 weeks

목표:
- 단일 파일 업로드부터 PPTX export까지 end-to-end 구현
- 텍스트/단순 도형/아이콘/이미지 fallback 지원

산출물:
- API server
- worker pipeline
- basic web editor
- PPTX export

### Phase 2: Editor and QA, 4 weeks

목표:
- 편집기 사용성 강화
- 원본/편집/diff view
- OCR 검수 UI
- export QA 자동화

산출물:
- 레이어 패널
- 속성 패널
- undo/redo
- visual QA report

### Phase 3: Commercial Beta, 6 weeks

목표:
- 결제/계정/팀/사용량 관리
- 배치 처리
- 품질 개선
- 운영 대시보드

산출물:
- Pro/Team beta
- admin dashboard
- storage lifecycle
- audit logs

### Phase 4: Advanced Recovery, 8 weeks

목표:
- 표/차트 복원 고도화
- 브랜드 템플릿 적용
- Enterprise 배포 옵션 설계

산출물:
- table recovery T2/T3
- chart recovery C2/C3
- brand template mapping
- VPC/on-prem architecture

---

## 19. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 이미지에서 원본 객체 구조를 완벽히 알 수 없음 | 사용자가 기대한 완전 편집 불가 | editable level과 fallback을 명확히 표시 |
| 한글 OCR 오류 | 텍스트 신뢰도 저하 | OCR 검수 UI, 언어 모델 후처리, 사용자 사전 |
| 차트 데이터 추정 실패 | native chart 복원 불가 | grouped shape chart와 image fallback 제공 |
| SVG to PPT 변환 한계 | PowerPoint에서 편집성 저하 | OpenXML 변환 계층 개발, path 수 제한 |
| GPU 비용 증가 | SaaS 원가 상승 | 슬라이드 분류 후 필요한 모델만 실행 |
| 처리 시간이 길어짐 | 이탈 증가 | 비동기 처리, 진행률, 우선순위 큐, 샘플 preview |
| 민감 문서 업로드 우려 | 기업 도입 저해 | on-prem/VPC, 외부 API 미사용 모드 |
| 모델 라이선스 변경 | 상용 사용 리스크 | 모델별 license registry와 fallback 모델 유지 |

---

## 20. Quality Benchmark Plan

### 20.1 Dataset

샘플셋 구성:
- NotebookLM 생성 PPTX/PDF
- Gamma/Canva/AI deck 생성물
- 일반 PDF 보고서
- 한글 교육자료
- 차트 중심 보고서
- 표 중심 문서
- 아이콘/인포그래픽 중심 슬라이드

최소 수량:
- MVP: 100 slides
- Beta: 1,000 slides
- Commercial: 10,000 slides

### 20.2 Metrics

객체 단위:
- detection precision/recall
- OCR character accuracy
- bbox IoU
- editable level distribution
- fallback ratio

슬라이드 단위:
- visual similarity
- export success rate
- edit completion time
- user correction count
- user satisfaction score

비즈니스 단위:
- upload to export conversion rate
- export per active user
- paid conversion
- cost per processed slide
- support ticket rate

---

## 21. Open Questions

1. 제품의 첫 타깃은 개인 Pro SaaS인가, 기업용 보안 변환 도구인가?
2. 초기에는 cloud GPU를 사용할 것인가, 로컬/on-prem을 우선할 것인가?
3. NotebookLM 산출물을 1차 최적화 대상으로 고정할 것인가?
4. 웹 편집기를 자체 구축할 것인가, 기존 canvas/editor SDK를 활용할 것인가?
5. PowerPoint native shape 변환을 얼마나 깊게 자체 구현할 것인가?
6. 한글 폰트 라이선스와 fallback font 정책은 어떻게 가져갈 것인가?
7. 원본 파일 보존 기간의 기본값은 얼마로 둘 것인가?

---

## 22. Source and Technology Notes

이 문서는 다음 공개 기술을 기준으로 작성되었다.

- Meta SAM3/SAM3.1: 이미지/비디오 객체 감지 및 segmentation 후보  
  https://github.com/facebookresearch/sam3
- Meta SAM models announcement: SAM3/SAM3D 공개 배경  
  https://about.fb.com/news/2025/11/new-sam-models-detect-objects-create-3d-reconstructions/
- vtracer: raster image to SVG vectorization 후보  
  https://github.com/visioncortex/vtracer
- python-pptx: PPTX text/shape/chart/table 생성 후보  
  https://python-pptx.readthedocs.io/
- PaddleOCR PP-OCRv5 multilingual: 한글 포함 다국어 OCR 후보  
  https://paddlepaddle.github.io/PaddleOCR/v3.1.0/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
- PaddleOCR PP-StructureV3: layout/table/formula/chart parsing 후보  
  https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html
- Microsoft 365 SVG editing: SVG 삽입/편집 가능성 및 PowerPoint 호환성 검토 대상  
  https://support.microsoft.com/en-us/office/edit-svg-images-in-microsoft-365-69f29d39-194a-4072-8c35-dbe5e7ea528c

최종 구현 전에는 각 모델/라이브러리의 상용 라이선스, 배포 제한, 성능, GPU 요구사항, 개인정보 처리 조건을 별도 검토해야 한다.

---

## 23. Definition of Done for v1 Commercial Release

v1 상용 릴리스는 다음 조건을 만족해야 한다.

- Pro 사용자가 가입 후 5분 안에 첫 PPTX export를 완료할 수 있다.
- 일반 한글 AI 슬라이드에서 텍스트 수정 가능률이 80% 이상이다.
- 실패한 객체는 숨겨지지 않고 명확한 fallback 상태로 표시된다.
- PPTX export 파일은 Microsoft PowerPoint 최신 버전에서 정상 열리고 주요 객체가 편집 가능하다.
- 원본 파일과 중간 산출물 삭제 기능이 제공된다.
- 운영자가 실패 작업과 GPU 비용을 추적할 수 있다.
- 제품 약관에 업로드 권한, 데이터 보존, 외부 모델 사용 여부가 명시되어 있다.
- 장애 발생 시 프로젝트 단위 데이터 손실 없이 재시도 가능하다.
