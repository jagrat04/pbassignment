from abc import ABC, abstractmethod


class ObjectNotFound(Exception):
    pass


class Storage(ABC):
    """The only thing the rest of the app knows about object storage.

    Nothing above this interface may import boto3, touch a filesystem path, or
    know whether an object lives on disk or in a bucket. Moving from local disk
    to Cloudflare R2 is swapping which subclass `get_storage()` returns.
    """

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> str:
        """Write an object and return its publicly reachable URL."""

    @abstractmethod
    def put_atomic(self, key: str, data: bytes, content_type: str) -> str:
        """Write an object such that a concurrent reader sees either the old
        object or the new one -- never a partially written one."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Read an object. Raises ObjectNotFound."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def url_for(self, key: str) -> str: ...
