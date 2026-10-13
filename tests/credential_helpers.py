"""Credential delivery regressions; no host or database access."""

import subprocess
import tempfile
from pathlib import Path

import yaml
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(undefined=StrictUndefined)
ENV.filters.update(FilterModule().filters())


def tasks(role, file):
    def walk(nodes):
        for task in nodes:
            yield task
            for key in ("block", "rescue", "always"):
                yield from walk(task.get(key, []))

    return list(
        walk(yaml.safe_load((ROOT / "roles" / role / "tasks" / file).read_text()))
    )


def assert_pgpass(test, role, expected):
    all_tasks = []
    for path in (ROOT / "roles" / role / "tasks").glob("*.yml"):
        all_tasks += tasks(role, path.name)
    clients = [t for t in all_tasks if "PGPASSFILE" in t.get("environment", {})]
    test.assertEqual(len(clients), expected)
    test.assertFalse(
        any("PGPASSWORD" in str(t.get("environment", {})) for t in all_tasks)
    )
    blocks = [
        t for t in all_tasks if "block" in t and "private passfile" in t.get("name", "")
    ]
    test.assertEqual(len(blocks), expected)
    for block in blocks:
        allocate = next(t for t in block["block"] if "ansible.builtin.tempfile" in t)
        render = next(t for t in block["block"] if "ansible.builtin.template" in t)
        client = next(
            t for t in block["block"] if "PGPASSFILE" in t.get("environment", {})
        )
        remove = block["always"][0]
        test.assertEqual(allocate["ansible.builtin.tempfile"]["state"], "directory")
        test.assertEqual(render["ansible.builtin.template"]["mode"], "0600")
        test.assertTrue(render["no_log"])
        test.assertEqual(allocate["become_user"], client["become_user"])
        test.assertEqual(render["become_user"], client["become_user"])
        test.assertEqual(remove["become_user"], client["become_user"])
        test.assertEqual(remove["ansible.builtin.file"]["state"], "absent")
        test.assertEqual(
            remove["ansible.builtin.file"]["path"],
            "{{ " + allocate["register"] + ".path }}",
        )
        validation = next(t for t in block["block"] if "ansible.builtin.assert" in t)
        expressions = validation["ansible.builtin.assert"]["that"]
        import re

        variable = re.search(r"\((\w+)", expressions[0])[1]
        for value, valid in [
            ("safe", True),
            ("a\nb", False),
            ("a\rb", False),
            (123, True),
            (None, True),
        ]:
            actual = all(
                bool(
                    ENV.from_string("{% if " + expression + " %}yes{% endif %}").render(
                        **{variable: value}
                    )
                )
                for expression in expressions
            )
            test.assertEqual(actual, valid, repr(value))
        test.assertIn("not ansible_check_mode", allocate["when"])
        for task in (allocate, render, remove):
            test.assertFalse(task["changed_when"])
    password = r"p:a\ss '$`"
    template = (ROOT / "roles" / role / "templates/task-pgpass.j2").read_text()
    result = ENV.from_string(template).render(task_pgpass_password=password)
    test.assertEqual(
        result, "*:*:*:*:" + password.replace("\\", "\\\\").replace(":", "\\:")
    )


def assert_env_source(
    test, role, task_file, template, secret_var, secret_key, expected
):
    from jinja2 import meta

    template_text = (ROOT / "roles" / role / "templates" / template).read_text()
    context = yaml.safe_load((ROOT / "roles" / role / "defaults/main.yml").read_text())
    for var in meta.find_undeclared_variables(ENV.parse(template_text)):
        context.setdefault(var, "fixture")
    secret = "space ' \" $() `false` \\\\ colon:;\nnext"
    context[secret_var] = secret
    context["task_shell_environment"] = True
    original = ENV.from_string(template_text).render(
        **dict(context, task_shell_environment=False)
    )
    test.assertIn(secret_key + "=" + secret, original)
    rendered = ENV.from_string(template_text).render(**context)
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / "service.env"
        env_file.write_text(rendered)
        result = subprocess.run(
            [
                "/bin/sh",
                "-c",
                'set -a; . "$1"; set +a; printf "%s" "$' + secret_key + '"',
                "env-test",
                str(env_file),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        test.assertEqual(result.returncode, 0, result.stderr)
        test.assertEqual(result.stdout, secret)
    found = [
        t
        for t in tasks(role, task_file)
        if (
            ("ansible.builtin.shell" in t or "shell" in t)
            and (
                ".env" in str(t.get("ansible.builtin.shell", t.get("shell")))
                or role == "archive_deploy"
            )
        )
    ]
    test.assertEqual(len(found), expected)
    companions = [
        t
        for file in (ROOT / "roles" / role / "tasks").glob("*.yml")
        for t in tasks(role, file.name)
        if t.get("vars", {}).get("task_shell_environment") is True
    ]
    test.assertEqual(len(companions), 1)
    test.assertEqual(companions[0]["ansible.builtin.template"]["mode"], "0600")
    test.assertTrue(companions[0]["no_log"])

    for task in found:
        test.assertNotIn("DATABASE_URL", task.get("environment", {}))
        test.assertNotIn("INITIAL_PASSWORD_HASH", task.get("environment", {}))
        command = str(task.get("ansible.builtin.shell", task.get("shell")))
        test.assertNotIn(secret_var, command)
        test.assertNotIn(secret_var, str(task.get("environment", {})))
        test.assertNotIn(secret_key, str(task.get("environment", {})))


def assert_mongo_files(test, role, expected):
    all_tasks = []
    for path in (ROOT / "roles" / role / "tasks").glob("*.yml"):
        all_tasks += tasks(role, path.name)
    blocks = [
        t
        for t in all_tasks
        if "block" in t and t.get("name", "").endswith("private credential script")
    ]
    test.assertEqual(len(blocks), expected)
    for block in blocks:
        allocate, render, client = block["block"]
        test.assertEqual(allocate["ansible.builtin.tempfile"]["state"], "directory")
        test.assertEqual(render["ansible.builtin.template"]["mode"], "0600")
        test.assertTrue(render["no_log"])
        test.assertIn("--file ", client["ansible.builtin.shell"])
        test.assertNotIn("unifi_mongodb_password", client["ansible.builtin.shell"])
        test.assertEqual(block["always"][0]["ansible.builtin.file"]["state"], "absent")
    import json

    password = "' \\\" \\\\ $() ;\nsecret"
    rendered = ENV.from_string(
        (ROOT / "roles" / role / "templates/task-mongosh.js.j2").read_text()
    ).render(
        task_mongo_auth_db="admin",
        task_mongo_database="fixture",
        unifi_mongodb_user="user",
        unifi_mongodb_password=password,
        task_mongo_script="quit(0);",
    )
    test.assertIn(json.dumps(password), rendered)
    test.assertIn("authDb.auth", rendered)


def assert_passphrase_stdin(test, role, file, name, variable):
    task = next(t for t in tasks(role, file) if t.get("name") == name)
    test.assertNotIn("environment", task)
    test.assertEqual(task["args"]["stdin"], "{{ " + variable + " | default('') }}")
    test.assertFalse(task["args"]["stdin_add_newline"])
    shell = task["ansible.builtin.shell"]
    prefix = shell[: shell.index("cd ")]
    password = "' $() \\\\ :\nsecond line"
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            ENV.from_string(prefix).render(**{variable: password})
            + 'printf "%s" "$PAPERLESS_PASSPHRASE"',
        ],
        check=False,
        input=password,
        text=True,
        capture_output=True,
    )
    test.assertEqual(result.returncode, 0, result.stderr)
    test.assertEqual(result.stdout, password)


def assert_empty_passphrase_does_not_read(test, role, file, name, variable):
    task = next(t for t in tasks(role, file) if t.get("name") == name)
    prefix = task["ansible.builtin.shell"].split("cd ", 1)[0]
    rendered = ENV.from_string(prefix).render(**{variable: ""})
    test.assertNotIn("read -r", rendered)
    # Keep stdin open: reading it would block just as an inherited SSH pty can.
    with subprocess.Popen(
        ["/bin/bash", "-c", rendered],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        try:
            test.assertEqual(process.wait(timeout=2), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
