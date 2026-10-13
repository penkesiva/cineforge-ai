"""Object storage backends: local filesystem (Phase 0) and a Supabase Storage stub."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

from cineforge.contracts.media import StorageError, StoredObject

_CHUNK = 1024 * 1024
_DRIVE = re.compile(r"^[A-Za-z]:")


def validate_key(key: str) -> str:
    """Reject keys that could escape the storage root (path traversal)."""
    if not key or not isinstance(key, str):
        raise StorageError("storage key must be a non-empty string")
    if key.startswith("/") or "\\" in key or "\x00" in key or _DRIVE.match(key):
        raise StorageError(f"invalid storage key {key!r}")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise StorageError(f"invalid storage key {key!r}")
    return key


class LocalStorage:
    """Filesystem backend rooted at ``root``. Writes are atomic (temp file + os.replace)."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError(f"storage key {key!r} escapes the storage root")
        return path

    def uri(self, key: str) -> str:
        return f"local://{key}"

    def _write(self, key: str, chunks: object, content_type: str) -> StoredObject:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                for chunk in chunks:  # type: ignore[attr-defined]
                    digest.update(chunk)
                    size += len(chunk)
                    fh.write(chunk)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return StoredObject(
            backend=self.name,
            key=key,
            uri=self.uri(key),
            size_bytes=size,
            sha256=digest.hexdigest(),
            content_type=content_type,
        )

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        return self._write(key, [data], content_type)

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject:
        source = Path(path)
        if not source.is_file():
            raise StorageError(f"source file not found: {source}")
        with source.open("rb") as fh:
            return self._write(key, iter(lambda: fh.read(_CHUNK), b""), content_type)

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"object not found: {key}")
        return path.open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path | None:
        return self._path(key)


_NOT_IMPLEMENTED = "Supabase Storage adapter is not implemented in Phase 0"


class SupabaseStorage:
    """Interface-ready stub for Supabase Storage (URIs ``supabase://<bucket>/<key>``)."""

    name = "supabase"

    def __init__(self, *, supabase_url: str, service_role_key: str, bucket: str) -> None:
        missing = [
            n
            for n, v in (
                ("SUPABASE_URL", supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", service_role_key),
                ("SUPABASE_STORAGE_BUCKET", bucket),
            )
            if not v
        ]
        if missing:
            raise StorageError(f"Supabase storage requires {', '.join(missing)}")
        self.supabase_url = supabase_url
        self.bucket = bucket
        self._service_role_key = service_role_key

    def uri(self, key: str) -> str:
        return f"supabase://{self.bucket}/{validate_key(key)}"

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        raise StorageError(_NOT_IMPLEMENTED)

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject:
        raise StorageError(_NOT_IMPLEMENTED)

    def open(self, key: str) -> BinaryIO:
        raise StorageError(_NOT_IMPLEMENTED)

    def exists(self, key: str) -> bool:
        raise StorageError(_NOT_IMPLEMENTED)

    def delete(self, key: str) -> None:
        raise StorageError(_NOT_IMPLEMENTED)

    def local_path(self, key: str) -> Path | None:
        return None
