#!/usr/bin/env python3
"""Attended, reversible external bind-storage cutover; no automatic expiry."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time

STATE_DIR = Path('/var/lib/host-storage-migrate')
CONFIG = Path('/etc/host-storage-migrate.json')
DAEMON = Path('/etc/docker/daemon.json')
SYSTEMD = Path('/etc/systemd/system')
BACKUPS = {'/opt/backups', '/var/backups/security-trust-remediation'}
SUPPORTED = BACKUPS | {'/var/lib/docker', '/var/lib/containerd'}
ENGINES = ['containerd.service', 'docker.socket', 'docker.service']
TIMER = 'docker-cache-cleanup.timer'


def run(args: list[str], *, timeout: int = 3600, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, env=env)
    if result.returncode:
        # Do not copy arbitrary daemon/rsync stderr into shared operator logs.
        if STATE_DIR.exists():
            try:
                write(STATE_DIR / f'command-failure-{time.time_ns()}.log',
                      result.stdout + result.stderr)
            except OSError:
                pass
        raise RuntimeError(f'{args[0]} {args[1] if len(args) > 1 else ""} failed ({result.returncode})')
    return result.stdout


def write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.host-storage-new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate(config: dict) -> None:
    for key in ('mount', 'root'):
        value = config[key]
        if not re.fullmatch(r'/[A-Za-z0-9_/-]+', value) or str(Path(value)) != value:
            raise ValueError(f'invalid {key}')
        if any(part == '..' for part in Path(value).parts):
            raise ValueError('parent traversal')
    mount, root = Path(config['mount']), Path(config['root'])
    if mount == Path('/') or root == mount or not root.is_relative_to(mount):
        raise ValueError('storage root must be a child of the external mount')
    sources = config['sources']
    if not isinstance(sources, list) or len(set(sources)) != len(sources):
        raise ValueError('duplicate/invalid sources')
    if not {'/var/lib/docker', '/var/lib/containerd'} <= set(sources) <= SUPPORTED:
        raise ValueError('Docker and containerd must migrate together; unsupported source')
    if not isinstance(config['cache_bytes'], int) or isinstance(config['cache_bytes'], bool) or config['cache_bytes'] < 1:
        raise ValueError('invalid cache byte target')
    if not re.fullmatch(r'[A-Za-z0-9-]+', config['uuid']):
        raise ValueError('invalid filesystem UUID')
    health_timeout = config.get('health_timeout', 300)
    if not isinstance(health_timeout, int) or isinstance(health_timeout, bool) or not 1 <= health_timeout <= 3600:
        raise ValueError('invalid health timeout')


def external(config: dict) -> None:
    result = json.loads(run(['findmnt', '--json', '--mountpoint', config['mount'],
                             '--output', 'TARGET,UUID,FSTYPE,OPTIONS']))
    rows = result.get('filesystems', [])
    if len(rows) != 1 or rows[0]['target'] != config['mount'] or rows[0]['uuid'] != config['uuid']:
        raise RuntimeError('expected external filesystem is not mounted')
    if 'rw' not in rows[0]['options'].split(','):
        raise RuntimeError('external filesystem is read-only')
    for path in [Path(config['mount']), Path(config['root'])]:
        if path.resolve() != path:
            raise RuntimeError('symlink in external storage path')


def identity(path: Path) -> list[int]:
    data = path.lstat()
    if not stat.S_ISDIR(data.st_mode) or path.resolve() != path:
        raise RuntimeError(f'expected ordinary directory: {path}')
    return [data.st_dev, data.st_ino]


def mounted_below(path: Path, include_self: bool = True) -> bool:
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        target = Path(line.split()[4].replace('\\040', ' ').replace('\\134', '\\'))
        if (include_self and target == path) or (target != path and target.is_relative_to(path)):
            return True
    return False


def closure(active: dict[str, dict[str, list[str]]], initial: set[str]) -> list[str]:
    affected = set(initial)
    while True:
        extra = {name for name, properties in active.items()
                 if any(affected.intersection(properties.get(key, []))
                        for key in ('Requires', 'BindsTo', 'PartOf', 'Wants', 'After'))}
        if extra <= affected:
            return sorted(affected.intersection(active))
        affected.update(extra)


def active_units() -> dict[str, dict[str, list[str]]]:
    output = run(['systemctl', 'list-units', '--type=service,socket,timer', '--state=active',
                  '--no-legend', '--plain'])
    names = [line.split()[0] for line in output.splitlines()]
    details = run(['systemctl', 'show', *names, '--property=Id,Requires,BindsTo,PartOf,Wants,After'])
    units = {}
    for block in details.strip().split('\n\n'):
        properties = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if properties.get('Id'):
            units[properties['Id']] = {k: v.split() for k, v in properties.items()}
    return units


def containers() -> dict:
    identifiers = run(['docker', 'ps', '-q']).split()
    if not identifiers:
        return {}
    inspected = json.loads(run(['docker', 'inspect', *identifiers]))
    return {item['Name'].lstrip('/'): {
        'image': item['Image'], 'health': item['State'].get('Health', {}).get('Status'),
    } for item in inspected}


def check_containers(baseline: dict, current: dict) -> None:
    if set(baseline) != set(current):
        raise RuntimeError('running container names differ from baseline')
    for name, before in baseline.items():
        now = current[name]
        if now['image'] != before['image']:
            raise RuntimeError(f'container image changed: {name}')
        if before['health'] == 'healthy' and now['health'] != 'healthy':
            raise RuntimeError(f'container not yet healthy: {name}')


def service_groups(units: list[str], *, starting: bool) -> list[list[str]]:
    """Compose ExecStop needs both engines alive; systemctl multi-unit is not atomic."""
    consumers = [unit for unit in units if unit not in ENGINES]
    docker = [unit for unit in ['docker.socket', 'docker.service'] if unit in units]
    backend = ['containerd.service'] if 'containerd.service' in units else []
    groups = [backend, docker, consumers] if starting else [consumers, docker, backend]
    return [group for group in groups if group]


def daemon_config(original: dict, cache_bytes: int) -> dict:
    result = json.loads(json.dumps(original))
    result.setdefault('builder', {})['gc'] = {
        'enabled': True,
        'policy': [{'all': True, 'reservedSpace': '0B', 'maxUsedSpace': str(cache_bytes)}],
    }
    return result


class Migration:
    def __init__(self, config: dict):
        validate(config)
        self.config = config
        self.root = Path(config['root'])
        self.sources = [Path(x) for x in config['sources']]
        self.path = STATE_DIR / 'state.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        if self.state:
            # An operator may extend health waiting during forward recovery;
            # storage identity, source list, guards and GC policy remain frozen.
            before = {k: v for k, v in self.state['config'].items() if k != 'health_timeout'}
            after = {k: v for k, v in config.items() if k != 'health_timeout'}
            if before != after:
                raise RuntimeError('configuration differs from existing migration state')
            self.state['config']['health_timeout'] = config.get('health_timeout', 300)

    def save(self) -> None:
        write(self.path, json.dumps(self.state, indent=2) + '\n')

    def target(self, source: Path) -> Path:
        return self.root / source.relative_to('/')

    @staticmethod
    def previous(source: Path) -> Path:
        return source.with_name(source.name + '.host-storage-previous')

    def copy(self, *, verify: bool = False) -> None:
        external(self.config)
        for source in self.sources:
            target = self.target(source)
            if target.exists() and target.resolve() != target:
                raise RuntimeError('symlink in copy destination')
        command = ['rsync', '-aHAXxR', '--numeric-ids', '--delete']
        if verify:
            command += ['--checksum', '--dry-run', '--itemize-changes']
        result = run(command + ['--', *[str(x) for x in self.sources], str(self.root) + '/'])
        if verify and result.strip():
            raise RuntimeError('offline checksum/metadata comparison differs')

    def unit_files(self) -> dict[Path, str]:
        external_unit = run(['systemd-escape', '--path', '--suffix=mount', self.config['mount']]).strip()
        files = {}
        names = {}
        for source in self.sources:
            name = run(['systemd-escape', '--path', '--suffix=mount', str(source)]).strip()
            names[str(source)] = name
            files[SYSTEMD / name] = (
                '[Unit]\nDescription=External bulk storage\n'
                f'RequiresMountsFor={self.config["mount"]}\n'
                f'BindsTo={external_unit}\nAfter={external_unit}\n'
                f'\n[Mount]\nWhat={self.target(source)}\nWhere={source}\nType=none\nOptions=bind\n'
                '\n[Install]\nWantedBy=local-fs.target\n')
            if str(source) in BACKUPS:
                # Keep autofs present even if the external bind mount stops:
                # root-run backup jobs then fail rather than write underneath.
                files[SYSTEMD / (name.removesuffix('.mount') + '.automount')] = (
                    '[Unit]\nDescription=Guard external backup storage access\n'
                    f'\n[Automount]\nWhere={source}\nTimeoutIdleSec=0\n'
                    '\n[Install]\nWantedBy=local-fs.target\n')
        for service, paths in [('docker.service', ['/var/lib/docker', '/var/lib/containerd']),
                               ('containerd.service', ['/var/lib/containerd'])]:
            units = ' '.join(names[x] for x in paths)
            files[SYSTEMD / f'{service}.d/90-host-storage.conf'] = (
                f'[Unit]\nRequires={units}\nAfter={units}\nBindsTo={units}\n')
        return files

    def verify_units(self) -> None:
        """Validate online, including fstab-generated mounts in the lookup path."""
        stage = STATE_DIR / 'unit-preflight'
        stage.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name, content in self.state['files'].items():
            write(stage / Path(name).relative_to(SYSTEMD), content, 0o644)
        paths = run(['systemd-analyze', 'unit-paths']).splitlines()
        environment = {**os.environ, 'SYSTEMD_UNIT_PATH': ':'.join([str(stage), *paths])}
        units = [str(stage / unit) for unit in self.mount_units() + self.automount_units()]
        run(['systemd-analyze', 'verify', *units, 'docker.service', 'containerd.service'],
            env=environment, timeout=120)

    def prepare(self) -> None:
        external(self.config)
        if self.state:
            if (self.state['phase'] not in ('preparing', 'rolled_back')
                    or self.state.get('external_exposed')
                    or self.state.get('root_identity') != identity(self.root)):
                raise RuntimeError('migration already prepared or destination identity changed; inspect state')
            for source in self.sources:
                if identity(source) != self.state['sources'][str(source)] or self.previous(source).exists():
                    raise RuntimeError('source identity changed during failed prepare')
            if self.state['phase'] == 'rolled_back':
                if any(Path(x).exists() for x in self.state['files']):
                    raise RuntimeError('rollback left installed storage units')
                if (DAEMON.read_text() if DAEMON.exists() else None) != self.state['daemon']:
                    raise RuntimeError('daemon configuration was not restored')
                receipt = STATE_DIR / f'state-before-reprepare-{time.time_ns()}.json'
                write(receipt, json.dumps(self.state, indent=2) + '\n')
                self.state.update(phase='preparing', installed=[], renamed=[], enabled=[])
                self.save()
            self.copy()
            self.verify_units()
            self.state['phase'] = 'prepared'
            self.save()
            print('Interrupted warm copy resumed; no services stopped.', flush=True)
            return
        if self.root.exists():
            raise RuntimeError('refusing to adopt an existing destination tree')
        sources = {}
        for source in self.sources:
            if mounted_below(source, include_self=True) and source != Path('/var/lib/docker'):
                raise RuntimeError(f'source already contains mounts: {source}')
            if self.previous(source).exists() or self.previous(source).is_symlink():
                raise RuntimeError('previous-source path already exists')
            sources[str(source)] = identity(source)
        files = self.unit_files()
        if any(path.exists() or path.is_symlink() for path in files):
            raise RuntimeError('storage units/drop-ins already exist')
        daemon = DAEMON
        if daemon.is_symlink():
            raise RuntimeError('daemon configuration must not be a symlink')
        original = daemon.read_text() if daemon.exists() else None
        metadata = ([stat.S_IMODE(daemon.stat().st_mode), daemon.stat().st_uid, daemon.stat().st_gid]
                    if daemon.exists() else None)
        candidate = daemon_config(json.loads(original) if original else {}, self.config['cache_bytes'])
        self.state = {'phase': 'preparing', 'config': self.config, 'sources': sources,
                      'files': {str(k): v for k, v in files.items()}, 'daemon': original,
                      'daemon_metadata': metadata, 'renamed': [], 'installed': [], 'enabled': []}
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        candidate_path = STATE_DIR / 'daemon.candidate.json'
        write(candidate_path, json.dumps(candidate, indent=2) + '\n')
        run(['dockerd', '--validate', '--config-file', str(candidate_path)])
        self.root.mkdir(mode=0o700)
        self.state['root_identity'] = identity(self.root)
        self.save()
        self.copy()
        self.verify_units()
        self.state['phase'] = 'prepared'
        self.save()
        print('Warm copy prepared; no services stopped.', flush=True)

    def mount_units(self) -> list[str]:
        return [Path(x).name for x in self.state['files'] if x.endswith('.mount')]

    def automount_units(self) -> list[str]:
        return [Path(x).name for x in self.state['files'] if x.endswith('.automount')]

    def mount_checks(self) -> None:
        external(self.config)
        for source in self.sources:
            if not os.path.ismount(source):
                raise RuntimeError(f'missing bind mount: {source}')
            if identity(source) != identity(self.target(source)):
                raise RuntimeError(f'wrong bind source: {source}')

    def restore_services(self) -> None:
        units = self.state['units']
        for group in service_groups(units, starting=True):
            run(['systemctl', 'start', *group], timeout=300)
        deadline = time.monotonic() + self.config.get('health_timeout', 300)
        while True:
            try:
                active = active_units()
                if not set(units) <= set(active):
                    raise RuntimeError('some previously active services did not return')
                check_containers(self.state['containers'], containers())
                return
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(3)

    def cutover(self) -> None:
        if self.state.get('phase') != 'prepared':
            raise RuntimeError('cutover requires a completed prepare')
        external(self.config)
        for guard in self.config.get('busy_sqlite', []):
            database = Path(guard['path'])
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5) as connection:
                if connection.execute(guard['query']).fetchone()[0]:
                    raise RuntimeError('backup/deployment activity is in progress; cutover refused')
        for source in self.sources:
            if identity(source) != self.state['sources'][str(source)] or self.previous(source).exists():
                raise RuntimeError('source identity changed since prepare')
        if any(Path(x).exists() or Path(x).is_symlink() for x in self.state['files']):
            raise RuntimeError('unit files appeared after prepare')
        daemon = DAEMON
        if daemon.is_symlink() or (daemon.read_text() if daemon.exists() else None) != self.state['daemon']:
            raise RuntimeError('daemon configuration changed after prepare')
        candidate = STATE_DIR / 'daemon.candidate.json'
        expected = daemon_config(json.loads(self.state['daemon']) if self.state['daemon'] else {},
                                 self.config['cache_bytes'])
        if json.loads(candidate.read_text()) != expected:
            raise RuntimeError('validated daemon candidate changed after prepare')
        run(['dockerd', '--validate', '--config-file', str(candidate)])
        self.verify_units()
        units = active_units()
        self.state['units'] = closure(units, set(ENGINES + [TIMER]))
        self.state['containers'] = containers()
        self.state['phase'] = 'stopping'
        self.save()
        try:
            print('Stopping recorded Docker dependencies and engines.', flush=True)
            for group in service_groups(self.state['units'], starting=False):
                run(['systemctl', 'stop', *group], timeout=300)
            if set(ENGINES).intersection(active_units()):
                raise RuntimeError('Docker engines or socket still active')
            if any(mounted_below(source) for source in self.sources):
                raise RuntimeError('source still has active mounts after stopping')
            print('Final copy and offline checksum verification.', flush=True)
            self.copy()
            self.copy(verify=True)
            run(['sync', '-f', str(self.root)])
            self.state['phase'] = 'copy_verified'
            self.save()
            for name, content in self.state['files'].items():
                # Record intent before mutation so interruption remains diagnosable.
                self.state['installed'].append(name)
                self.save()
                write(Path(name), content, 0o644)
            run(['systemctl', 'daemon-reload'])
            self.verify_units()
            for source in self.sources:
                self.state['renamed'].append(str(source))
                self.save()
                source.rename(self.previous(source))
                source.mkdir(mode=0o000)
            self.activate()
        except BaseException:
            if self.state.get('external_exposed'):
                # Background jobs or restarted applications may already have
                # written new data. Never roll back to a stale root snapshot.
                self.state['phase'] = 'needs_attention'
                self.save()
                print('External storage retained: repair forward with recover; no stale-data rollback.', flush=True)
            else:
                print('Cutover failed before external access; restoring original storage and services.', flush=True)
                self.rollback()
            raise

    def activate(self) -> None:
        external(self.config)
        self.state['external_exposed'] = True
        self.state['phase'] = 'activating'
        self.save()
        if self.automount_units():
            run(['systemctl', 'start', *self.automount_units()])
        run(['systemctl', 'start', *self.mount_units()])
        self.mount_checks()
        DAEMON.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        write(DAEMON, (STATE_DIR / 'daemon.candidate.json').read_text(), 0o644)
        for unit in self.mount_units() + self.automount_units():
            if unit.removesuffix('.mount') + '.automount' in self.automount_units():
                continue  # autofs owns boot-time backup mount activation
            if unit not in self.state['enabled']:
                self.state['enabled'].append(unit)
                self.save()
            run(['systemctl', 'enable', unit])
        self.restore_services()
        self.state['phase'] = 'verified'
        self.save()
        print('External mounts and prior service/container state verified; old copies retained.', flush=True)

    def recover(self) -> None:
        if self.state.get('phase') not in ('needs_attention', 'activating', 'stopping', 'copy_verified', 'rolling_back', 'rollback_failed'):
            raise RuntimeError('no interrupted cutover to recover')
        if not self.state.get('external_exposed'):
            self.rollback()
            return
        for name, content in self.state['files'].items():
            if Path(name).read_text() != content:
                raise RuntimeError('storage unit changed; operator reconciliation required')
        self.activate()

    def rollback(self) -> None:
        if self.state.get('external_exposed'):
            raise RuntimeError('external storage may contain new writes; rollback refused')
        self.state['phase'] = 'rolling_back'
        self.save()
        errors = []

        def attempt(action) -> bool:
            try:
                action()
                return True
            except Exception as error:
                errors.append(str(error))
                return False

        # Before any source rename there is no filesystem mutation to undo:
        # restore activity directly, instead of repeating a failed stop.
        if self.state['renamed']:
            for group in service_groups(self.state['units'], starting=False):
                attempt(lambda group=group: run(['systemctl', 'stop', *group], timeout=300))
        attempt(lambda: run(['systemctl', 'daemon-reload']))
        for unit in [*reversed(self.mount_units()), *reversed(self.automount_units())]:
            # Before files are installed these units do not exist. A failure
            # during the initial stop/copy must still restart original services.
            if str(SYSTEMD / unit) in self.state['installed'] and (SYSTEMD / unit).exists():
                attempt(lambda unit=unit: run(['systemctl', 'stop', unit]))
        files_ok = True
        for source_name in reversed(self.state['renamed']):
            source = Path(source_name)
            old = self.previous(source)
            def restore_source(source=source, old=old):
                if old.exists():
                    if identity(old) != self.state['sources'][str(source)] or mounted_below(source):
                        raise RuntimeError('unsafe rollback source identity/mount')
                    if source.exists():
                        source.rmdir()
                    old.rename(source)
                if identity(source) != self.state['sources'][str(source)]:
                    raise RuntimeError('original source was not restored')
            files_ok = attempt(restore_source) and files_ok

        def restore_daemon():
            if self.state['daemon'] is None:
                DAEMON.unlink(missing_ok=True)
            else:
                mode, uid, gid = self.state['daemon_metadata']
                write(DAEMON, self.state['daemon'], mode)
                os.chown(DAEMON, uid, gid)
        files_ok = attempt(restore_daemon) and files_ok
        for unit in self.state['enabled']:
            attempt(lambda unit=unit: run(['systemctl', 'disable', unit]))
        for name in self.state['installed']:
            attempt(lambda name=name: Path(name).unlink(missing_ok=True))
        reload_ok = attempt(lambda: run(['systemctl', 'daemon-reload']))
        if files_ok and reload_ok:
            attempt(self.restore_services)
        self.state['phase'] = 'rollback_failed' if errors else 'rolled_back'
        self.state['rollback_errors'] = errors
        self.save()
        if errors:
            raise RuntimeError('rollback needs attention: ' + '; '.join(errors))
        print('Original storage and services restored. Retained external copy needs operator review.', flush=True)

    def verify(self) -> None:
        if self.state.get('phase') not in ('verified', 'finalizing', 'finalized'):
            raise RuntimeError('migration is not verified')
        self.mount_checks()
        if not set(self.state['units']) <= set(active_units()):
            raise RuntimeError('a previously active service is stopped')
        check_containers(self.state['containers'], containers())
        print('Mount identities, prior units and container images/health verified.', flush=True)

    def finalize(self) -> None:
        self.verify()
        if self.state['phase'] == 'finalized':
            print('Already finalized.', flush=True)
            return
        for source in self.sources:
            old = self.previous(source)
            if old.exists() and (identity(old) != self.state['sources'][str(source)] or mounted_below(old)):
                raise RuntimeError('old source identity changed or contains mounts')
        self.state['phase'] = 'finalizing'
        self.save()
        for source in self.sources:
            old = self.previous(source)
            if old.exists():
                print(f'Removing verified old root copy: {old}', flush=True)
                shutil.rmtree(old)
        self.state['phase'] = 'finalized'
        self.save()
        print('Old root copies removed; external data retained.', flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'cutover', 'recover', 'verify', 'finalize'])
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('root required')
    with open('/run/lock/host-storage-migrate.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        migration = Migration(json.loads(CONFIG.read_text()))
        getattr(migration, arguments.action)()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Migration stopped: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
