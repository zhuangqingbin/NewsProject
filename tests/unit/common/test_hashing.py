# tests/unit/common/test_hashing.py
from news_pipeline.common.hashing import url_hash


def test_url_hash_stable_and_deterministic():
    h1 = url_hash("https://example.com/path?x=1")
    h2 = url_hash("https://example.com/path?x=1")
    assert h1 == h2
    assert len(h1) == 40  # sha1 hex


def test_url_hash_differs_for_different_urls():
    assert url_hash("https://a.com") != url_hash("https://b.com")
