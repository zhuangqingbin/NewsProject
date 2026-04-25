# tests/unit/common/test_hashing.py
from news_pipeline.common.hashing import hamming, title_simhash, url_hash


def test_url_hash_stable_and_deterministic():
    h1 = url_hash("https://example.com/path?x=1")
    h2 = url_hash("https://example.com/path?x=1")
    assert h1 == h2
    assert len(h1) == 40  # sha1 hex


def test_url_hash_differs_for_different_urls():
    assert url_hash("https://a.com") != url_hash("https://b.com")


def test_title_simhash_returns_int():
    h = title_simhash("英伟达盘后大跌 8%")
    assert isinstance(h, int)
    assert 0 <= h < (1 << 64)


def test_simhash_distance_close_for_similar_titles():
    a = title_simhash("英伟达盘后大跌 8%")
    b = title_simhash("英伟达盘后跌 8%")
    # Similar titles should have much smaller hamming distance than unrelated ones
    assert hamming(a, b) < 16


def test_simhash_distance_far_for_unrelated():
    a = title_simhash("英伟达盘后大跌 8%")
    b = title_simhash("茅台公布一季度财报营收增长")
    assert hamming(a, b) > 16
