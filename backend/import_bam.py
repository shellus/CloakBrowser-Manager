"""Copy a stopped BAM Windows profile into an independent Manager data store.

Run: python -m backend.import_bam --runtime-root ... --profile-id ... --data-dir ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from .bam_windows import IMPORT_MANIFEST, assert_stopped, fingerprint_seed


def digest(file: Path) -> str:
    result = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inventory(root: Path) -> dict[str, str]:
    result = {}
    for file in root.rglob('*'):
        if file.is_symlink() or getattr(file, 'is_junction', lambda: False)():
            raise ValueError(f'Linked profile entry: {file}')
        if file.is_file():
            result[file.relative_to(root).as_posix()] = digest(file)
    return result


def copy_verified(source: Path, destination: Path) -> dict[str, str]:
    before = inventory(source)
    shutil.copytree(source, destination)
    if inventory(source) != before or inventory(destination) != before:
        raise RuntimeError(f'Source changed or copy differs: {source}')
    return before


def import_profile(runtime_root: Path, profile_id: int, data_dir: Path, proxy: str | None = None) -> dict:
    if os.name != 'nt':
        raise RuntimeError('BAM Windows import must run on Windows under the original user')
    runtime_root, data_dir = runtime_root.resolve(), data_dir.resolve()
    if data_dir == runtime_root or data_dir.is_relative_to(runtime_root) or runtime_root.is_relative_to(data_dir):
        raise ValueError('Manager data and BAM Runtime Store must be separate')
    store = runtime_root / 'state' / 'profiles'
    document = json.loads((store / 'profiles.json').read_text(encoding='utf-8'))
    profile = next(p for p in document['profiles'] if p['id'] == profile_id)
    source = store / 'workers' / str(profile_id)
    assert_stopped(source)
    if not (source / 'Default' / 'Preferences').is_file():
        raise ValueError('Source is not an existing initialized profile')
    preferences = json.loads((source / 'Default' / 'Preferences').read_text(encoding='utf-8'))
    if preferences.get('profile', {}).get('exit_type') != 'Normal':
        raise ValueError('Source has not exited normally; import will not repair source data')

    # Import database only after selecting its independent data directory.
    os.environ['CLOAKBROWSER_MANAGER_DATA_DIR'] = str(data_dir)
    from . import database as db
    if db.DATA_DIR.resolve() != data_dir:
        raise RuntimeError('Database module already points at another data directory')
    db.init_db()
    for existing in db.list_profiles():
        marker = Path(existing['user_data_dir']) / IMPORT_MANIFEST
        if marker.exists() and json.loads(marker.read_text(encoding='utf-8'))['source_directory'] == str(source):
            raise ValueError(f'Already imported as {existing["id"]}; refusing duplicate identity')

    active = json.loads((runtime_root / 'active.json').read_text(encoding='utf-8'))
    package = runtime_root / 'packages' / active['activeRuntimeId']
    runtime_manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    pinned = data_dir / 'runtimes' / active['activeRuntimeId']
    pinned.parent.mkdir(parents=True, exist_ok=True)
    if not pinned.exists():
        staging = pinned.with_name(f'.{pinned.name}-{uuid.uuid4()}')
        copy_verified(package, staging)
        staging.rename(pinned)
    for entry in runtime_manifest['requiredFiles']:
        if digest(pinned / entry['path']) != entry['sha256']:
            raise ValueError(f'Pinned runtime differs: {entry["path"]}')

    # Pin extensions per import; later BAM updates cannot affect the copy.
    staged = data_dir / 'staging' / str(uuid.uuid4())
    staged.mkdir(parents=True)
    manager_profile = None
    try:
        copied_hashes = copy_verified(source, staged / 'profile')
        extension_roots = []
        extensions = runtime_root / 'extensions'
        if extensions.exists():
            for ext in sorted(extensions.iterdir()):
                if ext.is_dir() and (ext / 'manifest.json').is_file():
                    copy_verified(ext, staged / 'profile' / 'bam-extensions' / ext.name)
                    extension_roots.append(ext.name)
        assert_stopped(source)
        if inventory(source) != copied_hashes:
            raise RuntimeError('Source changed during import')
        environment = profile['environment']
        manager_profile = db.create_profile(
            name=profile['name'], fingerprint_seed=fingerprint_seed(str(profile_id)),
            launch_mode='bam-windows', proxy=proxy, locale=environment['locale'], timezone=environment['timezone'],
            geoip=False, set_google_default=False, restore_session=False, capture_preview=False,
        )
        target = Path(manager_profile['user_data_dir'])
        executable = pinned / runtime_manifest['browserExecutablePath']
        manifest = {
            'schema_version': 1, 'profile': profile, 'source_directory': str(source),
            'runtime_directory': str(pinned), 'browser_executable': runtime_manifest['browserExecutablePath'],
            'runtime_version': runtime_manifest['runtimeVersion'], 'browser_sha256': digest(executable),
            'extension_directories': [str(target / 'bam-extensions' / name) for name in extension_roots],
            'source_sha256': copied_hashes,
        }
        (staged / 'profile' / IMPORT_MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        target.parent.mkdir(parents=True, exist_ok=True)
        (staged / 'profile').rename(target)
        return manager_profile
    except BaseException:
        if manager_profile:
            db.delete_profile(manager_profile['id'])
        raise
    finally:
        shutil.rmtree(staged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--profile-id', type=int, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--proxy', help='Existing BAM account loopback proxy, until proxy_chain is configured')
    args = parser.parse_args()
    print(json.dumps(import_profile(args.runtime_root, args.profile_id, args.data_dir, args.proxy), ensure_ascii=False))


if __name__ == '__main__':
    main()
