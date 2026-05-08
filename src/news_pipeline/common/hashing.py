# src/news_pipeline/common/hashing.py
import hashlib

from simhash import Simhash


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


_U64_MASK = (1 << 64) - 1
_I64_MAX = (1 << 63) - 1


def title_simhash(title: str) -> int:
    # 64-bit simhash on character bigrams (works for both EN and CN).
    # Simhash returns unsigned u64; SQLite INTEGER is signed i64, so values
    # >= 2^63 raise "Python int too large to convert to SQLite INTEGER" on
    # insert. Reinterpret as signed i64 (bit pattern preserved → hamming
    # still correct as long as it masks back to 64 bits).
    text = title.strip()
    tokens = [text[i : i + 2] for i in range(len(text) - 1)] or [text]
    v = int(Simhash(tokens, f=64).value)
    return v - (1 << 64) if v > _I64_MAX else v


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & _U64_MASK).count("1")
