"""Restore archives are validated, staged and preserved instead of unpacked into /."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "roles/restore_preserve_internal/files/archive_members.py"


def flatten(tasks):
    result = []
    for task in tasks or []:
        result.append(task)
        for section in ("block", "rescue", "always"):
            result.extend(flatten(task.get(section, [])))
    return result


def check(archive, *tops):
    args = [sys.executable, str(CHECKER), str(archive)]
    for top in tops:
        args += ["--allow-top", top]
    return subprocess.run(args, capture_output=True, text=True)


class RealArchiveLayoutTests(unittest.TestCase):
    """Archives built by community.general.archive, as the backup roles do."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        etc = base / "etc"
        live = etc / "letsencrypt"
        for sub in ("live/example.org", "archive/example.org", "renewal", "accounts"):
            (live / sub).mkdir(parents=True)
        (live / "archive/example.org/cert1.pem").write_text("cert\n")
        os.symlink(
            "../../archive/example.org/cert1.pem", live / "live/example.org/cert.pem"
        )
        (live / "renewal/example.org.conf").write_text("conf\n")
        for name in ("postfix", "dovecot"):
            (etc / name).mkdir()
            (etc / name / "main.cf").write_text(name + "\n")
        playbook = base / "build.yml"
        playbook.write_text(
            textwrap.dedent(
                f"""\
                - hosts: localhost
                  gather_facts: false
                  tasks:
                    - community.general.archive:
                        path: "{live}"
                        dest: "{base}/certbot.tar.gz"
                        format: gz
                    - community.general.archive:
                        path: ["{etc}/postfix", "{etc}/dovecot", "{etc}/missing"]
                        dest: "{base}/config.tar.gz"
                        format: gz
                """
            )
        )
        subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
            check=True,
            capture_output=True,
            cwd=ROOT,
        )
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_certbot_archive_is_stored_relative_to_parent(self):
        with tarfile.open(self.base / "certbot.tar.gz") as archive:
            names = archive.getnames()
        self.assertTrue(all(name.startswith("letsencrypt/") for name in names), names)

    def test_certbot_archive_passes_and_extracts_below_staging(self):
        result = check(self.base / "certbot.tar.gz", "letsencrypt")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ARCHIVE_TOPS ["letsencrypt"]', result.stdout)
        staging = self.base / "staging"
        staging.mkdir()
        with tarfile.open(self.base / "certbot.tar.gz") as archive:
            archive.extractall(staging, filter="tar")
        restored = staging / "letsencrypt"
        for sub in ("live", "archive", "renewal", "accounts"):
            self.assertTrue((restored / sub).is_dir(), sub)
        self.assertEqual(
            (restored / "live/example.org/cert.pem").read_text(), "cert\n"
        )
        self.assertEqual(sorted(p.name for p in staging.iterdir()), ["letsencrypt"])

    def test_old_root_destination_would_miss_etc(self):
        # The archive has no etc/ component, so extracting into / never
        # reached /etc/letsencrypt; the allowed name must be the directory.
        result = check(self.base / "certbot.tar.gz", "etc")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the allowed directories", result.stderr)

    def test_mail_config_archive_uses_directory_names(self):
        result = check(
            self.base / "config.tar.gz", "postfix", "dovecot", "opendkim", "rspamd"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            sorted(json.loads(result.stdout.split(" ", 1)[1])), ["dovecot", "postfix"]
        )


class BadMemberTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def build(self, *members):
        path = Path(self.tmp.name) / "bad.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, kind, link in members:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = link
                data = b"x" if kind == tarfile.REGTYPE else b""
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def assert_rejected(self, message, *members):
        result = check(self.build(*members), "letsencrypt")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertNotIn("ARCHIVE_TOPS", result.stdout)

    def test_absolute_member(self):
        self.assert_rejected("absolute", ("/etc/letsencrypt/x", tarfile.REGTYPE, ""))

    def test_parent_traversal(self):
        self.assert_rejected(
            "escapes", ("letsencrypt/../../root/x", tarfile.REGTYPE, "")
        )

    def test_member_outside_allowed_directory(self):
        self.assert_rejected("outside", ("etc/letsencrypt/x", tarfile.REGTYPE, ""))

    def test_symlink_leaving_tree(self):
        self.assert_rejected(
            "symlink leaves", ("letsencrypt/live/x", tarfile.SYMTYPE, "../../../etc")
        )
        self.assert_rejected(
            "absolute symlink", ("letsencrypt/live/x", tarfile.SYMTYPE, "/etc/shadow")
        )

    def test_symlink_chain_leaving_tree(self):
        # Each link looks harmless alone; together they resolve to ../victim.
        self.assert_rejected(
            "symlink leaves",
            ("letsencrypt/deep/x", tarfile.DIRTYPE, ""),
            ("letsencrypt/shallow", tarfile.DIRTYPE, ""),
            ("letsencrypt/deep/shortcut", tarfile.SYMTYPE, "../shallow"),
            ("letsencrypt/creds.ini", tarfile.SYMTYPE, "deep/shortcut/../../victim"),
        )

    def test_hardlink_through_symlink_leaving_tree(self):
        self.assert_rejected(
            "leaves",
            ("letsencrypt/up", tarfile.SYMTYPE, ".."),
            ("letsencrypt/x", tarfile.LNKTYPE, "letsencrypt/up/victim"),
        )

    def test_hardlink_to_symlink(self):
        # Extracted, the hardlink becomes a second symlink with the same
        # relative target, which resolves differently at its own location.
        self.assert_rejected(
            "hardlink to a symlink",
            ("letsencrypt/sub", tarfile.DIRTYPE, ""),
            ("letsencrypt/sub/s", tarfile.SYMTYPE, "file"),
            ("letsencrypt/alias", tarfile.LNKTYPE, "letsencrypt/sub/s"),
        )

    def test_hardlink_chain_to_symlink(self):
        self.assert_rejected(
            "hardlink to a symlink",
            ("letsencrypt/sub", tarfile.DIRTYPE, ""),
            ("letsencrypt/sub/s", tarfile.SYMTYPE, "file"),
            ("letsencrypt/sub/first", tarfile.LNKTYPE, "letsencrypt/sub/s"),
            ("letsencrypt/second", tarfile.LNKTYPE, "letsencrypt/sub/first"),
        )

    def test_repeated_member_name(self):
        # The later entry replaces the symlink on extraction; checks keyed by
        # name must not be fooled into following the wrong one.
        self.assert_rejected(
            "duplicate member",
            ("letsencrypt/deep/nested", tarfile.DIRTYPE, ""),
            ("letsencrypt/deep/nested/s", tarfile.SYMTYPE, "../../inside"),
            ("letsencrypt/b", tarfile.LNKTYPE, "letsencrypt/deep/nested/s"),
            ("letsencrypt/regular", tarfile.REGTYPE, ""),
            ("letsencrypt/deep/nested/s", tarfile.LNKTYPE, "letsencrypt/regular"),
        )

    def test_repeated_name_after_normalisation(self):
        self.assert_rejected(
            "duplicate member",
            ("letsencrypt/file", tarfile.REGTYPE, ""),
            ("./letsencrypt//file", tarfile.REGTYPE, ""),
        )

    def test_hardlink_to_regular_file_is_accepted(self):
        archive = self.build(
            ("letsencrypt/file", tarfile.REGTYPE, ""),
            ("letsencrypt/copy", tarfile.LNKTYPE, "letsencrypt/file"),
        )
        result = check(archive, "letsencrypt")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ARCHIVE_TOPS ["letsencrypt"]', result.stdout)

    def test_top_level_entry_must_be_directory(self):
        self.assert_rejected("not a directory", ("letsencrypt", tarfile.REGTYPE, ""))

    def test_member_below_symlink(self):
        self.assert_rejected(
            "below a symlink",
            ("letsencrypt/link", tarfile.SYMTYPE, "live"),
            ("letsencrypt/link/x", tarfile.REGTYPE, ""),
        )

    def test_device_member(self):
        self.assert_rejected("unsupported", ("letsencrypt/dev", tarfile.CHRTYPE, ""))

    def test_empty_archive(self):
        self.assert_rejected("no members")


class RoleWiringTests(unittest.TestCase):
    def test_no_restore_role_unarchives_into_root(self):
        offenders = []
        for file in ROOT.glob("roles/*_restore/tasks/*.yml"):
            for task in flatten(yaml.safe_load(file.read_text())):
                for key in ("ansible.builtin.unarchive", "unarchive"):
                    if str(task.get(key, {}).get("dest", "")).strip() == "/":
                        offenders.append(f"{file.relative_to(ROOT)}: {task.get('name')}")
        defaults = (ROOT / "roles/certbot_dns_restore/defaults/main.yml").read_text()
        self.assertNotIn("certbot_dns_restore_dest", defaults)
        self.assertEqual(offenders, [])

    def test_certbot_and_mail_config_use_staged_replacement(self):
        for path in (
            "roles/certbot_dns_restore/tasks/main.yml",
            "roles/mail_restore/tasks/main.yml",
        ):
            self.assertIn(
                "restore_preserve_internal/tasks/replace_from_archive.yml",
                (ROOT / path).read_text(),
                path,
            )

    def test_mail_config_members_checked_before_services_stop(self):
        tasks = flatten(
            yaml.safe_load((ROOT / "roles/mail_restore/tasks/main.yml").read_text())
        )
        names = [task.get("name") for task in tasks]
        self.assertLess(
            names.index("Validate configuration archive members before stopping services"),
            names.index("Stop mail services"),
        )

    def test_replacement_validates_before_extracting_and_keeps_copies(self):
        tasks = flatten(
            yaml.safe_load(
                (
                    ROOT
                    / "roles/restore_preserve_internal/tasks/replace_from_archive.yml"
                ).read_text()
            )
        )
        names = [task.get("name", "") for task in tasks]
        self.assertLess(
            names.index(
                "replace_from_archive | Validate archive members before any live change"
            ),
            names.index("replace_from_archive | Extract archive into staging"),
        )
        for task in tasks:
            if task.get("ansible.builtin.file", {}).get("state") == "absent":
                self.assertIn("staging", str(task))
                self.assertNotIn("pre-restore", str(task))

    def test_replaced_directory_takes_metadata_from_the_pre_restore_copy(self):
        # Emptying a copied mount point resets its mode and owner, so both the
        # renamed and the copied pre-restore copy are the metadata reference.
        tasks = yaml.safe_load(
            (
                ROOT
                / "roles/restore_preserve_internal/tasks/replace_from_archive_top.yml"
            ).read_text()
        )
        move = next(task for task in tasks if "ansible.builtin.shell" in task)
        reference = " ".join(move["environment"]["REF"].split())
        self.assertIn(
            "restore_preserve_report.path if restore_preserve_report.method in "
            "['rename', 'copy']",
            reference,
        )


if __name__ == "__main__":
    unittest.main()
