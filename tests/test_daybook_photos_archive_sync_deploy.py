from pathlib import Path


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
    assert "daybook_photos_archive_sync_interval_seconds: 7200" in defaults
    assert "daybook_photos_archive_sync_timeout_seconds | int < daybook_photos_archive_sync_interval_seconds | int" in tasks
