from pathlib import Path
import json
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_role_is_disabled_first_single_writer_and_quiesce_first() -> None:
    defaults = _text("roles/daybook_photos_archive_sync_deploy/defaults/main.yml")
    tasks = _text("roles/daybook_photos_archive_sync_deploy/tasks/main.yml")

    assert "daybook_photos_archive_sync_enabled: false" in defaults
    assert "daybook_photos_archive_sync_launchd_enabled: false" in defaults
    assert "Resolve effective task identity" in tasks
    assert "ansible_user_id == daybook_photos_archive_sync_service_user" in tasks
    assert "expected_writer_host | lower == inventory_hostname | lower" in tasks
    assert tasks.index("quiesce | Disable") < tasks.index("source | Install")
    assert "launchctl" in tasks
    assert "gui/{{ daybook_photos_archive_sync_uid.stdout | trim }}" in tasks


def test_launcher_is_exact_clean_execute_summary_and_never_mounts() -> None:
    launcher = _text("roles/daybook_photos_archive_sync_deploy/templates/archive-sync.sh.j2")

    assert "rev-parse HEAD" in launcher
    assert "status --porcelain=v1 --untracked-files=all" in launcher
    assert "GIT_CONFIG_GLOBAL=/dev/null" in launcher
    assert "GIT_CONFIG_SYSTEM=/dev/null" in launcher
    assert "venv_path ~ '/bin/daybook'" in launcher
    assert "checkout is not at the pinned revision" in launcher
    assert "venv_path ~ '/bin/python'" in launcher
    assert "Photos.sqlite" in launcher
    assert "launchd Photos.sqlite access failed with status $photos_access_status" in launcher
    assert "configured Photos.sqlite path does not exist" in launcher
    assert "Photos.sqlite preflight failed with status $photos_access_status" in launcher
    assert "LaunchAgent interpreter (/bin/bash)" in launcher
    assert "exit 77" in launcher
    assert "exit 66" in launcher
    assert "exit 74" in launcher
    assert "77|124|137" in launcher
    assert "daybook_photos_archive_sync_photos_access_timeout_seconds | int" in launcher
    assert launcher.index("venv_path ~ '/bin/python'") < launcher.index("venv_path ~ '/bin/daybook'")
    assert launcher.index("/usr/bin/env -i") < launcher.index("venv_path ~ '/bin/python'")
    assert "--kill-after=5" in launcher
    assert "--signal=TERM" in launcher
    assert "--kill-after=60" in launcher
    assert "photos archive-sync" in launcher
    assert "--execute" in launcher
    assert "--summary-only" in launcher
    assert "--expected-writer-host" in launcher
    assert "mount_smbfs" not in launcher
    assert "osascript" not in launcher


def test_plist_is_aqua_run_at_load_and_two_hour_interval() -> None:
    plist = _text("roles/daybook_photos_archive_sync_deploy/templates/archive-sync.plist.j2")
    defaults = _text("roles/daybook_photos_archive_sync_deploy/defaults/main.yml")

    assert "<string>Aqua</string>" in plist
    assert "<key>RunAtLoad</key>\n  <true/>" in plist
    assert "<key>StartInterval</key>" in plist
    assert "daybook_photos_archive_sync_interval_seconds: 7200" in defaults
    assert "<key>UserName</key>" not in plist


def test_role_installs_exact_bundle_and_owner_private_paths() -> None:
    tasks = _text("roles/daybook_photos_archive_sync_deploy/tasks/main.yml")
    defaults = _text("roles/daybook_photos_archive_sync_deploy/defaults/main.yml")

    assert "Install controller-verified Daybook source bundle" in tasks
    assert "Clone protected Daybook bundle without checkout" in tasks
    assert "Fetch exact Daybook archive synchronization revision" in tasks
    assert "Materialize exact detached Daybook archive synchronization revision" in tasks
    assert "Refusing to overwrite a dirty managed" in tasks
    assert "Require clean materialized Daybook checkout" in tasks
    assert "Inspect existing checkout index" in tasks
    assert "daybook_photos_archive_sync_git_index.stat.exists" in tasks
    assert "Verify installed Daybook console script" in tasks
    assert "Require clean checkout after environment synchronization" in tasks
    assert 'mode: "0700"' in tasks
    assert 'mode: "0600"' in tasks
    assert "/Library/LaunchAgents/" in defaults


def test_activation_and_watchdog_are_strictly_gated() -> None:
    tasks = _text("roles/daybook_photos_archive_sync_deploy/tasks/main.yml")
    defaults = _text("roles/daybook_photos_archive_sync_deploy/defaults/main.yml")

    activation_block = tasks.split(
        "- name: activation | Activate Nikon archive synchronization fail-closed", 1
    )[1]
    activation_gate = activation_block.split("  block:", 1)[0]
    assert "daybook_photos_archive_sync_launchd_enabled | bool" in activation_gate
    assert "activation | Disable archive synchronization after activation failure" in tasks
    assert "activation | Boot out archive synchronization after activation failure" in tasks
    assert "activation | Report fail-closed activation failure" in tasks
    assert "daybook_photos_archive_sync_timeout_seconds: 5400" in defaults
    assert "daybook_photos_archive_sync_photos_access_timeout_seconds: 15" in defaults
    assert "daybook_photos_archive_sync_interval_seconds: 7200" in defaults
    assert "daybook_photos_archive_sync_photos_access_timeout_seconds | int + 5 + daybook_photos_archive_sync_timeout_seconds | int + 60 < daybook_photos_archive_sync_interval_seconds | int" in tasks


@pytest.mark.parametrize("variable,override", [
    (None, None),
    *[(variable, path) for variable in ("stdout_log", "stderr_log") for path in (
        "/tmp/outside.log", "relative.log",
        "/Users/fixture/.daybook/nikon-archive-sync/logs/../outside.log",
    )],
    *[("venv_path", path) for path in (
        "/tmp/other-venv", "relative-venv",
        "/Users/fixture/.local/share/daybook-photos-archive-sync/daybook/../other-venv",
    )],
    ("repo_bundle_path", "/Users/fixture/Documents/other.bundle"),
    ("log_dir", "/Users/fixture/.daybook/nikon-archive-sync/../other-logs"),
    ("state_path", "/Users/fixture/.daybook/nikon-archive-sync/../other-state.json"),
    ("folder_map_path", "/Users/fixture/.daybook/nikon-archive-sync/../other-map.json"),
])
def test_managed_path_overrides_use_actual_ansible_validation(tmp_path, variable, override):
    # Execute only the role's two pure assertions, never deployment/quiesce tasks.
    role_tasks = yaml.safe_load(_text("roles/daybook_photos_archive_sync_deploy/tasks/main.yml"))
    names = {
        "validate | Validate Nikon archive synchronization configuration",
        "validate | Reject relative or traversing managed paths",
    }
    tasks = [task for task in role_tasks if task.get("name") in names]
    assert len(tasks) == 2 and {task["name"] for task in tasks} == names
    for task in tasks:
        assert "ansible.builtin.assert" in task
        assert set(task) <= {"name", "ansible.builtin.assert", "when", "loop"}
    variables = {
        "daybook_photos_archive_sync_enabled": True,
        "daybook_photos_archive_sync_service_user": "fixture",
        "daybook_photos_archive_sync_repo_ref": "a" * 40,
        "daybook_photos_archive_sync_repo_bundle_src": "/fixture/source.bundle",
        "daybook_photos_archive_sync_expected_smb_server": "fractal.example.invalid",
        "daybook_photos_archive_sync_expected_writer_host": "localhost",
        "ansible_user_id": "fixture", "ansible_facts": {"os_family": "Darwin"},
    }
    if variable:
        variables["daybook_photos_archive_sync_" + variable] = override
    playbook = [{"name": "Validate fixture paths", "hosts": "localhost", "gather_facts": False,
        "vars_files": [str(ROOT / "roles/daybook_photos_archive_sync_deploy/defaults/main.yml")],
        "vars": variables, "tasks": tasks}]
    path = tmp_path / "validate.yml"
    path.write_text(yaml.safe_dump(playbook, sort_keys=False))
    overrides = tmp_path / "overrides.json"
    overrides.write_text(json.dumps(variables))
    result = subprocess.run([str(Path(sys.executable).parent / "ansible-playbook"),
        "-i", "localhost,", "-c", "local", "--extra-vars", "@" + str(overrides), str(path)], capture_output=True, text=True, timeout=30)
    if variable is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok=2" in result.stdout and "skipped=0" in result.stdout, result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert "Nikon archive synchronization needs an exact Daybook" in result.stdout or "Nikon archive synchronization paths" in result.stdout, result.stdout + result.stderr
