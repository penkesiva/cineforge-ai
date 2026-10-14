from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from cineforge.config import Settings
from cineforge.contracts.media import AssetKind, StorageBackend, StorageError, storage_key
from cineforge.media.factory import build_storage
from cineforge.media.storage import LocalStorage, SupabaseStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "media")


def test_put_open_exists_delete(storage: LocalStorage) -> None:
    assert isinstance(storage, StorageBackend)
    key = storage_key("tenant_demo", "prod_1", AssetKind.DOCUMENT, "notes.txt")
    data = b"hello cineforge"
    obj = storage.put_bytes(key, data, "text/plain")
    assert obj.key == key and obj.backend == "local"
    assert obj.uri == f"local://{key}"
    assert obj.size_bytes == len(data)
    assert obj.sha256 == hashlib.sha256(data).hexdigest()
    assert storage.exists(key)
    with storage.open(key) as fh:
        assert fh.read() == data
    path = storage.local_path(key)
    assert path is not None and path.read_bytes() == data
    assert path.is_relative_to(storage.root)
    storage.delete(key)
    assert not storage.exists(key)
    storage.delete(key)  # idempotent
    with pytest.raises(StorageError):
        storage.open(key)


def test_put_file_streams_and_hashes(storage: LocalStorage, tmp_path: Path) -> None:
    source = tmp_path / "big.bin"
    payload = os.urandom(3 * 1024 * 1024 + 17)
    source.write_bytes(payload)
    obj = storage.put_file("tenants/t/library/video/big.bin", source, "application/octet-stream")
    assert obj.size_bytes == len(payload)
    assert obj.sha256 == hashlib.sha256(payload).hexdigest()
    with pytest.raises(StorageError):
        storage.put_file("tenants/t/x.bin", tmp_path / "missing.bin", "application/octet-stream")


@pytest.mark.parametrize(
    "key",
    [
        "/etc/passwd",
        "../outside.txt",
        "tenants/../../outside.txt",
        "tenants/./x",
        "tenants//x",
        "tenants\\x",
        "C:/windows/x",
        "",
        "tenants/x/",
        "a\x00b",
    ],
)
def test_traversal_rejected(storage: LocalStorage, key: str) -> None:
    with pytest.raises(StorageError):
        storage.put_bytes(key, b"x", "text/plain")
    with pytest.raises(StorageError):
        storage.exists(key)


def test_symlink_escape_rejected(storage: LocalStorage, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (storage.root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageError):
        storage.put_bytes("link/evil.txt", b"x", "text/plain")
    assert not (outside / "evil.txt").exists()


def test_atomic_write_replaces_and_leaves_no_temp(storage: LocalStorage) -> None:
    key = "tenants/t/library/document/a.txt"
    storage.put_bytes(key, b"v1", "text/plain")
    storage.put_bytes(key, b"v2-longer", "text/plain")
    with storage.open(key) as fh:
        assert fh.read() == b"v2-longer"
    leftovers = [p.name for p in storage.local_path(key).parent.iterdir()]
    assert leftovers == ["a.txt"]


def test_failed_write_keeps_previous_version(storage: LocalStorage) -> None:
    key = "tenants/t/library/document/b.txt"
    storage.put_bytes(key, b"original", "text/plain")

    def exploding():
        yield b"partial"
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        storage._write(key, exploding(), "text/plain")
    with storage.open(key) as fh:
        assert fh.read() == b"original"
    assert [p.name for p in storage.local_path(key).parent.iterdir()] == ["b.txt"]


def test_supabase_stub() -> None:
    with pytest.raises(StorageError, match="SUPABASE_URL"):
        SupabaseStorage(supabase_url="", service_role_key="k", bucket="b")
    stub = SupabaseStorage(supabase_url="http://x", service_role_key="k", bucket="cineforge-media")
    assert isinstance(stub, StorageBackend)
    assert stub.uri("tenants/t/a.mp4") == "supabase://cineforge-media/tenants/t/a.mp4"
    assert stub.local_path("tenants/t/a.mp4") is None
    for call in (
        lambda: stub.put_bytes("k", b"", "text/plain"),
        lambda: stub.put_file("k", Path("x"), "text/plain"),
        lambda: stub.open("k"),
        lambda: stub.exists("k"),
        lambda: stub.delete("k"),
    ):
        with pytest.raises(StorageError, match="not implemented in Phase 0"):
            call()


def test_factory(tmp_path: Path) -> None:
    local = build_storage(Settings(storage_local_root=tmp_path / "root"))
    assert isinstance(local, LocalStorage) and (tmp_path / "root").is_dir()
    with pytest.raises(StorageError):
        build_storage(Settings(storage_backend="supabase", supabase_url=""))
    stub = build_storage(
        Settings(storage_backend="supabase", supabase_url="http://x", supabase_service_role_key="k")
    )
    assert isinstance(stub, SupabaseStorage)
