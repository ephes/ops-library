"""Static/render regressions for pinned, verified root downloads."""

import importlib.util
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "downloads", ROOT / "scripts/check_root_downloads.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.mark.parametrize("role", checker.ROLES)
def test_downloads_verified(role):
    for path in checker.task_files(role):
        assert not list(
            checker.findings(yaml.safe_load(path.read_text()), role, path.name)
        ), path


@pytest.mark.parametrize(
    "module,args",
    [
        ("get_url", {"url": "https://example.org/tool"}),
        (
            "ansible.builtin.get_url",
            {"url": "https://example.org/latest/tool", "checksum": "sha256:abc"},
        ),
        ("unarchive", {"src": "https://example.org/tool.tar.gz", "remote_src": True}),
        ("shell", "curl https://example.org/tool | sh"),
    ],
)
def test_checker_rejects_new_unverified_download(module, args):
    assert list(checker.findings([{"block": [{module: args}]}]))


def test_exception_is_exact():
    role, filename, url = checker.EXCEPTION
    assert not list(checker.findings([{"get_url": {"url": url}}], role, filename))
    assert list(checker.findings([{"get_url": {"url": url + "?new"}}], role, filename))


@pytest.mark.parametrize("role", checker.ROLES)
def test_defaults_pin_checksums_and_document_them(role):
    path = ROOT / "roles" / role
    defaults = yaml.safe_load((path / "defaults/main.yml").read_text())
    readme = (path / "README.md").read_text()
    checksums = {k: v for k, v in defaults.items() if "checksum" in k}
    assert checksums
    for key, value in checksums.items():
        assert key in readme
        for digest in (value.values() if isinstance(value, dict) else [value]):
            assert digest.startswith("sha256:") and len(digest) == 71
    for key, value in defaults.items():
        if key.endswith("_version") and key not in ("vibe_coding_node_major_version",):
            assert value != "latest"


def test_mc_reuses_installer_and_reconciles_existing_binary():
    nodes = yaml.safe_load((ROOT / "roles/echoport_backup/tasks/main.yml").read_text())
    include = next(n for n in nodes if "ansible.builtin.include_role" in n)
    assert include["ansible.builtin.include_role"] == {
        "name": "local.ops_library.minio_backup",
        "tasks_from": "mc_install",
    }
    assert "when" not in include


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_release_urls_render_with_matching_architecture_checksum(arch):
    env = Environment(undefined=StrictUndefined)
    for role in checker.ROLES:
        defaults = yaml.safe_load(
            (ROOT / f"roles/{role}/defaults/main.yml").read_text()
        )
        values = dict(
            defaults, ansible_architecture=arch, ansible_facts={"os_family": "Debian"}
        )
        # Follow the role's architecture selection facts, then render the actual
        # download arguments (not a duplicate URL built only by the test).
        for path in checker.task_files(role):
            for task in checker.walk(yaml.safe_load(path.read_text())):
                for key, expression in task.get("ansible.builtin.set_fact", {}).items():
                    if key.endswith(("_arch", "_target")):
                        values[key] = env.from_string(expression).render(values).strip()
                args = task.get("get_url", task.get("ansible.builtin.get_url"))
                if args and (role, path.name, args["url"]) != checker.EXCEPTION:
                    url = env.from_string(args["url"]).render(values)
                    digest = env.from_string(args["checksum"]).render(values)
                    assert url.startswith("https://") and "latest" not in url
                    assert digest.startswith("sha256:") and len(digest) == 71
                    if role not in ("echoport_backup", "sops_dependencies"):
                        target = (
                            "x86_64"
                            if arch == "x86_64"
                            else (
                                "arm64"
                                if role == "shell_basics_deploy"
                                or path.name in ("lazygit.yml", "neovim.yml")
                                else "aarch64"
                            )
                        )
                        if role == "shell_basics_deploy" and arch == "x86_64":
                            target = "amd64"
                        assert target in url


def test_shared_mc_download_has_checksum():
    nodes = yaml.safe_load(
        (ROOT / "roles/minio_backup/tasks/mc_install.yml").read_text()
    )
    assert not list(checker.findings(nodes))
    download = next(
        n["ansible.builtin.get_url"] for n in nodes if "ansible.builtin.get_url" in n
    )
    assert download["checksum"] == "{{ minio_mc_checksum }}"
    assert not any("when" in n for n in nodes if "ansible.builtin.get_url" in n)


def test_echoport_pins_are_passed_over_included_role_defaults():
    nodes = yaml.safe_load((ROOT / "roles/echoport_backup/tasks/main.yml").read_text())
    include = next(n for n in nodes if "ansible.builtin.include_role" in n)
    assert include["vars"]["minio_mc_version"] == "{{ echoport_backup_mc_version }}"
    assert include["vars"]["minio_mc_checksum"] == "{{ echoport_backup_mc_checksum }}"
    env = Environment(undefined=StrictUndefined)
    values = yaml.safe_load(
        (ROOT / "roles/echoport_backup/defaults/main.yml").read_text()
    )
    values["echoport_backup_mc_version"] = "custom-release"
    values["echoport_backup_mc_checksum"] = "custom-checksum"
    assert (
        env.from_string(include["vars"]["minio_mc_version"]).render(values)
        == "custom-release"
    )
    assert (
        env.from_string(include["vars"]["minio_mc_checksum"]).render(values)
        == "custom-checksum"
    )
    assert "custom-release" in env.from_string(
        values["echoport_backup_mc_download_url"]
    ).render(values)


@pytest.mark.parametrize(
    "task",
    [
        {"get_url": "url=https://example.org/tool dest=/tmp/tool"},
        {"unarchive": "src=https://example.org/tool.tar.gz dest=/opt"},
        {"shell": 'curl \\\n "$DOWNLOAD_URL" -o /tmp/tool'},
        {"shell": "wget\n https://example.org/tool"},
        {"unarchive": {"src": "{{ tool_url }}", "remote_src": True}},
        {"uri": {"url": "https://example.org/tool", "dest": "/tmp/tool"}},
    ],
)
def test_checker_rejects_bypass_forms(task):
    assert list(checker.findings([task]))


def test_empty_task_files_are_safe():
    assert not list(checker.findings(yaml.safe_load("# only a comment")))


@pytest.mark.parametrize("suffix", [".yaml", ".yml"])
def test_cli_scans_nested_task_files(tmp_path, monkeypatch, capsys, suffix):
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "ROLES", ("example",))
    path = tmp_path / "roles/example/tasks/nested" / ("download" + suffix)
    path.parent.mkdir(parents=True)
    path.write_text(
        "- get_url:\n    url: https://example.org/tool\n    dest: /tmp/tool\n"
    )
    assert list(checker.task_files("example")) == [path]
    assert checker.main()
    assert str(path.relative_to(tmp_path)) in capsys.readouterr().out


def test_archive_requires_preceding_verified_download():
    download = {
        "get_url": {
            "url": "https://example.org/tool",
            "dest": "{{ tmp.path }}/tool.tar.gz",
            "checksum": "sha256:test-fixture",
        }
    }
    extract = {"unarchive": {"src": "{{ tmp.path }}/tool.tar.gz", "remote_src": True}}
    assert not list(checker.findings([download, extract]))
    assert list(checker.findings([extract, download]))
    download["get_url"].pop("checksum")
    assert len(list(checker.findings([download, extract]))) == 2
