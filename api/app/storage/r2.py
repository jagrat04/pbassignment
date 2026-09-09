from app.storage.base import ObjectNotFound, Storage


class R2Storage(Storage):
    """Cloudflare R2 (S3-compatible) storage.

    This is the whole diff between local dev and production. R2's PutObject is
    atomic per key -- a reader gets the previous object or the new one, never a
    torn one -- so `put_atomic` is just `put`. No multipart is used: catalogue
    JSON and artwork are both far below the 5 GB single-part ceiling.
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base_url: str,
    ):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            # R2 ignores the region but the SDK insists on one.
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            # Artwork is immutable (content-addressed key); the catalogue is not.
            CacheControl="public, max-age=31536000, immutable"
            if key.startswith("artwork/")
            else "public, max-age=60",
        )
        return self.url_for(key)

    def put_atomic(self, key: str, data: bytes, content_type: str) -> str:
        return self.put(key, data, content_type)

    def get(self, key: str) -> bytes:
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
        except self._client.exceptions.NoSuchKey as exc:
            raise ObjectNotFound(key) from exc
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def url_for(self, key: str) -> str:
        return f"{self.public_base_url}/{key.lstrip('/')}"
