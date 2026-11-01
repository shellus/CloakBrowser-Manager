"""Preserve BAM's native Windows launch contract without wrapper defaults."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

IMPORT_MANIFEST = "bam-import.json"


def fingerprint_seed(profile_id: str) -> int:
    return int.from_bytes(hashlib.sha256(f"bam-profile:{profile_id}".encode()).digest()[:4], "big") & 0x7fffffff


def assert_stopped(directory: Path) -> None:
    """Match the exact user-data-dir, including processes started outside BAM."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
         "@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { "
         "$_.Name -match '^(chrome|chromium|cloakbrowser).*\\.exe$' } | "
         "Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"],
        check=True, capture_output=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
    )
    from ctypes import POINTER, byref, c_int, c_wchar_p, windll
    windll.shell32.CommandLineToArgvW.restype = POINTER(c_wchar_p)
    processes = json.loads(result.stdout or "[]")
    if isinstance(processes, dict):
        processes = [processes]
    expected = os.path.normcase(str(directory.resolve()))
    for process in processes:
        command = process.get("CommandLine")
        if not command:
            continue
        count = c_int()
        argv = windll.shell32.CommandLineToArgvW(command, byref(count))
        try:
            args = [argv[i] for i in range(count.value)]
        finally:
            windll.kernel32.LocalFree(argv)
        for i, arg in enumerate(args):
            value = arg.split("=", 1)[1] if arg.startswith("--user-data-dir=") else (
                args[i + 1] if arg == "--user-data-dir" and i + 1 < len(args) else None)
            if value and os.path.normcase(str(Path(value).resolve())) == expected:
                raise RuntimeError(f"Profile is running (PID {process['ProcessId']}): {directory}")


def launch_arguments(profile: dict[str, Any], manifest: dict, port: int, extensions: list[str]) -> list[str]:
    source = manifest["profile"]
    return [
        f"--worker-id={source['id']}", f"--user-data-dir={profile['user_data_dir']}",
        f"--remote-debugging-port={port}", f"--window-name={profile['name']} #{source['id']}",
        "--no-first-run", "--no-default-browser-check", "--disable-backgrounding-occluded-windows",
        f"--fingerprint={profile['fingerprint_seed']}", "--fingerprint-platform=windows",
        f"--lang={profile['locale']}", f"--fingerprint-locale={profile['locale']}",
        f"--fingerprint-timezone={profile['timezone']}",
        *([f"--proxy-server={profile['proxy']}"] if profile.get("proxy") else []),
        *([f"--load-extension={','.join(extensions)}"] if extensions else []),
    ]


class NativeContext:
    """Manager context facade; closing an attached context must close Chromium."""

    def __init__(self, context, browser, playwright, process):
        self.context, self.browser, self.playwright, self.process = context, browser, playwright, process
        self._closing = False

    def __getattr__(self, name):
        return getattr(self.context, name)

    async def close(self):
        if self._closing:
            return
        self._closing = True
        try:
            if self.process.poll() is None:
                session = await self.browser.new_browser_cdp_session()
                await session.send("Browser.close")
            await asyncio.to_thread(self.process.wait, 20)
        finally:
            await self.playwright.stop()


async def launch(profile: dict[str, Any], port: int) -> NativeContext:
    if os.name != "nt":
        raise RuntimeError("BAM Windows profiles require a Windows host")
    from playwright.async_api import async_playwright

    directory = Path(profile["user_data_dir"])
    manifest = json.loads((directory / IMPORT_MANIFEST).read_text(encoding="utf-8"))
    await asyncio.to_thread(assert_stopped, Path(manifest["source_directory"]))
    await asyncio.to_thread(assert_stopped, directory)
    runtime = Path(manifest["runtime_directory"])
    executable = runtime / manifest["browser_executable"]
    actual_hash = await asyncio.to_thread(lambda: hashlib.sha256(executable.read_bytes()).hexdigest())
    if actual_hash != manifest["browser_sha256"]:
        raise RuntimeError("Imported BAM browser changed; refusing fingerprint drift")
    extensions = manifest["extension_directories"]
    if any(not (Path(ext) / "manifest.json").is_file() for ext in extensions):
        raise RuntimeError("Imported BAM extension is missing")
    temp = directory.parent.parent / "temp"
    temp.mkdir(exist_ok=True)
    process = subprocess.Popen(
        [str(executable), *launch_arguments(profile, manifest, port, extensions)],
        env={**os.environ, "TEMP": str(temp), "TMP": str(temp)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    playwright = await async_playwright().start()
    try:
        # Wait for this exact process' endpoint. No automatic browser relaunch.
        import httpx
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError(f"BAM browser exited: {process.returncode}")
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/json/version", timeout=0.5)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("BAM browser CDP did not become ready")
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", no_defaults=True)
        return NativeContext(browser.contexts[0], browser, playwright, process)
    except BaseException:
        # Preserve a failed live process for diagnosis; never terminate it forcibly.
        await playwright.stop()
        raise
