import re
from pathlib import Path

import yaml
from jinja2 import Environment, nativetypes

from plugins.filter.zfs import zfs_size_to_bytes

ROOT = Path(__file__).resolve().parents[2]


def _regex_search(value: str, pattern: str) -> str | None:
    match = re.search(pattern, value)
    return match.group(0) if match else None


def _render_desired_value(task: dict, prefix: str, key: str, value: object) -> str:
    env = Environment()
    env.filters["local.ops_library.zfs_size_to_bytes"] = zfs_size_to_bytes
    env.filters["regex_search"] = _regex_search
    template = env.from_string(task["vars"][f"_{prefix}_desired_value"])
    return template.render(
        item={"key": key, "value": value},
        **{
            f"_{prefix}_size_properties": task["vars"][f"_{prefix}_size_properties"],
            f"_{prefix}_desired_raw": str(value).lower(),
        },
    ).strip()


def _render_native_desired_value(
    task: dict, prefix: str, key: str, value: object
) -> object:
    env = nativetypes.NativeEnvironment()
    env.filters["local.ops_library.zfs_size_to_bytes"] = zfs_size_to_bytes
    env.filters["regex_search"] = _regex_search
    raw_template = env.from_string(task["vars"][f"_{prefix}_desired_raw"])
    desired_raw = raw_template.render(item={"key": key, "value": value})
    template = env.from_string(task["vars"][f"_{prefix}_desired_value"])
    return template.render(
        item={"key": key, "value": value},
        **{
            f"_{prefix}_size_properties": task["vars"][f"_{prefix}_size_properties"],
            f"_{prefix}_desired_raw": desired_raw,
        },
    )


def test_dataset_byte_properties_use_parseable_comparison() -> None:
    path = ROOT / "roles/zfs_dataset/tasks/configure_dataset.yml"
    tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
    get_task = next(task for task in tasks if "get current" in task["name"])
    configure_task = next(
        task
        for task in tasks
        if task["name"] == "configure_dataset | configure dataset properties"
    )

    assert " -p " in f" {get_task['ansible.builtin.command']['cmd']} "
    size_properties = configure_task["vars"]["_zfs_dataset_size_properties"]
    assert {
        "quota",
        "refquota",
        "reservation",
        "refreservation",
        "recordsize",
        "volblocksize",
        "volsize",
        "special_small_blocks",
    } == set(size_properties)
    assert (
        _render_desired_value(configure_task, "zfs_dataset", "quota", "6.5T")
        == "7146825580544"
    )
    assert _render_desired_value(configure_task, "zfs_dataset", "quota", "none") == "0"
    assert (
        _render_desired_value(configure_task, "zfs_dataset", "recordsize", "128K")
        == "131072"
    )
    assert (
        _render_desired_value(configure_task, "zfs_dataset", "compression", "lz4")
        == "lz4"
    )
    assert (
        _render_desired_value(configure_task, "zfs_dataset", "quota", "6.5tb")
        == "7146825580544"
    )
    assert (
        _render_desired_value(configure_task, "zfs_dataset", "quota", "1.1T")
        == "1209462790553"
    )
    assert (
        _render_desired_value(configure_task, "zfs_dataset", "volsize", 8589934592)
        == "8589934592"
    )
    assert (
        _render_native_desired_value(
            configure_task, "zfs_dataset", "volsize", 8589934592
        )
        == 8589934592
    )
    assert (
        _render_native_desired_value(configure_task, "zfs_dataset", "quota", "6.5T")
        == 7146825580544
    )
    assert "\\" not in configure_task["vars"]["_zfs_dataset_desired_value"]
    assert "_zfs_dataset_desired_value | string" in configure_task["when"]
    assert "item.key == 'refreservation'" in configure_task["when"]
    assert "(_zfs_dataset_desired_raw | string) == 'auto'" in configure_task["when"]
    assert "refreservation" in configure_task["changed_when"]


def test_pool_root_byte_properties_match_dataset_normalization() -> None:
    path = ROOT / "roles/zfs_pool_deploy/tasks/configure.yml"
    tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
    get_task = next(
        task
        for task in tasks
        if task["name"] == "configure | Get current root filesystem properties"
    )
    configure_task = next(
        task
        for task in tasks
        if task["name"] == "configure | Configure root filesystem properties"
    )

    assert " -p " in f" {get_task['ansible.builtin.command']['cmd']} "
    assert set(configure_task["vars"]["_zfs_root_fs_size_properties"]) == {
        "quota",
        "refquota",
        "reservation",
        "refreservation",
        "recordsize",
        "volblocksize",
        "volsize",
        "special_small_blocks",
    }
    assert (
        _render_desired_value(configure_task, "zfs_root_fs", "quota", "6.5T")
        == "7146825580544"
    )
    assert _render_desired_value(configure_task, "zfs_root_fs", "quota", "none") == "0"
    assert (
        _render_desired_value(configure_task, "zfs_root_fs", "recordsize", "128K")
        == "131072"
    )
    assert (
        _render_desired_value(configure_task, "zfs_root_fs", "quota", "3.3T")
        == "3628388371660"
    )
    assert (
        _render_desired_value(configure_task, "zfs_root_fs", "compression", "lz4")
        == "lz4"
    )
    assert (
        _render_native_desired_value(configure_task, "zfs_root_fs", "quota", "6.5T")
        == 7146825580544
    )
    assert (
        _render_native_desired_value(
            configure_task, "zfs_root_fs", "recordsize", 131072
        )
        == 131072
    )
    assert "\\" not in configure_task["vars"]["_zfs_root_fs_desired_value"]
    assert "_zfs_root_fs_desired_value | string" in configure_task["when"]
    assert "item.key == 'refreservation'" in configure_task["when"]
    assert "(_zfs_root_fs_desired_raw | string) == 'auto'" in configure_task["when"]
    assert "refreservation" in configure_task["changed_when"]
