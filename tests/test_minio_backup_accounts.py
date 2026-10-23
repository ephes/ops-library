"""Contracts for per-target MinIO backup accounts and their mc aliases.

A backup target gets a MinIO user limited to its own key prefix
(`minio_deploy`, tasks_from backup_account) and an mc alias imported from stdin
(`echoport_backup`, tasks_from minio_alias). No credential may reach a command
line, where the host's process list shows it.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

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
    env.filters["to_json"] = json.dumps
    context = {
        "minio_backup_account_bucket": "backups",
        "minio_backup_account_prefixes": ["delve"],
        "minio_backup_account_allow_delete": False,
        "minio_backup_account_allow_put": True,
        "minio_backup_account_whole_bucket": False,
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

    def test_retention_account_reads_and_deletes_the_whole_bucket_but_never_writes(self):
        policy = render_policy(
            minio_backup_account_whole_bucket=True,
            minio_backup_account_allow_delete=True,
            minio_backup_account_allow_put=False,
        )
        location, listing, objects = policy["Statement"]
        self.assertEqual(location["Action"], ["s3:GetBucketLocation"])
        self.assertEqual(listing, {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": ["arn:aws:s3:::backups"]})
        self.assertEqual(objects["Action"], ["s3:GetObject", "s3:DeleteObject"])
        self.assertEqual(objects["Resource"], ["arn:aws:s3:::backups/*"])
        actions = [action for statement in policy["Statement"] for action in statement["Action"]]
        self.assertFalse([action for action in actions if "*" in action or "admin" in action])

    def test_whole_bucket_ignores_the_prefixes(self):
        policy = render_policy(minio_backup_account_whole_bucket=True, minio_backup_account_prefixes=["a", "b"])
        self.assertNotIn("Condition", policy["Statement"][1])
        self.assertEqual(policy["Statement"][2]["Resource"], ["arn:aws:s3:::backups/*"])

    def test_defaults_refuse_delete_and_derive_a_valid_user_name(self):
        defaults = yaml.safe_load((MINIO_ROLE / "defaults" / "main.yml").read_text())
        self.assertIs(defaults["minio_backup_account_allow_delete"], False)
        self.assertIs(defaults["minio_backup_account_allow_put"], True)
        self.assertIs(defaults["minio_backup_account_whole_bucket"], False)
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


class MediaRunnerTests(unittest.TestCase):
    """The rclone media runners work with a prefix-scoped account."""

    def test_only_the_manifest_upload_skips_the_destination_check(self):
        for name in ("homepage_media_backup.py.j2", "python_podcast_media_backup.py.j2"):
            with self.subTest(template=name):
                source = (BACKUP_ROLE / "templates" / name).read_text()
                # The manifest key is new on every run; `rclone copy` of the
                # objects must keep comparing, or every run uploads everything.
                self.assertEqual(source.count('"--no-check-dest"'), 1)
                manifest = source.index('f"dst:{bucket}/{key_prefix}/manifest.json",')
                self.assertGreater(source.index('"--no-check-dest"'), manifest)
                self.assertLess(source.index('"--no-check-dest"'), source.index("emit_step(\"snapshot_metadata\", \"success\""))


FAKE_MC = r"""#!/usr/bin/env python3
# Fake mc: knows the aliases in $FAKE_MC_ALIASES, stores "remote" objects
# below $FAKE_MC_REMOTE, logs every call to $FAKE_MC_LOG, and, like the real
# mc, treats a path whose first segment is no known alias as a local path.
import json, os, shutil, sys
args = sys.argv[1:]
with open(os.environ["FAKE_MC_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
aliases = json.loads(os.environ["FAKE_MC_ALIASES"])
remote = os.environ["FAKE_MC_REMOTE"]
def where(path):
    alias, _, rest = path.partition("/")
    return os.path.join(remote, alias, rest) if alias in aliases else path
if args[:3] == ["--json", "alias", "list"]:
    name = args[3]
    if name in aliases:
        print(json.dumps({"status": "success", "alias": name, "URL": "http://127.0.0.1:9000",
                          "accessKey": "AKFAKE", "secretKey": "SECRET-MUST-NOT-LEAK", "api": "s3v4", "path": "auto"}))
        sys.exit(0)
    print(json.dumps({"status": "error", "error": {"message": "No such alias `%s` found." % name}}))
    sys.exit(1)
if args[0] == "cp":
    dst = where(args[2])
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copyfile(where(args[1]), dst)
    sys.exit(0)
if args[0] == "stat":
    sys.exit(0 if os.path.exists(where(args[1])) else 1)
sys.exit(2)
"""


class GenericRunnerAliasTests(unittest.TestCase):
    """The generic runner picks the key's alias and fails closed without it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.workdir = self.tmp / "cwd"
        self.remote = self.tmp / "remote"
        self.data = self.tmp / "data"
        for path in (self.workdir, self.remote, self.data):
            path.mkdir()
        (self.data / "state.txt").write_text("state\n")
        self.mc = self.tmp / "mc"
        self.mc.write_text(FAKE_MC)
        self.mc.chmod(0o755)
        self.log = self.tmp / "mc.log"
        self.log.touch()

    def render(self, aliases: dict, require: bool = False) -> str:
        env = Environment(loader=FileSystemLoader(BACKUP_ROLE / "templates"))
        env.filters["to_json"] = json.dumps
        env.filters["bool"] = to_bool
        defaults = yaml.safe_load((BACKUP_ROLE / "defaults" / "main.yml").read_text())
        defaults["echoport_backup_minio_prefix_aliases"] = aliases
        defaults["echoport_backup_minio_require_prefix_alias"] = require
        defaults["echoport_backup_mc_install_path"] = str(self.mc)
        defaults["echoport_backup_allowed_roots"] = [str(self.data)]
        return env.get_template("backup.py.j2").render(**defaults)

    def load(self, aliases: dict, require: bool = False) -> types.ModuleType:
        module = types.ModuleType("echoport_generic_runner")
        exec(compile(self.render(aliases, require), "backup.py", "exec"), module.__dict__)  # noqa: S102
        # The external work dir check (_work_dir.py.j2) is covered by
        # test_echoport_runner_work_dirs; here run dirs go to the test tree.
        work = self.tmp / "work"

        def create_run_dir(prefix: str) -> Path:
            work.mkdir(exist_ok=True)
            return Path(tempfile.mkdtemp(prefix=prefix, dir=work))

        module.create_run_dir = create_run_dir
        return module

    def run_action(self, module, known_aliases: list[str], cenv: dict) -> tuple[int, str, str]:
        env = {
            "FAKE_MC_ALIASES": json.dumps(known_aliases),
            "FAKE_MC_REMOTE": str(self.remote),
            "FAKE_MC_LOG": str(self.log),
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.workdir)
        try:
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                if cenv.get("ECHOPORT_ACTION") == "restore":
                    rc = module.main_restore(None, {}, cenv)
                else:
                    rc = module.main_backup(None, {}, cenv)
        finally:
            os.chdir(cwd)
        return rc, stdout.getvalue(), stderr.getvalue()

    def backup(self, module, known_aliases: list[str], target: str = "radarr"):
        return self.run_action(module, known_aliases, {
            "ECHOPORT_TARGET": target,
            "ECHOPORT_KEY_PREFIX": f"{target}/2026-10-19T02-00-00",
            "ECHOPORT_BACKUP_FILES": str(self.data / "state.txt"),
        })

    def mc_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def local_files(self) -> list[Path]:
        return [path for path in self.workdir.rglob("*") if path.is_file()]

    def test_rendered_script_compiles(self):
        compile(self.render({"nyxmon": "backup-nyxmon"}), "backup.py", "exec")
        self.assertIn("MINIO_REQUIRE_PREFIX_ALIAS = False", self.render({}))
        self.assertIn("MINIO_REQUIRE_PREFIX_ALIAS = True", self.render({}, require=True))

    def test_alias_follows_the_first_key_segment(self):
        module = self.load({"nyxmon": "backup-nyxmon"})
        self.assertEqual(module.minio_alias_for("nyxmon/2026-10-13T02-00-00.tar.gz"), "backup-nyxmon")
        self.assertEqual(module.minio_alias_for("homelab/2026-10-13T02-00-00.tar.gz"), "minio")
        self.assertEqual(module.minio_alias_for("nyxmon-other/x.tar.gz"), "minio")

    def test_default_keeps_the_single_alias(self):
        source = self.render({})
        self.assertIn("MINIO_PREFIX_ALIASES = {}", source)
        self.assertEqual(self.load({}).minio_alias_for("nyxmon/x.tar.gz"), "minio")
        self.assertNotIn("{MINIO_ALIAS}", source)

    def test_missing_fallback_alias_fails_and_writes_nothing_locally(self):
        # 2026-10-19: radarr had no entry and root no longer had `minio`.
        module = self.load({"nyxmon": "backup-nyxmon"})
        rc, stdout, stderr = self.backup(module, ["backup-nyxmon"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.local_files(), [])
        self.assertEqual([call for call in self.mc_calls() if call[0] in ("cp", "stat")], [])
        self.assertIn("mc alias 'minio'", stdout)
        self.assertIn("key prefix 'radarr'", stdout)
        self.assertIn('\\"success\\": false', stdout)
        self.assertNotIn("SECRET-MUST-NOT-LEAK", stdout + stderr)

    def test_missing_prefix_alias_fails_and_writes_nothing_locally(self):
        module = self.load({"radarr": "backup-radarr"})
        rc, stdout, _ = self.backup(module, ["minio"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.local_files(), [])
        self.assertIn("mc alias 'backup-radarr'", stdout)
        self.assertNotIn(["cp"], [call[:1] for call in self.mc_calls()])

    def test_known_prefix_uploads_and_verifies_with_its_alias(self):
        module = self.load({"radarr": "backup-radarr"})
        rc, stdout, stderr = self.backup(module, ["backup-radarr", "minio"])
        self.assertEqual(rc, 0, stderr)
        self.assertEqual(self.local_files(), [])
        key = "backup-radarr/backups/radarr/2026-10-19T02-00-00.tar.gz"
        calls = self.mc_calls()
        self.assertEqual([call[0] for call in calls if call[0] in ("cp", "stat")], ["cp", "stat"])
        self.assertEqual([call for call in calls if call[0] == "cp"][0][2], key)
        self.assertEqual([call for call in calls if call[0] == "stat"][0], ["stat", key])
        self.assertTrue((self.remote / key).is_file())
        self.assertNotIn("SECRET-MUST-NOT-LEAK", stdout + stderr)

    def test_alias_is_checked_again_right_before_upload_and_stat(self):
        module = self.load({"radarr": "backup-radarr"})
        self.backup(module, ["backup-radarr"])
        calls = self.mc_calls()
        for index, call in enumerate(calls):
            if call[0] in ("cp", "stat"):
                self.assertEqual(calls[index - 1], ["--json", "alias", "list", "backup-radarr"])

    def test_required_prefix_alias_refuses_the_shared_fallback(self):
        module = self.load({"nyxmon": "backup-nyxmon"}, require=True)
        rc, stdout, _ = self.backup(module, ["backup-nyxmon", "minio"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.local_files(), [])
        self.assertIn("key prefix 'radarr'", stdout)
        self.assertNotIn(["cp"], [call[:1] for call in self.mc_calls()])

    def test_invalid_alias_name_is_refused(self):
        module = self.load({"radarr": "../radarr"})
        rc, _, _ = self.backup(module, ["../radarr"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.mc_calls(), [])

    def test_restore_download_is_guarded(self):
        module = self.load({"nyxmon": "backup-nyxmon"})
        # A stale local copy at the would-be path must not be restored.
        stale = self.workdir / "minio" / "backups" / "radarr" / "x.tar.gz"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"stale")
        rc, stdout, _ = self.run_action(module, ["backup-nyxmon"], {
            "ECHOPORT_ACTION": "restore",
            "ECHOPORT_TARGET": "radarr",
            "ECHOPORT_KEY": "radarr/x.tar.gz",
            "ECHOPORT_CHECKSUM": hashlib.sha256(b"stale").hexdigest(),
            "ECHOPORT_BACKUP_FILES": str(self.data / "state.txt"),
        })
        self.assertEqual(rc, 1)
        self.assertIn("mc alias 'minio'", stdout)
        self.assertEqual([call for call in self.mc_calls() if call[0] == "cp"], [])
        self.assertEqual((self.data / "state.txt").read_text(), "state\n")

    def test_download_function_is_guarded_on_its_own(self):
        module = self.load({})
        dest = self.tmp / "download.tar.gz"
        env = {"FAKE_MC_ALIASES": "[]", "FAKE_MC_REMOTE": str(self.remote), "FAKE_MC_LOG": str(self.log)}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertFalse(module.download_from_minio("backups", "radarr/x.tar.gz", dest))
            self.assertFalse(module.upload_to_minio(self.data / "state.txt", "backups", "radarr/x.tar.gz"))
        self.assertFalse(dest.exists())
        self.assertIn("mc alias 'minio'", stderr.getvalue())
        self.assertEqual([call[0] for call in self.mc_calls()], ["--json", "--json"])


if __name__ == "__main__":
    unittest.main()
