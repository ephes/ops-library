"""Execute the real role cleanup tasks on temporary source files."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROLES = Path(__file__).resolve().parents[1] / "roles"
PG = """Types: deb
URIs: https://apt.postgresql.org/pub/repos/apt
Suites: trixie-pgdg
Components: main
Signed-By: /etc/apt/keyrings/postgresql.asc
"""
VECTOR = """Types: deb
URIs: https://apt.vector.dev
Suites: stable
Components: vector-0
Signed-By: /usr/share/keyrings/datadog-archive-keyring.gpg
"""
OTHER = """Types: deb
URIs: https://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
"""


class AptRepositoryCleanupTests(unittest.TestCase):
    def test_exact_migration_preserves_other_stanzas_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "consolidated.sources"
            # Partial matches, extra fields, disabled sources, another suite,
            # and another signing key must all survive byte for byte.
            retained = (
                OTHER
                + "\n"
                + "\n".join(
                    [
                        "Enabled: no\n" + PG,
                        PG + "Architectures: arm64\n",
                        PG.replace("trixie-pgdg", "bookworm-pgdg"),
                        VECTOR.replace("datadog-archive-keyring", "other-keyring"),
                    ]
                )
            )
            original = PG + "\n" + retained + "\n" + VECTOR
            legacy.write_text(original)
            pg_canonical = root / "postgresql.sources"
            pg_canonical.write_text("Enabled: yes\n" + PG)
            vector_canonical = root / "vector.list"
            vector_canonical.write_text(
                "deb [signed-by=/usr/share/keyrings/datadog-archive-keyring.gpg] "
                "https://apt.vector.dev/ stable vector-0\n"
            )
            tasks = []
            for repeat in range(2):
                for role, canonical in (
                    ("postgres_install", pg_canonical),
                    ("vector_apt_install", vector_canonical),
                ):
                    tasks.append(
                        {
                            "name": f"Run {role} cleanup pass {repeat}",
                            "ansible.builtin.include_role": {
                                "name": str(ROLES / role),
                                "tasks_from": "repo_cleanup.yml",
                            },
                            "vars": {
                                "_repo_canonical_path": str(canonical),
                                f"{role}_repo_legacy_deb822_files": [
                                    str(legacy),
                                    str(root / "absent.sources"),
                                ],
                                "postgres_install_repo_codename": "trixie",
                            },
                        }
                    )
                    if repeat:
                        tasks.append(
                            {
                                "name": "Assert repeated cleanup changes nothing",
                                "ansible.builtin.assert": {
                                    "that": ["not _repo_cleanup_result.changed"],
                                },
                            }
                        )
            self._run(root, tasks)
            self.assertEqual(legacy.read_text(), "\n" + retained + "\n")
            self.assertEqual(pg_canonical.read_text(), "Enabled: yes\n" + PG)
            self.assertEqual(len(list(root.glob("consolidated.sources.*~"))), 2)

    def test_missing_managed_repository_refuses_to_remove_legacy_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.sources"
            legacy.write_text(PG)
            tasks = [
                {
                    "name": "Cleanup requires its managed replacement",
                    "ansible.builtin.include_role": {
                        "name": str(ROLES / "postgres_install"),
                        "tasks_from": "repo_cleanup.yml",
                    },
                    "vars": {
                        "_repo_canonical_path": str(root / "missing.sources"),
                        "postgres_install_repo_legacy_deb822_files": [str(legacy)],
                        "postgres_install_repo_codename": "trixie",
                    },
                }
            ]
            self._run(root, tasks, success=False)
            self.assertEqual(legacy.read_text(), PG)

    def _run(self, root, tasks, success=True):
        playbook = root / "test.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "name": "Repository cleanup fixture",
                        "hosts": "localhost",
                        "gather_facts": False,
                        "vars": {"ansible_become": False},
                        "tasks": tasks,
                    }
                ]
            )
        )
        cli = shutil.which("ansible-playbook")
        self.assertIsNotNone(cli, "ansible-playbook is required")
        result = subprocess.run(
            [cli, "-i", "localhost,", "-c", "local", str(playbook)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
