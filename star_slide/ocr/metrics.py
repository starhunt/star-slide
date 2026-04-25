"""OCR 정확도 메트릭 — CER, WER.

CER(Character Error Rate) = Levenshtein(pred, gt) / len(gt)
한국어는 자소 단위가 아닌 음절(글리프) 단위로 계산하는 게 사용자 체감과 일치.
"""

from __future__ import annotations

import re
import unicodedata


def _normalize(text: str, ignore_whitespace: bool = True) -> str:
    """비교용 정규화.

    - NFC 유니코드 정규화 (한글 자모 결합)
    - 모든 공백 제거 (ignore_whitespace=True 시) — 줄바꿈/스페이스 차이 무시
    """
    text = unicodedata.normalize("NFC", text)
    if ignore_whitespace:
        text = re.sub(r"\s+", "", text)
    return text


def levenshtein(a: str, b: str) -> int:
    """두 문자열의 편집 거리 (음절 단위)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, start=1):
        curr[0] = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,  # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev, curr = curr, prev
    return prev[len(b)]


def cer(pred: str, gt: str, ignore_whitespace: bool = True) -> float:
    """Character Error Rate. 0.0 = 완벽, 1.0 = 100% 오류.

    Args:
        pred: OCR 예측 텍스트
        gt: ground truth 텍스트
        ignore_whitespace: True면 공백/줄바꿈 차이 무시
    """
    p = _normalize(pred, ignore_whitespace)
    g = _normalize(gt, ignore_whitespace)
    if not g:
        return 1.0 if p else 0.0
    return levenshtein(p, g) / len(g)


def wer(pred: str, gt: str) -> float:
    """Word Error Rate. 한국어 어절 또는 영문 단어."""
    p_tokens = pred.split()
    g_tokens = gt.split()
    if not g_tokens:
        return 1.0 if p_tokens else 0.0
    # 단어 단위 levenshtein
    if p_tokens == g_tokens:
        return 0.0
    n = len(p_tokens)
    m = len(g_tokens)
    if n == 0:
        return 1.0
    if m == 0:
        return 1.0
    prev = list(range(m + 1))
    curr = [0] * (m + 1)
    for i, a in enumerate(p_tokens, start=1):
        curr[0] = i
        for j, b in enumerate(g_tokens, start=1):
            cost = 0 if a == b else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[m] / m
