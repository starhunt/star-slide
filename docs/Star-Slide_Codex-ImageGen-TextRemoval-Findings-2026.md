# Codex image_gen 마스크 편집 & 복잡 배경 텍스트 제거 — 조사 결과

> 작성일: 2026-06-13
> 목적: "텍스트만 지우고 배경 복원" 접근의 실현 가능성을 codex image_gen(gpt-image-2) 기준으로 검증. 특히 NotebookLM 슬라이드 특유의 **복잡 배경**(격자·색상·사진/일러스트 위 텍스트)에서의 한계 규명.
> 결론 요약: **마스크 편집은 기술적으로 경로는 있으나 실무적으로 신뢰 어렵고, 복잡 배경의 텍스트 제거는 원리적으로 불가능에 가깝다.** "배경 복원" 패러다임을 "배경 보존"으로 전환할 것을 권고.
> 관련: [Star-Slide_Pipeline-Optimization-2026.md](./Star-Slide_Pipeline-Optimization-2026.md) §3.1(P0) — 본 조사로 정정됨.

---

## 1. codex image_gen의 마스크 편집 지원 여부

검증 환경: `codex-cli 0.139.0` (`~/.npm-global/bin/codex`, Mach-O arm64), 기본 모델 `gpt-image-2`.

| 항목 | 결과 | 근거 |
|------|------|------|
| 마스크 편집 경로 존재 | **있음** | codex fallback 스크립트 `image_gen.py`가 `edit --image --mask` 서브커맨드로 OpenAI `POST /v1/images/edits` 호출 |
| `codex exec -i/--image` 첨부 | **가능** | 0.139.0에 `-i, --image <FILE>...` 옵션 존재. edit 모드 시 편집 입력으로 전달될 수 있음 |
| builtin `image_gen` 도구로 mask 직접 지정 | **불가** | builtin 도구는 `prompt`만 노출. reference/mask 입력 요청 [Issue #19136](https://github.com/openai/codex/issues/19136)·[#20839](https://github.com/openai/codex/issues/20839) **open 상태** |
| **마스크 외 영역 픽셀 보존** | **보장 안 됨** | gpt-image 계열은 마스크를 "정밀 경계"가 아니라 **전체 재합성 힌트**로 취급 (OpenAI 커뮤니티 다수 보고). 출력 해상도도 `size`로 결정 → 입력 해상도/픽셀 보존 미보장 |

### 함의
- **duct-cli(`codex exec` 경유)로는 마스크를 넘길 수 없다.** 마스크 편집을 쓰려면 codex의 `image_gen.py edit --image --mask` fallback CLI를 직접 호출해야 한다.
- 설사 마스크를 넘겨도 **dimension drift와 배경 변형이 완전히 사라지지 않는다.** gpt-image는 마스크 밖도 재합성하는 경향이 있어, "원본 픽셀 그대로 보존"이라는 마스크 편집의 핵심 이점이 약하다.

출처:
- [openai/codex SKILL.md (imagegen)](https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/imagegen/SKILL.md)
- [openai/codex image_gen.py](https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/imagegen/scripts/image_gen.py)
- [OpenAI API Reference — images.edit](https://developers.openai.com/api/reference/python/resources/images/methods/edit)
- [community: mask not constraining edit](https://community.openai.com/t/help-with-images-edit-mask-not-constraining-edit-to-specific-area/1351283)

---

## 2. 복잡 배경 텍스트 제거의 근본적 한계

핵심 원리: **텍스트에 가려진 배경 픽셀은 데이터가 존재하지 않는다.** 따라서 모든 inpainting(codex·LaMa·SOTA diffusion 무관)은 그 자리를 "복원"하는 게 아니라 주변을 보고 **그럴듯하게 추측 생성(hallucinate)**한다. 배경이 복잡할수록 추측이 정답과 어긋난다.

| 배경 유형 | 결과 | 이유 |
|-----------|------|------|
| 흰/단색 | ✅ 잘 됨 | 추측해도 정답과 일치 — *심플 슬라이드가 잘 되는 이유* |
| 격자/그리드 | ❌ 어긋남 | 규칙적 패턴의 연속 복원은 현 SOTA도 미해결. 격자가 끊기거나 틀어짐 |
| 그라데이션/색상 | 🟡 얼룩 | 경계 색 불일치 (CONTINUITY의 "색 배경 위 inpaint 얼룩"이 이것) |
| 사진/일러스트 위 | ❌ 환각 | 가려진 그림을 통째로 새로 지어냄 → 원본과 다른 그림 생성 |

> **검증 시 주의(실측 교훈)**: 심플(흰 배경) 슬라이드로 "마스크 편집/텍스트 제거가 잘 된다"고 판단하면 안 된다. NotebookLM 슬라이드의 실제 난이도는 격자·색상·사진 배경에 있다. 반드시 복잡 배경 샘플로 검증할 것.

학술 근거: diffusion inpainting은 원 배경을 충실히 재구성하기보다 새 객체를 hallucinate하는 경향이 정설(RePainter arXiv:2510.07721, EraseLoRA arXiv:2512.21545). 격자/그라데이션 같은 전역 규칙 패턴의 정밀 연속 복원은 미해결 과제.

---

## 3. 권고: "배경 복원" → "배경 보존" 패러다임 전환

복잡 배경에서 텍스트를 지우려 하지 말고, **원본 배경을 건드리지 않는** 방향으로 뒤집는다.

### 3.1 배경 유형별 전략

| 텍스트가 놓인 배경 | 전략 | 편집성 | 시각 충실도 |
|---|---|---|---|
| 흰/단색 | 국소 inpaint 또는 단색 패치 + 텍스트박스 | ✅ 높음 | ✅ 높음 |
| 격자/규칙 패턴 | 패턴을 **procedural 재생성**(반복 도형) 후 텍스트박스 | ✅ 높음 | ✅ (패턴 인식 성공 시) |
| 그라데이션 | 그라데이션 채우기 도형 재현 + 텍스트박스 | ✅ 높음 | 🟡 중간 |
| 사진/일러스트 위 | **지우지 않음.** 원본을 이미지 객체로 보존 + 그 위에 *불투명 배경 텍스트박스*로 원본 글자를 덮어 편집 | 🟡 텍스트만 | ✅ 높음 |

### 3.2 공통 안전장치 — composite back

codex(또는 어떤 도구든)로 무엇을 생성하든, **그 출력을 통째로 쓰지 말 것.** 텍스트 bbox 영역만 떼어내 **원본 위에 합성**한다. 그러면:
- 배경 변형·dimension drift가 **텍스트 영역에만 갇히고**,
- 비텍스트 영역(아이콘·차트·배경)은 **원본 픽셀 100% 보존**된다.

이는 마스크 편집의 신뢰성 부족(§1)과 inpainting 환각(§2)을 동시에 우회하는 가장 견고한 1차 방어선이다.

### 3.3 codex의 최적 활용 지점 (재포지셔닝)

- codex의 검증된 강점인 **한글 이해/판독**은 텍스트 제거가 아니라 **OCR·구조 분석(layout JSON)**에 활용하는 것이 가치가 높다.
- 텍스트 제거(textless basis) 엔진으로서의 codex는 **단색/단순 배경 슬라이드에 한정** 적용하고, 복잡 배경은 §3.1의 배경 보존으로 우회한다.

---

## 4. 미결정 사항 (후속 논의 필요)

- 복잡 배경 슬라이드에서 codex 텍스트 제거를 (가) 단순 배경에만 한정 사용할지, (나) 전면 배경 보존(불투명 텍스트박스 덮기)으로 갈지 — 실제 NotebookLM 복잡 슬라이드 PoC로 렌더 비교 후 결정.
- 격자/그라데이션의 procedural 재생성 자동화 가능 범위 (패턴 검출 신뢰도).
- `images/edits` fallback CLI 직접 호출을 파이프라인에 넣을 가치가 있는지 (§1 신뢰성 한계 고려 시 우선순위 낮음).

---

## 5. 핵심 출처

1. [openai/codex image_gen.py (edit --image --mask)](https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/imagegen/scripts/image_gen.py)
2. [openai/codex Issue #19136 — reference image 미지원](https://github.com/openai/codex/issues/19136)
3. [OpenAI images.edit API](https://developers.openai.com/api/reference/python/resources/images/methods/edit)
4. [community: gpt-image mask 비보존 보고](https://community.openai.com/t/help-with-images-edit-mask-not-constraining-edit-to-specific-area/1351283)
5. [RePainter (arXiv:2510.07721)](https://arxiv.org/html/2510.07721) — inpainting 환각/배경 복원 한계
6. [EraseLoRA (arXiv:2512.21545)](https://arxiv.org/pdf/2512.21545) — 복잡 패턴 재구성 실패
