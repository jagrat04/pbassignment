import os
import tempfile
from pathlib import Path

from app.storage.base import ObjectNotFound, Storage


class LocalStorage(Storage):
    """Disk-backed storage for local dev and CI.

    `put_atomic` writes to a temporary file in the *same directory* as the
    target (so os.replace stays on one filesystem and is a real atomic rename)
    and fsyncs both the file and its directory before swapping. A reader that
    opens the path at any instant sees a complete file.
    """

    def __init__(self, root: Path, public_base_url: str):
        self.root = Path(root)
        self.public_base_url = public_base_url.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are app-generated, but refuse traversal anyway.
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"illegal storage key: {key!r}")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.url_for(key)

    def put_atomic(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
            self._fsync_dir(path.parent)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        return self.url_for(key)

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        """Persist the rename itself. No-op on Windows, which cannot open a
        directory as a file descriptor -- dev machines only, containers are Linux."""
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except (OSError, PermissionError):
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def url_for(self, key: str) -> str:
        return f"{self.public_base_url}/{key.lstrip('/')}"
