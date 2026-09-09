from functools import lru_cache

from app.config import settings
from app.storage.base import ObjectNotFound, Storage

__all__ = ["Storage", "ObjectNotFound", "get_storage"]


@lru_cache
def get_storage() -> Storage:
    """The one place that knows which backend is in use."""
    if settings.storage_backend == "local":
        from app.storage.local import LocalStorage

        return LocalStorage(settings.storage_local_root, settings.storage_public_base_url)

    if settings.storage_backend == "r2":
        from app.storage.r2 import R2Storage

        missing = [
            name
            for name in ("r2_endpoint_url", "r2_access_key_id", "r2_secret_access_key", "r2_bucket")
            if not getattr(settings, name)
        ]
        if missing:
            raise RuntimeError(f"STORAGE_BACKEND=r2 but missing settings: {', '.join(missing)}")
        return R2Storage(
            endpoint_url=settings.r2_endpoint_url,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
            public_base_url=settings.r2_public_base_url or settings.r2_endpoint_url,
        )

    raise RuntimeError(f"unknown STORAGE_BACKEND {settings.storage_backend!r} (want 'local'|'r2')")
