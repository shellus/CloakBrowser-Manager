"""Regression boundaries for registry cold starts and client-based idleness."""
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from backend import database as db
from backend import remote_environment as remote
from backend.browser_manager import RunningProfile
from backend.browser_manager import BrowserManager
from unittest.mock import MagicMock


@pytest.fixture()
def proxy_runtime(monkeypatch):
    for name in ("_processes", "_proxy_dirs", "_proxy_ports", "_proxy_versions"):
        monkeypatch.setattr(remote, name, {})
    monkeypatch.setattr(remote, "ENABLED", True)


async def test_proxy_replacement_keeps_browser_and_listener_and_deduplicates(tmp_db, proxy_runtime, monkeypatch):
    old = [{"type": "socks5", "server": "old.invalid", "port": 1080}]
    chain = [{"type": "socks5", "server": "new.invalid", "port": 1080}]
    profile = db.create_profile("Synthetic", proxy_chain=old)
    pid = profile["id"]
    manager = BrowserManager()
    browser = RunningProfile(pid, MagicMock(), 40001)
    manager.running[pid] = browser
    remote._proxy_ports[pid] = 12345
    proc = MagicMock()
    proc.poll.return_value = None
    remote._processes[pid] = proc
    remote._proxy_versions[pid] = remote.chain_version(old)
    monkeypatch.setattr(remote, "_run", lambda *args: "")
    starts = []
    def start(updated, *, port, prepared):
        assert proc.terminate.call_count == 1
        starts.append((port, json.loads((prepared / "config.yaml").read_text())))
        remote._processes[pid] = proc
        remote._proxy_versions[pid] = remote.chain_version(updated["proxy_chain"])
    monkeypatch.setattr(remote, "start_proxy", start)
    expected = {"ready": True, "applied_version": remote.chain_version(chain)}
    assert await manager.apply_proxy_chain(pid, chain) == expected
    assert await manager.apply_proxy_chain(pid, chain) == expected
    assert len(starts) == 1
    assert starts[0][0] == starts[0][1]["mixed-port"] == 12345
    assert manager.running[pid] is browser
    browser.context.close.assert_not_called()
    assert db.get_profile(pid)["proxy_chain"] == chain


async def test_invalid_chain_preserves_old_process_and_target(tmp_db, proxy_runtime, monkeypatch):
    profile = db.create_profile("Synthetic", proxy_chain=[{"type": "socks5"}])
    pid = profile["id"]
    manager = BrowserManager()
    manager.running[pid] = RunningProfile(pid, MagicMock(), 40001)
    remote._proxy_ports[pid] = 12345
    proc = MagicMock()
    remote._processes[pid] = proc
    monkeypatch.setattr(remote, "_run", MagicMock(side_effect=RuntimeError("invalid config")))
    with pytest.raises(RuntimeError, match="invalid config"):
        await manager.apply_proxy_chain(pid, [{"type": "unknown"}])
    proc.terminate.assert_not_called()
    assert db.get_profile(pid)["proxy_chain"] == profile["proxy_chain"]


async def test_failed_replacement_keeps_port_for_retry_without_restoring_old_chain(tmp_db, proxy_runtime, monkeypatch):
    profile = db.create_profile("Synthetic", proxy_chain=[{"type": "socks5"}])
    pid = profile["id"]
    manager = BrowserManager()
    manager.running[pid] = RunningProfile(pid, MagicMock(), 40001)
    remote._proxy_ports[pid] = 12345
    proc = MagicMock()
    proc.poll.return_value = None
    remote._processes[pid] = proc
    monkeypatch.setattr(remote, "_run", lambda *args: "")
    chain = [{"type": "http", "server": "new.invalid", "port": 8080}]
    monkeypatch.setattr(remote, "start_proxy", MagicMock(side_effect=RuntimeError("bind failed")))
    with pytest.raises(RuntimeError, match="bind failed"):
        await manager.apply_proxy_chain(pid, chain)
    assert remote.proxy_status(pid) == {"ready": False, "applied_version": None}
    assert remote.proxy_port(pid) == 12345
    assert db.get_profile(pid)["proxy_chain"] == chain
    assert pid in manager.running


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
