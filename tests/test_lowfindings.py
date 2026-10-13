"""Render/static regressions for the October audit follow-ups; no host access."""
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tasks(path):
    return yaml.safe_load((ROOT / path).read_text())


def walk(nodes):
    for node in nodes:
        yield node
        for key in ("block", "rescue", "always"):
            yield from walk(node.get(key, []))


ENV = Environment(
    undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True
)
ENV.filters.update(bool=bool, basename=lambda x: Path(x).name)


def variables(role):
    values = {}
    shared = ROOT / "roles" / role.replace("_deploy", "_shared") / "defaults/main.yml"
    if shared.exists():
        values.update(yaml.safe_load(shared.read_text()))
    values.update(tasks(f"roles/{role}/defaults/main.yml"))
    return values


def render(text, values):
    return ENV.from_string(text).render(values)


def test_fastdeploy_proxy_flags():
    values = variables("fastdeploy_deploy")
    text = (
        ROOT / "roles/fastdeploy_deploy/templates/fastdeploy.service.j2"
    ).read_text()
    assert "--proxy-headers --forwarded-allow-ips 127.0.0.1" in render(text, values)
    values["fastdeploy_forwarded_allow_ips"] = ["192.168.1.2", "::1"]
    assert "--forwarded-allow-ips 192.168.1.2,::1" in render(text, values)


@pytest.mark.parametrize(
    "value,valid",
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("192.168.1.2", True),
        ("*", False),
        ("127.0.0.1 --host x", False),
        ("127.0.0.1\n", False),
        ("999.1.1.1", False),
        ("localhost", False),
        ("10.0.0.0/8", False),
        ("fe80::1%eth0", False),
        (None, False),
    ],
)
def test_proxy_address_validation(value, valid):
    network = load_module(ROOT / "plugins/filter/network.py")
    assert network.is_ip_address(value) is valid


def test_proxy_validation_wired_and_rejects_invalid_lists():
    main = tasks("roles/fastdeploy_deploy/tasks/main.yml")
    assert any(
        t.get("ansible.builtin.include_tasks") == "validate_proxy_headers.yml"
        for t in main
    )
    validation = tasks("roles/fastdeploy_deploy/tasks/validate_proxy_headers.yml")
    for value in ([], "127.0.0.1", {"ip": "127.0.0.1"}, None):
        conditions = validation[0]["ansible.builtin.assert"]["that"]
        assert not all(
            ENV.compile_expression(c)(fastdeploy_forwarded_allow_ips=value)
            for c in conditions
        )
    assert validation[1]["ansible.builtin.assert"]["that"] == [
        "item | local.ops_library.is_ip_address"
    ]


@pytest.mark.parametrize(
    "stdout,changed",
    [
        ("Database is up to date\n", False),
        ("all database updates are applied (version 1845)\n", False),
        ("all database updates are applied (version 9999)\n", False),
        (
            "<p>Updating database:</p><p>- old version: 1844; target version: 1845</p>\n"
            "<p>updating to version 1845 (all databases)...\n &nbsp; done\n",
            True,
        ),
        ("", True),
        ("Unexpected output\n", True),
    ],
)
def test_postfixadmin_schema_change_detection(stdout, changed):
    task = tasks("roles/postfixadmin_deploy/tasks/schema.yml")[0]
    result = {"stdout": stdout, "rc": 0}
    assert (
        ENV.compile_expression(task["changed_when"])(**{task["register"]: result})
        is changed
    )


def test_postfixadmin_queries_are_protected():
    checker = load_module(ROOT / "scripts/check_secret_no_log.py")
    for path in (
        "roles/postfixadmin_deploy/tasks/admin.yml",
        "roles/postfixadmin_backup/tasks/main.yml",
    ):
        assert list(checker.iter_findings(tasks(path))) == []
    nodes = tasks("roles/postfixadmin_deploy/tasks/admin.yml")
    for name in ("Create superadmin account", "Update superadmin password if changed"):
        node = next(n for n in nodes if n["name"] == name)
        assert node["no_log"] is True
        node.pop("no_log")
        assert list(checker.iter_findings([node]))
    nodes = tasks("roles/postfixadmin_backup/tasks/main.yml")
    for name in ("Backup PostfixAdmin admin table", "Write admin table backup"):
        assert next(n for n in nodes if n["name"] == name)["no_log"] is True


@pytest.mark.parametrize(
    "query,args,flagged",
    [
        ("SELECT * FROM admin", {}, True),
        ("SELECT * FROM mailbox", {}, True),
        ("SELECT * FROM mail_users", {}, True),
        ("SELECT password FROM mailbox", {}, True),
        (
            "UPDATE mailbox SET password = %(password)s",
            {"password": "{{ password_hash }}"},
            True,
        ),
        ("SELECT domain FROM domain", {}, False),
    ],
)
def test_query_checker(query, args, flagged):
    checker = load_module(ROOT / "scripts/check_secret_no_log.py")
    node = {
        "community.postgresql.postgresql_query": {"query": query, "named_args": args}
    }
    assert bool(list(checker.iter_findings([node]))) is flagged
    node["no_log"] = True
    assert not list(checker.iter_findings([node]))


@pytest.mark.parametrize(
    "role,var",
    [
        ("unifi_deploy", "unifi_homeassistant_password_effective"),
        ("homeassistant_deploy", "homeassistant_unifi_password_effective"),
    ],
)
def test_unifi_password_required(role, var):
    filename = "homeassistant" if role == "unifi_deploy" else "unifi"
    nodes = tasks(f"roles/{role}/tasks/{filename}.yml")
    assert "lookup('password'" not in str(nodes)
    failure = next(n for n in nodes if "ansible.builtin.fail" in n)
    expression = (
        failure["when"][0] if isinstance(failure["when"], list) else failure["when"]
    )
    assert ENV.compile_expression(expression)(**{var: ""})
    assert not ENV.compile_expression(expression)(**{var: "supplied"})


def test_no_controller_tmp_password_lookups():
    for path in (ROOT / "roles").rglob("*.yml"):
        assert not re.search(
            r"lookup\(['\"]password['\"],\s*['\"]/tmp/", path.read_text()
        ), path


@pytest.mark.parametrize(
    "path,allocation",
    [
        ("roles/minecraft_java_deploy/tasks/install.yml", "directory"),
        ("roles/unifi_deploy/tasks/mongodb.yml", "file"),
        ("roles/unifi_deploy/tasks/homeassistant.yml", "file"),
    ],
)
def test_remote_tempfile_cleanup(path, allocation):
    nodes = tasks(path)
    assert "/tmp/" not in str(nodes)
    block = next(
        n
        for n in walk(nodes)
        if any("ansible.builtin.tempfile" in c for c in n.get("block", []))
    )
    alloc = next(n for n in block["block"] if "ansible.builtin.tempfile" in n)
    assert alloc["ansible.builtin.tempfile"]["state"] == allocation
    var = alloc["register"]
    cleanup = block["always"][0]
    assert cleanup["ansible.builtin.file"] == {
        "path": "{{ " + var + ".path }}",
        "state": "absent",
    }
    assert cleanup["when"] == var + ".path is defined"
    uses = str(block["block"])
    assert uses.count(var + ".path") >= 2


UNITS = [
    ("marina_deploy", "systemd", "marina", ["marina_site_path", "marina_cache_dir"]),
    (
        "takahe_deploy",
        "gunicorn",
        "takahe",
        ["takahe_site_path", "takahe_media_root", "takahe_cache_root"],
    ),
    (
        "takahe_deploy",
        "stator",
        "takahe",
        ["takahe_site_path", "takahe_media_root", "takahe_cache_root"],
    ),
    (
        "takahe_deploy",
        "nginx",
        "takahe",
        ["takahe_cache_root", "takahe_nginx_run_dir", "takahe_nginx_log_dir"],
    ),
    (
        "metube_deploy",
        "metube",
        "metube",
        [
            "metube_home",
            "metube_download_dir",
            "metube_temp_dir",
            "metube_state_dir",
            "metube_audio_download_dir",
        ],
    ),
    (
        "navidrome_deploy",
        "navidrome",
        "navidrome",
        [
            "navidrome_home",
            "navidrome_data_dir",
            "navidrome_cache_dir",
            "navidrome_log_dir",
        ],
    ),
    (
        "open_webui_venv_deploy",
        "open-webui",
        "open_webui",
        ["open_webui_home", "open_webui_data_dir", "open_webui_log_dir"],
    ),
]


@pytest.mark.parametrize("role,name,prefix,paths", UNITS)
def test_hardening_default_unchanged_and_opt_in(role, name, prefix, paths):
    values = variables(role)
    assert values[prefix + "_systemd_hardening"] is False
    # Use distinct custom paths to catch omitted or hard-coded writable paths.
    values.update({key: "/custom/" + key for key in paths})
    text = (ROOT / f"roles/{role}/templates/{name}.service.j2").read_text()
    previous = (ROOT / f"tests/fixtures/lowfindings/{role}-{name}.j2").read_text()
    assert render(text, values) == render(previous, values)
    values[prefix + "_systemd_hardening"] = True
    output = render(text, values)
    for directive in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=false",
    ):
        assert directive in output
    assert "ReadWritePaths=" + " ".join(values[p] for p in paths) in output


def test_tracked_text_has_no_conflict_markers():
    paths = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    marker = re.compile(r"^(?:<{7}|>{7}|\|{7})(?: |$)", re.MULTILINE)
    for path in filter(None, paths):
        data = (ROOT / path).read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        assert not marker.search(text), path


@pytest.mark.parametrize(
    "tasks_max,memory_max", [("512", ""), ("", "2G"), ("512", "2G")]
)
def test_metube_hardening_with_resource_limits(tasks_max, memory_max):
    values = variables("metube_deploy")
    text = (ROOT / "roles/metube_deploy/templates/metube.service.j2").read_text()
    previous = (ROOT / "tests/fixtures/lowfindings/metube_deploy-metube.j2").read_text()
    values.update(
        metube_systemd_tasks_max=tasks_max, metube_systemd_memory_max=memory_max
    )
    assert render(text, values) == render(previous, values)
    values["metube_systemd_hardening"] = True
    lines = render(text, values).splitlines()
    assert "NoNewPrivileges=true" in lines
    if tasks_max:
        assert "TasksMax=" + tasks_max in lines
    if memory_max:
        assert "MemoryMax=" + memory_max in lines


def test_related_password_rows_remain_protected():
    for path, names in [
        (
            "roles/postfixadmin_deploy/tasks/migrate_backup.yml",
            ["Backup old mail_users table", "Write mail_users backup"],
        ),
        (
            "roles/postfixadmin_restore/tasks/main.yml",
            ["Read admin table backup", "Parse admin backup data"],
        ),
        (
            "roles/mail_users_sync/tasks/sync_user.yml",
            ["Normalize existing user rows for {{ user.email }}"],
        ),
    ]:
        nodes = list(walk(tasks(path)))
        for name in names:
            assert next(n for n in nodes if n.get("name") == name)["no_log"] is True


def test_unifi_password_validation_is_early_and_guarded():
    main = tasks("roles/unifi_deploy/tasks/main.yml")
    assert main[0]["ansible.builtin.import_tasks"] == "validate.yml"
    nodes = tasks("roles/unifi_deploy/tasks/validate.yml")
    validation = next(
        n for n in nodes if "Require Home Assistant password" in n.get("name", "")
    )
    assert validation["when"] == "unifi_create_homeassistant_user | bool"
    conditions = validation["ansible.builtin.assert"]["that"]
    for value in ("", None, 123):
        assert not all(
            ENV.compile_expression(c)(unifi_homeassistant_password=value)
            for c in conditions
        )
    assert all(
        ENV.compile_expression(c)(unifi_homeassistant_password="supplied")
        for c in conditions
    )
