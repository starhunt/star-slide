# SAM 3 Box Prompt PoC — slide 5

## 환경
- device: mps
- image: 1376x768
- OCR lines (conf>=0.3): 24

## 타이밍
- OCR: 7.7s
- SAM 3 inference: 4.3s (24 box prompts)
- LaMa inpaint: 6.5s

## 산출물
- slide5_orig.png         원본 렌더
- slide5_ocr_overlay.png  OCR bbox 시각화
- slide5_sam3_masks.png   SAM 3 정밀 마스크 union
- slide5_sam3_masks_dilated.png  +5px dilate
- slide5_inpaint_test.png 정밀 마스크 LaMa 인페인팅 결과

## 평가 기준 (사용자 결정)
- 텍스트 잔재(글자 외곽선)가 사라졌는가?
- 게이지 그래픽이 보존됐는가?
- 시간 비용이 받아들일 만한가?

## 다음 단계
- 결과 좋으면 → orchestrator에서 sam2_auto → sam3 box-prompt 모드로 전환
- 결과 미흡하면 → text prompt 모드 ("text", "korean letter") 시도
