"""Execute production passfile lifetime blocks against fake clients, without databases."""

import copy
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]


def walk(nodes):
    for task in nodes:
        yield task
        for key in ["block", "rescue", "always"]:
            yield from walk(task.get(key, []))


class ModuleTransportTests(unittest.TestCase):
    def test_empty_password_private_file_and_rollback_failures(self):
        source = yaml.safe_load(
            (root / "roles/mastodon_restore/tasks/main.yml").read_text()
        )
        wrapper = next(
            t
            for t in walk(source)
            if t.get("name", "").startswith("main | Run Roll back the database")
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client = directory / "fake-postgres"
            client.write_text(
                "#!"
                + sys.executable
                + '\nimport json,os,stat\np=os.getenv("PGPASSFILE")\nprint(json.dumps({"passfile":p, "body":open(p).read() if p else "", "mode":stat.S_IMODE(os.stat(p).st_mode) if p else 0, "owner":os.stat(p).st_uid == os.geteuid() if p else True}))\n'
            )
            client.chmod(0o700)
            for case, password in [
                ("empty", ""),
                ("normal", r"p:a\ss"),
                ("allocation-failure", "fixture"),
                ("cleanup-failure", "fixture"),
            ]:
                block = copy.deepcopy(wrapper)
                for task in walk([block]):
                    if "become" in task:
                        task["become"] = False
                    if "args" in task and "executable" in task["args"]:
                        task["args"]["executable"] = (
                            "/opt/homebrew/bin/bash"
                            if Path("/opt/homebrew/bin/bash").exists()
                            else "/bin/bash"
                        )
                    if "ansible.builtin.tempfile" in task:
                        task["ansible.builtin.tempfile"]["path"] = tmp
                    if "ansible.builtin.template" in task:
                        task["ansible.builtin.template"]["src"] = str(
                            root / "roles/mastodon_restore/templates/task-pgpass.j2"
                        )
                if case == "allocation-failure":
                    task = next(
                        t for t in block["block"] if "ansible.builtin.tempfile" in t
                    )
                    task.pop("ansible.builtin.tempfile")
                    task["ansible.builtin.fail"] = {"msg": "fixture allocation failure"}
                if case == "cleanup-failure":
                    task = block["always"][0]
                    task.pop("ansible.builtin.file")
                    task["ansible.builtin.fail"] = {"msg": "fixture cleanup failure"}
                next(
                    t["register"]
                    for t in block["block"]
                    if t.get("register", "").endswith("pgpass_6")
                )
                check = [
                    "remaining_rollback_reached | bool",
                    "mastodon_restore_db_rollback.rc == "
                    + ("1" if case == "allocation-failure" else "0"),
                ]
                if case in ["empty", "normal"]:
                    check += [
                        "(mastodon_restore_db_rollback.stdout_lines | first | from_json).body == expected_body",
                        "(mastodon_restore_db_rollback.stdout_lines | first | from_json).owner | bool",
                        "(mastodon_restore_db_rollback.stdout_lines | first | from_json).mode == "
                        + ("384" if password else "0"),
                    ]
                variables = {
                    "ansible_python_interpreter": sys.executable,
                    "mastodon_restore_postgres_password": password,
                    "mastodon_restore_postgres_become_user": os.environ["USER"],
                    "mastodon_restore_db_exists": True,
                    "mastodon_restore_rescue_running": False,
                    "mastodon_restore_postgres_dropdb_binary": str(client),
                    "mastodon_restore_postgres_createdb_binary": str(client),
                    "mastodon_restore_postgres_restore_binary": str(client),
                    "mastodon_restore_postgres_database": "fixture",
                    "mastodon_restore_postgres_user": "fixture",
                    "mastodon_restore_safety_dump": str(directory / "fake.dump"),
                    "mastodon_restore_postgres_host": "",
                    "mastodon_restore_postgres_port": "",
                    "expected_body": (r"*:*:*:*:p\:a\\ss" + "\n" if password else ""),
                }
                play = [
                    {
                        "name": "Private passfile fixture",
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": variables,
                        "tasks": [
                            block,
                            {
                                "name": "Reached remaining rollback",
                                "ansible.builtin.set_fact": {
                                    "remaining_rollback_reached": True
                                },
                            },
                            {
                                "name": "Assert fixture result",
                                "ansible.builtin.assert": {"that": check},
                            },
                        ],
                    }
                ]
                file = directory / "fixture.yml"
                file.write_text(yaml.safe_dump(play, sort_keys=False))
                env = os.environ.copy()
                env.pop("PGPASSFILE", None)
                env.pop("PGPASSWORD", None)
                result = subprocess.run(
                    [
                        str(root / ".venv/bin/ansible-playbook"),
                        "-i",
                        "localhost,",
                        "-c",
                        "local",
                        str(file),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode, 0, result.stdout[-7000:] + result.stderr
                )
