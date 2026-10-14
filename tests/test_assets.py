import hashlib

import pytest

from rummage import assets


def test_every_host_has_a_default_runtime(monkeypatch):
    for (system, arch), backend in assets._DEFAULT_BACKEND.items():
        monkeypatch.setattr(assets, "host", lambda s=system, a=arch: (s, a))
        asset = assets.runtime_asset()
        assert asset.name.startswith(f"llama-{assets.LLAMA_TAG}-bin-")
        assert asset.url.endswith(asset.name) and len(asset.sha256) == 64
        assert backend in assets.backends()


def test_unknown_backend_names_the_choices(monkeypatch):
    monkeypatch.setattr(assets, "host", lambda: ("linux", "x64"))
    with pytest.raises(RuntimeError, match="cpu, vulkan"):
        assets.runtime_asset("metal")


def test_download_checks_size_and_digest(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"model bytes" * 1000)
    good = assets.Asset("m.gguf", source.as_uri(), source.stat().st_size,
                        hashlib.sha256(source.read_bytes()).hexdigest())
    target = assets.download(good, tmp_path / "out" / "m.gguf")
    assert target.read_bytes() == source.read_bytes()

    bad = assets.Asset("n.gguf", source.as_uri(), good.size, "0" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        assets.download(bad, tmp_path / "out" / "n.gguf")
    assert not (tmp_path / "out" / "n.gguf").exists()
    assert not (tmp_path / "out" / "n.gguf.part").exists()


def test_archive_entries_must_stay_inside():
    with pytest.raises(RuntimeError):
        assets._check_members(["build/bin/llama-server", "../../etc/cron.d/x"])
    assets._check_members(["build/bin/llama-server"])
