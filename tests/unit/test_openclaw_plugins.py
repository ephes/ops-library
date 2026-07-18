from pathlib import Path

import yaml


TASKS_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "tasks"
    / "plugins.yml"
)


def test_codex_plugin_install_uses_host_networking() -> None:
    tasks = yaml.safe_load(TASKS_PATH.read_text(encoding="utf-8"))
    install_task = next(
        (
            task
            for task in tasks
            if task.get("name")
            == "plugins | Install configured official Codex plugin release"
        ),
        None,
    )
    assert install_task is not None, "Codex plugin installation task not found"
    argv = install_task["ansible.builtin.command"]["argv"]

    assert argv[argv.index("--network") + 1] == "host"
