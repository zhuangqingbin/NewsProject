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
    # signed i64 range — must fit SQLite INTEGER
    assert -(1 << 63) <= h <= (1 << 63) - 1


def test_title_simhash_fits_sqlite_integer_for_many_titles():
    # Regression: u64 simhash values >= 2^63 used to raise
    # "Python int too large to convert to SQLite INTEGER" on insert.
    samples = [
        "外交部：中方就中东局势与包括以色列在内各方保持不同层级沟通",  # noqa: RUF001
        "Nvidia Q2 revenue beats estimates by 8%",
        "茅台公布一季度财报营收增长",
        "data",
        "a",
        "",
        "🚀 stocks soar after fed cut",
        "地中海航运公司宣布推出新的欧洲-红海-中东快递服务。",
    ]
    for t in samples:
        h = title_simhash(t)
        assert -(1 << 63) <= h <= (1 << 63) - 1, f"out of i64 range for {t!r}: {h}"


def test_simhash_hamming_handles_negative_values():
    # After u64→i64 reinterpret, a hash with top-bit set becomes negative.
    # hamming must still count bits correctly (bit pattern preserved).
    assert hamming(-1, 0) == 64
    assert hamming(-1, -1) == 0
    assert hamming(0, 1) == 1


def test_simhash_distance_close_for_similar_titles():
    a = title_simhash("英伟达盘后大跌 8%")
    b = title_simhash("英伟达盘后跌 8%")
    # Similar titles should have much smaller hamming distance than unrelated ones
    assert hamming(a, b) < 16


def test_simhash_distance_far_for_unrelated():
    a = title_simhash("英伟达盘后大跌 8%")
    b = title_simhash("茅台公布一季度财报营收增长")
    assert hamming(a, b) > 16
