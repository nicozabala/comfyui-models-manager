import posixpath

import pytest

from comfy_network_tools.errors import TransferError
from comfy_network_tools.ssh import InMemoryRemoteFS, download_atomic, upload_atomic


@pytest.fixture
def fs():
    remote = InMemoryRemoteFS()
    remote.add_dir("/models")
    return remote


@pytest.fixture
def local_file(tmp_path):
    p = tmp_path / "model.safetensors"
    p.write_bytes(b"\0" * 2048)
    return p


# --- contract: the fake behaves like a filesystem ---


def test_makedirs_is_recursive_and_stat_reports_dirs(fs):
    fs.makedirs("/models/loras/nested")
    assert fs.stat("/models/loras").is_dir
    assert fs.stat("/models/loras/nested").is_dir
    assert fs.stat("/models/missing") is None


def test_listdir_returns_direct_children_only(fs):
    fs.add_file("/models/loras/a.safetensors", 10)
    fs.add_file("/models/loras/b.safetensors", 20)
    fs.add_file("/models/vae/c.safetensors", 30)
    assert fs.listdir("/models/loras") == ["a.safetensors", "b.safetensors"]
    assert fs.listdir("/models") == ["loras", "vae"]
    assert fs.listdir("/models/nope") == []


def test_put_requires_parent_dir_and_records_size(fs, local_file):
    with pytest.raises(TransferError):
        fs.put(local_file, "/models/loras/x.safetensors")
    fs.makedirs("/models/loras")
    fs.put(local_file, "/models/loras/x.safetensors")
    assert fs.stat("/models/loras/x.safetensors").size == 2048


def test_rename_and_remove(fs, local_file):
    fs.put(local_file, "/models/tmp")
    fs.rename("/models/tmp", "/models/final")
    assert fs.stat("/models/tmp") is None
    assert fs.stat("/models/final").size == 2048
    fs.remove("/models/final")
    assert fs.stat("/models/final") is None
    fs.remove("/models/final")  # idempotent


# --- upload_atomic ---


def test_upload_atomic_success_renames_part_into_place(fs, local_file):
    fs.makedirs("/models/loras")
    seen = []
    upload_atomic(
        fs, local_file, "/models/loras/m.safetensors", progress=lambda a, b: seen.append((a, b))
    )
    assert fs.stat("/models/loras/m.safetensors").size == 2048
    assert fs.stat("/models/loras/m.safetensors.cnt-part") is None
    assert seen and seen[-1] == (2048, 2048)


def test_upload_atomic_failure_removes_part_and_leaves_no_file(fs, local_file):
    fs.makedirs("/models/loras")
    fs.fail_paths.add(posixpath.normpath("/models/loras/m.safetensors.cnt-part"))
    with pytest.raises(TransferError):
        upload_atomic(fs, local_file, "/models/loras/m.safetensors")
    assert fs.stat("/models/loras/m.safetensors") is None
    assert fs.stat("/models/loras/m.safetensors.cnt-part") is None


# --- get / download_atomic ---


def test_get_requires_remote_file_and_writes_local_bytes(fs, tmp_path):
    dest = tmp_path / "out.safetensors"
    with pytest.raises(TransferError):
        fs.get("/models/loras/x.safetensors", dest)
    fs.add_file("/models/loras/x.safetensors", 2048)
    fs.get("/models/loras/x.safetensors", dest)
    assert dest.stat().st_size == 2048


def test_download_atomic_success_renames_part_into_place(fs, tmp_path):
    fs.add_file("/models/loras/m.safetensors", 2048)
    dest = tmp_path / "m.safetensors"
    seen = []
    download_atomic(
        fs, "/models/loras/m.safetensors", dest, progress=lambda a, b: seen.append((a, b))
    )
    assert dest.is_file() and dest.stat().st_size == 2048
    assert not dest.with_name(dest.name + ".cnt-part").exists()
    assert seen and seen[-1] == (2048, 2048)


def test_download_atomic_failure_removes_part_and_leaves_no_file(fs, tmp_path):
    fs.add_file("/models/loras/m.safetensors", 2048)
    fs.fail_paths.add(posixpath.normpath("/models/loras/m.safetensors"))
    dest = tmp_path / "m.safetensors"
    with pytest.raises(TransferError):
        download_atomic(fs, "/models/loras/m.safetensors", dest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".cnt-part").exists()
