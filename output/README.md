# output/

Star-Slide CLI 변환 결과 기본 출력 디렉토리. **`.gitignore`로 변환 산출물 자체는 추적 안 됨** (이 README와 `.gitkeep`만 추적).

## 디렉토리 규약

```
output/
├── README.md                              (이 문서)
├── .gitkeep                               빈 디렉토리 보존
└── <project_name>/                        프로젝트별 서브폴더 권장
    ├── <project>_edited.pptx              편집 가능 PPTX
    ├── <project>_edited.report.json       품질 리포트
    └── _workdir_<project>_edited/         중간 산출물
        └── renders/                       슬라이드별 PNG
            ├── slide_001.png
            └── slide_002.png
```

## 사용 예

### 단일 변환

```bash
# 권장: 프로젝트별 서브폴더에 출력
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  uv run star-slide convert run refdata/sample2.pptx \
  -o output/sample2/sample2_edited.pptx \
  --no-libreoffice

# 결과:
#   output/sample2/sample2_edited.pptx
#   output/sample2/sample2_edited.report.json
#   output/sample2/_workdir_sample2_edited/renders/*.png
```

### 결과 PowerPoint로 열기

```bash
open output/sample2/sample2_edited.pptx
```

### 리포트 확인

```bash
cat output/sample2/sample2_edited.report.json | jq .
```

## 옵션 플래그

| 플래그 | 효과 |
|--------|------|
| `--no-libreoffice` | LibreOffice 미설치 환경에서 임베드 이미지 직접 추출 fallback (현재 Mac 환경 권장) |
| `--ocr-confidence 0.5` | OCR 라인 채택 임계값 (기본 0.7) |
| `--workdir custom_dir` | 중간 산출물 위치 커스터마이즈 |
| `--report custom.json` | 리포트 JSON 위치 커스터마이즈 |

## 산출물 정리

```bash
# 특정 프로젝트만
rm -rf output/sample2/

# 모든 변환 결과 (중간 산출물 포함)
rm -rf output/*/

# .gitignore 덕분에 git status에 영향 없음
```
