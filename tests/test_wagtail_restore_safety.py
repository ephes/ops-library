"""Safety contracts for the Wagtail restore role (weeknotes.home).

The role used to stop the web service with `failed_when: false`, drop the
live database and restore an unchecked plain SQL dump without a single
transaction; its rescue only restarted the services. These tests pin the
safer order: validate the dump, stop (fail closed), take a safety dump,
restore in one transaction with ON_ERROR_STOP, and roll back to the safety
dump with the units left stopped. The shell snippets run here against temp
files and stub binaries, so nothing touches a host or a database.
"""

from __future__ import annotations

import gzip
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "wagtail_restore"


def load_tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))


def flatten(tasks: list[dict], sections: tuple[str, ...] = ("block", "rescue", "always")) -> list[dict]:
    flat: list[dict] = []
    for task in tasks:
        nested = False
        for section in ("block", "rescue", "always"):
            if section in task:
                nested = True
                if section in sections:
                    flat.extend(flatten(task[section], sections))
        if not nested:
            flat.append(task)
    return flat


def find(tasks: list[dict], name: str) -> dict:
    for task in tasks:
        if task.get("name") == name:
            return task
        for section in ("block", "rescue", "always"):
            for child in task.get(section, []):
                try:
                    return find([child], name)
                except KeyError:
                    pass
    raise KeyError(name)


def index_of(tasks: list[dict], name: str) -> int:
    for index, task in enumerate(tasks):
        if task.get("name") == name:
            return index
    raise AssertionError(f"task {name!r} not found")


def shell_cmd(task: dict) -> str:
    shell = task["ansible.builtin.shell"]
    return shell["cmd"] if isinstance(shell, dict) else shell


def write_stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class WagtailRestoreOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = load_tasks()
        self.main = flatten(self.tasks, ("block",))

    def test_validation_and_safety_dump_precede_the_drop(self) -> None:
        main = self.main
        validate = index_of(main, "Validate the database dump")
        stop_aux = index_of(main, "Stop auxiliary Wagtail units before restore")
        stop = index_of(main, "Stop Wagtail service before restore")
        confirm = index_of(main, "Confirm Wagtail units are stopped")
        safety_dump = index_of(main, "Take safety dump of the live database")
        check_safety = index_of(main, "Check the safety dump")
        drop = index_of(main, "Drop Wagtail database")
        restore = index_of(main, "Restore PostgreSQL dump")
        start = index_of(main, "Start Wagtail service after restore")

        self.assertLess(validate, stop_aux)
        self.assertLess(stop_aux, stop)
        self.assertLess(stop, confirm)
        self.assertLess(confirm, safety_dump)
        self.assertLess(safety_dump, check_safety)
        self.assertLess(check_safety, drop)
        self.assertLess(drop, restore)
        self.assertLess(restore, start)

        self.assertEqual(main[drop]["community.postgresql.postgresql_db"]["state"], "absent")
        dump_argv = main[safety_dump]["ansible.builtin.command"]["argv"]
        self.assertIn("--format=custom", dump_argv)

        restore_cmd = shell_cmd(main[restore])
        self.assertIn("--single-transaction", restore_cmd)
        self.assertIn("ON_ERROR_STOP=1", restore_cmd)

        validation = shell_cmd(main[validate])
        self.assertIn("gzip -t", validation)
        self.assertIn("PostgreSQL database dump complete", validation)

    def test_validation_runs_in_dry_run_and_destruction_does_not(self) -> None:
        outer = find(self.tasks, "Restore with staging cleanup")
        top_names = [task["name"] for task in outer["block"]]
        self.assertIn("Validate the database dump", top_names)
        self.assertNotIn("when", find(self.tasks, "Validate the database dump"))
        destructive = find(self.tasks, "Restore the database")
        self.assertEqual(destructive["when"], "not wagtail_restore_dry_run | bool")
        self.assertLess(top_names.index("Validate the database dump"), top_names.index("Restore the database"))

    def test_no_failure_is_swallowed_before_or_during_the_restore(self) -> None:
        for task in self.main:
            self.assertNotEqual(task.get("failed_when"), False, task.get("name"))
            self.assertNotIn("ignore_errors", task, task.get("name"))
        confirm = find(self.tasks, "Confirm Wagtail units are stopped")
        self.assertIn("not in ['inactive', 'failed']", confirm["failed_when"])
        # The confirmation is not gated on wagtail_restore_stop_service.
        self.assertNotIn("when", confirm)

    def test_rescue_restores_the_safety_dump_and_never_starts(self) -> None:
        block = find(self.tasks, "Restore Wagtail with rollback")
        names = [task["name"] for task in block["rescue"]]
        self.assertIn("Roll back the database from the safety dump", names)
        for task in block["rescue"]:
            systemd = task.get("ansible.builtin.systemd")
            if systemd and "state" in systemd:
                self.assertEqual(systemd["state"], "stopped")
        rollback = shell_cmd(block["rescue"][names.index("Roll back the database from the safety dump")])
        self.assertIn("$SAFETY_DUMP", rollback)
        self.assertIn("--single-transaction", rollback)
        final = block["rescue"][-1]["ansible.builtin.fail"]["msg"]
        self.assertIn("Safety dump:", final)
        self.assertIn("left stopped", final)

        guard = find(self.tasks, "Stop units and take the safety dump")
        self.assertEqual(len(guard["rescue"]), 1)
        self.assertIn("ansible.builtin.fail", guard["rescue"][0])

        outer = find(self.tasks, "Restore with staging cleanup")
        self.assertEqual([task["name"] for task in outer["always"]], ["Cleanup restore staging directory"])

    def test_defaults(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
        self.assertTrue(defaults["wagtail_restore_safety_root"].startswith("/"))
        self.assertTrue(defaults["wagtail_restore_dry_run"] is False)


class WagtailRestoreScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.log"
        tasks = load_tasks()
        self.validate = shell_cmd(find(tasks, "Validate the database dump"))
        self.restore = shell_cmd(find(tasks, "Restore PostgreSQL dump"))
        self.rollback = shell_cmd(find(tasks, "Roll back the database from the safety dump"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        full_env = {"PATH": f"{self.bin}:{os.environ['PATH']}", **env}
        return subprocess.run(["bash", "-c", script], env=full_env, capture_output=True, text=True, check=False)

    def dump(self, body: bytes, truncate: int = 0) -> Path:
        path = self.root / "db.sql.gz"
        data = gzip.compress(body)
        path.write_bytes(data[: len(data) - truncate] if truncate else data)
        return path

    COMPLETE = (
        b"--\n-- PostgreSQL database dump\n--\n\nCREATE TABLE t (id int);\nCOPY t (id) FROM stdin;\n1\n\\.\n\n"
        b"--\n-- PostgreSQL database dump complete\n--\n\n\\unrestrict abc\n\n"
    )

    def test_validation_accepts_a_complete_dump(self) -> None:
        result = self.run_script(self.validate, {"DUMP": str(self.dump(self.COMPLETE))})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validation_rejects_a_dump_without_trailer(self) -> None:
        body = self.COMPLETE.split(b"--\n-- PostgreSQL database dump complete")[0]
        result = self.run_script(self.validate, {"DUMP": str(self.dump(body))})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incomplete", result.stderr)

    def test_validation_rejects_a_truncated_gzip(self) -> None:
        result = self.run_script(self.validate, {"DUMP": str(self.dump(self.COMPLETE * 50, truncate=12))})
        self.assertNotEqual(result.returncode, 0)

    def test_restore_pipes_into_one_transaction(self) -> None:
        write_stub(
            self.bin,
            "fake_psql",
            f'printf "%s\\n" "$@" > "{self.log}"\ncat > "{self.root}/stdin.sql"\n',
        )
        env = {
            "PG_HOST": "localhost",
            "PG_PORT": "",
            "PSQL": "fake_psql",
            "DUMP": str(self.dump(self.COMPLETE)),
            "DB": "weeknotes_home",
            "DB_USER": "weeknotes_home",
            "TARGET_OPTS": "",
        }
        result = self.run_script(self.restore, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.log.read_text().splitlines()
        self.assertIn("--single-transaction", args)
        self.assertIn("ON_ERROR_STOP=1", args)
        self.assertIn("--host=localhost", args)
        self.assertFalse(any(a.startswith("--port") for a in args))
        self.assertIn("--dbname=weeknotes_home", args)
        self.assertEqual((self.root / "stdin.sql").read_bytes(), self.COMPLETE)

    def test_restore_fails_when_psql_fails(self) -> None:
        write_stub(self.bin, "fake_psql", "cat >/dev/null\nexit 3\n")
        env = {
            "PG_HOST": "",
            "PG_PORT": "5432",
            "PSQL": "fake_psql",
            "DUMP": str(self.dump(self.COMPLETE)),
            "DB": "db",
            "DB_USER": "u",
            "TARGET_OPTS": "--echo-errors",
        }
        self.assertNotEqual(self.run_script(self.restore, env).returncode, 0)

    def test_rollback_recreates_the_database_from_the_safety_dump(self) -> None:
        for name in ("fake_dropdb", "fake_createdb", "fake_pg_restore"):
            write_stub(
                self.bin,
                name,
                f'echo "{name} PGPASSWORD=${{PGPASSWORD-unset}} $*" >> "{self.log}"\n',
            )
        env = {
            "ADMIN_PASSWORD": "admin-pw",
            "OWNER_PASSWORD": "owner-pw",
            "ADMIN_USER": "admin",
            "DROPDB": "fake_dropdb",
            "CREATEDB": "fake_createdb",
            "PG_RESTORE": "fake_pg_restore",
            "DB": "weeknotes_home",
            "DB_OWNER": "weeknotes_home",
            "SAFETY_DUMP": "/var/backups/x/weeknotes_home.dump",
            "PG_HOST": "localhost",
            "PG_PORT": "",
        }
        result = self.run_script(self.rollback, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text().splitlines()
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0].startswith("fake_dropdb PGPASSWORD=admin-pw --host=localhost --username=admin"))
        self.assertIn("--if-exists", calls[0])
        self.assertIn("fake_createdb PGPASSWORD=admin-pw", calls[1])
        self.assertIn("--owner=weeknotes_home weeknotes_home", calls[1])
        self.assertIn("fake_pg_restore PGPASSWORD=owner-pw", calls[2])
        self.assertIn("--single-transaction", calls[2])
        self.assertTrue(calls[2].endswith("/var/backups/x/weeknotes_home.dump"))

    def test_rollback_stops_at_the_first_failure(self) -> None:
        write_stub(self.bin, "fake_dropdb", "exit 1\n")
        write_stub(self.bin, "fake_createdb", f'echo createdb >> "{self.log}"\n')
        env = {
            "ADMIN_PASSWORD": "",
            "OWNER_PASSWORD": "pw",
            "ADMIN_USER": "admin",
            "DROPDB": "fake_dropdb",
            "CREATEDB": "fake_createdb",
            "PG_RESTORE": "true",
            "DB": "db",
            "DB_OWNER": "db",
            "SAFETY_DUMP": "/x.dump",
            "PG_HOST": "",
            "PG_PORT": "",
        }
        self.assertNotEqual(self.run_script(self.rollback, env).returncode, 0)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
