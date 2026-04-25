# src/news_pipeline/charts/uploader.py
from typing import Any


class OSSUploader:
    def __init__(
        self, *, bucket: Any, endpoint: str, bucket_name: str, https: bool = True
    ) -> None:
        self._bucket = bucket
        self._endpoint = endpoint
        self._name = bucket_name
        self._scheme = "https" if https else "http"

    def upload(
        self,
        *,
        path_in_bucket: str,
        content: bytes,
        content_type: str = "image/png",
    ) -> str:
        result = self._bucket.put_object(
            path_in_bucket, content, headers={"Content-Type": content_type}
        )
        if getattr(result, "status", 0) != 200:
            raise RuntimeError(f"OSS upload failed: status={result.status}")
        return f"{self._scheme}://{self._name}.{self._endpoint}/{path_in_bucket}"

    @classmethod
    def from_secrets(
        cls,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        access_key_secret: str,
    ) -> "OSSUploader":
        import oss2

        auth = oss2.Auth(access_key_id, access_key_secret)
        b = oss2.Bucket(auth, f"https://{endpoint}", bucket)
        return cls(bucket=b, endpoint=endpoint, bucket_name=bucket)
