from pathlib import Path

import yaml


ROLE_ROOT = Path(__file__).resolve().parents[2] / "roles" / "paperless_deploy"


def _tasks_by_name(filename: str) -> dict[str, dict]:
    tasks = yaml.safe_load((ROLE_ROOT / "tasks" / filename).read_text(encoding="utf-8"))
    return {task["name"]: task for task in tasks}


def test_release_checksum_is_required_and_always_passed_to_get_url():
    validation = _tasks_by_name("validate.yml")["Validate required secrets"]
    download = _tasks_by_name("application.yml")[
        "Download Paperless release archive"
    ]

    checksum_checks = "\n".join(validation["ansible.builtin.assert"]["that"])
    assert "^sha256:[a-f0-9]{64}$" in checksum_checks
    assert download["ansible.builtin.get_url"]["checksum"] == (
        "{{ paperless_release_checksum }}"
    )


def test_release_extraction_stages_before_switching_current_symlink():
    tasks = yaml.safe_load(
        (ROLE_ROOT / "tasks" / "application.yml").read_text(encoding="utf-8")
    )
    tasks_by_name = {task["name"]: task for task in tasks}
    extraction = tasks_by_name["Extract Paperless release"]
    extraction_tasks = {task["name"]: task for task in extraction["block"]}

    unarchive = extraction_tasks["Unarchive release tarball"][
        "ansible.builtin.unarchive"
    ]
    move = extraction_tasks["Move extracted release to versioned directory"][
        "ansible.builtin.command"
    ]["cmd"]

    assert unarchive["dest"] == "{{ paperless_release_staging_dir }}"
    assert "paperless_release_staging_dir" in move
    assert "paperless_release_dir" in move
    assert extraction["always"][0]["ansible.builtin.file"]["state"] == "absent"

    names = [task["name"] for task in tasks]
    assert names.index("Extract Paperless release") < names.index(
        "Remove legacy non-symlink Paperless current path"
    ) < names.index("Update current release symlink")
