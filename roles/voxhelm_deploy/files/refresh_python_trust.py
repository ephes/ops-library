#!/usr/bin/env python3
"""Bounded existing launchd Python cache refresh; output aggregate metadata only."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import platform
import plistlib
import pwd
import re
import signal
import sqlite3
import stat
import subprocess
import time

LABELS = {'de.wersdoerfer.voxhelm', 'de.wersdoerfer.voxhelm-worker',
          'de.wersdoerfer.voxhelm-wyoming-stt', 'de.wersdoerfer.voxhelm-remote-worker'}
TRUST_PROBE = r'''
import certifi, hashlib, importlib.metadata, json, re, ssl, urllib.request
version = importlib.metadata.version('certifi')
assert tuple(map(int, version.split('.'))) >= (2026, 10, 19), 'certifi is too old'
bundle = open(certifi.where()).read()
bad = {'d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4',
       '86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b'}
roots = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', bundle, re.S)
assert roots and not bad.intersection(hashlib.sha256(ssl.PEM_cert_to_DER_cert(x)).hexdigest() for x in roots)
if __import__('sys').argv[-1] == '--local-trust-only':
    print(json.dumps({'certifi': version, 'bundle_sha256': hashlib.sha256(bundle.encode()).hexdigest()}))
    raise SystemExit(0)
context = ssl.create_default_context(cafile=certifi.where())
# A verification failure is required: DNS/timeouts do not count as rejection.
for host in ['dv-g3b-emudhra.we-have-a-problem.com', 'dv-g3b-aaa-emudhra.we-have-a-problem.com']:
    import socket
    try:
        with socket.create_connection((host, 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                raise ValueError('compromised TLS chain accepted')
    except ssl.SSLCertVerificationError:
        pass
with urllib.request.urlopen('https://www.python.org/', context=context, timeout=10) as response:
    assert response.status == 200
print(json.dumps({'certifi': version, 'negative_chains': 2, 'positive_tls': True}))
'''


def command(argv, timeout=30, uid=None):
    options = {}
    if uid is not None:
        account = pwd.getpwuid(uid)
        options['env'] = {'HOME': account.pw_dir, 'USER': account.pw_name,
                          'LOGNAME': account.pw_name, 'PATH': '/usr/bin:/bin'}
        if os.getuid() == 0 and uid != 0:
            options.update(user=uid, group=account.pw_gid,
                           extra_groups=[])
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, **options)
    except subprocess.TimeoutExpired as error:
        raise ValueError('Required native command timed out: ' + Path(argv[0]).name) from error
    if result.returncode:
        reason = re.search(r'(?:^|\n)(?:\w+\.)?([A-Za-z]+(?:Error|Exception))(?::|$)', result.stderr)
        suffix = ' (' + reason.group(1) + ')' if reason else ''
        raise ValueError('Required native command failed: ' + Path(argv[0]).name + suffix)
    return result.stdout


def idle(database):
    if not Path(database).is_absolute():
        raise ValueError('Database path must be absolute')
    with closing(sqlite3.connect(Path(database).as_uri() + '?mode=ro', uri=True)) as db:
        counts = {
            'queued_or_running_jobs': db.execute("SELECT count(*) FROM jobs_job WHERE state IN ('queued','running')").fetchone()[0],
            'live_leases': db.execute("SELECT count(*) FROM jobs_job WHERE lease_expires_at IS NOT NULL AND julianday(lease_expires_at)>julianday('now')").fetchone()[0],
            'reported_worker_jobs': db.execute('SELECT coalesce(sum(json_array_length(running_job_ids)),0) FROM jobs_worker').fetchone()[0],
        }
    if any(counts.values()):
        raise ValueError('Voxhelm is not idle: ' + json.dumps(counts, sort_keys=True))
    return counts


def snapshot(label, environment):
    if label not in LABELS or not Path(environment).is_absolute():
        raise ValueError('Explicit known label and absolute environment required')
    path = Path('/Library/LaunchDaemons') / (label + '.plist')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Unsafe launchd plist ownership/type/mode')
    content = path.read_bytes()
    config = plistlib.loads(content)
    if config.get('Label') != label or config.get('KeepAlive') is not True:
        raise ValueError('Expected unchanged KeepAlive unit')
    uid = pwd.getpwnam(config.get('UserName', 'root')).pw_uid
    output = command(['/bin/launchctl', 'print', 'system/' + label])
    pid = re.search(r'^\s*pid = (\d+)\s*$', output, re.M)
    if not pid or not re.search(r'^\s*state = running\s*$', output, re.M):
        raise ValueError('Expected running managed unit')
    pid = int(pid.group(1))
    actual_uid, executable = command(['/bin/ps', '-p', str(pid), '-o', 'uid=,comm=']).strip().split(None, 1)
    if not Path(executable).is_absolute():
        executable = os.path.normpath(os.path.join(config.get('WorkingDirectory', '/'), executable))
    if executable == '/usr/bin/caffeinate' and label == 'de.wersdoerfer.voxhelm-remote-worker':
        children = []
        for row in command(['/bin/ps', '-axo', 'pid=,ppid=,uid=,comm=']).splitlines():
            child_pid, parent, child_uid, child_executable = row.strip().split(None, 3)
            if int(parent) == pid:
                children.append((int(child_pid), int(child_uid), child_executable))
        if len(children) != 1 or int(actual_uid) != uid:
            raise ValueError('Expected one owned caffeinate Python child')
        pid, actual_uid, executable = children[0]
    if int(actual_uid) != uid or not re.fullmatch(re.escape(environment.rstrip('/') + '/bin/python') + r'(?:3(?:\.\d+)?)?', executable):
        raise ValueError('Managed process owner or Python prefix differs')
    if os.getuid() not in (0, uid):
        raise ValueError('Only root or the existing child owner may refresh')
    return {'pid': pid, 'uid': uid, 'plist': content}


def refresh(label, environment, check=False, local_trust_only=False):
    before = snapshot(label, environment)
    trust = json.loads(command([str(Path(environment) / 'bin/python'), '-c', TRUST_PROBE] + (['--local-trust-only'] if local_trust_only else []), timeout=60, uid=before['uid']))
    if snapshot(label, environment) != before:
        raise ValueError('Managed unit changed during preflight')
    if check:
        return {'label': label, 'check': True, 'pid': before['pid'], 'trust': trust}
    if os.getuid() == 0:
        command(['/bin/launchctl', 'kickstart', '-k', 'system/' + label])
        method = 'launchctl kickstart'
    else:
        # launchctl(1): system domain modifications require root. Kill only the
        # same revalidated owned KeepAlive child; launchd performs replacement.
        os.kill(before['pid'], signal.SIGTERM)
        method = 'owned KeepAlive child SIGTERM'
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            after = snapshot(label, environment)
            if after['pid'] != before['pid'] and after['plist'] == before['plist']:
                return {'label': label, 'method': method, 'old_pid': before['pid'], 'new_pid': after['pid'], 'trust': trust}
        except ValueError:
            pass
        time.sleep(1)
    raise ValueError('Managed unit did not return with a new verified PID')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--idle-database')
    parser.add_argument('--unit')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--local-trust-only', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        raise ValueError('This entrypoint requires Darwin')
    if bool(args.idle_database) == bool(args.unit):
        raise ValueError('Choose exactly one mode')
    result = idle(args.idle_database) if args.idle_database else refresh(**json.loads(args.unit), check=args.check, local_trust_only=args.local_trust_only)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
