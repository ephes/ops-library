"""Incident-only certifi update; no application dependency resolution or additions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib

TARGET = "2026.10.19"
UV = "/opt/homebrew/bin/uv"
WHEEL = "https://files.pythonhosted.org/packages/c4/51/29046e48f693c54e5b7412216d447a1d8362c9653148d98c02cdf65fa733/certifi-2026.10.19-py3-none-any.whl"
HASH = "42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b"
STANZA = """[[package]]
name = "certifi"
version = "2026.10.19"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/a6/bd/1436c50cc46699de0230fbaacc1d1de7bfec413176099949e9d5112e88f2/certifi-2026.10.19.tar.gz", hash = "sha256:035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae", size = 137598, upload-time = "2026-10-20T02:24:16.604Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/c4/51/29046e48f693c54e5b7412216d447a1d8362c9653148d98c02cdf65fa733/certifi-2026.10.19-py3-none-any.whl", hash = "sha256:42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b", size = 136464, upload-time = "2026-10-20T02:24:15.072Z" },
]

"""
INSPECT = """import importlib.metadata as m,json,sys
packages={}
for name in ('certifi','pip','sigstore'):
 try: packages[name]=m.version(name)
 except m.PackageNotFoundError: packages[name]=None
print(json.dumps({'prefix':sys.prefix,'packages':packages}))
"""
VERIFY = """import certifi,ssl,json
context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.load_verify_locations(certifi.where())
names={v for cert in context.get_ca_certs() for rdn in cert['subject'] for k,v in rdn if k=='commonName'}
blocked={'AAA Certificate Services','emSign ECC Root CA - G3'}
if names & blocked: raise SystemExit('Affected root remains in installed certifi')
if not names: raise SystemExit('Installed CA bundle is empty')
print(json.dumps({'verified_ca_count':len(names)}))
"""


def version(value):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        raise ValueError("Unexpected package version format")
    return tuple(int(part) for part in value.split('.'))


def patch_lock(text):
    before = tomllib.loads(text)
    packages = [p for p in before.get('package',[]) if p['name']=='certifi']
    if len(packages)!=1:
        raise ValueError('Expected exactly one deployed certifi lock record')
    current = packages[0]
    if version(current['version']) >= version(TARGET):
        return text
    if set(current) - {'name','version','source','sdist','wheels'}:
        raise ValueError('Unexpected certifi lock fields require explicit review')
    if {'exclude-newer','exclude-newer-package'} & set(before.get('options',{})):
        raise ValueError('Lock exclude-newer policy needs explicit incident review')
    replacement = tomllib.loads(STANZA)['package'][0]
    if current.get('source') != replacement['source']:
        raise ValueError('Deployed certifi registry differs; explicit review required')
    pattern = re.compile(r'(?ms)^\[\[package\]\]\n(?:(?!^\[\[package\]\]).)*')
    result = pattern.sub(lambda match: STANZA if tomllib.loads(match.group())['package'][0]['name']=='certifi' else match.group(), text)
    after = tomllib.loads(result)
    expected = dict(before)
    expected['package']=[replacement if p['name']=='certifi' else p for p in before['package']]
    if after != expected:
        raise ValueError('Deployed lock changed outside certifi record')
    return result


def run(*args):
    return subprocess.check_output(args, text=True)


def remediate(path, lockfile=None, check=False):
    path = Path(path)
    if not path.is_absolute() or not (path/'pyvenv.cfg').is_file():
        raise ValueError('Target must be an explicit existing virtual environment')
    if lockfile and not Path(lockfile).is_absolute():
        raise ValueError('Lockfile must be an explicit absolute path')
    python = str(path/'bin/python')
    metadata = json.loads(run(python,'-c',INSPECT))
    if Path(metadata['prefix']).resolve()!=path.resolve():
        raise ValueError('Interpreter prefix differs from target environment')
    uv_version=run(UV,'--version').split()[1]
    if version(uv_version)<version('0.13.4'):
        raise ValueError('Patched uv>=0.13.4 required before download')
    for package,floor in (('pip','26.2.2'),('sigstore','4.5.1')):
        installed=metadata['packages'][package]
        if installed is not None and version(installed)<version(floor):
            raise ValueError(package+' requires separate installed-package remediation')
    installed=metadata['packages']['certifi']
    if installed is None:
        print('UNCHANGED'); print('certifi absent; no package inserted'); return
    lock_path=Path(lockfile) if lockfile else None
    lock_before=lock_path.read_text() if lock_path else None
    lock_after=patch_lock(lock_before) if lock_before is not None else None
    if version(installed)>version(TARGET) and lock_before!=lock_after:
        raise ValueError('Newer installed certifi requires matching reviewed lock metadata')
    changed=version(installed)<version(TARGET) or lock_before!=lock_after
    if check:
        print('CHANGED' if changed else 'UNCHANGED');return
    if changed:
        state=Path.home()/'.local/state/managed-python-ca'
        state.mkdir(parents=True,exist_ok=True,mode=0o700)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        receipt=state/(hashlib.sha256(str(path).encode()).hexdigest()[:16]+'-'+stamp+'.json')
        receipt.write_text(json.dumps({'path':str(path),'before':metadata,'lockfile':str(lock_path) if lock_path else None,'lock_sha256':hashlib.sha256(lock_before.encode()).hexdigest() if lock_before is not None else None},indent=2)+'\n')
        receipt.chmod(0o600)
        if lock_before!=lock_after:
            backup=receipt.with_suffix('.uv.lock')
            shutil.copy2(lock_path,backup);backup.chmod(0o600)
            descriptor,temporary=tempfile.mkstemp(prefix='.uv-lock-ca-',dir=lock_path.parent)
            try:
                with os.fdopen(descriptor,'w') as target:target.write(lock_after)
                shutil.copystat(lock_path,temporary)
                stat=lock_path.stat();os.chown(temporary,stat.st_uid,stat.st_gid)
                os.replace(temporary,lock_path)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
        if version(installed)<version(TARGET):
            with tempfile.TemporaryDirectory(prefix='certifi-remediation-') as temporary:
                requirement=Path(temporary)/'requirements.txt'
                requirement.write_text('certifi @ '+WHEEL+' --hash=sha256:'+HASH+'\n')
                run(UV,'pip','install','--python',python,'--no-deps','--require-hashes','-r',str(requirement))
        print('Receipt: '+str(receipt))
    final=json.loads(run(python,'-c',INSPECT))
    if version(final['packages']['certifi'])<version(TARGET):
        raise ValueError('Installed certifi below security floor')
    print(run(python,'-c',VERIFY).strip())
    print('CHANGED' if changed else 'UNCHANGED')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('path');parser.add_argument('--lockfile');parser.add_argument('--check',action='store_true')
    args=parser.parse_args();remediate(args.path,args.lockfile,args.check)
