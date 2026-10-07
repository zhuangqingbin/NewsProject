import hashlib


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()
