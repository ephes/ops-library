"""vibe_coding_deploy applies the dotfiles without chezmoi externals."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = yaml.safe_load(
    (ROOT / "roles/vibe_coding_deploy/tasks/chezmoi.yml").read_text()
)


def _task(name):
    (task,) = [t for t in TASKS if t["name"] == name]
    return task


def _argv(name):
    return _task(name)["ansible.builtin.command"]["argv"]


def test_apply_excludes_externals_and_keeps_force():
    argv = _argv("chezmoi | Apply dotfiles")
    assert argv[:2] == ["/usr/local/bin/chezmoi", "apply"]
    assert "--force" in argv
    assert "--exclude=externals" in argv


def test_status_excludes_externals_so_changed_when_converges():
    argv = _argv("chezmoi | Check for pending dotfile changes")
    assert argv[:2] == ["/usr/local/bin/chezmoi", "status"]
    assert "--exclude=externals" in argv
    apply = _task("chezmoi | Apply dotfiles")
    assert "vibe_coding_chezmoi_status.stdout" in apply["changed_when"]


def test_no_chezmoi_command_touches_externals():
    for task in TASKS:
        argv = task.get("ansible.builtin.command", {}).get("argv", [])
        if argv[:1] == ["/usr/local/bin/chezmoi"] and argv[1] in (
            "apply",
            "status",
            "update",
            "diff",
        ):
            assert "--exclude=externals" in argv, task["name"]
