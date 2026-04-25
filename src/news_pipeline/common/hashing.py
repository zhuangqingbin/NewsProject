# src/news_pipeline/common/hashing.py
import hashlib

from simhash import Simhash


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def title_simhash(title: str) -> int:
    # 64-bit simhash on character bigrams (works for both EN and CN)
    text = title.strip()
    tokens = [text[i : i + 2] for i in range(len(text) - 1)] or [text]
    return int(Simhash(tokens, f=64).value)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
