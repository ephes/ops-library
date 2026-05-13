import json
from pathlib import Path
from typing import Any

from jinja2 import Environment


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "nyxmon_storage_exporter"
    / "templates"
    / "nyxmon-storage-metrics.py.j2"
)


def _ansible_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _ternary(value: Any, true_value: Any, false_value: Any) -> Any:
    return true_value if _ansible_bool(value) else false_value


def _load_exporter_namespace(tmp_path: Path) -> dict[str, Any]:
    env = Environment()
    env.filters["bool"] = _ansible_bool
    env.filters["ternary"] = _ternary
    env.filters["to_json"] = json.dumps

    template = env.from_string(TEMPLATE_PATH.read_text(encoding="utf-8"))
    rendered = template.render(
        nyxmon_storage_exporter_smartctl_no_spinup=False,
        nyxmon_storage_exporter_quiet_hours_enabled=False,
        nyxmon_storage_exporter_quiet_hours_start="06:00",
        nyxmon_storage_exporter_quiet_hours_end="22:00",
        nyxmon_storage_exporter_quiet_hours_skip_pools=[],
        nyxmon_storage_exporter_quiet_hours_skip_disk_types=["sat"],
        nyxmon_storage_exporter_quiet_hours_spindown_enabled=False,
        nyxmon_storage_exporter_quiet_hours_spindown_script="",
        nyxmon_storage_exporter_quiet_hours_spindown_min_interval_sec=300,
        nyxmon_storage_exporter_quiet_hours_spindown_state_file=str(
            tmp_path / "spindown.ts"
        ),
        nyxmon_storage_exporter_pool_cache_path=str(tmp_path / "pool-cache.json"),
        nyxmon_storage_exporter_pools=[],
        nyxmon_storage_exporter_disks=[],
        nyxmon_storage_exporter_filesystems=[],
    )
    namespace: dict[str, Any] = {"__name__": "nyxmon_storage_exporter_test"}
    exec(compile(rendered, str(TEMPLATE_PATH), "exec"), namespace)
    return namespace


def test_zpool_list_uses_cached_pool_metrics_for_skipped_pool(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    cache_path = tmp_path / "pool-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "pools": {
                    "tank": {
                        "ts": 1_700_000_000,
                        "sample": {
                            "health": "ONLINE",
                            "size": "10.9T",
                            "alloc": "9.8T",
                            "free": "1.1T",
                            "cap": "90%",
                            "cap_ratio": 0.9,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    payload = namespace["_zpool_list"](["tank"], {"tank"})

    assert payload["tank"]["cap_ratio"] == 0.9
    assert payload["tank"]["health"] == "ONLINE"
    assert payload["tank"]["skipped"] is True
    assert payload["tank"]["reason"] == "quiet_hours"
    assert payload["tank"]["cached"] is True
    assert payload["tank"]["cache_timestamp"] == 1_700_000_000
    assert payload["tank"]["cache_age_seconds"] >= 0


def test_zpool_list_discovers_names_before_skipping_pools(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    cache_path = tmp_path / "pool-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "pools": {
                    "tank": {
                        "ts": 1_700_000_000,
                        "sample": {"health": "ONLINE", "cap_ratio": 0.9},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_run(argv: list[str]) -> Any:
        if argv == ["zpool", "list", "-H", "-o", "name,health,size,alloc,free,cap"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="tank\tONLINE\t10.9T\t9.8T\t1.1T\t90%\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    namespace["_run"] = fake_run

    payload = namespace["_zpool_list"]([], {"tank"})

    assert payload["tank"]["cap_ratio"] == 0.9
    assert payload["tank"]["cached"] is True
    assert payload["tank"]["skipped"] is True


def test_zpool_list_preserves_skipped_payload_when_no_cache_exists(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    payload = namespace["_zpool_list"](["tank"], {"tank"})

    assert payload == {"tank": {"skipped": True, "reason": "quiet_hours"}}


def test_zpool_list_ignores_malformed_pool_cache_for_skipped_pool(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    (tmp_path / "pool-cache.json").write_text("not json", encoding="utf-8")

    payload = namespace["_zpool_list"](["tank"], {"tank"})

    assert payload == {"tank": {"skipped": True, "reason": "quiet_hours"}}


def test_zpool_list_writes_successful_pool_sample_to_cache(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    def fake_run(argv: list[str]) -> Any:
        if argv[:5] == ["zpool", "list", "-H", "-o", "name,health,size,alloc,free,cap"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="tank\tONLINE\t10.9T\t9.8T\t1.1T\t90%\n",
                stderr="",
            )
        if argv == ["zpool", "status", "tank"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="  scan: scrub repaired 0B in 00:00:01 on Sun Dec 14 07:24:50 2025\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    namespace["_run"] = fake_run

    payload = namespace["_zpool_list"](["tank"], set())

    assert payload["tank"]["cached"] is False
    assert payload["tank"]["cap_ratio"] == 0.9

    cache = json.loads((tmp_path / "pool-cache.json").read_text(encoding="utf-8"))
    sample = cache["pools"]["tank"]["sample"]
    assert sample["cap_ratio"] == 0.9
    assert sample["health"] == "ONLINE"
    assert not {
        "cached",
        "cache_age_seconds",
        "cache_timestamp",
        "cache_write_error",
        "reason",
        "skipped",
    }.intersection(sample)


def test_zpool_list_marks_successful_pool_when_cache_write_fails(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    def fake_run(argv: list[str]) -> Any:
        if argv[:5] == ["zpool", "list", "-H", "-o", "name,health,size,alloc,free,cap"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="tank\tONLINE\t10.9T\t9.8T\t1.1T\t90%\n",
                stderr="",
            )
        if argv == ["zpool", "status", "tank"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    namespace["_run"] = fake_run
    namespace["_write_json_file"] = lambda _path, _data: False

    payload = namespace["_zpool_list"](["tank"], set())

    assert payload["tank"]["cached"] is False
    assert payload["tank"]["cache_write_error"] is True
