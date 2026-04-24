# Star-SlideMaster 상세 제품 요구사항 정의서 (PRD)

**작성일**: 2026년 4월 25일
**작성자**: Manus AI
**문서 상태**: Draft

---

## 1. 제품 개요 (Product Overview)

### 1.1 제품 명칭
**Star-SlideMaster** (스타 슬라이드마스터)

### 1.2 제품 비전
"단일 슬라이드 이미지에 갇힌 아이디어를 완벽하게 제어 가능한 프레젠테이션 자산으로 해방시킨다."

### 1.3 배경 및 시장 기회
최근 NotebookLM과 같은 생성형 AI 도구들이 사용자의 문서나 데이터를 바탕으로 훌륭한 프레젠테이션 초안을 생성해주고 있습니다. 하지만 이러한 도구들이 출력하는 결과물은 대부분 단일 이미지 기반의 PDF나 정적인 슬라이드 형태로 제공됩니다 [1]. 사용자는 생성된 슬라이드에서 텍스트의 오타를 수정하거나, 차트의 색상을 브랜드 가이드라인에 맞게 변경하거나, 특정 아이콘의 위치를 미세 조정하기를 원하지만, 현재의 이미지 기반 출력 방식에서는 이를 직접 편집할 수 없습니다 [2].

시장 조사에 따르면, AI 프레젠테이션 생성 도구 시장은 2026년 24억 3천만 달러에서 2030년 60억 달러 규모로 연평균 25.3% 성장할 것으로 전망됩니다 [3]. 이에 따라 생성된 슬라이드 결과물을 실무에 바로 적용하기 위해 편집 가능한 포맷으로 변환하려는 수요가 폭발적으로 증가하고 있습니다. 특히, 기존 Codia AI의 NoteSlide나 PreciseDeck과 같은 도구들이 시장에 존재하지만, 한국어 텍스트 인식의 정확도 문제와 복잡한 다채색 그래픽 객체의 벡터화 품질 등에서 뚜렷한 한계를 보이고 있습니다 [4] [5].

### 1.4 핵심 가치 제안 (Value Proposition)
Star-SlideMaster는 정적인 슬라이드 이미지(Raster Image)를 지능적으로 분석하여, 의미 있는 개별 객체(텍스트, 아이콘, 배경, 차트 등)로 분해하고, 이를 사용자가 직접 수정 가능한 네이티브 파워포인트(PPTX) 및 벡터 그래픽(SVG) 포맷으로 변환합니다. 특히, 최신 비전 AI 기술인 **OpenAI gpt-image-2**와 **Meta SAM 3**를 결합하여 한글 텍스트의 완벽한 복원과 복잡한 객체의 정밀한 분할을 지원합니다.

---

## 2. 목표 사용자 및 유스케이스 (Target Users & Use Cases)

### 2.1 핵심 타겟 고객
*   **지식 노동자 및 기획자**: NotebookLM, ChatGPT 등으로 생성한 슬라이드 초안을 실무 보고서로 다듬어야 하는 직장인.
*   **디자이너 및 마케터**: 핀터레스트나 웹에서 캡처한 슬라이드 레퍼런스 이미지를 편집 가능한 템플릿으로 재구성하려는 전문가.
*   **교육자 및 학생**: 논문이나 교재에 삽입된 복잡한 다이어그램 이미지를 추출하여 강의 자료(PPTX)에 맞게 텍스트를 수정하고 재배치하려는 사용자.

### 2.2 주요 유스케이스 시나리오
1.  **AI 생성 슬라이드 편집**: 사용자가 NotebookLM에서 추출한 PDF 슬라이드 이미지를 Star-SlideMaster에 업로드합니다. 시스템이 이미지를 분석하여 텍스트 박스와 SVG 도형이 분리된 PPTX 파일을 제공하며, 사용자는 파워포인트에서 직접 텍스트를 한글로 수정하고 차트 색상을 변경합니다.
2.  **레퍼런스 이미지 템플릿화**: 웹에서 찾은 영어로 된 인포그래픽 이미지를 업로드합니다. 시스템이 영문 텍스트를 인식하여 지우고 빈 텍스트 박스를 생성해주며, 배경과 아이콘을 SVG로 분리해 줍니다. 사용자는 빈 텍스트 박스에 한글 내용을 입력하여 자신만의 인포그래픽을 완성합니다.

---

## 3. 핵심 기능 요구사항 (Functional Requirements)

### 3.1 지능형 텍스트 추출 및 인페인팅 (Text Extraction & Inpainting)
*   **다국어 텍스트 인식**: 최신 **OpenAI gpt-image-2** 모델의 강력한 시각적 이해 능력을 활용하여 이미지 내의 한글, 영문 및 혼용 텍스트를 99% 이상의 글리프(Glyph) 정확도로 인식해야 합니다 [6].
*   **메타데이터 추출**: 인식된 텍스트의 바운딩 박스(Bounding Box) 좌표, 폰트 크기, 색상, 텍스트 정렬 상태를 정확하게 추출해야 합니다.
*   **배경 복원 (Inpainting)**: 텍스트가 있던 자리를 주변 배경과 자연스럽게 융합하여 지우는 인페인팅 기능을 제공해야 합니다. gpt-image-2의 마스크 기반 인페인팅(Mask-based Inpainting) API를 활용하여 텍스트 찌꺼기가 남지 않는 깨끗한 배경 이미지를 생성합니다 [7].

### 3.2 고정밀 객체 세그멘테이션 (High-Precision Object Segmentation)
*   **제로샷 마스크 생성**: Meta의 **SAM 3 (Segment Anything Model 3)**를 활용하여 사전 학습된 라벨 없이도 이미지 내의 모든 시각적 객체(도형, 아이콘, 사진 등)에 대한 세그멘테이션 마스크를 자동으로 생성해야 합니다 [8].
*   **계층적 레이어 분류**: 추출된 마스크의 면적과 겹침 정도를 분석하여 배경 레이어와 전경 객체 레이어로 지능적으로 분류해야 합니다.
*   **투명 객체 추출**: 각 전경 마스크를 기반으로 원본 이미지에서 객체를 크롭하고, 알파 채널을 적용하여 배경이 완벽하게 투명한 개별 RGBA PNG 파일로 분리해야 합니다.

### 3.3 지능형 래스터-벡터 변환 (Raster-to-Vector Conversion)
*   **다채색 SVG 변환**: 분리된 전경 객체(PNG)들을 **VTracer**를 사용하여 크기 조절이 가능하고 해상도가 깨지지 않는 다채색(Multi-color) SVG 벡터 그래픽으로 변환해야 합니다 [9].
*   **사진 예외 처리**: 모든 객체를 벡터화할 경우 실사 사진은 용량이 과도하게 커지는 문제가 발생합니다. 시스템은 객체의 색상 분산도(Color Variance)를 분석하여 복잡한 사진으로 판별될 경우, 벡터화 단계를 건너뛰고 투명 PNG 상태를 유지하는 스마트 폴백(Smart Fallback) 기능을 제공해야 합니다.

### 3.4 네이티브 PPTX 슬라이드 재조립 (Native PPTX Reassembly)
*   **슬라이드 생성**: `python-pptx` 라이브러리를 사용하여 사용자가 지정한 화면 비율(기본 16:9)의 빈 파워포인트 슬라이드를 생성합니다 [10].
*   **객체 정밀 배치**: 분리된 배경 이미지, 벡터화된 SVG 도형, 투명 PNG 사진들을 원본 이미지에서 추출한 (x, y) 좌표와 크기 비율에 맞게 슬라이드 위에 정확히 배치해야 합니다.
*   **편집 가능한 텍스트 박스**: 텍스트가 있던 좌표에 파워포인트 네이티브 텍스트 박스(Text Box)를 생성하고, 추출된 텍스트와 폰트 스타일(색상, 크기)을 적용하여 원본과 시각적으로 유사하면서도 완벽하게 수정 가능한 상태로 제공해야 합니다.

---

## 4. 시스템 아키텍처 및 기술 스택 (System Architecture & Tech Stack)

Star-SlideMaster의 파이프라인은 5단계의 모듈화된 프로세스로 구성됩니다.

| 처리 단계 | 핵심 수행 작업 | 적용 기술 및 모델 | 출력 산출물 |
| :--- | :--- | :--- | :--- |
| **1. 입력 전처리** | 이미지 정규화 및 해상도 최적화 | OpenCV / PIL | 정규화된 슬라이드 이미지 |
| **2. 텍스트 분석** | 텍스트 좌표/내용 추출 및 배경 인페인팅 | **OpenAI gpt-image-2 API** | 텍스트 메타데이터 (JSON) 및 텍스트가 지워진 배경 이미지 |
| **3. 객체 분할** | 시각적 요소 분리 및 투명화 처리 | **Meta SAM 3** | 개별 분리된 전경 객체 (투명 PNG 배열) |
| **4. 벡터화** | 픽셀 그래픽을 수학적 곡선으로 변환 | **VTracer (Python)** | 크기 조절 가능한 다채색 벡터 그래픽 (SVG 배열) |
| **5. PPTX 조립** | 추출된 요소들을 네이티브 포맷으로 병합 | **python-pptx** | 최종 편집 가능한 파워포인트 파일 (PPTX) |

---

## 5. 차별화 포인트 및 경쟁 우위 (Competitive Advantage)

현재 시장에 존재하는 Codia AI NoteSlide, PreciseDeck 등과 비교할 때, Star-SlideMaster는 다음과 같은 강력한 차별화 포인트를 가집니다.

1.  **압도적인 한글 텍스트 처리 능력**: 기존 OCR 도구들이 복잡한 배경 위의 한글 인식에 취약했던 반면, Star-SlideMaster는 **OpenAI gpt-image-2**의 99% 글리프 정확도를 활용하여 한글, 영문, 특수기호가 혼용된 슬라이드에서도 완벽한 텍스트 추출과 인페인팅을 보장합니다 [6].
2.  **최신 비전 모델(SAM 3) 기반의 정밀한 레이어 분해**: Qwen-Image-Layered와 같은 생성형 레이어 분해 기술은 PPTX 좌표 매핑이 불가능한 한계가 있습니다 [11]. 반면, Star-SlideMaster는 **SAM 3**의 제로샷 마스크 생성 능력을 활용하여 객체의 정확한 경계와 좌표를 유지한 채 레이어를 분리합니다 [8].
3.  **VTracer를 통한 고품질 벡터 그래픽(SVG) 지원**: 픽셀 기반의 PNG로만 객체를 분리하는 경쟁 제품들과 달리, 다채색 벡터화 기술인 **VTracer**를 도입하여 사용자가 파워포인트 내에서 도형의 크기를 무한대로 확대해도 품질이 저하되지 않는 진정한 의미의 '편집 가능한' 에셋을 제공합니다 [9].
4.  **LLM 기반 차트/표 구조 인식 (향후 확장성)**: 단순한 객체 분할을 넘어, gpt-image-2의 시각적 추론 능력을 활용하여 선이 교차하는 표나 막대 차트의 기저 데이터(JSON/CSV)를 추출하고, 이를 네이티브 PPTX 차트 객체로 재구성하는 고급 기능으로의 확장이 용이합니다.

---

## 6. 제약 사항 및 위험 관리 (Constraints & Risk Management)

*   **한글 폰트 매칭의 한계**: 텍스트 내용은 완벽히 추출하더라도, 원본 이미지에 사용된 상용 폰트 파일이 사용자의 PC에 설치되어 있지 않으면 파워포인트에서 똑같이 렌더링되지 않습니다. 
    *   *대응 방안*: 이미지 내 텍스트의 획 두께와 세리프(Serif) 유무를 분석하여 고딕(Sans-serif) 계열과 명조(Serif) 계열을 대략적으로 구분하고, 맑은 고딕이나 바탕체와 같은 OS 기본 폰트로 맵핑하는 지능형 폴백(Fallback) 로직을 적용합니다.
*   **API 비용 및 처리 지연 시간**: gpt-image-2 API 호출 및 SAM 3 추론 과정에서 이미지당 약 10~15초의 처리 시간이 발생하며, 클라우드 인프라 비용이 소모됩니다.
    *   *대응 방안*: SAM 3 모델을 ONNX 또는 TensorRT로 경량화하여 추론 속도를 개선하고, 사용자에게 변환 진행률을 보여주는 직관적인 로딩 UI를 제공하여 체감 대기 시간을 줄입니다.

---

## 7. 향후 로드맵 (Future Roadmap)

*   **Phase 1 (MVP)**: 단일 이미지 업로드 및 기본적인 텍스트/도형 분리 기반 PPTX 다운로드 지원.
*   **Phase 2**: Human-in-the-loop 검수 웹 UI 도입. 사용자가 자동 분할된 레이어 마스크를 시각적으로 확인하고, 잘못된 부분을 병합하거나 텍스트를 직접 수정할 수 있는 중간 편집 단계 제공.
*   **Phase 3**: 멀티모달 LLM을 활용한 차트 및 표 데이터 구조화 인식 기능 추가. 단순 이미지가 아닌 네이티브 PPTX 차트(엑셀 데이터 연동)로 완벽한 재구성 지원.

---

## References
[1] "Customizing NotebookLM slides (can't)," Reddit r/notebooklm.
[2] Cpunk, "I Finally Found a Way to Edit NotebookLM Slides — And It Actually Works," Medium, Dec 2025.
[3] Research and Markets, "AI Presentation Generation Market Report 2026."
[4] Codia AI, "Turn NotebookLM Slides into Fully Editable PowerPoint."
[5] PreciseDeck, "PreciseDeck vs Codia AI NoteSlide."
[6] OpenAI, "Introducing ChatGPT Images 2.0," Apr 2026. [Online]. Available: https://openai.com/index/introducing-chatgpt-images-2-0/.
[7] Fal.ai, "openai/gpt-image-2/edit - Mask-Based Inpainting."
[8] Meta AI, "SAM 3.1: Faster and More Accessible Real-Time Video Detection and Tracking With Multiplexing and Global Reasoning," Mar 2026. [Online]. Available: https://ai.meta.com/blog/segment-anything-model-3/.
[9] visioncortex, "VTracer: Python Binding," PyPI. [Online]. Available: https://pypi.org/project/vtracer/.
[10] python-pptx Documentation. [Online]. Available: https://python-pptx.readthedocs.io/.
[11] QwenTeam, "Qwen-Image-Layered: Layered Decomposition for Inherent Editablity," Alibaba, Dec 2025.
