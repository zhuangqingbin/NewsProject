# tests/unit/charts/test_uploader.py
from unittest.mock import MagicMock

import pytest

from news_pipeline.charts.uploader import OSSUploader


def test_upload_returns_public_url():
    bucket = MagicMock()
    bucket.put_object.return_value = MagicMock(status=200)
    u = OSSUploader(
        bucket=bucket, endpoint="oss-cn-hangzhou.aliyuncs.com",
        bucket_name="news-charts",
    )
    url = u.upload(path_in_bucket="charts/2026/04/x.png", content=b"PNG")
    assert "news-charts" in url and "x.png" in url
    bucket.put_object.assert_called_once()


def test_upload_failure_raises():
    bucket = MagicMock()
    bucket.put_object.return_value = MagicMock(status=500)
    u = OSSUploader(bucket=bucket, endpoint="x", bucket_name="b")
    with pytest.raises(RuntimeError):
        u.upload(path_in_bucket="x.png", content=b"P")
