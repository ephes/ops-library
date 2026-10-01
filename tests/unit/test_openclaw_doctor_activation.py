from pathlib import Path

import yaml


ROLE_PATH = Path(__file__).resolve().parents[2] / "roles" / "openclaw_deploy"


def _tasks(name: str) -> list:
    return yaml.safe_load((ROLE_PATH / "tasks" / name).read_text(encoding="utf-8"))


def _activation_block() -> dict:
    return next(task for task in _tasks("doctor_activation.yml") if "block" in task)


def _block_task(suffix: str) -> dict:
    return next(
        task
        for task in _activation_block()["block"]
        if task["name"].endswith(suffix)
    )


def test_doctor_activation_runs_before_any_cli_task_opens_state() -> None:
    imports = [
        task["ansible.builtin.import_tasks"]
        for task in _tasks("main.yml")
        if "ansible.builtin.import_tasks" in task
    ]
    activation = imports.index("doctor_activation.yml")

    assert imports.index("config.yml") < activation
    assert activation < imports.index("plugins.yml")
    assert activation < imports.index("audio_transcription.yml")


def test_doctor_activation_is_gated_to_v2026_9_7_and_later() -> None:
    task = next(
        task
        for task in _tasks("main.yml")
        if task.get("ansible.builtin.import_tasks") == "doctor_activation.yml"
    )
    conditions = task["when"]

    assert "openclaw_doctor_activation_enabled | bool" in conditions
    assert "not ansible_check_mode" in conditions
    assert any("'2026.9.7', '>='" in condition for condition in conditions)
    defaults = yaml.safe_load(
        (ROLE_PATH / "defaults" / "main.yml").read_text(encoding="utf-8")
    )
    assert defaults["openclaw_doctor_activation_enabled"] is True


def test_doctor_activation_only_runs_when_running_image_differs() -> None:
    assert _activation_block()["when"] == (
        "_openclaw_doctor_activation_required | bool"
    )
    decision = next(
        task
        for task in _tasks("doctor_activation.yml")
        if task["name"].endswith("needs activation")
    )
    expression = decision["ansible.builtin.set_fact"][
        "_openclaw_doctor_activation_required"
    ]
    assert "_openclaw_doctor_current_image.rc != 0" in expression
    assert "openclaw_image_name ~ ':' ~ openclaw_image_tag" in expression


def test_doctor_activation_stops_gateway_before_doctor() -> None:
    names = [task["name"] for task in _activation_block()["block"]]
    stop = next(i for i, name in enumerate(names) if "Stop gateway" in name)
    doctor = next(i for i, name in enumerate(names) if "Doctor repair" in name)

    assert stop < doctor
    stop_task = _activation_block()["block"][stop]
    assert stop_task["ansible.builtin.systemd"]["state"] == "stopped"


def test_doctor_activation_matches_official_entrypoint_invocation() -> None:
    task = _block_task("Doctor repair with the target image")
    argv = task["ansible.builtin.command"]["argv"]

    # Doctor refreshes configured npm plugins, so it needs network access.
    assert argv[argv.index("--network") + 1] == "host"
    assert argv[argv.index("--user") + 1] == "1000:1000"
    assert argv[argv.index("--entrypoint") + 1] == "node"
    image = argv.index("{{ openclaw_image_name }}:{{ openclaw_image_tag }}")
    assert argv[image + 1 :] == ["openclaw.mjs", "doctor", "--fix", "--non-interactive"]
    assert task["notify"] == "restart openclaw"


def test_failed_doctor_keeps_gateway_stopped() -> None:
    rescue = _activation_block()["rescue"]

    assert [next(iter(set(task) - {"name"})) for task in rescue] == [
        "ansible.builtin.fail"
    ]
