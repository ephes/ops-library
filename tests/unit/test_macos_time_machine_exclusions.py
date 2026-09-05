import shlex
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = ROOT / "roles/macos_time_machine_exclusions/tasks/main.yml"
PLIST_PATH = ROOT / (
    "roles/macos_time_machine_exclusions/templates/time-machine-exclusions.plist.j2"
)
SCRIPT_PATH = ROOT / (
    "roles/macos_time_machine_exclusions/templates/apply-exclusions.zsh.j2"
)


def test_first_bootstrap_does_not_start_a_second_exclusion_pass() -> None:
    tasks = yaml.safe_load(TASKS_PATH.read_text(encoding="utf-8"))
    apply_task = next(
        task
        for task in tasks
        if task["name"].startswith("Apply configured Time Machine exclusions")
    )

    conditions = apply_task["when"]
    assert "_macos_time_machine_exclusions_launchd.rc == 0" in conditions
    assert "not _macos_time_machine_exclusions_script.changed" in conditions
    assert "not _macos_time_machine_exclusions_plist.changed" in conditions

    plist = PLIST_PATH.read_text(encoding="utf-8")
    assert "<key>RunAtLoad</key>\n  <true/>" in plist

    bootstrap_task = next(
        task
        for task in tasks
        if task["name"] == "Load Time Machine exclusion LaunchAgent"
    )
    assert bootstrap_task["retries"] == 5
    assert bootstrap_task["delay"] == 1
    assert "_macos_time_machine_exclusions_bootstrap.rc == 0" in bootstrap_task["until"]
    bootout_task = next(
        task
        for task in tasks
        if task["name"] == "Unload changed Time Machine exclusion LaunchAgent"
    )
    assert bootout_task["failed_when"] is False
    assert bootout_task["changed_when"] == "_macos_time_machine_exclusions_bootout.rc == 0"


def test_exclusion_script_never_deletes_or_thins_data() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "tmutil addexclusion" in script
    assert "tmutil delete" not in script
    assert "tmutil thin" not in script
    assert "rm " not in script


def test_exclusion_script_continues_after_one_path_fails() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'local tm_path="$1"' in script
    assert "\npath=" not in script
    assert "overall_status=0" in script
    assert "apply_exclusion {{ path | quote }} || overall_status=1" in script
    assert 'exit "$overall_status"' in script


def test_steady_state_apply_reports_new_exclusions_as_changed() -> None:
    tasks = yaml.safe_load(TASKS_PATH.read_text(encoding="utf-8"))
    apply_task = next(
        task
        for task in tasks
        if task["name"].startswith("Apply configured Time Machine exclusions")
    )

    assert apply_task["register"] == "_macos_time_machine_exclusions_apply"
    assert "changed=true" in apply_task["changed_when"]
    assert 'print -r -- "changed=true path=$tm_path"' in SCRIPT_PATH.read_text(
        encoding="utf-8"
    )


def test_exclusion_script_quotes_paths_with_spaces() -> None:
    env = Environment()
    env.filters["quote"] = shlex.quote
    path = "/Users/jochen/Library/Application Support/Claude/vm_bundles"
    rendered = env.from_string(SCRIPT_PATH.read_text(encoding="utf-8")).render(
        macos_time_machine_exclusions_paths=[path]
    )

    assert f"apply_exclusion {shlex.quote(path)}" in rendered


@pytest.mark.skipif(
    not Path("/bin/zsh").exists() or not Path("/usr/bin/grep").exists(),
    reason="rendered exclusion script requires macOS zsh and /usr/bin/grep",
)
def test_rendered_exclusion_script_attempts_later_paths_after_failure(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    log_path = tmp_path / "tmutil.log"
    stub_path = tmp_path / "tmutil"
    stub_path.write_text(
        "#!/bin/zsh\n"
        f'print -r -- "$@" >> {shlex.quote(str(log_path))}\n'
        'if [[ "$1" == isexcluded && "$2" == '
        f"{shlex.quote(str(first))} ]]; then exit 2; fi\n"
        "if [[ \"$1\" == isexcluded ]]; then print '[Included]'; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub_path.chmod(0o755)

    env = Environment()
    env.filters["quote"] = shlex.quote
    rendered = env.from_string(SCRIPT_PATH.read_text(encoding="utf-8")).render(
        macos_time_machine_exclusions_paths=[str(first), str(second)]
    )
    rendered = rendered.replace("/usr/bin/tmutil", str(stub_path))
    script_path = tmp_path / "apply-exclusions"
    script_path.write_text(rendered, encoding="utf-8")
    script_path.chmod(0o755)

    result = subprocess.run(
        ["/bin/zsh", str(script_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert f"isexcluded {first}" in calls
    assert f"isexcluded {second}" in calls
    assert f"addexclusion {second}" in calls
