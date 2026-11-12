"""Contracts for the credential redaction of MinIO metadata backups.

`mc admin cluster bucket export` stores every remote target with its secret
key, and the env file copy holds the root password. The backup must drop the
targets from the export and redact the env copy (metadata scope), and the
restore must refuse to install a redacted env file.
"""

from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "roles" / "minio_backup"
RESTORE = ROOT / "roles" / "minio_restore"
SCRIPT = BACKUP / "files" / "redact_backup_secrets.py"
FAKE_SECRET = "fixture-not-a-real-secret-0123456789"  # pragma: allowlist secret

# Produced by Go's encoding/json (json.Marshal) and encoding/xml (xml.Marshal)
# for GO_SECRET, the encoders MinIO's IAM (JSON) and bucket (XML) exports use.
GO_SECRET = "pw<&\"'>\t\n\r\\x\u2028y"  # pragma: allowlist secret
GO_JSON = rb"pw\u003c\u0026\"'\u003e\t\n\r\\x\u2028y"
GO_XML = b"pw&lt;&amp;&#34;&#39;&gt;&#x9;&#xA;&#xD;\\x\xe2\x80\xa8y"

TARGETS_XML = (
    "<BucketTargets><Targets><SourceBucket>b</SourceBucket>"
    "<Endpoint>replica.example:9001</Endpoint><Credentials>"
    "<AccessKeyId>root</AccessKeyId>"
    f"<SecretAccessKey>{FAKE_SECRET}</SecretAccessKey>"
    "<SessionToken></SessionToken></Credentials>"
    "<Arn>arn:minio:replication::id:b</Arn></Targets></BucketTargets>"
)


def load_script():
    spec = importlib.util.spec_from_file_location("redact_backup_secrets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def task(tasks: list[dict], name: str) -> dict:
    for item in tasks:
        if item.get("name") == name:
            return item
        for sub in item.get("block", []) or []:
            if sub.get("name") == name:
                return sub
    raise AssertionError(f"task {name!r} not found")


class RedactScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_script()
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.tmp.rmdir()

    def make_zip(self) -> Path:
        path = self.tmp / "cluster-metadata.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for bucket in ("backups", "voxhelm"):
                zf.writestr(f"{bucket}/bucket-targets.json", TARGETS_XML)
                zf.writestr(f"{bucket}/replication.xml", "<ReplicationConfiguration/>")
                zf.writestr(f"{bucket}/versioning.xml", "<VersioningConfiguration/>")
            zf.writestr("blub/bucket-targets.json", "<BucketTargets></BucketTargets>")
            zf.writestr("blub/quota.json", "{}")
        return path

    def test_bucket_zip_drops_targets_and_keeps_everything_else(self) -> None:
        path = self.make_zip()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "bucket-zip", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dropped 3 bucket-targets.json", result.stdout)
        self.assertNotIn(FAKE_SECRET, result.stdout + result.stderr)
        with zipfile.ZipFile(path) as zf:
            names = sorted(zf.namelist())
            self.assertEqual(
                names,
                [
                    "backups/replication.xml",
                    "backups/versioning.xml",
                    "blub/quota.json",
                    "voxhelm/replication.xml",
                    "voxhelm/versioning.xml",
                ],
            )
        self.assertNotIn(FAKE_SECRET.encode(), path.read_bytes())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), [path.name])

    def test_bucket_zip_fails_closed_on_a_broken_archive(self) -> None:
        path = self.tmp / "broken.zip"
        path.write_bytes(b"not a zip")
        self.assertEqual(self.mod.main(["bucket-zip", str(path)]), 1)
        self.assertEqual(path.read_bytes(), b"not a zip")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["broken.zip"])

    def test_env_copy_redacts_secret_values_only(self) -> None:
        src = self.tmp / "minio"
        src.write_text(
            "# MinIO\n"
            'MINIO_VOLUMES="/mnt/cryptdata/minio/data"\n'
            'MINIO_OPTS="--address 127.0.0.1:9001"\n'
            "MINIO_ROOT_USER=admin\n"
            f'MINIO_ROOT_PASSWORD="{FAKE_SECRET}"\n'
            f"export MINIO_KMS_SECRET_KEY={FAKE_SECRET}\n"
            "MINIO_EMPTY_TOKEN=\n",
            encoding="utf-8",
        )
        dest = self.tmp / "out" / "minio.env"
        self.assertEqual(self.mod.main(["env", str(src), str(dest)]), 0)
        text = dest.read_text(encoding="utf-8")
        self.assertNotIn(FAKE_SECRET, text)
        self.assertIn("MINIO_ROOT_PASSWORD=REDACTED-BY-MINIO-BACKUP\n", text)
        self.assertIn("export MINIO_KMS_SECRET_KEY=REDACTED-BY-MINIO-BACKUP\n", text)
        self.assertIn("MINIO_ROOT_USER=admin\n", text)
        self.assertIn('MINIO_VOLUMES="/mnt/cryptdata/minio/data"\n', text)
        self.assertIn("MINIO_EMPTY_TOKEN=\n", text)
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)

    def test_env_copy_refuses_multi_line_values(self) -> None:
        for text in (
            f"MINIO_ROOT_PASSWORD=\\\n{FAKE_SECRET}\n",
            f'MINIO_ROOT_PASSWORD="first\n{FAKE_SECRET}"\n',  # pragma: allowlist secret
            f"MINIO_OPTS='--a\nMINIO_ROOT_PASSWORD={FAKE_SECRET}'\n",
            f'MINIO_ROOT_PASSWORD="start\\"\n{FAKE_SECRET}"\n',  # pragma: allowlist secret
            f'MINIO_ROOT_PASSWORD="a" {FAKE_SECRET}\n',
        ):
            with self.subTest(text=text.replace(FAKE_SECRET, "<s>")):
                src = self.tmp / "minio"
                src.write_text(text, encoding="utf-8")
                dest = self.tmp / "minio.env"
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "env", str(src), str(dest)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertRegex(result.stderr, "multi-line|continues on the next line")
                self.assertNotIn(FAKE_SECRET, result.stdout + result.stderr)
                self.assertFalse(dest.exists())

    def test_single_line_value(self) -> None:
        f = self.mod._single_line_value
        for value, want in {
            '"abc\\"': False,
            '"abc\\\\"': True,
            '"a\\"b"': True,
            "'x'": True,
            "'x": False,
            "plain": True,
            'a"b': False,
            '""': True,
            "x\\": False,
        }.items():
            with self.subTest(value=value):
                self.assertIs(f(value), want)

    def test_env_copy_keeps_assignment_spacing(self) -> None:
        text, count = self.mod.redact_env(f"MINIO_ROOT_PASSWORD= {FAKE_SECRET}\n")
        self.assertEqual(count, 1)
        self.assertEqual(text, "MINIO_ROOT_PASSWORD= REDACTED-BY-MINIO-BACKUP\n")

    def test_verify_absent_finds_plain_and_zipped_secrets(self) -> None:
        snap = self.tmp / "snap"
        (snap / "metadata").mkdir(parents=True)
        (snap / "config.env").write_text(
            "MINIO_ROOT_PASSWORD=REDACTED-BY-MINIO-BACKUP\n"
        )
        secret = {"value": FAKE_SECRET}

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(SCRIPT), "verify-absent", str(snap)],
                capture_output=True,
                text=True,
                check=False,
                input=secret["value"],
            )

        clean = run()
        self.assertEqual(clean.returncode, 0, clean.stderr)
        with zipfile.ZipFile(snap / "metadata" / "iam.zip", "w") as zf:
            zf.writestr("iam-assets/x.json", FAKE_SECRET)
        leak = run()
        self.assertEqual(leak.returncode, 1)
        self.assertIn("metadata/iam.zip", leak.stderr)
        self.assertNotIn(FAKE_SECRET, leak.stdout + leak.stderr)
        secret["value"] = ""
        self.assertEqual(run().returncode, 1)

    def test_verify_absent_matches_go_encoder_output(self) -> None:
        forms = self.mod.secret_forms(GO_SECRET)
        self.assertIn(GO_JSON, forms)
        self.assertIn(GO_XML, forms)
        snap = self.tmp / "snap"
        snap.mkdir()
        (snap / "targets.xml").write_bytes(
            b"<SecretAccessKey>" + GO_XML + b"</SecretAccessKey>"
        )
        with zipfile.ZipFile(
            snap / "iam.zip", "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            zf.writestr("iam-assets/users.json", b'{"secretKey":"' + GO_JSON + b'"}')
        self.assertEqual(
            sorted(self.mod.verify_absent([snap], GO_SECRET)),
            [str(snap / "iam.zip"), str(snap / "targets.xml")],
        )

    def test_usage_error(self) -> None:
        self.assertEqual(self.mod.main(["bogus"]), 2)


class RedactRoleWiringTests(unittest.TestCase):
    def test_defaults(self) -> None:
        defaults = load(BACKUP / "defaults" / "main.yml")
        self.assertIs(defaults["minio_backup_redact_target_secrets"], True)
        self.assertEqual(
            defaults["minio_backup_redact_env_secrets"],
            "{{ not (minio_backup_include_data | bool) }}",
        )

    def test_targets_are_dropped_before_the_export_is_stored(self) -> None:
        tasks = load(BACKUP / "tasks" / "metadata_export.yml")
        names = [t["name"] for t in tasks]
        drop = "Drop remote targets (with their credentials) from the bucket metadata export"
        self.assertLess(
            names.index(drop), names.index("Copy bucket metadata into backup directory")
        )
        script = task(tasks, drop)["ansible.builtin.script"]
        self.assertIn("redact_backup_secrets.py bucket-zip", script["cmd"])
        self.assertIn(
            "minio_backup_redact_target_secrets | bool", task(tasks, drop)["when"]
        )

    def test_env_copy_is_redacted_in_metadata_scope_only(self) -> None:
        tasks = load(BACKUP / "tasks" / "config.yml")
        decide = task(tasks, "Decide whether the env file copy is redacted")[
            "ansible.builtin.set_fact"
        ]
        self.assertIn(
            "not (minio_backup_include_data | bool)",
            decide["minio_backup_env_redacted"],
        )
        self.assertIn(
            "minio_backup_redact_env_secrets | bool",
            decide["minio_backup_env_redacted"],
        )
        plain = task(tasks, "Copy MinIO environment file")
        self.assertEqual(plain["when"], "not minio_backup_env_redacted")
        redacted = task(
            tasks, "Copy MinIO environment file with secret values redacted"
        )
        self.assertEqual(redacted["when"], "minio_backup_env_redacted")
        write = task(tasks, "Write redacted MinIO environment file")[
            "ansible.builtin.script"
        ]
        self.assertIn("redact_backup_secrets.py env", write["cmd"])

    def test_metadata_records_redaction(self) -> None:
        finalize = load(BACKUP / "tasks" / "finalize.yml")
        metadata = task(finalize, "Build backup metadata structure")[
            "ansible.builtin.set_fact"
        ]["minio_backup_metadata"]
        self.assertEqual(
            sorted(metadata["redacted_secrets"]),
            ["env_file", "remote_target_credentials"],
        )

    def test_restore_refuses_a_redacted_env_file_during_validation(self) -> None:
        # In validate.yml: before preparation and outside restore.yml's
        # rollback-protected block, so a refusal never triggers a rollback.
        tasks = load(RESTORE / "tasks" / "validate.yml")
        look = task(tasks, "Look for redacted secrets in the snapshot environment file")
        argv = look["ansible.builtin.command"]["argv"]
        self.assertIn("-F", argv)
        self.assertIn("REDACTED-BY-MINIO-BACKUP", argv)
        self.assertEqual(
            look["failed_when"], "minio_restore_env_redacted.rc not in [0, 1]"
        )
        for name in (
            "Look for redacted secrets in the snapshot environment file",
            "Refuse to restore a redacted environment file",
        ):
            self.assertIn(
                "minio_restore_metadata_restore_system_files", task(tasks, name)["when"]
            )
        main = load(RESTORE / "tasks" / "main.yml")
        names = [t.get("name") for t in main]
        self.assertLess(
            names.index("Validate restore inputs and snapshot"),
            names.index("Prepare host for MinIO restore"),
        )
        system = [t.get("name") for t in load(RESTORE / "tasks" / "restore_system.yml")]
        self.assertNotIn("Refuse to restore a redacted environment file", system)

    def test_backup_scans_the_snapshot_for_the_root_password(self) -> None:
        main = load(BACKUP / "tasks" / "main.yml")
        names = [t.get("name") for t in main]
        scan_name = "Verify the root password is absent from the snapshot"
        self.assertLess(
            names.index("Scan the snapshot for the root password"),
            names.index("Generate backup metadata, manifests, and report"),
        )
        scan = task(main, scan_name)
        self.assertIs(scan["no_log"], True)
        self.assertNotIn("environment", scan)
        command = scan["ansible.builtin.command"]
        self.assertEqual(command["stdin"], "{{ minio_root_password }}")
        self.assertIs(command["stdin_add_newline"], False)
        self.assertIn("verify-absent", command["argv"])
        self.assertNotIn("minio_root_password", " ".join(command["argv"]))
        report = task(main, "Fail when the root password is in the snapshot")
        self.assertIn(
            "minio_backup_secret_scan.rc == 0", report["ansible.builtin.assert"]["that"]
        )
        self.assertNotIn("no_log", report)


if __name__ == "__main__":
    unittest.main()
