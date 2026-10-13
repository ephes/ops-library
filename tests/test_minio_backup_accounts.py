"""Contracts for per-target MinIO backup accounts and their mc aliases.

A backup target gets a MinIO user limited to its own key prefix
(`minio_deploy`, tasks_from backup_account) and an mc alias imported from stdin
(`echoport_backup`, tasks_from minio_alias). No credential may reach a command
line, where the host's process list shows it.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
MINIO_ROLE = ROOT / "roles" / "minio_deploy"
BACKUP_ROLE = ROOT / "roles" / "echoport_backup"
ACCOUNT_TASKS = MINIO_ROLE / "tasks" / "backup_account.yml"
ALIAS_TASKS = BACKUP_ROLE / "tasks" / "minio_alias.yml"


def tasks(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text())


def command_of(task: dict) -> dict | None:
    command = task.get("ansible.builtin.command")
    return command if isinstance(command, dict) else None


def render_policy(**overrides: object) -> dict:
    env = Environment(
        loader=FileSystemLoader(MINIO_ROLE / "templates"),
        undefined=StrictUndefined,
        trim_blocks=True,
    )
    env.filters["bool"] = to_bool
    context = {
        "minio_backup_account_bucket": "backups",
        "minio_backup_account_prefixes": ["delve"],
        "minio_backup_account_allow_delete": False,
    }
    context.update(overrides)
    return json.loads(env.get_template("backup-account-policy.json.j2").render(**context))


class BackupAccountPolicyTests(unittest.TestCase):
    def test_policy_is_limited_to_the_target_prefix(self):
        policy = render_policy()
        location, listing, objects = policy["Statement"]
        self.assertEqual(location["Action"], ["s3:GetBucketLocation"])
        self.assertEqual(location["Resource"], ["arn:aws:s3:::backups"])
        self.assertEqual(listing["Action"], ["s3:ListBucket"])
        self.assertEqual(listing["Resource"], ["arn:aws:s3:::backups"])
        self.assertEqual(listing["Condition"], {"StringLike": {"s3:prefix": ["delve/*"]}})
        self.assertEqual(objects["Action"], ["s3:GetObject", "s3:PutObject"])
        self.assertEqual(objects["Resource"], ["arn:aws:s3:::backups/delve/*"])
        self.assertTrue(all(statement["Effect"] == "Allow" for statement in policy["Statement"]))

    def test_policy_grants_no_delete_and_no_wildcard_action_by_default(self):
        actions = [action for statement in render_policy()["Statement"] for action in statement["Action"]]
        self.assertNotIn("s3:DeleteObject", actions)
        self.assertFalse([action for action in actions if "*" in action])

    def test_delete_is_opt_in(self):
        objects = render_policy(minio_backup_account_allow_delete=True)["Statement"][2]
        self.assertEqual(objects["Action"], ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"])

    def test_several_prefixes_render_valid_json(self):
        policy = render_policy(minio_backup_account_prefixes=["a", "b/c"])
        self.assertEqual(policy["Statement"][1]["Condition"]["StringLike"]["s3:prefix"], ["a/*", "b/c/*"])
        self.assertEqual(
            policy["Statement"][2]["Resource"],
            ["arn:aws:s3:::backups/a/*", "arn:aws:s3:::backups/b/c/*"],
        )

    def test_defaults_refuse_delete_and_derive_a_valid_user_name(self):
        defaults = yaml.safe_load((MINIO_ROLE / "defaults" / "main.yml").read_text())
        self.assertIs(defaults["minio_backup_account_allow_delete"], False)
        self.assertEqual(
            defaults["minio_backup_account_user"],
            "bk-{{ (minio_backup_account_name | hash('sha256'))[:17] }}",
        )
        # MinIO accepts user names of 3 to 20 characters.
        self.assertEqual(len("bk-" + hashlib.sha256(b"python-podcast-production-db").hexdigest()[:17]), 20)


class NoCredentialOnCommandLineTests(unittest.TestCase):
    def test_no_task_uses_alias_set(self):
        for path in (ACCOUNT_TASKS, ALIAS_TASKS, BACKUP_ROLE / "tasks" / "main.yml"):
            with self.subTest(path=path.name):
                for task in tasks(path):
                    command = command_of(task)
                    if command:
                        argv = command.get("argv", [])
                        self.assertFalse("alias" in argv and "set" in argv, task["name"])

    def test_secrets_never_appear_in_arguments(self):
        for path in (ACCOUNT_TASKS, ALIAS_TASKS):
            for task in tasks(path):
                command = command_of(task)
                if not command:
                    self.assertNotIn("ansible.builtin.shell", task, task["name"])
                    continue
                with self.subTest(task=task["name"]):
                    self.assertIn("argv", command)
                    arguments = " ".join(command["argv"])
                    self.assertNotIn("secret", arguments)
                    self.assertNotIn("access_key", arguments)
                    self.assertNotIn("password", arguments)

    def test_tasks_fed_on_stdin_hide_their_arguments(self):
        fed = []
        for path in (ACCOUNT_TASKS, ALIAS_TASKS):
            for task in tasks(path):
                command = command_of(task)
                if command and "stdin" in command:
                    fed.append(task["name"])
                    self.assertIs(task.get("no_log"), True, task["name"])
        self.assertEqual(
            fed,
            ["backup_account | Create or update backup account user", "minio_alias | Import mc alias from stdin"],
        )

    def test_policy_is_written_to_the_server_on_every_run(self):
        create = {task["name"]: task for task in tasks(ACCOUNT_TASKS)}[
            "backup_account | Create or update backup account policy"
        ]
        # A `when` would let a failed or hand-edited server policy survive.
        self.assertNotIn("when", create)
        self.assertEqual(create["ansible.builtin.command"]["argv"][1:4], ["admin", "policy", "create"])

    def test_alias_listing_is_hidden_and_never_looped_over_in_the_open(self):
        by_name = {task["name"]: task for task in tasks(ALIAS_TASKS)}
        self.assertIs(by_name["minio_alias | Read current mc alias"]["no_log"], True)
        # `mc alias list` prints the stored secret; the only task that loops
        # over its result must hide its items too.
        readers = [
            task["name"]
            for task in tasks(ALIAS_TASKS)
            if "echoport_backup_minio_alias_current" in str(task.get("loop", ""))
        ]
        self.assertEqual(readers, ["minio_alias | Import mc alias from stdin"])
        self.assertIs(by_name["minio_alias | Import mc alias from stdin"]["no_log"], True)

    def test_retired_aliases_are_removed_without_listing_them(self):
        remove = {task["name"]: task for task in tasks(ALIAS_TASKS)}["minio_alias | Remove retired mc aliases"]
        self.assertEqual(remove["ansible.builtin.command"]["argv"][1:3], ["alias", "remove"])
        self.assertIn("No such alias", str(remove["failed_when"]))

    def test_role_configures_its_alias_through_the_shared_tasks(self):
        main = {task["name"]: task for task in tasks(BACKUP_ROLE / "tasks" / "main.yml")}
        self.assertEqual(
            main["Configure mc alias for MinIO"]["ansible.builtin.include_tasks"], "minio_alias.yml"
        )


class GenericRunnerAliasTests(unittest.TestCase):
    def render(self, aliases: dict) -> str:
        env = Environment(loader=FileSystemLoader(BACKUP_ROLE / "templates"))
        env.filters["to_json"] = json.dumps
        defaults = yaml.safe_load((BACKUP_ROLE / "defaults" / "main.yml").read_text())
        defaults["echoport_backup_minio_prefix_aliases"] = aliases
        return env.get_template("backup.py.j2").render(**defaults)

    def alias_for(self, source: str, key: str) -> str:
        start = source.index("MINIO_ALIAS = ")
        end = source.index("def upload_to_minio")
        chosen = source[start : source.index("\n", start)] + "\n"
        chosen += source[source.index("MINIO_PREFIX_ALIASES = ") : source.index("\n", source.index("MINIO_PREFIX_ALIASES = "))]
        chosen += "\n" + source[source.index("def minio_alias_for") : end]
        namespace: dict = {}
        exec(chosen, namespace)  # noqa: S102 - rendered role template under test
        return namespace["minio_alias_for"](key)

    def test_rendered_script_compiles(self):
        compile(self.render({"nyxmon": "backup-nyxmon"}), "backup.py", "exec")

    def test_alias_follows_the_first_key_segment(self):
        source = self.render({"nyxmon": "backup-nyxmon"})
        self.assertEqual(self.alias_for(source, "nyxmon/2026-10-13T02-00-00.tar.gz"), "backup-nyxmon")
        self.assertEqual(self.alias_for(source, "homelab/2026-10-13T02-00-00.tar.gz"), "minio")
        self.assertEqual(self.alias_for(source, "nyxmon-other/x.tar.gz"), "minio")

    def test_default_keeps_the_single_alias(self):
        source = self.render({})
        self.assertIn("MINIO_PREFIX_ALIASES = {}", source)
        self.assertEqual(self.alias_for(source, "nyxmon/x.tar.gz"), "minio")
        self.assertNotIn("{MINIO_ALIAS}", source)


if __name__ == "__main__":
    unittest.main()
