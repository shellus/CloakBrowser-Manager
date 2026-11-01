"""Regression boundaries for registry cold starts and client-based idleness."""
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from backend import database as db
from backend import remote_environment as remote
from backend.browser_manager import RunningProfile


@pytest.fixture()
def registry(monkeypatch, tmp_path):
    monkeypatch.setattr(remote, "ENABLED", True)
    monkeypatch.setattr(remote, "STORAGE", "registry")
    monkeypatch.setattr(remote, "REGISTRY", "registry.invalid/test")
    monkeypatch.setattr(remote, "_sync_status", {})
    monkeypatch.setattr(remote, "_sync_errors", {})
    return tmp_path / "layer.tgz"


def test_proxy_chain_is_ordered_without_mutating_input():
    chain = [{"name": "same", "type": "http"}, {"name": "same", "dialer-proxy": "wrong", "type": "socks5"}]
    cfg = remote.proxy_config(chain, 12345)
    assert cfg["proxies"][1]["dialer-proxy"] == cfg["proxies"][0]["name"]
    assert cfg["rules"] == ["MATCH,hop-1"]
    assert chain[1]["dialer-proxy"] == "wrong"
    assert "dialer-proxy" not in cfg["proxies"][0]


def test_idle_starts_when_last_cdp_or_vnc_client_disconnects(monkeypatch):
    running = RunningProfile("test", None, 1234, last_activity=0)
    running.client_connected("cdp")
    running.client_connected("vnc")
    assert not running.idle_due(1000, 300)
    monkeypatch.setattr("backend.browser_manager.time.monotonic", lambda: 1000)
    running.client_disconnected("cdp")
    assert not running.idle_due(1400, 300)
    running.client_disconnected("vnc")
    assert not running.idle_due(1299, 300)
    assert running.idle_due(1300, 300)


def test_cold_start_restores_metadata_tags_and_browser_data(tmp_db, registry, monkeypatch):
    profile = db.create_profile("Synthetic inbox", proxy_chain=[{"name": "p", "type": "http"}], tags=[{"tag": "mail", "color": "blue"}])
    source = Path(profile["user_data_dir"])
    (source / "Default").mkdir(parents=True)
    (source / "Default" / "Preferences").write_text(json.dumps({"profile": {"exit_type": "Normal"}}))
    (source / "Default" / "Cookies").write_bytes(b"synthetic session")
    (source / "Default" / "Cache").mkdir()
    (source / "Default" / "Cache" / "temporary").write_text("cache")
    def crane(*args):
        if args[1] == "append":
            shutil.copyfile(args[3], registry)
        elif args[1] == "ls":
            return profile["id"]
        elif args[1] == "export":
            # crane export returns an uncompressed filesystem tar.
            with tarfile.open(registry, "r:gz") as src, tarfile.open(args[3], "w") as dst:
                for member in src:
                    dst.addfile(member, src.extractfile(member) if member.isfile() else None)
        return ""
    monkeypatch.setattr(remote, "_run", crane)
    remote.push_profile(profile)
    assert remote.sync_status(profile["id"]) == "synced"
    db.delete_profile(profile["id"])
    shutil.rmtree(source)
    remote._sync_status.clear()
    remote.rebuild_profiles()
    restored = db.get_profile(profile["id"])
    assert restored["fingerprint_seed"] == profile["fingerprint_seed"]
    assert restored["proxy_chain"] == profile["proxy_chain"]
    assert restored["tags"] == profile["tags"]
    assert (source / "Default" / "Cookies").read_bytes() == b"synthetic session"
    assert not (source / "Default" / "Cache").exists()
    assert remote.sync_status(profile["id"]) == "synced"
    remote.rebuild_profiles()  # idempotent when local index exists


def test_unclean_profile_is_not_published(tmp_db, registry, monkeypatch):
    profile = db.create_profile("Crash")
    default = Path(profile["user_data_dir"]) / "Default"
    default.mkdir(parents=True)
    (default / "Preferences").write_text('{"profile":{"exit_type":"Crashed"}}')
    monkeypatch.setattr(remote, "_run", lambda *args: pytest.fail("must not publish"))
    with pytest.raises(RuntimeError, match="Normal"):
        remote.push_profile(profile)
    assert remote.sync_status(profile["id"]) == "failed"


def test_publish_failure_is_visible(tmp_db, registry, monkeypatch):
    profile = db.create_profile("Empty")
    def fail(*args):
        raise RuntimeError("registry unavailable")
    monkeypatch.setattr(remote, "_run", fail)
    with pytest.raises(RuntimeError, match="unavailable"):
        remote.push_profile(profile)
    assert remote.sync_status(profile["id"]) == "failed"
    assert remote.sync_error(profile["id"]) == "registry unavailable"
