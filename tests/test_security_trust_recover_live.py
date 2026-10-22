"""Actual collection-loader/uv recovery in an isolated, offline Docker target.

Docker and community.docker are required: infrastructure failures are failures,
not skipped acceptance. Only the controller downloads SHA-pinned fixture inputs;
the disposable target has no network, host mounts or Docker socket.
"""

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
import urllib.request
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXED_SHA = "42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b"
WHEELS = {
    "pip-26.2.1-py3-none-any.whl": (
        "f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd",
        "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e",
    ),
    "pip-26.2.2-py3-none-any.whl": (
        "3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f",
        "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70",
    ),
    "packaging-25.0-py3-none-any.whl": (
        "20/12/38679034af332785aac8774540895e234f4d07f7545804097de4b666afd8",
        "29572ef2b1f17581046b3a2227d5c611fb25ec70ca1ba8554b24b0e69331a484",
    ),
    "certifi-2026.10.19-py3-none-any.whl": (
        "c4/51/29046e48f693c54e5b7412216d447a1d8362c9653148d98c02cdf65fa733",
        FIXED_SHA,
    ),
    "certifi-2025.1.31-py3-none-any.whl": (
        "38/fc/bce832fd4fd99766c04d1ee0eead6b0ec6486fb100ae5e74c1d91292b982",
        "ca78db4565a652026a4db2bcdf68f2fb589ea80d0be70e03929ed730746b84fe",
    ),
}
PREFIX = "/home/recovery/site/.venv"
EVIDENCE = "/var/backups/security-trust-remediation/environment-live/before.json"
FIXED_WHEEL = "/var/cache/recovery/certifi-2026.10.19-py3-none-any.whl"


def run(argv, *, check=True, **kwargs):
    result = subprocess.run(argv, check=False, capture_output=True, text=True, **kwargs)
    if check and result.returncode:
        raise AssertionError(
            f"{argv!r}: exit {result.returncode}\n{result.stdout}\n{result.stderr}"
        )
    return result


def fetch(url, destination, sha256):
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise AssertionError(f"Fixture input checksum mismatch: {url}")
    destination.write_bytes(data)


class RecoveryLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="ops-recovery-live-")
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.base = Path(cls.scratch.name)
        cls.name = "ops-recovery-live-" + uuid.uuid4().hex[:12]
        image = "geerlingguy/docker-debian13-ansible:latest"
        run(["docker", "image", "inspect", image])
        run(["ansible-doc", "-t", "connection", "community.docker.docker"])
        architecture = run(
            ["docker", "image", "inspect", "--format", "{{.Architecture}}", image]
        ).stdout.strip()
        target = {"arm64": "aarch64", "amd64": "x86_64"}[
            architecture
        ] + "-unknown-linux-gnu"
        uv_defaults = yaml.safe_load(
            (ROOT / "roles/uv_install/defaults/main.yml").read_text()
        )
        version = uv_defaults["uv_version"]
        archive = cls.base / "uv.tar.gz"
        fetch(
            f"https://github.com/astral-sh/uv/releases/download/{version}/uv-{target}.tar.gz",
            archive,
            uv_defaults["uv_checksum"][target].removeprefix("sha256:"),
        )
        with tarfile.open(archive) as packed:
            source = packed.extractfile(f"uv-{target}/uv")
            (cls.base / "uv").write_bytes(source.read())
        (cls.base / "uv").chmod(0o755)
        for filename, (location, digest) in WHEELS.items():
            fetch(
                f"https://files.pythonhosted.org/packages/{location}/{filename}",
                cls.base / filename,
                digest,
            )
        collection = cls.base / "collections/ansible_collections/local/ops_library"
        collection.parent.mkdir(parents=True)
        collection.symlink_to(ROOT, target_is_directory=True)
        cls.env = {
            **os.environ,
            "ANSIBLE_COLLECTIONS_PATH": os.pathsep.join(
                [
                    str(cls.base / "collections"),
                    os.environ.get(
                        "ANSIBLE_COLLECTIONS_PATH",
                        str(Path.home() / ".ansible/collections")
                        + os.pathsep
                        + "/usr/share/ansible/collections",
                    ),
                ]
            ),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_HOST_KEY_CHECKING": "False",
        }
        cls.inventory = cls.base / "inventory.yml"
        cls.inventory.write_text(
            yaml.safe_dump(
                {
                    "all": {
                        "hosts": {
                            "fixture": {
                                "ansible_host": cls.name,
                                "ansible_connection": "community.docker.docker",
                                "ansible_python_interpreter": "/usr/bin/python3",
                            }
                        }
                    }
                }
            )
        )
        run(
            [
                "docker",
                "run",
                "--pull=never",
                "--rm",
                "-d",
                "--network=none",
                "--name",
                cls.name,
                image,
                "sleep",
                "infinity",
            ]
        )
        cls.addClassCleanup(lambda: run(["docker", "rm", "-f", cls.name], check=False))
        cls.exec("useradd", "--create-home", "recovery")
        cls.exec("mkdir", "-p", "/var/cache/recovery")
        for filename in ["uv", *WHEELS]:
            destination = (
                "/usr/local/bin/uv"
                if filename == "uv"
                else "/var/cache/recovery/" + filename
            )
            run(
                ["docker", "cp", str(cls.base / filename), cls.name + ":" + destination]
            )
        cls.exec("chown", "-R", "root:root", "/var/cache/recovery")
        cls.exec("chmod", "-R", "go-w", "/var/cache/recovery")
        run(
            [
                "docker",
                "cp",
                str(
                    ROOT / "roles/security_trust_remediate/files/inspect_environment.py"
                ),
                cls.name + ":/tmp/inspect_environment.py",
            ]
        )
        cls.exec("/usr/local/bin/uv", "--version")

    @classmethod
    def exec(cls, *argv, check=True, user=None):
        command = ["docker", "exec"]
        if user:
            command += ["--user", user]
        return run([*command, cls.name, *argv], check=check)

    @classmethod
    def python(cls, code, *, user=None):
        return cls.exec("/usr/bin/python3", "-c", code, user=user).stdout

    def setUp(self):
        self.exec(
            "rm",
            "-rf",
            "/home/recovery/site",
            "/var/backups/security-trust-remediation",
            "/tmp/outside",
        )
        self.exec("mkdir", "-p", "/home/recovery/site")
        self.exec("chown", "recovery:recovery", "/home/recovery/site")
        self.exec(
            "/usr/local/bin/uv",
            "venv",
            "--python",
            "/usr/bin/python3",
            PREFIX,
            user="recovery",
        )
        self.exec(
            "/usr/local/bin/uv",
            "pip",
            "install",
            "--python",
            PREFIX + "/bin/python",
            "--no-index",
            "--no-deps",
            "/var/cache/recovery/certifi-2025.1.31-py3-none-any.whl",
            "/var/cache/recovery/packaging-25.0-py3-none-any.whl",
            user="recovery",
        )
        if (
            self._testMethodName
            == "test_completed_recovery_noops_after_later_pip_upgrade"
        ):
            self.exec(
                "/usr/local/bin/uv",
                "pip",
                "install",
                "--python",
                PREFIX + "/bin/python",
                "--no-index",
                "--no-deps",
                "/var/cache/recovery/pip-26.2.1-py3-none-any.whl",
                user="recovery",
            )
        # The original immutable evidence is produced by the production inspector,
        # before interruption, with a genuine full-environment tar backup.
        before = self.exec(
            PREFIX + "/bin/python", "-B", "/tmp/inspect_environment.py", user="recovery"
        ).stdout
        self.before = json.loads(before)
        self.site = str(Path(self.before["bundles"]["certifi"]["path"]).parent.parent)
        self.cache = self.site + "/certifi/__pycache__"
        self.python(
            f"from pathlib import Path; import os; p=Path({EVIDENCE!r}); p.parent.mkdir(parents=True,mode=0o700); p.write_text({before!r}); p.chmod(0o600)"
        )
        self.exec(
            "tar",
            "-cf",
            str(Path(EVIDENCE).parent / "environment.tar"),
            "-C",
            PREFIX,
            ".",
        )
        self.exec(
            PREFIX + "/bin/python", "-c", "import certifi; print(certifi.where())"
        )
        self.paths = json.loads(
            self.python(
                f"import json; from pathlib import Path; p=Path({self.cache!r}); print(json.dumps([str(p),*[str(x) for x in sorted(p.iterdir())]]))"
            )
        )
        self.entry = {
            "path": PREFIX,
            "owner": "recovery",
            "before": EVIDENCE,
            "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
            "archive_sha256": self.python(
                f"import hashlib; print(hashlib.sha256(open({str(Path(EVIDENCE).parent / 'environment.tar')!r}, 'rb').read()).hexdigest())"
            ).strip(),
            "cache_paths": self.paths,
        }
        self.python(
            "from pathlib import Path; p=Path('/home/recovery/site/untouched-root'); p.write_text('retain root ownership')"
        )
        if self._testMethodName.startswith("test_normal_"):
            self.baseline = self.snapshot()
            return
        interrupted = self.exec(
            "/usr/local/bin/uv",
            "pip",
            "uninstall",
            "--python",
            PREFIX + "/bin/python",
            "certifi",
            user="recovery",
            check=False,
        )
        self.assertNotEqual(
            interrupted.returncode, 0, interrupted.stdout + interrupted.stderr
        )
        self.assertIn("Permission denied", interrupted.stderr)
        self.assertEqual(
            self.python(
                f"from pathlib import Path; print(len(list(Path({self.site!r}).glob('certifi-*.dist-info'))))"
            ).strip(),
            "0",
        )
        self.baseline = self.snapshot()

    def snapshot(self):
        return json.loads(
            self.python(f"""
import hashlib,json,os
from pathlib import Path
paths=[Path({PREFIX!r}),Path({EVIDENCE!r}).parent,Path('/tmp/outside'),Path('/home/recovery/site/untouched-root')]
result={{}}
for parent in paths:
 for p in [parent,*sorted(parent.rglob('*'))] if parent.exists() else []:
  s=p.lstat()
  result[str(p)]=[s.st_uid,s.st_gid,s.st_mode,os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None]
print(json.dumps(result))
""")
        )

    def invoke(self, *, check=False):
        play = self.base / "play.yml"
        play.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "fixture",
                        "gather_facts": False,
                        "vars": {
                            "security_trust_recover_entries": [self.entry],
                            "security_trust_recover_wheel": FIXED_WHEEL,
                            "security_trust_recover_sha256": FIXED_SHA,
                        },
                        "roles": ["local.ops_library.security_trust_recover"],
                    }
                ]
            )
        )
        result = run(
            [
                "ansible-playbook",
                "-i",
                str(self.inventory),
                str(play),
                *(["--check"] if check else []),
            ],
            env=self.env,
            check=False,
        )
        print(result.stdout, result.stderr, flush=True)
        return result

    def test_actual_interrupted_owner_uninstall_restored_offline(self):
        preview = self.invoke(check=True)
        self.assertEqual(preview.returncode, 0)
        self.assertEqual(
            self.snapshot(), self.baseline, "check mode mutated interrupted state"
        )
        result = self.invoke()
        self.assertEqual(result.returncode, 0)
        # importlib.metadata needs dist-info: importing a leftover module cannot
        # accidentally satisfy this assertion after a fake/mock installation.
        installed = self.exec(
            PREFIX + "/bin/python",
            "-B",
            "-c",
            "import importlib.metadata,os; print(importlib.metadata.version('certifi')); print(os.getuid())",
            user="recovery",
        ).stdout.splitlines()
        self.assertEqual(installed[0], "2026.10.19")
        uid = int(installed[1])
        after = self.snapshot()
        for path, original in self.baseline.items():
            if path.startswith(str(Path(EVIDENCE).parent)):
                self.assertEqual(after[path], original, path)
        for path in self.paths:
            if path in after:  # uv may remove obsolete bytecode during replacement.
                self.assertEqual(after[path][0], uid, path)
        for path, value in after.items():
            if path.startswith(self.site + "/certifi"):
                self.assertEqual(value[0], uid, path)
        self.assertFalse(any("certifi-2025.1.31.dist-info" in p for p in after))
        for path, original in self.baseline.items():
            if path.startswith(self.site + "/packaging"):
                self.assertEqual(after[path], original, path)
        self.assertEqual(
            after["/home/recovery/site/untouched-root"],
            self.baseline["/home/recovery/site/untouched-root"],
        )

        # Generated caches can disappear between retries (for example through
        # an owner cleanup). uv need not remove them itself. Keep the original
        # allowlist so the already-completed recovery sees stale cache paths.
        self.exec("rm", "-rf", self.cache, user="recovery")
        after = self.snapshot()
        self.assertTrue(all(path not in after for path in self.paths))
        repeat = self.invoke()
        self.assertEqual(repeat.returncode, 0)
        self.assertRegex(repeat.stdout, r"changed=0\s")
        self.assertEqual(
            self.snapshot(), after, "standalone retry changed a completed recovery"
        )

    def test_completed_recovery_noops_after_later_pip_upgrade(self):
        self.assertEqual(self.before["packages"]["pip"]["version"], "26.2.1")
        first = self.invoke()
        self.assertEqual(first.returncode, 0)
        # The later normal remediation advances pip too. Reuse the original
        # recovery evidence, which necessarily still describes the old pip.
        self.exec(
            "/usr/local/bin/uv",
            "pip",
            "install",
            "--python",
            PREFIX + "/bin/python",
            "--no-index",
            "--no-deps",
            "/var/cache/recovery/pip-26.2.2-py3-none-any.whl",
            user="recovery",
        )
        version = self.exec(
            PREFIX + "/bin/python",
            "-B",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('pip'))",
            user="recovery",
        ).stdout.strip()
        self.assertEqual(version, "26.2.2")
        self.exec("rm", "-rf", self.cache, user="recovery")
        completed = self.snapshot()
        for path, original in self.baseline.items():
            if path.startswith(str(Path(EVIDENCE).parent)):
                self.assertEqual(completed[path], original, path)
        repeat = self.invoke()
        self.assertEqual(repeat.returncode, 0)
        self.assertRegex(repeat.stdout, r"changed=0\s")
        self.assertEqual(self.snapshot(), completed)

    def invoke_normal(self):
        play = self.base / "normal.yml"
        play.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "fixture",
                        "gather_facts": False,
                        "vars": {
                            "trust_env": {
                                "path": PREFIX,
                                "services": [],
                                "health_urls": [],
                                "cache_recovery_paths": self.paths,
                            },
                            "security_trust_apt": {"changed": False},
                            "security_trust_wheel_dir": "/var/cache/main-role-only",
                            "security_trust_uv_bin": "/opt/main-role-only/uv",
                            "security_trust_certifi_version": "2026.10.19",
                            "security_trust_wheels": [
                                {
                                    "package": "certifi",
                                    "name": "certifi-2026.10.19-1-py3-none-any.whl",
                                    "sha256": FIXED_SHA,
                                }
                            ],
                        },
                        "tasks": [
                            {
                                "ansible.builtin.import_role": {
                                    "name": "local.ops_library.security_trust_remediate",
                                    "tasks_from": "environment",
                                }
                            }
                        ],
                    }
                ]
            )
        )
        # Move defaults away, so accidental recovery-default fallbacks cannot
        # pass while the normal caller claims to use its configured inputs.
        custom_wheel = "/var/cache/main-role-only/certifi-2026.10.19-1-py3-none-any.whl"
        self.exec("mkdir", "-p", "/var/cache/main-role-only", "/opt/main-role-only")
        self.exec("mv", FIXED_WHEEL, custom_wheel)
        self.exec("mv", "/usr/local/bin/uv", "/opt/main-role-only/uv")
        try:
            result = run(
                ["ansible-playbook", "-i", str(self.inventory), str(play)],
                env=self.env,
                check=False,
            )
        finally:
            self.exec("mv", custom_wheel, FIXED_WHEEL)
            self.exec("mv", "/opt/main-role-only/uv", "/usr/local/bin/uv")
        print(result.stdout, result.stderr, flush=True)
        return result

    def test_normal_main_role_backs_up_before_cache_recovery_and_updates(self):
        result = self.invoke_normal()
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "Verify actual bundle files independently with system Python", result.stdout
        )
        report = json.loads(
            self.exec(
                PREFIX + "/bin/python",
                "-B",
                "/tmp/inspect_environment.py",
                user="recovery",
            ).stdout
        )
        self.assertEqual(report["packages"]["certifi"]["version"], "2026.10.19")
        self.assertNotIn("pip", report["packages"])
        self.assertEqual(
            report["packages"]["packaging"], self.before["packages"]["packaging"]
        )
        after = self.snapshot()
        for path, original in self.baseline.items():
            if path.startswith(self.site + "/packaging"):
                self.assertEqual(after[path], original, path)
        archives = json.loads(
            self.python(
                "import json; from pathlib import Path; print(json.dumps([str(p) for p in Path('/var/backups/security-trust-remediation').glob('environment-*/environment.tar') if p.parent.name!='environment-live']))"
            )
        )
        self.assertEqual(len(archives), 1)
        # The automatic caller must capture old metadata and root-owned cache
        # before recovery; a backup made after mutation cannot pass this check.
        self.python(
            f"import tarfile; from pathlib import Path; p=Path({archives[0]!r}); t=tarfile.open(p); assert any('certifi-2025.1.31.dist-info/METADATA' in m.name for m in t); assert any('/certifi/__pycache__/' in m.name and m.uid==0 for m in t); assert '2025.1.31' in (p.parent/'before.json').read_text()"
        )
        self.assertEqual(
            self.snapshot()["/home/recovery/site/untouched-root"],
            self.baseline["/home/recovery/site/untouched-root"],
        )
        repeat = self.invoke_normal()
        self.assertEqual(repeat.returncode, 0)
        self.assertRegex(repeat.stdout, r"changed=0\s")

    def test_normal_main_role_does_not_insert_absent_package(self):
        self.exec(
            "rm",
            "-rf",
            self.site + "/certifi",
            self.site + "/certifi-2025.1.31.dist-info",
        )
        original = self.snapshot()
        result = self.invoke_normal()
        self.assertEqual(result.returncode, 0)
        self.assertRegex(result.stdout, r"changed=0\s")
        self.assertEqual(self.snapshot(), original)

    def test_reject_wrong_archive_digest_without_changes(self):
        self.entry["archive_sha256"] = "0" * 64
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Original archive digest mismatch", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), self.baseline)

    def test_reject_receipt_prefix_mismatch_without_changes(self):
        self.before["prefix"] = "/home/another/site/.venv"
        raw = json.dumps(self.before)
        self.python(f"from pathlib import Path; Path({EVIDENCE!r}).write_text({raw!r})")
        self.entry["before_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        original = self.snapshot()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No proven previous certifi", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), original)

    def test_reject_wrong_receipt_digest_without_changes(self):
        self.entry["before_sha256"] = "0" * 64
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Prior evidence digest mismatch", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), self.baseline)

    def test_reject_current_package_drift_without_changes(self):
        self.python(
            f"from pathlib import Path; p=Path({self.site!r})/'unrelated-1.dist-info'; p.mkdir(); (p/'METADATA').write_text('Name: unrelated\\nVersion: 1\\n')"
        )
        original = self.snapshot()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Installed distributions changed", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), original)

    def test_reject_absent_prior_distribution_without_insertion(self):
        self.before["packages"].pop("certifi")
        raw = json.dumps(self.before)
        self.python(f"from pathlib import Path; Path({EVIDENCE!r}).write_text({raw!r})")
        self.entry["before_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        original = self.snapshot()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No proven previous certifi", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), original)

    def test_reject_cache_symlink_escape_without_changes(self):
        victim = self.paths[-1]
        self.python(
            f"from pathlib import Path; p=Path({victim!r}); p.unlink(); q=Path('/tmp/outside'); q.write_text('untouched'); p.symlink_to(q)"
        )
        original = self.snapshot()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("without symlinks", result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), original)


if __name__ == "__main__":
    unittest.main()
