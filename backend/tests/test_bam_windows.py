"""Regression coverage for copied identities and native browser ownership."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import database as db
from backend import import_bam
from backend.bam_windows import IMPORT_MANIFEST, NativeContext, fingerprint_seed, launch_arguments


@pytest.fixture
def bam_store(tmp_db, monkeypatch):
    root = tmp_db.parent / (tmp_db.name + '-bam')
    store = root / 'state' / 'profiles'
    source = store / 'workers' / '7'
    (source / 'Default').mkdir(parents=True)
    (source / 'Default' / 'Preferences').write_text(json.dumps({'profile': {'exit_type': 'Normal'}}))
    (source / 'Default' / 'Cookies').write_bytes(b'synthetic-encrypted-cookie')
    (source / 'Local State').write_bytes(b'synthetic-dpapi-key')
    profile = {'id': 7, 'name': '\u4fdd\u7559 identity', 'createdAt': '2026-01-01T00:00:00Z',
               'environment': {'locale': 'en-US', 'timezone': 'America/Chicago',
                               'latitude': '30.0', 'longitude': '-97.0'}}
    (store / 'profiles.json').write_text(json.dumps({'schemaVersion': 1, 'profiles': [profile]}))
    package = root / 'packages' / 'pinned'
    package.mkdir(parents=True)
    (package / 'chrome.exe').write_bytes(b'synthetic-browser')
    (package / 'manifest.json').write_text(json.dumps({
        'runtimeVersion': '1-test', 'browserExecutablePath': 'chrome.exe',
        'requiredFiles': [{'path': 'chrome.exe', 'sha256': import_bam.digest(package / 'chrome.exe')}],
    }))
    (root / 'active.json').write_text(json.dumps({'activeRuntimeId': 'pinned'}))
    ext = root / 'extensions' / 'blocker'
    ext.mkdir(parents=True)
    (ext / 'manifest.json').write_text('{"manifest_version":3}')
    monkeypatch.setattr(import_bam, 'assert_stopped', MagicMock())
    return root, source, profile


@pytest.mark.skipif(import_bam.os.name != 'nt', reason='Windows-only import')
def test_import_preserves_identity_and_never_writes_source(tmp_db, bam_store):
    root, source, metadata = bam_store
    before = import_bam.inventory(root)
    profile = import_bam.import_profile(root, 7, tmp_db, 'http://127.0.0.1:30001')
    target = Path(profile['user_data_dir'])
    manifest = json.loads((target / IMPORT_MANIFEST).read_text(encoding='utf-8'))
    assert profile['name'] == metadata['name']
    assert profile['launch_mode'] == 'bam-windows'
    assert profile['fingerprint_seed'] == fingerprint_seed('7')
    assert profile['geoip'] == profile['set_google_default'] == profile['restore_session'] == 0
    assert manifest['profile'] == metadata
    assert import_bam.inventory(root) == before
    assert (target / 'Default' / 'Cookies').read_bytes() == (source / 'Default' / 'Cookies').read_bytes()
    assert (target / 'Local State').read_bytes() == (source / 'Local State').read_bytes()
    assert all(Path(p).is_relative_to(target) for p in manifest['extension_directories'])
    with pytest.raises(ValueError, match='Already imported'):
        import_bam.import_profile(root, 7, tmp_db)
    assert len(db.list_profiles()) == 1


@pytest.mark.skipif(import_bam.os.name != 'nt', reason='Windows-only import')
def test_active_source_is_rejected_before_any_copy(tmp_db, bam_store, monkeypatch):
    root, _, _ = bam_store
    before = import_bam.inventory(root)
    monkeypatch.setattr(import_bam, 'assert_stopped', MagicMock(side_effect=RuntimeError('Profile is running')))
    with pytest.raises(RuntimeError, match='running'):
        import_bam.import_profile(root, 7, tmp_db)
    assert import_bam.inventory(root) == before
    assert db.list_profiles() == []


@pytest.mark.skipif(import_bam.os.name != 'nt', reason='Windows-only import')
def test_failed_copy_does_not_publish_database_identity(tmp_db, bam_store, monkeypatch):
    root, _, _ = bam_store
    original = import_bam.copy_verified
    def fail_profile(source, destination):
        if source.name == '7':
            raise RuntimeError('source changed')
        return original(source, destination)
    monkeypatch.setattr(import_bam, 'copy_verified', fail_profile)
    with pytest.raises(RuntimeError, match='source changed'):
        import_bam.import_profile(root, 7, tmp_db)
    assert db.list_profiles() == []
    assert not list((tmp_db / 'staging').iterdir())


def test_native_arguments_keep_seed_and_do_not_apply_manager_emulation():
    profile = {'name': 'Imported', 'user_data_dir': 'copy', 'fingerprint_seed': 123,
               'locale': 'en-US', 'timezone': 'America/Chicago', 'proxy': 'http://127.0.0.1:30001',
               'screen_width': 999, 'gpu_family': 'intel', 'launch_args': ['--headless']}
    args = launch_arguments(profile, {'profile': {'id': 7}}, 40001, ['blocker'])
    assert '--fingerprint=123' in args
    assert '--fingerprint-platform=windows' in args
    assert '--load-extension=blocker' in args
    assert '--proxy-server=http://127.0.0.1:30001' in args
    assert not any(arg.startswith(('--headless', '--fingerprint-gpu', '--window-size', '--restore-last-session', '--enable-automation')) for arg in args)


@pytest.mark.skipif(import_bam.os.name != 'nt', reason='Windows-only import')
@pytest.mark.parametrize('exit_type', ['SessionEnded', 'metadata-only', 'Crashed'])
def test_import_handles_unstarted_and_session_ended_profiles_without_repair(tmp_db, bam_store, exit_type):
    import shutil
    root, source, metadata = bam_store
    if exit_type == 'metadata-only':
        shutil.rmtree(source)
    else:
        (source / 'Default' / 'Preferences').write_text(json.dumps({'profile': {'exit_type': exit_type}}))
    before = import_bam.inventory(root)
    if exit_type == 'Crashed':
        with pytest.raises(ValueError, match='not exited normally'):
            import_bam.import_profile(root, 7, tmp_db)
        assert db.list_profiles() == []
    else:
        profile = import_bam.import_profile(root, 7, tmp_db)
        marker = json.loads((Path(profile['user_data_dir']) / IMPORT_MANIFEST).read_text(encoding='utf8'))
        assert marker['source_metadata_only'] == (exit_type == 'metadata-only')
        if exit_type == 'SessionEnded':
            assert (Path(profile['user_data_dir']) / 'Default' / 'Preferences').read_bytes() == (source / 'Default' / 'Preferences').read_bytes()
        else:
            assert not source.exists()
        assert profile['name'] == metadata['name']
    assert import_bam.inventory(root) == before


@pytest.mark.asyncio
async def test_close_attached_browser_uses_browser_close_and_waits_for_process():
    context, browser, playwright, process = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    session = MagicMock()
    session.send = AsyncMock()
    browser.new_browser_cdp_session = AsyncMock(return_value=session)
    playwright.stop = AsyncMock()
    process.poll.return_value = None
    native = NativeContext(context, browser, playwright, process)
    await native.close()
    session.send.assert_awaited_once_with('Browser.close')
    process.wait.assert_called_once_with(20)
    playwright.stop.assert_awaited_once()
    context.close.assert_not_called()


def test_launch_mode_survives_database_rebuild(tmp_db):
    profile = db.create_profile('Imported', launch_mode='bam-windows')
    with db.get_db() as conn:
        conn.execute('ALTER TABLE profiles ADD COLUMN retired TEXT')
        conn.commit()
    db.init_db()
    db.init_db()
    assert db.get_profile(profile['id'])['launch_mode'] == 'bam-windows'
    with db.get_db() as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
