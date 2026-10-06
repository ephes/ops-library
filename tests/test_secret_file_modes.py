"""Static checks that files rendered with secrets are not world-readable.

Every ``template``/``copy`` task whose template source (or inline ``content``)
references a secret-named variable must set an explicit octal ``mode`` with no
permission bits for "other". systemd unit templates must not embed secrets at
all, because unit files are world-readable and ``systemctl show`` exposes
``Environment=`` to every local user.
"""

import os
import re
import stat
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import ChainableUndefined, Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"

TEMPLATE_MODULES = {"template", "ansible.builtin.template"}
COPY_MODULES = {"copy", "ansible.builtin.copy"}
SECRET_SEGMENT = re.compile(
    r"(?:^|_)(?:password|passwd|secret|token|api_key|apikey|private_key|access_key)(?:$|_)",
    re.IGNORECASE,
)
# Variables that name a secret's location or property, not the secret itself.
NON_SECRET_SUFFIX = re.compile(
    r"_(?:hash|path|file|dir|scheme|length|ttl|name|user|url|header|enabled|mode|id)$",
    re.IGNORECASE,
)
JINJA_EXPRESSION = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
OCTAL_MODE = re.compile(r"^0?[0-7]{3,4}$")


def secret_references(text):
    """Return secret-named identifiers used inside ``{{ ... }}`` expressions."""
    found = set()
    for expression in JINJA_EXPRESSION.findall(text):
        # Ignore string literals so filter arguments do not count.
        expression = re.sub(r"'[^']*'|\"[^\"]*\"", "", expression)
        for identifier in IDENTIFIER.findall(expression):
            if SECRET_SEGMENT.search(identifier) and not NON_SECRET_SUFFIX.search(
                identifier
            ):
                found.add(identifier)
    return found


def iter_tasks(tasks):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        for key in ("block", "rescue", "always"):
            if key in task:
                yield from iter_tasks(task[key])
        yield task


def role_defaults(role):
    defaults = {}
    path = ROLES / role / "defaults" / "main.yml"
    if path.exists():
        defaults = yaml.safe_load(path.read_text()) or {}
    return defaults


def resolve_mode(role, mode):
    """Resolve a literal mode or a ``{{ var }}`` mode from role defaults."""
    if mode is None:
        return None
    mode = str(mode).strip()
    match = re.fullmatch(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", mode)
    if match:
        value = role_defaults(role).get(match.group(1))
        return None if value is None else str(value).strip()
    return mode


def secret_bearing_tasks():
    """Yield (role, task file, task, module args, secret names)."""
    for task_file in sorted(ROLES.glob("*/tasks/**/*.yml")):
        role = task_file.relative_to(ROLES).parts[0]
        tasks = yaml.safe_load(task_file.read_text())
        if not isinstance(tasks, list):
            continue
        for task in iter_tasks(tasks):
            for module in TEMPLATE_MODULES | COPY_MODULES:
                args = task.get(module)
                if not isinstance(args, dict):
                    continue
                text = ""
                if isinstance(args.get("content"), str):
                    text = args["content"]
                elif module in TEMPLATE_MODULES and isinstance(args.get("src"), str):
                    source = ROLES / role / "templates" / args["src"]
                    if "{{" not in args["src"] and source.exists():
                        text = source.read_text()
                secrets = secret_references(text)
                if secrets:
                    yield role, task_file, task, args, secrets


class SecretReferenceDetectionTests(unittest.TestCase):
    def test_detects_secret_variables_and_ignores_locations(self):
        self.assertEqual(
            secret_references("{{ unifi_mongodb_password }}"),
            {"unifi_mongodb_password"},
        )
        self.assertEqual(secret_references("{{ tsig_key.secret }}"), {"secret"})
        self.assertEqual(secret_references("{{ x_htpasswd_path }}"), set())
        self.assertEqual(secret_references("{{ x_password_hash }}"), set())
        self.assertEqual(secret_references("{{ x_tokens_to_remove }}"), set())
        self.assertEqual(secret_references("{{ 'password' }}"), set())


class SecretFileModeTests(unittest.TestCase):
    def test_scan_finds_known_secret_bearing_tasks(self):
        names = {(role, task.get("name", "")) for role, _, task, _, _ in secret_bearing_tasks()}
        for expected in [
            ("unifi_deploy", "systemd | Deploy MongoDB JVM argument file"),
            ("livekit_deploy", "config | Render egress.yaml"),
            ("minecraft_java_deploy", "Create server.properties"),
            ("minecraft_java_deploy", "Create backup script"),
        ]:
            self.assertIn(expected, names)

    def test_secret_bearing_files_are_not_world_accessible(self):
        failures = []
        for role, task_file, task, args, secrets in secret_bearing_tasks():
            mode = resolve_mode(role, args.get("mode"))
            label = f"{task_file.relative_to(ROOT)}: {task.get('name', '?')} ({', '.join(sorted(secrets))})"
            if mode is None:
                failures.append(f"{label}: no explicit mode")
            elif not OCTAL_MODE.match(mode):
                failures.append(f"{label}: non-octal mode {mode!r}")
            elif int(mode, 8) & 0o007:
                failures.append(f"{label}: mode {mode} grants access to others")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_systemd_unit_templates_do_not_embed_secrets(self):
        failures = []
        for unit in sorted(ROLES.glob("*/templates/**/*.service.j2")) + sorted(
            ROLES.glob("*/templates/**/systemd_service*.j2")
        ):
            secrets = secret_references(unit.read_text())
            if secrets:
                failures.append(f"{unit.relative_to(ROOT)}: {', '.join(sorted(secrets))}")
        self.assertEqual(failures, [], "\n".join(failures))


def load_tasks(path):
    return {task.get("name"): task for task in iter_tasks(yaml.safe_load(path.read_text()))}


class UnifiMongoCredentialTests(unittest.TestCase):
    role = ROLES / "unifi_deploy"

    def test_unit_uses_argfile_instead_of_inline_uri(self):
        unit = (self.role / "templates/unifi.service.j2").read_text()
        self.assertNotIn("MONGO_URI", unit)
        self.assertNotIn("db.mongo.uri", unit)
        self.assertIn("@{{ unifi_mongodb_jvm_args_path }}", unit)
        exec_start = unit[unit.index("ExecStart=") :]
        self.assertLess(
            exec_start.index("@{{ unifi_mongodb_jvm_args_path }}"),
            exec_start.index("-jar "),
            "Java only expands @argfiles before -jar",
        )

    def test_argfile_task_is_private_and_not_logged(self):
        tasks = load_tasks(self.role / "tasks/systemd.yml")
        argfile = tasks["systemd | Deploy MongoDB JVM argument file"]["ansible.builtin.template"]
        self.assertEqual(argfile["owner"], "root")
        self.assertEqual(argfile["group"], "{{ unifi_group }}")
        self.assertEqual(argfile["mode"], "0640")
        self.assertTrue(tasks["systemd | Deploy MongoDB JVM argument file"]["no_log"])
        directory = tasks["systemd | Ensure default credentials directory exists"]["ansible.builtin.file"]
        self.assertEqual(directory["mode"], "0750")
        names = list(tasks)
        self.assertLess(
            names.index("systemd | Deploy MongoDB JVM argument file"),
            names.index("systemd | Deploy service"),
        )

    def test_argfile_quotes_special_characters(self):
        environment = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
        template = environment.from_string(
            (self.role / "templates/mongodb.jvmargs.j2").read_text()
        )
        rendered = template.render(
            unifi_service_name="unifi",
            unifi_mongodb_user="unifi",
            unifi_mongodb_password='p"a\\ss #x',
            unifi_mongodb_host="127.0.0.1",
            unifi_mongodb_port=27017,
            unifi_mongodb_database="unifi",
        )
        argument_lines = [line for line in rendered.splitlines() if not line.startswith("#")]
        self.assertEqual(
            argument_lines,
            [
                '"-Ddb.mongo.uri=mongodb://unifi:p\\"a\\\\ss #x@127.0.0.1:27017/unifi?authSource=admin"'
            ],
        )

    def test_remove_role_cleans_up_argfile(self):
        tasks = load_tasks(ROLES / "unifi_remove/tasks/main.yml")
        self.assertEqual(
            tasks["Remove MongoDB JVM argument file"]["ansible.builtin.file"]["path"],
            "{{ unifi_mongodb_jvm_args_path }}",
        )


class UnifiBackupRestoreArgfileTests(unittest.TestCase):
    def test_backup_and_restore_roles_carry_the_argfile(self):
        system = load_tasks(ROLES / "unifi_backup/tasks/system.yml")
        copy = system["Copy MongoDB JVM argument file"]["ansible.builtin.copy"]
        self.assertEqual(copy["src"], "{{ unifi_mongodb_jvm_args_path }}")
        self.assertEqual(copy["mode"], "{{ unifi_backup_file_mode }}")
        self.assertEqual(role_defaults("unifi_backup")["unifi_backup_file_mode"], "0600")
        for path, name in [
            ("unifi_restore/tasks/restore.yml", "Restore extracted MongoDB JVM argument file"),
            ("unifi_restore/tasks/rollback.yml", "Restore safety MongoDB JVM argument file"),
        ]:
            args = load_tasks(ROLES / path)[name]["ansible.builtin.copy"]
            self.assertEqual(args["dest"], "{{ unifi_mongodb_jvm_args_path }}")
            self.assertEqual(args["owner"], "root")
            self.assertEqual(args["mode"], "0640")

    def test_deploy_only_locks_down_the_dedicated_directory(self):
        tasks = load_tasks(ROLES / "unifi_deploy/tasks/systemd.yml")
        directory = tasks["systemd | Ensure default credentials directory exists"]
        self.assertEqual(directory["ansible.builtin.file"]["path"], "/etc/{{ unifi_service_name }}-secrets")
        self.assertIn("unifi_mongodb_jvm_args_path | dirname", directory["when"])
        self.assertIn("systemd | Require existing custom credentials directory", tasks)

    def load_echoport_script(self, chowns):
        environment = Environment(undefined=ChainableUndefined)
        source = environment.from_string(
            (ROLES / "echoport_backup/templates/unifi_backup.py.j2").read_text()
        ).render(unifi_echoport_backup_group="unifi")
        namespace = {"__name__": "unifi_backup_under_test"}
        exec(compile(source, "unifi_backup.py", "exec"), namespace)
        commands = []
        namespace["run_cmd"] = lambda args, check=True: commands.append(args)

        class FakeGroup:
            gr_gid = os.getgid()

        class FakeGrp:
            @staticmethod
            def getgrnam(name):
                self.assertEqual(name, "unifi")
                return FakeGroup

        class FakeOs:
            def __getattr__(self, name):
                return getattr(os, name)

            @staticmethod
            def fchown(fd, uid, gid):
                chowns.append((uid, gid))

        namespace["grp"] = FakeGrp
        namespace["os"] = FakeOs()
        return namespace, commands

    def test_echoport_restore_writes_argfile_privately(self):
        chowns = []
        namespace, commands = self.load_echoport_script(chowns)
        self.assertEqual(namespace["JVM_ARGS_FILE"], "/etc/unifi-secrets/mongodb.jvmargs")
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / "mongodb.jvmargs"
            src.write_text("secret")
            dst = Path(directory) / "etc/unifi-secrets/mongodb.jvmargs"
            old_umask = os.umask(0o022)
            try:
                self.assertTrue(namespace["restore_private_file"](src, dst))
            finally:
                os.umask(old_umask)
            self.assertEqual(dst.read_text(), "secret")
            self.assertEqual(stat.S_IMODE(dst.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(dst.parent.stat().st_mode), 0o750)
            self.assertEqual(chowns, [(0, os.getgid())])
            self.assertIn(["chown", "root:unifi", str(dst.parent)], commands)
            self.assertEqual(sorted(p.name for p in dst.parent.iterdir()), ["mongodb.jvmargs"])
            self.assertFalse(namespace["restore_private_file"](Path(directory) / "missing", dst))

    def test_echoport_restore_ignores_planted_temp_files_and_symlinks(self):
        chowns = []
        namespace, _ = self.load_echoport_script(chowns)
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / "source"
            src.write_text("secret")
            credentials = Path(directory) / "credentials"
            credentials.mkdir()
            victim = Path(directory) / "victim"
            victim.write_text("untouched")
            # Names the earlier implementation would have reused.
            (credentials / ".mongodb.jvmargs.restore").symlink_to(victim)
            planted = credentials / ".mongodb.jvmargs.planted"
            planted.write_text("")
            planted.chmod(0o644)
            dst = credentials / "mongodb.jvmargs"
            self.assertTrue(namespace["restore_private_file"](src, dst))
            self.assertEqual(victim.read_text(), "untouched")
            self.assertEqual(planted.read_text(), "")
            self.assertEqual(dst.read_text(), "secret")
            self.assertFalse(dst.is_symlink())
            self.assertEqual(stat.S_IMODE(dst.stat().st_mode), 0o640)


class FastdeploySelfDeployUnitTests(unittest.TestCase):
    role = ROLES / "fastdeploy_self_deploy"

    def test_unit_loads_root_only_env_file(self):
        unit = (self.role / "templates/systemd_service.j2").read_text()
        self.assertIn("EnvironmentFile=/etc/default/{{ service_name }}", unit)
        self.assertNotIn("Environment=\"DATABASE_URL", unit)
        self.assertNotIn("Environment=\"SECRET_KEY", unit)
        for path, env_task, unit_task, service in [
            ("tasks/deploy_staging.yml", "Render fastdeploy-staging systemd environment file", "Deploy staging systemd service", "fastdeploy-staging"),
            ("tasks/blue_green_swap.yml", "Render fastdeploy systemd environment file", "Update production systemd service", "fastdeploy"),
        ]:
            tasks = load_tasks(self.role / path)
            env_file = tasks[env_task]["template"]
            self.assertEqual(env_file["dest"], f"/etc/default/{service}")
            self.assertEqual((env_file["owner"], env_file["mode"]), ("root", "0600"))
            self.assertTrue(tasks[env_task]["no_log"])
            self.assertEqual(tasks[unit_task]["vars"]["service_name"], service)
            names = list(tasks)
            self.assertLess(names.index(env_task), names.index(unit_task))

    def test_env_file_escapes_values_for_systemd(self):
        template = Environment(undefined=StrictUndefined).from_string(
            (self.role / "templates/systemd_env.j2").read_text()
        )
        rendered = template.render(
            service_name="fastdeploy",
            postgres_password='p\'w"d\\x',
            postgres_host="127.0.0.1",
            postgres_db_name="fd",
            secret_key='\'a"b\\c',
        )
        lines = [line for line in rendered.splitlines() if not line.startswith("#")]
        self.assertEqual(
            lines,
            [
                'DATABASE_URL="postgresql+asyncpg://fastdeploy:p\'w\\"d\\\\x@127.0.0.1:5432/fd"',
                'SECRET_KEY="\'a\\"b\\\\c"',
            ],
        )


class MinecraftRconPasswordTests(unittest.TestCase):
    def test_rcon_password_is_not_passed_on_the_command_line(self):
        script = (ROLES / "minecraft_java_deploy/templates/backup-world.sh.j2").read_text()
        self.assertNotIn("-p ", script)
        self.assertIn("export MCRCON_PASS=", script)
        self.assertIn("umask 077", script)
        backup = (ROLES / "minecraft_java_backup/tasks/main.yml").read_text()
        self.assertNotIn("-p ", backup)
        self.assertEqual(backup.count("MCRCON_PASS:"), 3)

    def test_backup_archives_are_private(self):
        tasks = load_tasks(ROLES / "minecraft_java_backup/tasks/main.yml")
        archive = tasks["Create backup archive"]["ansible.builtin.archive"]
        self.assertEqual(archive["mode"], "0600")
        directory = tasks["Create backup directory"]["ansible.builtin.file"]
        self.assertEqual(directory["mode"], "0700")


class RedisConfigModeTests(unittest.TestCase):
    def test_active_config_and_backups_are_group_readable_only(self):
        tasks = load_tasks(ROLES / "redis_install/tasks/configure.yml")
        for name, module in [
            ("configure | Atomically install validated Redis configuration", "ansible.builtin.copy"),
            ("configure | Render Redis configuration without execution validation", "ansible.builtin.template"),
            ("configure | Restrict earlier Redis configuration backups", "ansible.builtin.file"),
        ]:
            args = tasks[name][module]
            self.assertEqual(args["mode"], "0640", name)
            self.assertEqual(args["group"], "{{ redis_install_group }}", name)


if __name__ == "__main__":
    unittest.main()
