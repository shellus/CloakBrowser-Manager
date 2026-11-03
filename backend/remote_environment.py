"""Opt-in per-profile proxy processes and registry snapshots (Linux/Windows)."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import logging
import os
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger("cloakbrowser.manager.remote")
ENABLED = os.environ.get("REMOTE_ENVIRONMENT_ENABLED", "").lower() in {"1", "true", "yes"}
STORAGE = os.environ.get("PROFILE_STORAGE", "local").lower()
IDLE_SECONDS = int(os.environ.get("PROFILE_IDLE_STOP_SECONDS", "0") or 0)
MIHOMO_PATH = os.environ.get("MIHOMO_PATH", "mihomo")
CRANE_PATH = os.environ.get("CRANE_PATH", "crane")
REGISTRY = os.environ.get("PROFILE_REGISTRY", "")
REGISTRY_PREFIX = os.environ.get("PROFILE_REGISTRY_PREFIX", "profile")
METADATA_FILE = ".manager-profile.json"
_processes: dict[str, subprocess.Popen] = {}
_proxy_dirs: dict[str, Path] = {}
_proxy_ports: dict[str, int] = {}
_proxy_versions: dict[str, str] = {}
_sync_status: dict[str, str] = {}
_sync_errors: dict[str, str] = {}
_published: set[str] = set()


def registry_enabled() -> bool:
    return ENABLED and STORAGE == "registry"


def sync_status(profile_id: str) -> str:
    return _sync_status.get(profile_id, "not_synced")


def sync_error(profile_id: str) -> str | None:
    return _sync_errors.get(profile_id)


def mark_dirty(profile_id: str) -> None:
    if registry_enabled():
        _sync_status[profile_id] = "not_synced"
        _sync_errors.pop(profile_id, None)


def environment_info(version: str | None = None) -> dict[str, Any]:
    from .runtime import resolve_runtime
    runtime = resolve_runtime()
    return {"host_os": runtime.host_os, "storage": STORAGE if ENABLED else "local",
            "idle_stop_seconds": IDLE_SECONDS if ENABLED else 0,
            "remote_view": runtime.viewer_mode == "vnc", "version": version or "unknown"}


def _run(*args: str) -> str:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} {args[1]} failed: " + result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8")


def _tag(profile_id: str) -> str:
    return f"{REGISTRY.rstrip('/')}/{REGISTRY_PREFIX}:{profile_id}"


def _extract(archive: Path, target: Path) -> dict | None:
    with tarfile.open(archive, "r:*") as tar:
        members = tar.getmembers()
        for member in members:
            dest = (target / member.name).resolve()
            if not dest.is_relative_to(target.resolve()) or member.issym() or member.islnk():
                raise ValueError(f"Invalid profile archive member: {member.name}")
        metadata = next((m for m in members if Path(m.name).name == METADATA_FILE), None)
        if metadata is None:
            return None
        profile = json.load(tar.extractfile(metadata))
        tar.extractall(target, members=members, filter="data")
        return profile


def rebuild_profiles() -> None:
    """Rebuild a disposable SQLite index from self-contained profile tags."""
    if not registry_enabled():
        return
    if not REGISTRY:
        raise ValueError("PROFILE_REGISTRY is required for registry storage")
    from . import database as db
    try:
        tags = _run(CRANE_PATH, "ls", f"{REGISTRY.rstrip('/')}/{REGISTRY_PREFIX}").splitlines()
    except RuntimeError as exc:
        # An empty registry has no profile repository yet. Docker Hub style
        # registries answer NAME_UNKNOWN; docker.cnb.cool answers NOT_FOUND.
        if "NAME_UNKNOWN" in str(exc) or "NOT_FOUND" in str(exc):
            return
        raise
    for tag in tags:
        try:
            uuid.UUID(tag)
        except ValueError:
            continue
        _published.add(tag)
        if db.get_profile(tag):
            continue
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "profile.tar"
            _run(CRANE_PATH, "export", _tag(tag), str(archive))
            staged = Path(td) / "staged"
            staged.mkdir()
            profile = _extract(archive, staged)
            if profile is None:
                log.info("Skipping legacy tag without Manager metadata: %s", tag)
                continue
            if profile["id"] != tag:
                raise ValueError("Profile metadata ID does not match registry tag")
            target = db.DATA_DIR / "profiles" / tag
            if target.exists():
                raise RuntimeError(f"Unindexed local profile directory exists: {tag}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged, target)
            db.import_profile(profile)
            _sync_status[tag] = "synced"


def restore_profile(profile: dict[str, Any]) -> None:
    if not registry_enabled():
        return
    target = Path(profile["user_data_dir"])
    if target.exists() and any(target.iterdir()):
        return
    if sync_status(profile["id"]) != "synced":
        return
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "profile.tar"
        _run(CRANE_PATH, "export", _tag(profile["id"]), str(archive))
        if _extract(archive, target) is None:
            raise RuntimeError("Registry profile is missing Manager metadata")


def push_profile(profile: dict[str, Any]) -> None:
    if not registry_enabled():
        return
    pid = profile["id"]
    _sync_status[pid] = "syncing"
    try:
        target = Path(profile["user_data_dir"])
        preferences = target / "Default" / "Preferences"
        if preferences.exists():
            exit_type = json.loads(preferences.read_text(encoding="utf-8")).get("profile", {}).get("exit_type")
            if exit_type != "Normal":
                raise RuntimeError(f"Profile exit_type must be Normal before sync, got {exit_type!r}")
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "profile.tar.gz"
            excluded = {"Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache",
                        "GraphiteDawnCache", "DawnGraphiteCache", "DawnWebGPUCache", ".mihomo"}
            def keep(info):
                if any(p in excluded or p.startswith("Singleton") for p in Path(info.name).parts):
                    return None
                return info if not (info.issym() or info.islnk()) else None
            with tarfile.open(archive, "w:gz") as tar:
                if target.exists():
                    for child in target.iterdir():
                        if child.name != METADATA_FILE:
                            tar.add(child, arcname=child.name, filter=keep)
                payload = json.dumps(profile, ensure_ascii=False).encode("utf-8")
                info = tarfile.TarInfo(METADATA_FILE)
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            _run(CRANE_PATH, "append", "-f", str(archive), "-t", _tag(pid))
        _sync_status[pid] = "synced"
        _published.add(pid)
        _sync_errors.pop(pid, None)
        log.info("Profile registry sync complete: %s", pid)
    except Exception as exc:
        _sync_status[pid] = "failed"
        _sync_errors[pid] = str(exc)
        log.error("Profile registry sync failed for %s: %s", pid, exc)
        raise


def delete_profile(profile_id: str) -> None:
    if registry_enabled() and profile_id in _published:
        _run(CRANE_PATH, "delete", _tag(profile_id))
    _published.discard(profile_id)
    _sync_status.pop(profile_id, None)
    _sync_errors.pop(profile_id, None)


def proxy_config(chain: list[dict], port: int) -> dict:
    proxies = copy.deepcopy(chain)
    for i, proxy in enumerate(proxies):
        proxy["name"] = f"hop-{i}"
        proxy.pop("dialer-proxy", None)
        if i:
            proxy["dialer-proxy"] = f"hop-{i - 1}"
    return {"mixed-port": port, "bind-address": "127.0.0.1", "allow-lan": False,
            "mode": "rule", "proxies": proxies,
            "rules": [f"MATCH,hop-{len(proxies) - 1}" if proxies else "MATCH,DIRECT"]}


def chain_version(chain: list[dict]) -> str:
    return hashlib.sha256(json.dumps(chain, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def proxy_status(profile_id: str) -> dict:
    proc = _processes.get(profile_id)
    ready = proc is not None and proc.poll() is None
    return {"ready": ready, "applied_version": _proxy_versions.get(profile_id) if ready else None}


def proxy_port(profile_id: str) -> int | None:
    return _proxy_ports.get(profile_id)


def start_proxy(profile: dict[str, Any], *, port: int | None = None, prepared: Path | None = None, allow_direct: bool = False) -> str | None:
    chain = profile.get("proxy_chain") or []
    if not (ENABLED and (chain or allow_direct)):
        return None
    if port is None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
    _proxy_ports[profile["id"]] = port
    directory = prepared or prepare_proxy(chain, port)
    _proxy_dirs[profile["id"]] = directory
    config = directory / "config.yaml"
    log_path = directory / "mihomo.log"
    try:
        with log_path.open("wb") as output:
            proc = subprocess.Popen([MIHOMO_PATH, "-d", str(directory), "-f", str(config)], stdout=output, stderr=subprocess.STDOUT)
        _processes[profile["id"]] = proc
        until = time.monotonic() + 10
        while time.monotonic() < until:
            if proc.poll() is not None:
                raise RuntimeError("mihomo exited: " + log_path.read_text(encoding="utf-8"))
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    _proxy_versions[profile["id"]] = chain_version(chain)
                    return f"http://127.0.0.1:{port}"
            except OSError:
                time.sleep(.05)
        raise RuntimeError("mihomo listener did not become ready")
    except BaseException:
        stop_proxy(profile["id"], preserve_port=True)
        raise


def prepare_proxy(chain: list[dict], port: int) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="manager-mihomo-"))
    config = directory / "config.yaml"
    try:
        config.write_text(json.dumps(proxy_config(chain, port)), encoding="utf-8")
        _run(MIHOMO_PATH, "-t", "-d", str(directory), "-f", str(config))
        return directory
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def replace_proxy(profile: dict[str, Any], prepared: Path) -> None:
    profile_id = profile["id"]
    port = _proxy_ports[profile_id]
    try:
        stop_proxy(profile_id, preserve_port=True)
        start_proxy(profile, port=port, prepared=prepared)
    finally:
        if _proxy_dirs.get(profile_id) != prepared:
            shutil.rmtree(prepared, ignore_errors=True)


def stop_proxy(profile_id: str, *, preserve_port: bool = False) -> None:
    proc = _processes.get(profile_id)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    _processes.pop(profile_id, None)
    _proxy_versions.pop(profile_id, None)
    if not preserve_port:
        _proxy_ports.pop(profile_id, None)
    directory = _proxy_dirs.pop(profile_id, None)
    if directory:
        shutil.rmtree(directory, ignore_errors=True)


async def push_profile_async(profile: dict[str, Any]) -> None:
    await asyncio.to_thread(push_profile, profile)


class ProxyProbeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def probe_proxy(profile: dict, chain: list[dict], url: str, connect_timeout: float,
                timeout: float, *, running: bool) -> dict:
    """Probe only through this Profile's Mihomo; never persist a diagnostic chain."""
    if not ENABLED:
        raise ProxyProbeError("PROXY_PROBE_UNAVAILABLE", "Remote proxy runtime is disabled")
    profile_id = profile["id"]
    version = chain_version(chain)
    temporary = not running
    if running and (proxy_status(profile_id) != {"ready": True, "applied_version": version}
                    or proxy_port(profile_id) is None):
        raise ProxyProbeError("PROXY_PROBE_CHAIN_CHANGED", "Running Profile proxy does not match the requested chain")
    try:
        if temporary:
            start_proxy({**profile, "proxy_chain": chain}, allow_direct=True)
        proc = _processes.get(profile_id)
        port = proxy_port(profile_id)
        if proc is None or proc.poll() is not None or port is None:
            raise ProxyProbeError("PROXY_PROBE_UNAVAILABLE", "Profile Mihomo is not ready")
        source = {"profileId": profile_id, "pid": proc.pid, "port": port,
                  "temporary": temporary, "chainVersion": version}
        log.info("Profile proxy probe start profile=%s mihomo_pid=%s port=%s temporary=%s chain_version=%s",
                 profile_id, proc.pid, port, temporary, version)
        result = subprocess.run(
            ["curl.exe" if os.name == "nt" else "curl", "--silent", "--show-error",
             "--noproxy", "", "--proxy", f"http://127.0.0.1:{port}",
             "--proto", "=http,https", "--connect-timeout", str(connect_timeout),
             "--max-time", str(timeout), "--write-out", "\n%{http_code}", "--url", url],
            check=True, capture_output=True, encoding="utf-8", timeout=timeout + 5,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        body, separator, status = result.stdout.rpartition("\n")
        if not separator or not status.isdigit() or not 100 <= int(status) <= 599:
            raise RuntimeError("Probe response has no HTTP status")
        log.info("Profile proxy probe complete profile=%s mihomo_pid=%s port=%s temporary=%s http_status=%s",
                 profile_id, proc.pid, port, temporary, status)
        return {"httpStatus": int(status), "body": body, "source": source}
    except ProxyProbeError:
        raise
    except Exception as exc:
        log.warning("Profile proxy probe failed profile=%s temporary=%s: %s", profile_id, temporary, exc)
        raise ProxyProbeError("PROXY_VERIFY_REQUEST_FAILED", "Profile Mihomo probe request failed") from exc
    finally:
        if temporary:
            stop_proxy(profile_id)
