import unittest

from tests.credential_helpers import assert_env_source


class CredentialTests(unittest.TestCase):
    def test_source_env_file(self):
        assert_env_source(
            self,
            "archive_deploy",
            "django.yml",
            "archive.env.j2",
            "archive_django_secret_key",
            "DJANGO_SECRET_KEY",
            3,
        )

    def test_shell_companion_survives_deleting_source_sync(self):
        import subprocess
        import tempfile
        from pathlib import Path

        from tests.credential_helpers import ENV, tasks

        sync = next(
            t
            for t in tasks("archive_deploy", "source_rsync.yml")
            if "ansible.posix.synchronize" in t
        )
        with tempfile.TemporaryDirectory() as tmp:
            source, site = Path(tmp) / "source", Path(tmp) / "site"
            source.mkdir()
            site.mkdir()
            (source / "manage.py").write_text("fixture")
            companion = site / ".env.shell"
            companion.write_text("fixture")
            opts = [
                ENV.from_string(option).render(
                    archive_site_path=str(site), archive_env_path=str(site / ".env")
                )
                for option in sync["ansible.posix.synchronize"]["rsync_opts"]
            ]
            result = subprocess.run(
                ["rsync", "-a", "--delete", *opts, str(source) + "/", str(site) + "/"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(companion.exists())
            result = subprocess.run(
                [
                    "rsync",
                    "-ani",
                    "--delete",
                    *opts,
                    str(source) + "/",
                    str(site) + "/",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
