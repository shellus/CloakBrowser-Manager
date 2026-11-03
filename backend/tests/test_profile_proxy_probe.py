"""Profile proxy diagnostics preserve the browser's runtime and persisted chain."""
import asyncio
import subprocess
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import database as db
from backend import main
from backend import remote_environment as remote
from backend.browser_manager import BrowserManager, RunningProfile


CHAIN = [{"name": "exit", "type": "http", "server": "proxy.invalid", "port": 8080}]
REQUEST = {"proxy_chain": CHAIN, "url": "https://probe.invalid/json",
           "connect_timeout_seconds": 2, "timeout_seconds": 5}


@pytest.fixture()
def probe_runtime(tmp_db, monkeypatch):
    monkeypatch.setattr(remote, "ENABLED", True)
    for name in ("_processes", "_proxy_dirs", "_proxy_ports", "_proxy_versions"):
        monkeypatch.setattr(remote, name, {})
    profile = db.create_profile("Synthetic probe", proxy_chain=CHAIN)
    starts, stops, requests = [], [], []
    proc = MagicMock(pid=7654)
    proc.poll.return_value = None

    def start(candidate, **kwargs):
        starts.append((candidate, kwargs))
        remote._processes[profile["id"]] = proc
        remote._proxy_ports[profile["id"]] = 32123
        remote._proxy_versions[profile["id"]] = remote.chain_version(candidate["proxy_chain"])

    original_stop = remote.stop_proxy
    def stop(profile_id):
        stops.append(profile_id)
        original_stop(profile_id)

    def request(args, **kwargs):
        requests.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, '{"ip":"192.0.2.12"}\n200', '')

    monkeypatch.setattr(remote, "start_proxy", start)
    monkeypatch.setattr(remote, "stop_proxy", stop)
    monkeypatch.setattr(remote.subprocess, "run", request)
    return profile, proc, starts, stops, requests


@pytest.mark.parametrize("chain", [CHAIN, []], ids=["proxy-chain", "direct-via-mihomo"])
async def test_stopped_profile_probes_temporary_mihomo_without_saving_or_launching(probe_runtime, chain):
    profile, proc, starts, stops, requests = probe_runtime
    manager = BrowserManager()
    result = await manager.probe_proxy(profile["id"], chain, REQUEST["url"], 2, 5)
    assert result["source"] == {"profileId": profile["id"], "pid": 7654, "port": 32123,
                                "temporary": True, "chainVersion": remote.chain_version(chain)}
    assert result["httpStatus"] == 200
    assert result["body"] == '{"ip":"192.0.2.12"}'
    assert starts[0][0]["proxy_chain"] == chain
    assert starts[0][1] == {"allow_direct": True}
    assert stops == [profile["id"]]
    assert proc.terminate.call_count == 1
    assert remote.proxy_port(profile["id"]) is None
    assert db.get_profile(profile["id"])["proxy_chain"] == CHAIN
    assert manager.running == {}
    args = requests[0][0]
    assert args[args.index("--proxy") + 1] == "http://127.0.0.1:32123"
    assert args[args.index("--noproxy") + 1] == ""
    assert requests[0][1]["timeout"] == 10


async def test_running_profile_reuses_its_mihomo_and_rejects_changed_chain(probe_runtime):
    profile, proc, starts, stops, requests = probe_runtime
    remote._processes[profile["id"]] = proc
    remote._proxy_ports[profile["id"]] = 32123
    remote._proxy_versions[profile["id"]] = remote.chain_version(CHAIN)
    manager = BrowserManager()
    manager.running[profile["id"]] = RunningProfile(profile["id"], MagicMock(), 40001)
    result = await manager.probe_proxy(profile["id"], CHAIN, REQUEST["url"], 2, 5)
    assert not result["source"]["temporary"]
    assert not starts and not stops
    proc.terminate.assert_not_called()
    with pytest.raises(remote.ProxyProbeError, match="does not match") as error:
        await manager.probe_proxy(profile["id"], [], REQUEST["url"], 2, 5)
    assert error.value.code == "PROXY_PROBE_CHAIN_CHANGED"
    assert len(requests) == 1


async def test_network_failure_cleans_up_temporary_process(probe_runtime, monkeypatch):
    profile, proc, starts, stops, requests = probe_runtime
    monkeypatch.setattr(remote.subprocess, "run", MagicMock(side_effect=subprocess.TimeoutExpired("curl", 10)))
    with pytest.raises(remote.ProxyProbeError) as error:
        await BrowserManager().probe_proxy(profile["id"], CHAIN, REQUEST["url"], 2, 5)
    assert error.value.code == "PROXY_VERIFY_REQUEST_FAILED"
    assert stops == [profile["id"]]
    assert not remote._processes


async def test_failed_start_cleans_up_partial_listener(probe_runtime, monkeypatch):
    profile, proc, starts, stops, requests = probe_runtime
    def failed_start(candidate, **kwargs):
        remote._proxy_ports[profile["id"]] = 32123
        raise RuntimeError("Synthetic invalid configuration")
    monkeypatch.setattr(remote, "start_proxy", failed_start)
    with pytest.raises(remote.ProxyProbeError) as error:
        await BrowserManager().probe_proxy(profile["id"], CHAIN, REQUEST["url"], 2, 5)
    assert error.value.code == "PROXY_VERIFY_REQUEST_FAILED"
    assert not remote._proxy_ports and not requests


async def test_cancelled_request_waits_for_worker_cleanup_and_keeps_lifecycle_lock(probe_runtime, monkeypatch):
    profile, proc, starts, stops, requests = probe_runtime
    entered, release = threading.Event(), threading.Event()
    original = remote.subprocess.run
    def wait(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(remote.subprocess, "run", wait)
    manager = BrowserManager()
    task = asyncio.create_task(manager.probe_proxy(profile["id"], CHAIN, REQUEST["url"], 2, 5))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert manager._lock.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stops == [profile["id"]]
    assert not manager._lock.locked()


def test_direct_chain_has_direct_mihomo_rule():
    assert remote.proxy_config([], 32123)["rules"] == ["MATCH,DIRECT"]


def test_probe_endpoint_forwards_input_and_structured_errors(app_client, sample_profile, monkeypatch):
    probe = AsyncMock(return_value={"httpStatus": 200, "body": "{}", "source": {}})
    monkeypatch.setattr(main.browser_mgr, "probe_proxy", probe)
    path = f'/api/profiles/{sample_profile["id"]}/proxy-probe'
    assert app_client.post(path, json=REQUEST).json()["httpStatus"] == 200
    probe.assert_awaited_once_with(sample_profile["id"], CHAIN, REQUEST["url"], 2, 5)
    for code, status in [("PROXY_PROBE_CHAIN_CHANGED", 409), ("PROXY_VERIFY_REQUEST_FAILED", 503)]:
        probe.side_effect = remote.ProxyProbeError(code, "Synthetic failure")
        response = app_client.post(path, json=REQUEST)
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code
    probe.side_effect = LookupError()
    assert app_client.post(path, json=REQUEST).status_code == 404


@pytest.mark.parametrize("url", ["file:///tmp/example", "https://user:password@probe.invalid", "-o/tmp/example"])
def test_probe_endpoint_rejects_non_http_or_credential_url(app_client, url):
    response = app_client.post("/api/profiles/synthetic/proxy-probe", json={**REQUEST, "url": url})
    assert response.status_code == 422


def test_probe_endpoint_uses_existing_authentication(app_client, monkeypatch):
    monkeypatch.setattr(main, "AUTH_TOKEN", "synthetic-secret")
    response = app_client.post("/api/profiles/synthetic/proxy-probe", json=REQUEST)
    assert response.status_code == 401


async def test_disabled_runtime_fails_before_any_probe(probe_runtime, monkeypatch):
    profile, proc, starts, stops, requests = probe_runtime
    monkeypatch.setattr(remote, "ENABLED", False)
    with pytest.raises(remote.ProxyProbeError) as error:
        await BrowserManager().probe_proxy(profile["id"], CHAIN, REQUEST["url"], 2, 5)
    assert error.value.code == "PROXY_PROBE_UNAVAILABLE"
    assert not starts and not requests
