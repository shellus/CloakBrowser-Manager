"""Optional remote-environment support.

All features are disabled unless REMOTE_ENVIRONMENT_ENABLED is true.  The
registry is deliberately command based so the same code works on Linux and
Windows when crane/mihomo paths are configured explicitly.
"""
from __future__ import annotations
import asyncio, json, logging, os, shutil, subprocess, tarfile, tempfile
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
HOST_OS = "windows" if os.name == "nt" else "linux"
_processes: dict[str, subprocess.Popen] = {}

def environment_info(version: str | None = None) -> dict[str, Any]:
    return {"host_os": HOST_OS, "storage": STORAGE if ENABLED else "local",
            "idle_stop_seconds": IDLE_SECONDS, "remote_view": HOST_OS == "linux",
            "version": version or "unknown"}

def _run(*args: str) -> None:
    subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def _tag(profile_id: str) -> str:
    return f"{REGISTRY.rstrip('/')}/{REGISTRY_PREFIX}:{profile_id}"

def restore_profile(profile: dict[str, Any]) -> None:
    if not (ENABLED and STORAGE == "registry" and REGISTRY): return
    target = Path(profile["user_data_dir"])
    if target.exists() and any(target.iterdir()): return
    target.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "profile.tar.gz"
            _run(CRANE_PATH, "export", _tag(profile["id"]), str(archive))
            with tarfile.open(archive, "r:gz") as tar: tar.extractall(target)
    except Exception as exc: log.warning("registry restore failed for %s: %s", profile["id"], exc)

def push_profile(profile: dict[str, Any]) -> None:
    if not (ENABLED and STORAGE == "registry" and REGISTRY): return
    target = Path(profile["user_data_dir"])
    if not target.exists(): return
    try:
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "profile.tar.gz"
            with tarfile.open(archive, "w:gz") as tar: tar.add(target, arcname=".")
            _run(CRANE_PATH, "append", "-f", str(archive), _tag(profile["id"]))
    except Exception as exc: log.warning("registry push failed for %s: %s", profile["id"], exc)

def start_proxy(profile: dict[str, Any]) -> str | None:
    chain = profile.get("proxy_chain") or []
    if not (ENABLED and chain): return None
    # mihomo relay groups provide the ordered chain.  The generated config is
    # per profile and removed with the profile process.
    port = 20000 + (abs(hash(profile["id"])) % 20000)
    config_dir = Path(profile["user_data_dir"]) / ".mihomo"
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"mixed-port": port, "allow-lan": False, "proxies": chain,
           "proxy-groups": [{"name": "PROFILE", "type": "select", "proxies": [p.get("name") for p in chain if p.get("name") and not p.get("dialer-proxy")]}],
           "rules": ["MATCH,PROFILE"]}
    path = config_dir / "config.yaml"
    # JSON is valid YAML and avoids a hard dependency on a YAML package.
    path.write_text(json.dumps(cfg), encoding="utf-8")
    try:
        _processes[profile["id"]] = subprocess.Popen([MIHOMO_PATH, "-d", str(config_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"http://127.0.0.1:{port}"
    except Exception as exc:
        log.warning("mihomo start failed for %s: %s", profile["id"], exc); return None

def stop_proxy(profile_id: str) -> None:
    proc = _processes.pop(profile_id, None)
    if proc:
        proc.terminate()
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: proc.kill()

async def push_profile_async(profile: dict[str, Any]) -> None:
    await asyncio.to_thread(push_profile, profile)
