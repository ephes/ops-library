"""Run the Echoport backup runners' S3 data path against MinIO and RustFS.

MinIO is being replaced by RustFS; backups must work unchanged against either
store. For each store this starts a pinned server container and a client
container (the pinned mc and rclone of the runners) on an internal Docker
network without outside access, creates the scoped per-target account the way
``minio_deploy``'s ``backup_account`` tasks do (``mc admin`` with the rendered
``backup-account-policy.json.j2``) and imports its mc alias from stdin like
``echoport_backup``'s ``minio_alias`` tasks. Then it runs the rendered runners
as FastDeploy would:

- the generic runner (``backup.py.j2``): SQLite plus files, a multipart
  upload, ``mc stat``, then a restore that downloads, verifies and puts the
  data back; a key whose alias belongs to another prefix is refused by the
  store;
- the rclone media runner (``homepage_media_backup.py.j2``): copy, size and
  manifest upload with the prefix-scoped account, then a restore into the
  source bucket. The runner's source remote is AWS; ``RCLONE_CONFIG_SRC_*``
  environment overrides point it at a bucket on the same test store instead.

Needs Docker; the first run builds the client image (Debian packages, the mc
release from GitHub, checked against its sha256) and pulls the store images.
Containers and the network carry the prefix ``echoport-s3-backend-neutral-``
and a random suffix, and are removed afterwards. ``just test-echoport-s3-backends``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from ansible.plugins.filter.core import FilterModule
from jinja2 import ChainableUndefined, Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[2]
RUNNER_TEMPLATES = ROOT / "roles" / "echoport_backup" / "templates"
POLICY_TEMPLATES = ROOT / "roles" / "minio_deploy" / "templates"
CLIENT_CONTEXT = Path(__file__).resolve().parent / "echoport_s3"

NAME_PREFIX = "echoport-s3-backend-neutral"
ROOT_USER = "labroot"
ROOT_PASSWORD = "labroot-password-0123456789"  # pragma: allowlist secret
BUCKET = "backups"


@dataclass(frozen=True)
class Store:
    name: str
    image: str
    env: dict[str, str]
    command: tuple[str, ...]


STORES = {
    "minio": Store(
        "minio",
        "minio/minio:RELEASE.2025-01-20T14-49-07Z"
        "@sha256:ed9be66eb5f2636c18289c34c3b725ddf57815f2777c77b5938543b78a44f144",
        {"MINIO_ROOT_USER": ROOT_USER, "MINIO_ROOT_PASSWORD": ROOT_PASSWORD},
        ("server", "/data"),
    ),
    "rustfs": Store(
        "rustfs",
        "rustfs/rustfs:1.0.3@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b",
        {"RUSTFS_ACCESS_KEY": ROOT_USER, "RUSTFS_SECRET_KEY": ROOT_PASSWORD},
        (),
    ),
}


def docker(*args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=900)
    if check and result.returncode != 0:
        raise AssertionError(f"docker {' '.join(args[:3])} failed ({result.returncode}): {result.stderr[-2000:]}")
    return result


def client_image() -> str:
    digest = hashlib.sha256((CLIENT_CONTEXT / "Dockerfile").read_bytes()).hexdigest()[:12]
    tag = f"{NAME_PREFIX}-client:{digest}"
    if docker("image", "inspect", tag, check=False).returncode != 0:
        docker("build", "--quiet", "--tag", tag, str(CLIENT_CONTEXT))
    return tag


def render(directory: Path, template: str, **variables: object) -> str:
    env = Environment(loader=FileSystemLoader(directory), undefined=ChainableUndefined, trim_blocks=True)
    # Ansible's filters where Jinja has none; Jinja's own ``default`` stays (Ansible's
    # does not apply to ChainableUndefined, and the runners' defaults would vanish).
    for name, function in FilterModule().filters().items():
        env.filters.setdefault(name, function)
    return env.get_template(template).render(**variables)


def scoped_user(target: str) -> str:
    # backup_minio_account_user of ops-control: bk- + 17 hex digits of the name's SHA-256.
    return "bk-" + hashlib.sha256(target.encode()).hexdigest()[:17]


def scoped_secret(target: str) -> str:
    return hashlib.sha256(f"lab-secret-{target}".encode()).hexdigest()[:36]


@dataclass
class Lab:
    store: Store
    client: str
    url: str

    def sh(self, script: str, *, stdin: str | None = None, env: dict[str, str] | None = None,
           check: bool = True) -> subprocess.CompletedProcess[str]:
        flags = [arg for key, value in (env or {}).items() for arg in ("-e", f"{key}={value}")]
        return docker("exec", "-i", *flags, self.client, "sh", "-c", script, stdin=stdin, check=check)

    def put_file(self, path: str, content: str, mode: str = "0600") -> None:
        self.sh(f"mkdir -p \"$(dirname '{path}')\" && cat > '{path}' && chmod {mode} '{path}'", stdin=content)

    def scoped_account(self, target: str, *, alias: str | None = None) -> None:
        """minio_deploy backup_account plus echoport_backup minio_alias for one target."""

        policy = render(
            POLICY_TEMPLATES,
            "backup-account-policy.json.j2",
            minio_backup_account_bucket=BUCKET,
            minio_backup_account_prefixes=[target],
            minio_backup_account_allow_put=True,
            minio_backup_account_allow_delete=False,
            minio_backup_account_whole_bucket=False,
        )
        self.put_file(f"/etc/minio/policies/backup-{target}.json", policy)
        self.sh(f"mc admin policy create admin backup-{target} /etc/minio/policies/backup-{target}.json")
        self.sh("mc admin user add admin >/dev/null", stdin=f"{scoped_user(target)}\n{scoped_secret(target)}\n")
        self.sh(f"mc admin policy attach admin backup-{target} --user {scoped_user(target)}")
        if alias:
            wanted = {"url": self.url, "accessKey": scoped_user(target), "secretKey": scoped_secret(target),
                      "api": "s3v4", "path": "auto"}
            self.sh(f"mc alias import {alias} >/dev/null", stdin=json.dumps(wanted))

    def run_runner(self, script: str, cfg_env: dict[str, str], *,
                   env: dict[str, str] | None = None) -> tuple[dict, list[dict]]:
        """Run a rendered runner like FastDeploy; return its ECHOPORT result and all events."""

        self.put_file("/run/echoport-lab/config.json", json.dumps({"context": {"env": cfg_env}}))
        # rclone and mc retry for a long time; a hung runner fails the test instead.
        result = self.sh(f"timeout 300 python3 {script}", env={"DEPLOY_CONFIG_FILE": "/run/echoport-lab/config.json", **(env or {})},
                         check=False)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        results = [e for e in events if str(e.get("message", "")).startswith("ECHOPORT_RESULT:")]
        assert results, f"no result (rc {result.returncode}): {result.stdout[-2000:]} {result.stderr[-2000:]}"
        return json.loads(results[-1]["message"].removeprefix("ECHOPORT_RESULT:")), events


@pytest.fixture(scope="module", params=sorted(STORES))
def lab(request: pytest.FixtureRequest) -> Iterator[Lab]:
    assert shutil.which("docker"), "The S3 backend integration check requires Docker"
    store = STORES[request.param]
    image = client_image()
    run = f"{NAME_PREFIX}-{store.name}-{uuid.uuid4().hex[:8]}"
    network, server, client = f"{run}-net", f"{run}-server", f"{run}-client"
    # --internal: neither container reaches anything outside this network.
    docker("network", "create", "--internal", network)
    started: list[str] = []
    try:
        env = [arg for key, value in store.env.items() for arg in ("-e", f"{key}={value}")]
        docker("run", "-d", "--name", server, "--network", network, *env, store.image, *store.command)
        started.append(server)
        # The runners require their work dir on a separate mount (_work_dir.py.j2).
        docker("run", "-d", "--name", client, "--network", network, "--tmpfs", "/mnt/work", image,
               "sleep", "infinity")
        started.append(client)
        current = Lab(store, client, f"http://{server}:9000")
        deadline = time.monotonic() + 90
        while current.sh(f"mc alias set admin {current.url} {ROOT_USER} {ROOT_PASSWORD} >/dev/null && "
                         "mc ls admin >/dev/null", check=False).returncode != 0:
            assert time.monotonic() < deadline, docker("logs", server, check=False).stderr[-2000:]
            time.sleep(1)
        current.sh(f"mc mb admin/{BUCKET} && mc version enable admin/{BUCKET}")
        yield current
    finally:
        for name in reversed(started):
            docker("rm", "--force", "--volumes", name, check=False)
        docker("network", "rm", network, check=False)


def generic_runner(lab: Lab, prefix_aliases: dict[str, str]) -> str:
    script = render(
        RUNNER_TEMPLATES,
        "backup.py.j2",
        echoport_backup_mc_install_path="/usr/local/bin/mc",
        # The shared alias is never configured: every key needs its own.
        echoport_backup_minio_alias="minio",
        echoport_backup_minio_prefix_aliases=prefix_aliases,
        echoport_backup_minio_require_prefix_alias=True,
        echoport_backup_default_bucket=BUCKET,
        echoport_backup_work_dir="/mnt/work/echoport-backup",
        echoport_backup_work_mount="/mnt/work",
        echoport_backup_work_retention_hours=24,
        echoport_backup_allowed_roots=["/var/lib/"],
    )
    path = f"/opt/runner/{hashlib.sha256(script.encode()).hexdigest()[:8]}/backup.py"
    lab.put_file(path, script, "0700")
    return path


def test_generic_runner_backs_up_and_restores_with_a_scoped_account(lab: Lab) -> None:
    lab.scoped_account("nyxmon", alias="backup-nyxmon")
    runner = generic_runner(lab, {"nyxmon": "backup-nyxmon"})
    lab.sh(
        "set -e; mkdir -p /var/lib/nyxmon/files; "
        "sqlite3 /var/lib/nyxmon/db.sqlite3 \"create table t(v text); insert into t values ('original');\"; "
        "echo original > /var/lib/nyxmon/files/note.txt; "
        # Incompressible and above mc's 16 MiB part size: a multipart upload.
        "head -c 20000000 /dev/urandom > /var/lib/nyxmon/files/blob.bin; "
        "sha256sum /var/lib/nyxmon/files/blob.bin > /root/blob.sha256"
    )
    env = {
        "ECHOPORT_TARGET": "nyxmon",
        "ECHOPORT_DB_PATH": "/var/lib/nyxmon/db.sqlite3",
        "ECHOPORT_BACKUP_FILES": "/var/lib/nyxmon/files/note.txt,/var/lib/nyxmon/files/blob.bin",
        "ECHOPORT_BUCKET": BUCKET,
    }
    result, _ = lab.run_runner(runner, {**env, "ECHOPORT_ACTION": "backup",
                                        "ECHOPORT_KEY_PREFIX": "nyxmon/2026-11-03T02-00-00"})
    assert result["success"], result
    assert result["key"] == "nyxmon/2026-11-03T02-00-00.tar.gz"
    assert result["size_bytes"] > 16 * 1024 * 1024
    stored = json.loads(lab.sh(f"mc stat --json admin/{BUCKET}/{result['key']}").stdout)
    assert stored["size"] == result["size_bytes"]

    lab.sh("sqlite3 /var/lib/nyxmon/db.sqlite3 \"update t set v = 'changed';\"; "
           "echo changed > /var/lib/nyxmon/files/note.txt; rm /var/lib/nyxmon/files/blob.bin")
    restored, _ = lab.run_runner(runner, {**env, "ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": result["key"],
                                          "ECHOPORT_CHECKSUM": result["checksum_sha256"]})
    assert restored["success"], restored
    assert lab.sh("sqlite3 /var/lib/nyxmon/db.sqlite3 'select v from t;'").stdout.strip() == "original"
    assert lab.sh("cat /var/lib/nyxmon/files/note.txt").stdout.strip() == "original"
    lab.sh("sha256sum -c /root/blob.sha256 >/dev/null")


def test_scoped_account_stays_in_its_prefix(lab: Lab) -> None:
    lab.scoped_account("chesslab", alias="backup-chesslab")
    lab.sh(f"echo foreign | mc pipe admin/{BUCKET}/other/foreign.txt >/dev/null && "
           f"echo own | mc pipe admin/{BUCKET}/chesslab/own.txt >/dev/null")
    denied = {
        "write a foreign prefix": f"echo x | mc pipe backup-chesslab/{BUCKET}/other/x.txt",
        "read a foreign prefix": f"mc cat backup-chesslab/{BUCKET}/other/foreign.txt",
        "list a foreign prefix": f"mc ls backup-chesslab/{BUCKET}/other/",
        "list the bucket": f"mc ls backup-chesslab/{BUCKET}",
        "delete its own object": f"mc rm backup-chesslab/{BUCKET}/chesslab/own.txt",
        "use the admin API": "mc admin user list backup-chesslab",
    }
    allowed = {name: script for name, script in denied.items() if lab.sh(script, check=False).returncode == 0}
    assert not allowed, f"{lab.store.name} allowed: {sorted(allowed)}"
    assert lab.sh(f"mc cat backup-chesslab/{BUCKET}/chesslab/own.txt").stdout.strip() == "own"

    # A runner whose alias map hands the key of another target to this
    # account: the store refuses the upload and the runner reports it.
    lab.sh("mkdir -p /var/lib/other && echo data > /var/lib/other/data.txt")
    runner = generic_runner(lab, {"chesslab": "backup-chesslab", "other": "backup-chesslab"})
    result, _ = lab.run_runner(runner, {"ECHOPORT_ACTION": "backup", "ECHOPORT_TARGET": "other",
                                        "ECHOPORT_BACKUP_FILES": "/var/lib/other/data.txt",
                                        "ECHOPORT_KEY_PREFIX": "other/2026-11-03T02-00-00"})
    assert not result["success"]
    assert result["error"] == "MinIO upload failed"
    assert lab.sh(f"mc stat admin/{BUCKET}/other/2026-11-03T02-00-00.tar.gz", check=False).returncode != 0


def test_media_runner_copies_and_restores_with_a_prefix_scoped_account(lab: Lab) -> None:
    lab.scoped_account("homepage-media")
    lab.sh(
        "set -e; mc mb --ignore-existing admin/media-src >/dev/null; "
        "head -c 20000000 /dev/urandom > /root/big.bin; echo small > /root/small.txt; "
        "mc cp -q /root/big.bin admin/media-src/images/big.bin >/dev/null; "
        "mc cp -q /root/small.txt admin/media-src/small.txt >/dev/null"
    )
    lab.put_file(
        "/etc/echoport-media/homepage-media-backup.json",
        json.dumps({
            # The source is the stand-in for the site's AWS bucket.
            "source_access_key": ROOT_USER,
            "source_secret_key": ROOT_PASSWORD,
            "dest_access_key": scoped_user("homepage-media"),
            "dest_secret_key": scoped_secret("homepage-media"),
        }),
    )
    script = render(
        RUNNER_TEMPLATES,
        "homepage_media_backup.py.j2",
        homepage_media_backup_rclone_path="/usr/bin/rclone",
        homepage_media_backup_work_dir="/mnt/work/homepage-media-backup",
        homepage_media_backup_work_mount="/mnt/work",
        homepage_media_backup_credentials_file="/etc/echoport-media/homepage-media-backup.json",
        homepage_media_backup_source_bucket="media-src",
        homepage_media_backup_minio_url=lab.url,
        homepage_media_backup_default_bucket=BUCKET,
        homepage_media_backup_prefix_root="homepage-media",
    )
    lab.put_file("/opt/runner/homepage_media_backup.py", script, "0700")
    # The source remote is AWS (virtual-hosted buckets); the stand-in bucket on the
    # test store needs an endpoint and path-style requests, which rclone only
    # makes for a non-AWS provider. The destination side stays as rendered.
    source = {"RCLONE_CONFIG_SRC_ENDPOINT": lab.url, "RCLONE_CONFIG_SRC_PROVIDER": "Minio"}

    result, _ = lab.run_runner("/opt/runner/homepage_media_backup.py",
                               {"ECHOPORT_ACTION": "backup", "ECHOPORT_KEY_PREFIX": "homepage-media/2026-11-03T02-00-00"},
                               env=source)
    assert result["success"], result
    assert (result["file_count"], result["size_bytes"]) == (2, 20000006)
    lab.sh(f"mc stat admin/{BUCKET}/homepage-media/2026-11-03T02-00-00/manifest.json >/dev/null && "
           f"mc stat admin/{BUCKET}/homepage-media/current/objects/images/big.bin >/dev/null")

    lab.sh("mc rm -q --recursive --force admin/media-src/ >/dev/null")
    restored, _ = lab.run_runner(
        "/opt/runner/homepage_media_backup.py",
        {"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": result["key"], "ECHOPORT_CHECKSUM": result["checksum_sha256"]},
        env=source,
    )
    assert restored["success"], restored
    lab.sh("mc cat admin/media-src/images/big.bin | cmp - /root/big.bin && "
           "mc cat admin/media-src/small.txt | cmp - /root/small.txt")
