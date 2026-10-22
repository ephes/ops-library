#!/usr/bin/env python3
"""One bounded trust-only Compose transaction; application images never change."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import ssl
import time


def run(argv, input_text=None):
    result = subprocess.run(argv, input=input_text, capture_output=True, text=True)
    if result.returncode:
        # Compose output may contain interpolated credentials. Keep it private.
        raise RuntimeError(f"Command failed: {argv[0]} {argv[1]}; exit {result.returncode}")
    return result.stdout


def inspect(names, execute=run):
    return json.loads(execute(['docker', 'inspect', *names]))


def compose(project, overlay=None):
    command = ['docker', 'compose', '--project-name', project['project'],
               '--project-directory', project['directory']]
    for path in project['files']:
        command += ['-f', path]
    if overlay:
        command += ['-f', str(overlay)]
    return command


def binding(source, target):
    if not Path(source).exists():
        raise ValueError('Prepared trust source is missing')
    return {'type': 'bind', 'source': source, 'target': target, 'read_only': True,
            'bind': {'create_host_path': False}}


def overlay_for(project, states):
    services = {}
    for record in project['containers']:
        state = states[record['name']]
        label = state['Config']['Labels']
        service = label['com.docker.compose.service']
        item = {'image': state['Image']}
        volumes = []
        if record.get('store'):
            store = Path(record['store'])
            if not (store / 'bundle.pem').is_file() or not (store / 'empty').is_dir():
                raise ValueError('Replacement trust store was not prepared')
            manifest = json.loads((store / 'manifest.json').read_text())
            if manifest['image'] != state['Image']:
                raise ValueError('Prepared trust store image changed')
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(str(store / 'bundle.pem'))
            roots = {hashlib.sha256(cert).hexdigest() for cert in context.get_ca_certs(binary_form=True)}
            blocked = {'d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4',
                       '86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b'}
            if not roots or roots & blocked or list((store / 'empty').iterdir()):
                raise ValueError('Replacement trust verification failed')
            volumes.append(binding(str(store), '/run/managed-ca'))
            item['environment'] = {'SSL_CERT_FILE': '/run/managed-ca/bundle.pem',
                                   'SSL_CERT_DIR': '/run/managed-ca/empty'}
        if record.get('node'):
            if not record.get('store'):
                raise ValueError('Node replacement requires a prepared store')
            env = dict(pair.split('=', 1) for pair in state['Config']['Env'])
            raw_options = env.get('NODE_OPTIONS', '')
            if not re.fullmatch(r'[A-Za-z0-9_./:=,+ \-]*', raw_options):
                raise ValueError('Complex Node options require explicit review')
            options = raw_options.split()
            if any(option.startswith(('--use-bundled-ca', '--use-system-ca')) for option in options):
                raise ValueError('Conflicting Node trust mode requires review')
            if '--use-openssl-ca' not in options:
                options.append('--use-openssl-ca')
            item['environment']['NODE_OPTIONS'] = ' '.join(options)
        if record.get('chrome_policy'):
            if not Path(record['chrome_policy']).is_file():
                raise ValueError('Prepared Chrome policy is missing')
            volumes.append(binding(record['chrome_policy'], '/etc/opt/chrome/policies/managed/99-emudhra.json'))
        if record.get('linuxserver_hook'):
            root = Path(record['linuxserver_hook'])
            for filename in ('repair_ca.py', '10-emudhra-ca.sh'):
                if not (root / filename).is_file():
                    raise ValueError('Prepared native trust hook is missing')
            volumes += [binding(str(root), '/run/managed-ca-init'),
                        binding(str(root / '10-emudhra-ca.sh'), '/custom-cont-init.d/10-emudhra-ca.sh')]
        if volumes:
            item['volumes'] = volumes
        if not volumes:
            raise ValueError('Every activation container needs explicit trust protection')
        services[service] = item
    return {'services': services}


def configuration_hashes(project, states, execute):
    command = compose(project)
    hashes = dict(line.split() for line in execute(command + ['config', '--hash', '*']).splitlines())
    services = {states[r['name']]['Config']['Labels']['com.docker.compose.service']: states[r['name']]
                for r in project['containers']}
    if len(services) != len(project['containers']):
        raise ValueError('One explicitly inventoried container per Compose service required')
    mismatches = [name for name, state in services.items()
                  if hashes.get(name) != state['Config']['Labels']['com.docker.compose.config-hash']]
    if not mismatches:
        return hashes
    # Compose stamps a service namespace after resolving its dependency to a
    # container ID; config --hash retains service:<name>. Normalize ONLY that
    # proven equivalence, then let Compose hash every other setting unchanged.
    configuration = json.loads(execute(command + ['config', '--format', 'json']))
    overrides = {}
    for name in mismatches:
        mode = configuration.get('services', {}).get(name, {}).get('network_mode', '')
        dependency = mode.removeprefix('service:')
        actual = services[name].get('HostConfig', {}).get('NetworkMode')
        if not mode.startswith('service:') or dependency not in services:
            raise ValueError('Original Compose configuration drift requires review')
        expected = 'container:' + services[dependency]['Id']
        if actual != expected:
            raise ValueError('Compose service namespace differs from inventoried dependency')
        overrides[name] = {'network_mode': actual}
    return dict(line.split() for line in execute(command + ['-f', '-', 'config', '--hash', '*'],
                                                 input_text=json.dumps({'services': overrides})).splitlines())


def validate(projects, states, execute=run):
    names = [r['name'] for p in projects for r in p['containers']]
    if not names or len(names) != len(set(names)):
        raise ValueError('Explicit unique container names required')
    running = set(execute(['docker', 'ps', '--format', '{{.Names}}']).splitlines())
    if running != set(names):
        raise ValueError('Docker restart must cover the entire running fleet')
    if len({p['project'] for p in projects}) != len(projects):
        raise ValueError('Unique Compose projects required')
    for project in projects:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]+', project['project']):
            raise ValueError('Invalid Compose project')
        if not project['files'] or not Path(project['directory']).is_absolute():
            raise ValueError('Explicit Compose files and absolute directory required')
        for source in project['files']:
            if not Path(source).is_absolute() or not Path(source).is_file():
                raise ValueError('Original Compose file is missing')
        hashes = configuration_hashes(project, states, execute)
        seen = set()
        for record in project['containers']:
            state = states[record['name']]
            labels = state['Config']['Labels']
            service = labels['com.docker.compose.service']
            seen.add(service)
            if labels['com.docker.compose.project'] != project['project']:
                raise ValueError('Container Compose project changed')
            if hashes.get(service) != labels['com.docker.compose.config-hash']:
                raise ValueError('Original Compose configuration drift requires review')
            if not state['State']['Running']:
                raise ValueError('Only an explicitly running fleet can be activated')
            if state['State'].get('Health', {}).get('Status', 'healthy') != 'healthy':
                raise ValueError('Original container is unhealthy')
        if seen != set(hashes):
            raise ValueError('Compose service coverage differs from explicit inventory')


def healthy(names, execute=run, timeout=180):
    deadline = time.monotonic() + timeout
    while True:
        states = inspect(names, execute)
        if all(s['State']['Running'] and s['State'].get('Health', {}).get('Status', 'healthy') == 'healthy' for s in states):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Container health did not converge')
        time.sleep(2)


def preflight(projects, execute=run):
    names = [r['name'] for p in projects for r in p['containers']]
    original = inspect(names, execute)
    states = {s['Name'].lstrip('/'): s for s in original}
    validate(projects, states, execute)
    return original, [overlay_for(p, states) for p in projects]


def transaction(projects, receipt, execute=run, health=healthy):
    names = [r['name'] for p in projects for r in p['containers']]
    original, overlays = preflight(projects, execute)
    receipt.mkdir(mode=0o700, parents=True, exist_ok=False)
    # Sensitive original Compose/environment metadata is never emitted on stdout.
    (receipt / 'original-inspect.json').write_text(json.dumps(original))
    for i, (project, overlay) in enumerate(zip(projects, overlays)):
        (receipt / f'active-{i}.json').write_text(json.dumps(overlay))
        rollback = {'services': {s: {'image': data['image']} for s, data in overlay['services'].items()}}
        (receipt / f'rollback-{i}.json').write_text(json.dumps(rollback))
        for j, source in enumerate(project['files']):
            shutil.copyfile(source, receipt / f'original-{i}-{j}.compose')
        env = Path(project['directory']) / '.env'
        if env.is_file():
            shutil.copyfile(env, receipt / f'original-{i}.env')
    for path in receipt.iterdir():
        path.chmod(0o600)
    restarted = False
    current_step = 'prepared'
    failed_step = None

    def outcome(status, required=False):
        target = receipt / 'result.json'
        try:
            target.write_text(json.dumps({'status': status, 'step': current_step,
                                         'failed_step': failed_step,
                                         'docker_restart_attempted': restarted, 'containers': names}))
            target.chmod(0o600)
        except OSError:
            if required:
                raise
            # Receipt storage failure must never block recovery or undo healthy activation.
            print('WARNING: activation receipt is unreliable; status persistence failed; investigate storage before retry')

    def step(label, argv):
        nonlocal current_step
        current_step = label
        outcome('in_progress')
        return execute(argv)

    outcome('prepared', required=True)
    try:
        step('stop', ['docker', 'stop', '--time', '30', *names])
        for i, project in enumerate(projects):
            step(f'create-{i}', compose(project, receipt / f'active-{i}.json') + ['create', '--pull', 'never', '--no-build', '--force-recreate'])
        # Persist before the call: a failed systemctl result must not cause a second restart.
        restarted = True
        step('docker_restart', ['systemctl', 'restart', 'docker.service'])
        for i, project in enumerate(projects):
            step(f'start-{i}', compose(project, receipt / f'active-{i}.json') + ['start'])
        current_step = 'health'
        outcome('in_progress')
        health(names, execute)
        outcome('activated')
    except Exception:
        failed_step = current_step
        outcome('recovering')
        try:
            present = set(step('recovery_inventory', ['docker', 'ps', '-a', '--format', '{{.Names}}']).splitlines())
            existing = [name for name in names if name in present]
            if existing:
                step('recovery_stop', ['docker', 'stop', '--time', '30', *existing])
            for i, project in enumerate(projects):
                step(f'recovery_create-{i}', compose(project, receipt / f'rollback-{i}.json') + ['create', '--pull', 'never', '--no-build', '--force-recreate'])
            if not restarted:
                restarted = True
                step('recovery_docker_restart', ['systemctl', 'restart', 'docker.service'])
            for i, project in enumerate(projects):
                step(f'recovery_start-{i}', compose(project, receipt / f'rollback-{i}.json') + ['start'])
            current_step = 'recovery_health'
            outcome('recovering')
            health(names, execute)
        except Exception:
            outcome('recovery_failed')
            raise
        outcome('rolled_back')
        raise
    finally:
        try:
            for path in receipt.iterdir():
                path.chmod(0o600)
        except OSError:
            print('WARNING: cannot refresh private receipt modes; investigate storage before retry')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('configuration')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    projects = json.loads(args.configuration)
    if os.geteuid() != 0 or platform.system() != 'Linux':
        raise ValueError('Container activation requires Linux root')
    if args.check:
        preflight(projects)
        print('Preflight passed; no runtime changes')
    else:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        receipt = transaction(projects, Path('/var/lib/managed-container-ca/activation') / stamp)
        print('Receipt: ' + str(receipt))
