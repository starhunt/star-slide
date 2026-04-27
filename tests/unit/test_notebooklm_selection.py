from star_slide.pipeline.notebooklm_auto import has_significant_text_loss


def test_detects_meaningful_hybrid_text_loss() -> None:
    vector = {"count": 52, "chars": 2173, "primary_count": 52, "primary_chars": 2173}
    hybrid = {"count": 28, "chars": 1981, "primary_count": 28, "primary_chars": 1981}

    assert has_significant_text_loss(vector, hybrid)


def test_ignores_small_label_differences() -> None:
    vector = {"count": 12, "chars": 300, "primary_count": 9, "primary_chars": 260}
    hybrid = {"count": 11, "chars": 292, "primary_count": 8, "primary_chars": 252}

    assert not has_significant_text_loss(vector, hybrid)


def test_ignores_sparse_text_slides() -> None:
    vector = {"count": 3, "chars": 120, "primary_count": 3, "primary_chars": 120}
    hybrid = {"count": 1, "chars": 30, "primary_count": 1, "primary_chars": 30}

    assert not has_significant_text_loss(vector, hybrid)
