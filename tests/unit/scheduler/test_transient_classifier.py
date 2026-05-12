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


def test_curl_cffi_error_is_transient():
    # akshare uses curl_cffi; CURLE_OPERATION_TIMEDOUT bubbles up as
    # CurlError("Failed to perform, curl: (28) ...") and must NOT page Bark.
    from curl_cffi.curl import CurlError

    err = CurlError(
        "Failed to perform, curl: (28) Operation timed out after 30001 milliseconds"
        " with 0 bytes received.",
        28,
    )
    assert _is_transient(err) is True
