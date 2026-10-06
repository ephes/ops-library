"""Static and behavioral checks that piped shell tasks do not hide failures.

Without ``set -o pipefail`` a shell pipeline returns the exit status of its
last command only, so ``pg_dump ... | gzip > dump.gz`` "succeeds" with an empty
dump when pg_dump fails. Every ``shell`` task under ``roles/*/tasks`` and
``roles/*/handlers`` that pipes one command into another must therefore set
``pipefail`` (and run under bash), unless it is listed in ``ALLOWED`` with the
reason the masked exit status does not matter.

The mail backup/restore tasks are also executed with stub binaries to prove
that a failed dump fails the task and never leaves a ``database.sql.gz``.
"""

import os
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"

SHELL_MODULES = {"shell", "ansible.builtin.shell", "ansible.legacy.shell"}

# Reviewed piped shell tasks whose masked upstream exit status is harmless.
# Key: (path relative to roles/, task name). Value: reason.
ALLOWED = {
    (
        "dns_deploy/tasks/configure_unbound_only.yml",
        "Check if Unbound service exists",
    ): "probe with failed_when: false; pipefail would turn grep -q's early exit "
    "(SIGPIPE in systemctl) into a false 'missing'",
    (
        "fastdeploy_backup/tasks/main.yml",
        "Check available disk space under backup root",
    ): "a df failure yields empty output, read as 0 bytes, so the following "
    "disk-space check fails closed",
    (
        "paperless_backup/tasks/main.yml",
        "Check available disk space under backup root",
    ): "a df failure yields empty output, read as 0 bytes, so the following "
    "disk-space check fails closed",
    (
        "fastdeploy_deploy/tasks/frontend.yml",
        "Download NodeSource GPG key",
    ): "creates:-guarded key download; a bad keyring makes the following apt "
    "update fail loudly",
    (
        "metube_deploy/tasks/nodejs.yml",
        "Download NodeSource GPG key",
    ): "creates:-guarded key download; a bad keyring makes the following apt "
    "update fail loudly",
    (
        "mail_relay_deploy/tasks/sasl.yml",
        "sasl | Create relay user in sasldb2",
    ): "echo cannot fail; saslpasswd2 is the last command, so its status is "
    "the task status",
    (
        "mail_relay_deploy/tasks/sasl.yml",
        "sasl | Update relay user password in sasldb2",
    ): "echo cannot fail; saslpasswd2 is the last command, so its status is "
    "the task status",
    (
        "remote_luks_unlock/tasks/cleanup.yml",
        "Read current GRUB_CMDLINE_LINUX_DEFAULT for cleanup",
    ): "best-effort read that ends in '|| echo \"\"'; a missing value is "
    "expected and handled",
    (
        "remote_luks_unlock/tasks/network-initramfs.yml",
        "Read current GRUB_CMDLINE_LINUX_DEFAULT for cleanup",
    ): "best-effort read that ends in '|| echo \"\"'; a missing value is "
    "expected and handled",
    (
        "remote_luks_unlock/tasks/cleanup.yml",
        "Read current DEVICE from initramfs.conf for cleanup",
    ): "best-effort read that ends in '|| echo \"\"'; a missing value is "
    "expected and handled",
    (
        "remote_luks_unlock/tasks/network-grub.yml",
        "Read current DEVICE from initramfs.conf",
    ): "best-effort read that ends in '|| echo \"\"'; a missing value is "
    "expected and handled",
    (
        "samba_share/tasks/users.yml",
        "users | Create new Samba users",
    ): "printf cannot fail; smbpasswd is the last command, so its status is "
    "the task status",
    (
        "samba_timemachine/tasks/users.yml",
        "Create new Samba users",
    ): "printf cannot fail; smbpasswd is the last command, so its status is "
    "the task status",
}


def iter_tasks(tasks):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        for key in ("block", "rescue", "always"):
            if key in task:
                yield from iter_tasks(task[key])
        yield task


def shell_command(task):
    for module in SHELL_MODULES:
        if module in task:
            value = task[module]
            if isinstance(value, dict):
                return str(value.get("cmd", ""))
            return str(value)
    return None


def shell_executable(task):
    """Return ``executable`` from ``args:`` or the module's own mapping."""
    for module in SHELL_MODULES:
        value = task.get(module)
        if isinstance(value, dict) and value.get("executable"):
            return str(value["executable"])
    return str((task.get("args") or {}).get("executable", ""))


COMMENT = re.compile(r"(?m)(?:^|\s)#.*$")


# Characters after which ``#`` starts a comment. A ``)`` counts only when it
# is an operator (subshell or case pattern); after the ``)`` that closes a
# ``$(...)`` substitution, ``#`` continues the word.
COMMENT_START = " \t\n;&|("


def _scan(text, i=0, in_substitution=False):
    """Scan shell text for an unquoted ``|``; return (found, next index).

    Quote-aware: single quotes are literal, double quotes are literal except
    for ``$(...)`` and backtick substitutions, ``#`` starts a comment at a
    word boundary, and ``||`` is not a pipe. With ``in_substitution`` the scan
    stops after the ``)`` that closes the current ``$(``.
    """
    found, depth, n = False, 0, len(text)
    operator_close = -1  # index just after the last operator ``)``

    def backtick(start):
        end = text.find("`", start + 1)
        end = n if end == -1 else end
        return _scan(text[start + 1 : end])[0], end + 1

    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
        elif c == "'":
            end = text.find("'", i + 1)
            i = n if end == -1 else end + 1
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 2
                elif text.startswith("$(", i):
                    inner, i = _scan(text, i + 2, True)
                    found = found or inner
                elif text[i] == "`":
                    inner, i = backtick(i)
                    found = found or inner
                else:
                    i += 1
            i += 1
        elif c == "#" and (
            i == 0 or text[i - 1] in COMMENT_START or i == operator_close
        ):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("$(", i):
            inner, i = _scan(text, i + 2, True)
            found = found or inner
        elif c == "`":
            inner, i = backtick(i)
            found = found or inner
        elif c == "(":
            depth += 1
            i += 1
        elif c == ")":
            if in_substitution and depth == 0:
                return found, i + 1
            depth -= 1
            i += 1
            operator_close = i
        elif text.startswith("||", i):
            i += 2
        elif c == "|":
            found = True
            i += 1
        else:
            i += 1
    return found, i


def has_pipe(command):
    """Return True if the shell command contains a real ``|`` pipeline.

    Jinja expressions (their ``|`` are filters) are removed first; quoting,
    comments, ``||`` and command substitutions follow shell rules.
    """
    text = re.sub(r"\{\{.*?\}\}", "X", command, flags=re.DOTALL)
    text = re.sub(r"\{%.*?%\}|\{#.*?#\}", "", text, flags=re.DOTALL)
    return _scan(text)[0]


PIPEFAIL = re.compile(r"\bset\s+(?:-[A-Za-z]+\s+)*-[A-Za-z]*o\s+pipefail\b")


def sets_pipefail(command):
    return PIPEFAIL.search(COMMENT.sub("", command)) is not None


def task_files():
    yield from sorted(ROLES.glob("*/tasks/**/*.yml"))
    yield from sorted(ROLES.glob("*/handlers/**/*.yml"))


def piped_shell_tasks():
    """Yield (relative path, task name, task, command) for piped shell tasks."""
    for path in task_files():
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, list):
            continue
        for task in iter_tasks(data):
            command = shell_command(task)
            if command is None or not has_pipe(command):
                continue
            yield str(path.relative_to(ROLES)), task.get("name", ""), task, command


class PipeDetectionTest(unittest.TestCase):
    def test_detects_plain_pipe(self):
        self.assertTrue(has_pipe('pg_dump "db" | gzip > out.gz'))

    def test_ignores_jinja_filters_or_and_quotes(self):
        self.assertFalse(has_pipe("echo \"{{ items | join(',') }}\" || true"))
        self.assertFalse(has_pipe("grep -E 'a|b' file"))
        self.assertFalse(has_pipe("echo hi  # a | b"))

    def test_detects_pipe_in_quoted_command_substitution(self):
        self.assertTrue(has_pipe("size=\"$(du -sb /missing | awk '{print $1}')\""))
        self.assertTrue(has_pipe("size=`du -sb /missing | awk '{print $1}'`"))
        self.assertFalse(has_pipe('size="$(du -sb /missing)"'))
        self.assertTrue(has_pipe("value=\"$(printf ')' | cat)\""))
        self.assertTrue(has_pipe("echo $(( 1 + 2 )) && a | b"))
        self.assertFalse(has_pipe("echo '$(a | b)'"))
        self.assertFalse(has_pipe('echo "a | b"'))
        self.assertFalse(has_pipe("echo $(date) # a | b"))
        self.assertTrue(has_pipe("printf '%s\\n' $(printf stamp)#suffix | cat"))
        self.assertTrue(has_pipe('echo "x"#y | cat'))
        self.assertTrue(has_pipe("(true)# don't hide this\nfalse | cat"))
        self.assertFalse(has_pipe("(true) # a | b"))

    def test_pipefail_detection(self):
        self.assertTrue(sets_pipefail("set -euo pipefail\n"))
        self.assertTrue(sets_pipefail("set -o pipefail\n"))
        self.assertTrue(sets_pipefail("set -e -o pipefail\n"))
        self.assertFalse(sets_pipefail("echo pipefail | cat\n"))
        self.assertFalse(sets_pipefail("# set -o pipefail\na | b\n"))
        self.assertFalse(sets_pipefail("a | b  # set -o pipefail\n"))


class ShellPipefailTest(unittest.TestCase):
    def test_piped_shell_tasks_set_pipefail_under_bash(self):
        problems = []
        for rel, name, task, command in piped_shell_tasks():
            if (rel, name) in ALLOWED:
                continue
            if not sets_pipefail(command):
                problems.append(f"{rel}: {name!r} pipes without set -o pipefail")
                continue
            executable = shell_executable(task)
            if not str(executable).endswith("bash"):
                problems.append(
                    f"{rel}: {name!r} sets pipefail but does not run under bash "
                    "(add args: executable: /bin/bash)"
                )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_allow_list_entries_are_current(self):
        found = {
            (rel, name)
            for rel, name, _task, command in piped_shell_tasks()
            if not sets_pipefail(command)
        }
        stale = sorted(set(ALLOWED) - found)
        self.assertEqual(
            stale,
            [],
            f"ALLOWED lists tasks that no longer exist or no longer need it: {stale}",
        )


def load_tasks(rel):
    return list(iter_tasks(yaml.safe_load((ROLES / rel).read_text())))


def find_task(tasks, name):
    for task in tasks:
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found")


def render(command, variables):
    env = Environment(undefined=StrictUndefined)
    env.filters["dirname"] = os.path.dirname
    env.filters["basename"] = os.path.basename
    return env.from_string(command).render(**variables)


def write_stub(bindir, name, body):
    path = Path(bindir) / name
    path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class MailBackupDumpTest(unittest.TestCase):
    """Run the rendered dump task with a stubbed pg_dump."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.bindir = base / "bin"
        self.bindir.mkdir()
        self.backup_dir = base / "backup"
        self.backup_dir.mkdir()
        task = find_task(
            load_tasks("mail_backup/tasks/main.yml"), "Backup PostgreSQL database"
        )
        self.script = render(
            shell_command(task),
            {
                "mail_backup_dir": str(self.backup_dir),
                "mail_backup_postgres_database": "mail",
            },
        )

    def run_dump(self, pg_dump_body):
        write_stub(self.bindir, "pg_dump", pg_dump_body)
        env = dict(os.environ, PATH=f"{self.bindir}:{os.environ['PATH']}")
        return subprocess.run(
            ["bash", "-c", self.script],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_failed_pg_dump_fails_and_leaves_no_dump(self):
        result = self.run_dump("echo 'connection refused' >&2\nexit 1\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sorted(p.name for p in self.backup_dir.iterdir()), [])

    def test_partial_output_then_failure_leaves_no_dump(self):
        result = self.run_dump("echo '-- PostgreSQL database dump'\nexit 1\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sorted(p.name for p in self.backup_dir.iterdir()), [])

    def test_empty_dump_fails(self):
        result = self.run_dump("exit 0\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty dump", result.stderr)
        self.assertEqual(sorted(p.name for p in self.backup_dir.iterdir()), [])

    def test_successful_dump_is_moved_into_place(self):
        result = self.run_dump("echo 'CREATE TABLE domain (name text);'\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            sorted(p.name for p in self.backup_dir.iterdir()), ["database.sql.gz"]
        )
        content = subprocess.run(
            ["gzip", "-cd", str(self.backup_dir / "database.sql.gz")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("CREATE TABLE domain", content)


class MailBackupStructureTest(unittest.TestCase):
    """A failed component must stop the run before retention deletes anything."""

    def setUp(self):
        self.top = yaml.safe_load((ROLES / "mail_backup/tasks/main.yml").read_text())

    def index_of(self, name):
        for index, task in enumerate(self.top):
            if task.get("name") == name:
                return index
        raise AssertionError(f"top-level task {name!r} not found")

    def test_components_run_in_block_with_failing_rescue(self):
        block = self.top[self.index_of("Create backup")]
        names = [task.get("name") for task in block["block"]]
        for name in (
            "Backup PostgreSQL database",
            "Backup maildir",
            "Backup configuration files",
            "Create backup manifest",
            "Create tar.gz archive",
            "Create tar.zst archive",
        ):
            self.assertIn(name, names)
        rescue = block["rescue"]
        removal = rescue[0]
        self.assertEqual(removal["ansible.builtin.file"]["state"], "absent")
        self.assertIn("mail_backup_dir", removal["loop"])
        self.assertIn("ansible.builtin.fail", rescue[-1])

    def test_refuses_existing_paths_before_creating_anything(self):
        guard = self.index_of("Refuse to overwrite an existing backup")
        self.assertLess(
            self.index_of("Check that this run's backup paths are new"), guard
        )
        self.assertLess(guard, self.index_of("Create timestamped backup directory"))
        self.assertLess(guard, self.index_of("Create backup"))
        # The archive path is fixed before any step that can fail, so the
        # rescue never acts on a value left over from an earlier invocation.
        facts = self.top[self.index_of("Compute backup directory name")]
        self.assertIn("mail_backup_archive_path", facts["ansible.builtin.set_fact"])
        block = self.top[self.index_of("Create backup")]
        for task in iter_tasks(block["block"] + block["rescue"]):
            self.assertNotIn(
                "mail_backup_archive_path", task.get("ansible.builtin.set_fact", {})
            )

    def test_backup_files_use_backup_owner_and_group(self):
        for task in iter_tasks(self.top):
            for module in ("ansible.builtin.file", "ansible.builtin.copy"):
                args = task.get(module) or {}
                if "group" in args:
                    self.assertEqual(
                        args["group"], "{{ mail_backup_group }}", task.get("name")
                    )
                if "owner" in args:
                    self.assertEqual(
                        args["owner"], "{{ mail_backup_owner }}", task.get("name")
                    )

    def test_retention_runs_only_after_backup_block(self):
        block_index = self.index_of("Create backup")
        for name in (
            "Remove old backup directories (not archives)",
            "Remove old backup archives",
        ):
            self.assertGreater(self.index_of(name), block_index)

    def test_maildir_tar_written_to_temp_file_first(self):
        task = find_task(load_tasks("mail_backup/tasks/main.yml"), "Backup maildir")
        command = shell_command(task)
        self.assertTrue(sets_pipefail(command))
        self.assertIn('tar -czf "$tmp"', command)
        self.assertIn('mv -- "$tmp" "$dest"', command)


class MailRestoreDumpCheckTest(unittest.TestCase):
    def setUp(self):
        self.tasks = load_tasks("mail_restore/tasks/main.yml")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)

    def run_check(self):
        task = find_task(
            self.tasks, "Verify database dump before dropping the database"
        )
        script = render(shell_command(task), {"mail_restore_source": str(self.source)})
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=False
        )

    def write_dump(self, raw):
        (self.source / "database.sql.gz").write_bytes(raw)

    def gzip_bytes(self, text):
        return subprocess.run(
            ["gzip", "-c"], input=text.encode(), capture_output=True, check=True
        ).stdout

    def test_check_runs_before_drop(self):
        names = [task.get("name") for task in self.tasks]
        self.assertLess(
            names.index("Verify database dump before dropping the database"),
            names.index("Drop existing database"),
        )

    def test_rejects_empty_dump(self):
        self.write_dump(self.gzip_bytes(""))
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_rejects_corrupt_dump(self):
        self.write_dump(self.gzip_bytes("SELECT 1;\n" * 100)[:-12])
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_accepts_valid_dump(self):
        self.write_dump(self.gzip_bytes("SELECT 1;\n"))
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
