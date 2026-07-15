from pathlib import Path
import re

import yaml


ROLE_PATH = (
    Path(__file__).resolve().parents[2] / "roles" / "homeassistant_deploy" / "tasks"
)
ROLE_ROOT = ROLE_PATH.parent


def _tasks_by_name(filename: str) -> dict[str, dict]:
    tasks = yaml.safe_load((ROLE_PATH / filename).read_text(encoding="utf-8"))
    return {task["name"]: task for task in tasks}


def test_python_inspection_commands_run_in_check_mode():
    tasks = _tasks_by_name("python.yml")
    inspection_tasks = {
        "Check for requested Python version",
        "Determine python executable path",
        "Detect current virtualenv Python version",
        "Check current virtualenv pip availability",
        "Check for legacy Matter server package in Home Assistant virtualenv",
        "Read installed Home Assistant version",
        "Capture installed Home Assistant version",
    }

    assert all(tasks[name]["check_mode"] is False for name in inspection_tasks)


def test_matter_server_inspection_commands_run_in_check_mode():
    tasks = _tasks_by_name("matter_server.yml")
    inspection_tasks = {
        "Detect current Matter server virtualenv Python version",
        "Check current Matter server virtualenv pip availability",
        "Check Matter server chip dependency",
        "Read installed Matter server version",
    }

    assert all(tasks[name]["check_mode"] is False for name in inspection_tasks)


def test_api_helper_cleanup_does_not_report_persistent_changes():
    cleanup_tasks = {
        "area_registry.yml":
            "Clean up Home Assistant area registry update result file",
        "assist_pipelines.yml": "Clean up Assist pipelines helper result file",
        "assist_pipeline_stt.yml": "Clean up Assist pipeline update result file",
    }

    assert all(
        _tasks_by_name(filename)[task_name]["changed_when"] is False
        for filename, task_name in cleanup_tasks.items()
    )


def test_virtualenv_commands_run_as_homeassistant_user():
    virtualenv_commands = []
    for task_file in ROLE_PATH.glob("*.yml"):
        tasks = yaml.safe_load(task_file.read_text(encoding="utf-8"))
        for task in tasks:
            command = task.get("ansible.builtin.command")
            if command is None or "virtualenv_path" not in str(command):
                continue
            virtualenv_commands.append((task_file.name, task))

    assert virtualenv_commands
    assert all(task.get("become") is True for _, task in virtualenv_commands)
    assert all(
        task.get("become_user") == "{{ homeassistant_user }}"
        for _, task in virtualenv_commands
    )


def test_virtualenv_ownership_is_reconciled_recursively():
    ownership_tasks = {
        "python.yml": "Ensure Home Assistant virtualenv ownership",
        "matter_server.yml": "Ensure Matter server virtualenv ownership",
    }

    assert all(
        _tasks_by_name(filename)[task_name]["ansible.builtin.file"]["recurse"]
        is True
        for filename, task_name in ownership_tasks.items()
    )


def test_configuration_template_omits_removed_yaml_integrations():
    template = (ROLE_ROOT / "templates" / "configuration.yaml.j2").read_text(
        encoding="utf-8"
    )

    assert "\nsystem_monitor:" not in template
    assert "\ndiscovery:" not in template


def test_existing_role_generated_yaml_integrations_are_migrated():
    task = _tasks_by_name("configuration.yml")[
        "Remove obsolete role-generated YAML integration blocks"
    ]

    assert len(task["loop"]) == 2
    assert any("system_monitor" in pattern for pattern in task["loop"])
    assert any("discovery" in pattern for pattern in task["loop"])

    configuration = """\
# Before
mobile_app:

# System monitor
system_monitor:
  process:
    - python3
  resources:
    - type: disk_use_percent
      arg: /
    - type: memory_free
    - type: memory_use_percent
    - type: processor_use
    - type: processor_temperature
    - type: last_boot

# User content between legacy blocks
history:

# Discovery
discovery:
  ignore:
    - sonos
    - samsung_tv

# After
mqtt:
"""
    migrated = configuration
    for pattern in task["loop"]:
        migrated = re.sub(pattern, "", migrated)

    assert migrated == """\
# Before
mobile_app:

# User content between legacy blocks
history:

# After
mqtt:
"""
