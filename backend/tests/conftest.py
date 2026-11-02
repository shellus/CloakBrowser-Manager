"""Shared test fixtures for backend tests."""

from __future__ import annotations

import sys
import types
import tempfile
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Collection imports main.py, which otherwise loads the real source .env and
# native settings before tmp_db can run. Never read deployment configuration.
from backend import env_file

_test_data = tempfile.TemporaryDirectory(prefix="manager-tests-")
_test_environment = pytest.MonkeyPatch()
_test_environment.setattr(env_file, "load_env_file", lambda: None)
_test_environment.setenv("CLOAKBROWSER_MANAGER_DATA_DIR", _test_data.name)
_test_environment.setenv("AUTH_TOKEN", "")
_test_environment.setenv("CLOAKBROWSER_LICENSE_KEY", "")
_test_environment.setenv("REMOTE_ENVIRONMENT_ENABLED", "false")


def pytest_unconfigure(config):
    main = sys.modules.get("backend.main")
    for handler in getattr(main, "_LOG_HANDLERS", []):
        logging.getLogger().removeHandler(handler)
        handler.close()
    _test_environment.undo()
    _test_data.cleanup()

# ---------------------------------------------------------------------------
# Mock cloakbrowser BEFORE any backend module is imported.
# browser_manager.py does `from cloakbrowser import launch_persistent_context_async`
# at module level, and main.py imports BrowserManager which triggers it.
# main.py:381 also does `from cloakbrowser.config import CHROMIUM_VERSION`.
# ---------------------------------------------------------------------------

_mock_cloakbrowser = types.ModuleType("cloakbrowser")
_mock_cloakbrowser.launch_persistent_context_async = AsyncMock()  # type: ignore[attr-defined]

_mock_config = types.ModuleType("cloakbrowser.config")
_mock_config.CHROMIUM_VERSION = "0.0.0-test"  # type: ignore[attr-defined]
_mock_config.IGNORE_DEFAULT_ARGS = ["--enable-automation"]
_mock_config.get_chromium_version = lambda: "0.0.0-test"  # type: ignore[attr-defined]

# BrowserManager.resolve_binary_status() (run in the lifespan) imports these.
_mock_download = types.ModuleType("cloakbrowser.download")
_mock_download.ensure_binary = MagicMock()  # type: ignore[attr-defined]

_mock_license = types.ModuleType("cloakbrowser.license")
_mock_license.resolve_license_key = lambda key=None: key  # type: ignore[attr-defined]
_mock_license.validate_license = lambda key: None  # type: ignore[attr-defined]
_mock_license.get_pro_latest_version = lambda channel=None: None  # type: ignore[attr-defined]
# browser_manager.py surfaces license/seat denials — it imports these at module
# level, so the mock must expose them or collection fails with ImportError.
_mock_license.CloakBrowserLicenseError = type(  # type: ignore[attr-defined]
    "CloakBrowserLicenseError", (RuntimeError,), {}
)
_mock_license.license_error_for_code = lambda code: None  # type: ignore[attr-defined]
_mock_license.read_denial_file = lambda path: None  # type: ignore[attr-defined]

sys.modules.setdefault("cloakbrowser", _mock_cloakbrowser)
sys.modules.setdefault("cloakbrowser.config", _mock_config)
sys.modules.setdefault("cloakbrowser.download", _mock_download)
sys.modules.setdefault("cloakbrowser.license", _mock_license)


from backend import database as db  # noqa: E402
from backend.runtime import RuntimeConfig  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point database module at a temp directory and init schema."""
    db_file = tmp_path / "profiles.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    db.init_db()
    return tmp_path


@pytest.fixture()
def sample_profile(tmp_db: Path):
    """Create and return a sample profile dict."""
    return db.create_profile(name="Test Profile", fingerprint_seed=12345)


@pytest.fixture()
def app_client(tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with mocked DB and browser manager."""
    from backend import main

    # API tests exercise the existing Linux Docker contract on every host OS.
    monkeypatch.setattr(
        main.browser_mgr,
        "runtime",
        RuntimeConfig("linux", "docker", "vnc", tmp_db),
    )
    monkeypatch.setattr(main.browser_mgr.vnc, "enabled", True)

    # Patch lifespan-called methods to avoid host KasmVNC/process requirements.
    monkeypatch.setattr(main.browser_mgr.vnc, "validate_available", MagicMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())

    from starlette.testclient import TestClient

    with TestClient(main.app) as client:
        yield client
