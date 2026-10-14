import unittest

from tests.credential_helpers import assert_env_source


class CredentialTests(unittest.TestCase):
    def test_source_env_file(self):
        assert_env_source(
            self,
            "fastdeploy_deploy",
            "initialize.yml",
            "fastdeploy.env.j2",
            "fastdeploy_secret_key",
            "SECRET_KEY",
            2,
        )

    def test_initial_hash_is_read_from_stdin(self):
        import subprocess
        import tempfile
        from pathlib import Path

        from tests.credential_helpers import ENV, tasks

        task = next(
            t
            for t in tasks("fastdeploy_deploy", "initialize.yml")
            if t.get("name") == "initialize | Create initial admin user"
        )
        module = task["ansible.builtin.shell"]
        self.assertEqual(module["stdin"], "{{ fastdeploy_initial_password_hash }}")
        self.assertNotIn("INITIAL_PASSWORD_HASH", task.get("environment", {}))
        self.assertNotIn("DATABASE_URL", task.get("environment", {}))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env.shell").write_text(
                "SECRET_KEY='key$'\nDATABASE_URL='db:$'\n"
            )
            shell = ENV.from_string(module["cmd"]).render(
                fastdeploy_site_path=tmp, fastdeploy_venv_bin=tmp
            )
            prefix = shell[: shell.index("exec ")]
            value = "$2b$12$hash with ' quotes"
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    prefix
                    + 'printf "%s|%s|%s" "$INITIAL_PASSWORD_HASH" "$SECRET_KEY" "$DATABASE_URL"',
                ],
                input=value + "\n",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, value + "|key$|db:$")
