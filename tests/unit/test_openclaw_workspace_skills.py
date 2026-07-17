from pathlib import Path

import yaml


ROLE_PATH = Path(__file__).resolve().parents[2] / "roles" / "openclaw_deploy"


def _tasks(filename: str) -> list[dict]:
    return yaml.safe_load(
        (ROLE_PATH / "tasks" / filename).read_text(encoding="utf-8")
    )


def test_workspace_skills_are_disabled_by_default() -> None:
    defaults = yaml.safe_load(
        (ROLE_PATH / "defaults" / "main.yml").read_text(encoding="utf-8")
    )

    assert defaults["openclaw_workspace_skills"] == []


def test_workspace_skill_files_are_copied_into_active_workspace() -> None:
    task = next(
        task
        for task in _tasks("workspace_skills.yml")
        if task["name"] == "workspace_skills | Deploy managed skill files"
    )
    copy = task["ansible.builtin.copy"]

    assert copy["src"] == "{{ item.1.src }}"
    assert "openclaw_agent_workspace_dir" in copy["dest"]
    assert "/skills/" in copy["dest"]
    assert task["register"] == "_openclaw_workspace_skill_files_write"


def test_workspace_skills_are_deployed_before_session_refresh() -> None:
    tasks = _tasks("main.yml")
    imports = [
        task["ansible.builtin.import_tasks"]
        for task in tasks
        if "ansible.builtin.import_tasks" in task
    ]

    assert imports.index("workspace_skills.yml") < imports.index("session_state.yml")


def test_session_refresh_tracks_workspace_skill_names_and_content() -> None:
    tasks = _tasks("session_state.yml")
    render = next(
        task
        for task in tasks
        if task["name"] == "session_state | Render managed skills manifest"
    )
    refresh = next(
        task
        for task in tasks
        if task["name"] == "session_state | Reset session bindings when managed skills changed"
    )
    manifest = render["ansible.builtin.copy"]["content"]
    condition = "\n".join(refresh["when"])

    assert '"managed_workspace_skills"' in manifest
    assert "_openclaw_workspace_skill_files_write is changed" in condition
