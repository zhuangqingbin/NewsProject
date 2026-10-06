import re

_BRACKET = re.compile(r"^\s*【([^】]{4,90})】")


def headline(title: str, body: str | None = None) -> str:
    """Extract the source's title sentence without including subsequent commentary."""
    title, body = (title or "").strip(), (body or "").strip()
    match = _BRACKET.match(body) or _BRACKET.match(title)
    if match:
        return match.group(1)
    if body and (not title or body.startswith(title[:20])):
        return re.split(r"[。\uff01\uff1f\uff1b\n]", body, maxsplit=1)[0][:90]
    return title[:90]
