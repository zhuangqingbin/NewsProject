"""Lock in: `requests.exceptions.ConnectionError` (raised by akshare-backed
scrapers when the upstream API blips) is classified as TRANSIENT, not
structural — otherwise every network hiccup pages the user via Bark."""

import httpx
import requests

from news_pipeline.scheduler.jobs import _is_transient


def test_requests_connection_error_is_transient():
    # akshare wraps requests; the typical upstream-down message we see
    err = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='np-weblist.eastmoney.com', port=443): "
        "Max retries exceeded with url: /comm/web/getFastNewsList"
    )
    assert _is_transient(err) is True


def test_requests_timeout_is_transient():
    assert _is_transient(requests.exceptions.Timeout("read timeout")) is True


def test_httpx_connect_error_still_transient():
    assert _is_transient(httpx.ConnectError("refused")) is True


def test_value_error_not_transient():
    assert _is_transient(ValueError("oops")) is False
