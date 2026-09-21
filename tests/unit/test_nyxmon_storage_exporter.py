import io
import json
import plistlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
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


def _load_exporter_namespace(
    tmp_path: Path,
    zfs_datasets: list[dict[str, str]] | None = None,
    disks: list[dict[str, str]] | None = None,
    pools: list[str] | None = None,
    pool_capacity_thresholds: dict[str, dict[str, float | int]] | None = None,
    timemachine_bundle_dirs: list[str] | None = None,
) -> dict[str, Any]:
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
        nyxmon_storage_exporter_quiet_hours_cache_max_age_sec=172800,
        nyxmon_storage_exporter_pool_cache_path=str(tmp_path / "pool-cache.json"),
        nyxmon_storage_exporter_pools=pools or [],
        nyxmon_storage_exporter_pool_capacity_thresholds=(
            pool_capacity_thresholds or {}
        ),
        nyxmon_storage_exporter_disks=disks or [],
        nyxmon_storage_exporter_filesystems=[],
        nyxmon_storage_exporter_zfs_datasets=zfs_datasets or [],
        nyxmon_storage_exporter_timemachine_bundle_dirs=timemachine_bundle_dirs or [],
    )
    namespace: dict[str, Any] = {"__name__": "nyxmon_storage_exporter_test"}
    exec(compile(rendered, str(TEMPLATE_PATH), "exec"), namespace)
    return namespace


def _local_timestamp(value: str) -> int:
    dt = datetime.strptime(value, "%a %b %d %H:%M:%S %Y")
    return int(time.mktime(dt.timetuple()))


def test_percent_ratio_accepts_zpool_parseable_output(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    assert namespace["_parse_percent_ratio"]("95") == 0.95
    assert namespace["_parse_percent_ratio"]("95%") == 0.95


def test_size_parser_accepts_zpool_parseable_bytes(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    assert namespace["_parse_size_to_bytes"]("7996794994688") == 7996794994688


def test_pool_capacity_policy_separates_unknown_warning_and_observed_failure(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(
        tmp_path,
        pools=["fast"],
        pool_capacity_thresholds={
            "fast": {
                "warning_ratio": 0.9,
                "critical_ratio": 0.95,
                "warning_free_bytes": 1000,
                "critical_free_bytes": 500,
            }
        },
    )
    unknown = namespace["_unknown_pool_payload"]("fast")
    namespace["_apply_pool_capacity_policy"](unknown, "fast")
    assert unknown["capacity_known"] is False
    assert unknown["capacity_warning_failed"] is False
    assert unknown["capacity_critical_failed"] is False

    observed = {"cap_ratio": 0.92, "free_bytes": 900}
    namespace["_apply_pool_capacity_policy"](observed, "fast")
    assert observed["capacity_known"] is True
    assert observed["capacity_warning_failed"] is True
    assert observed["capacity_critical_failed"] is False

    free_warning_only = {"cap_ratio": 0.5, "free_bytes": 900}
    namespace["_apply_pool_capacity_policy"](free_warning_only, "fast")
    assert free_warning_only["capacity_warning_failed"] is True
    assert free_warning_only["capacity_critical_failed"] is False

    free_critical_only = {"cap_ratio": 0.5, "free_bytes": 500}
    namespace["_apply_pool_capacity_policy"](free_critical_only, "fast")
    assert free_critical_only["capacity_warning_failed"] is True
    assert free_critical_only["capacity_critical_failed"] is True


def test_zfs_dataset_stats_reports_snapshot_and_quota_bytes(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    values = {
        "used": "7146825580544",
        "available": "213674622976",
        "referenced": "6387487248384",
        "usedbysnapshots": "754840371200",
        "usedbydataset": "6387487248384",
        "usedbychildren": "0",
        "usedbyrefreservation": "0",
        "quota": "none",
        "refquota": "6597069766656",
        "reservation": "0",
        "refreservation": "0",
    }

    def fake_run(argv: list[str]) -> Any:
        assert argv[:6] == ["zfs", "get", "-H", "-p", "-o", "property,value"]
        assert argv[-1] == "fast/timemachine"
        return namespace["subprocess"].CompletedProcess(
            args=argv,
            returncode=0,
            stdout="".join(f"{key}\t{value}\n" for key, value in values.items()),
            stderr="",
        )

    namespace["_run"] = fake_run
    payload = namespace["_zfs_dataset_stats"]("fast/timemachine")

    assert payload["ok"] is True
    assert payload["metrics_known"] is True
    assert payload["cached"] is False
    assert payload["cache_timestamp"] is None
    assert payload["cache_age_seconds"] is None
    assert payload["available_bytes"] == 213674622976
    assert payload["used_by_snapshots_bytes"] == 754840371200
    assert payload["refquota_bytes"] == 6597069766656
    assert payload["quota_bytes"] is None
    assert payload["reservation_bytes"] is None


def test_zfs_dataset_stats_preserves_command_error(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    def fake_run(argv: list[str]) -> Any:
        return namespace["subprocess"].CompletedProcess(
            args=argv,
            returncode=1,
            stdout="",
            stderr="cannot open 'fast/missing': dataset does not exist",
        )

    namespace["_run"] = fake_run
    payload = namespace["_zfs_dataset_stats"]("fast/missing")

    assert payload["ok"] is False
    assert payload["metrics_known"] is False
    assert payload["available_bytes"] is None
    assert payload["used_by_snapshots_bytes"] is None
    assert "dataset does not exist" in payload["error"]


def test_zfs_dataset_stats_marks_missing_property_as_observed_failure(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_run"] = lambda argv: namespace["subprocess"].CompletedProcess(
        args=argv,
        returncode=0,
        stdout="used\t1024\n",
        stderr="",
    )

    payload = namespace["_zfs_dataset_stats"]("fast/incomplete")

    assert payload["ok"] is False
    assert payload["metrics_known"] is False
    assert payload["used_bytes"] is None
    assert "missing ZFS properties" in payload["error"]


def test_zfs_dataset_stats_marks_non_numeric_property_as_observed_failure(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    values = {property_name: "0" for property_name in namespace["ZFS_DATASET_PROPERTIES"]}
    values["available"] = "unknown"
    namespace["_run"] = lambda argv: namespace["subprocess"].CompletedProcess(
        args=argv,
        returncode=0,
        stdout="".join(f"{key}\t{value}\n" for key, value in values.items()),
        stderr="",
    )

    payload = namespace["_zfs_dataset_stats"]("fast/malformed")

    assert payload["ok"] is False
    assert payload["metrics_known"] is False
    assert payload["available_bytes"] is None
    assert "was not numeric" in payload["error"]


def test_main_exports_zfs_datasets_by_stable_name(tmp_path: Path, capsys: Any) -> None:
    namespace = _load_exporter_namespace(
        tmp_path,
        zfs_datasets=[{"name": "timemachine", "dataset": "fast/timemachine"}],
    )
    namespace["_zpool_list"] = lambda _pools, _skip: {}
    namespace["_zfs_dataset_stats"] = lambda dataset: {
        "dataset": dataset,
        "available_bytes": 412316860416,
        "used_by_snapshots_bytes": 0,
        "ok": True,
    }
    namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    namespace["_edac_status"] = lambda: {"loaded": True, "ce": 0, "ue": 0}

    assert namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)

    dataset = payload["zfs_datasets_by_name"]["timemachine"]
    assert dataset["dataset"] == "fast/timemachine"
    assert dataset["available_bytes"] == 412316860416
    assert payload["zfs_datasets"] == [dataset]


def test_main_skips_datasets_on_quiet_pool(tmp_path: Path, capsys: Any) -> None:
    namespace = _load_exporter_namespace(
        tmp_path,
        zfs_datasets=[{"name": "archive", "dataset": "tank/archive"}],
    )
    namespace["QUIET_SKIP_POOLS"] = ["tank"]
    namespace["_in_quiet_hours"] = lambda: True
    namespace["_zpool_list"] = lambda _pools, _skip: {}
    namespace["_zfs_dataset_stats"] = lambda _dataset: (_ for _ in ()).throw(
        AssertionError("quiet-hours dataset probe must not run")
    )
    namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    namespace["_edac_status"] = lambda: {"loaded": True, "ce": 0, "ue": 0}

    assert namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)

    dataset = payload["zfs_datasets_by_name"]["archive"]
    assert dataset["ok"] is None
    assert dataset["metrics_known"] is False
    assert dataset["available_bytes"] is None
    assert dataset["used_by_snapshots_bytes"] is None
    assert dataset["skipped"] is True
    assert dataset["reason"] == "quiet_hours"


def test_main_uses_cached_disk_health_during_quiet_hours(
    tmp_path: Path, capsys: Any
) -> None:
    namespace = _load_exporter_namespace(
        tmp_path,
        disks=[{"name": "tank-hdd-1", "device": "/dev/sda", "type": "sat"}],
    )
    cache_path = tmp_path / "pool-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "disks": {
                    "tank-hdd-1": {
                        "ts": 1_700_000_000,
                        "sample": {"device": "/dev/sda", "ok": True},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    namespace["QUIET_SKIP_DISK_TYPES"] = ["sat"]
    namespace["_in_quiet_hours"] = lambda: True
    namespace["_now_ts"] = lambda: 1_700_000_100
    namespace["_zpool_list"] = lambda _pools, _skip: {}
    namespace["_smartctl_health"] = lambda _device: (_ for _ in ()).throw(
        AssertionError("quiet-hours SMART probe must not run")
    )
    namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    namespace["_edac_status"] = lambda: {"loaded": True, "ce": 0, "ue": 0}

    assert namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)

    disk = payload["disks_by_name"]["tank-hdd-1"]
    assert disk["ok"] is True
    assert disk["health_known"] is True
    assert disk["health_failed"] is False
    assert disk["cached"] is True
    assert disk["skipped"] is True
    assert disk["reason"] == "quiet_hours"


def test_main_reports_unknown_quiet_disk_without_false_failure(
    tmp_path: Path, capsys: Any
) -> None:
    namespace = _load_exporter_namespace(
        tmp_path,
        disks=[{"name": "tank-hdd-1", "device": "/dev/sda", "type": "sat"}],
    )
    namespace["QUIET_SKIP_DISK_TYPES"] = ["sat"]
    namespace["_in_quiet_hours"] = lambda: True
    namespace["_zpool_list"] = lambda _pools, _skip: {}
    namespace["_smartctl_health"] = lambda _device: (_ for _ in ()).throw(
        AssertionError("quiet-hours SMART probe must not run")
    )
    namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    namespace["_edac_status"] = lambda: {
        "loaded": True,
        "counters_available": False,
        "ce": None,
        "ue": None,
        "correctable_ok": True,
        "uncorrectable_ok": True,
    }

    assert namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)

    disk = payload["disks_by_name"]["tank-hdd-1"]
    assert disk["ok"] is None
    assert disk["health_known"] is False
    assert disk["health_failed"] is False
    assert disk["cached"] is False
    assert disk["cache_timestamp"] is None
    assert disk["cache_age_seconds"] is None
    assert disk["skipped"] is True


def test_smartctl_nonzero_failed_health_is_observed_failure(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_run"] = lambda argv: namespace["subprocess"].CompletedProcess(
        args=argv,
        returncode=8,
        stdout="SMART overall-health self-assessment test result: FAILED!\n",
        stderr="",
    )

    payload = namespace["_smartctl_health"]("/dev/sda")

    assert payload["ok"] is False
    assert payload["health_known"] is True
    assert payload["health_failed"] is True
    assert payload["smartctl_exit_status"] == 8


def test_smartctl_attribute_failure_bit_overrides_passed_line(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_run"] = lambda argv: namespace["subprocess"].CompletedProcess(
        args=argv,
        returncode=16,
        stdout="SMART overall-health self-assessment test result: PASSED\n",
        stderr="",
    )

    payload = namespace["_smartctl_health"]("/dev/sda")

    assert payload["ok"] is False
    assert payload["health_known"] is True
    assert payload["health_failed"] is True
    assert payload["smartctl_exit_status"] == 16


def test_smartctl_historical_bits_do_not_report_current_failure(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_run"] = lambda argv: namespace["subprocess"].CompletedProcess(
        args=argv,
        returncode=32 | 64 | 128,
        stdout="SMART overall-health self-assessment test result: PASSED\n",
        stderr="",
    )

    payload = namespace["_smartctl_health"]("/dev/sda")

    assert payload["ok"] is True
    assert payload["health_known"] is True
    assert payload["health_failed"] is False
    assert payload["smartctl_historical_failure_bits"] == 32 | 64 | 128


@pytest.mark.parametrize("returncode", [-9, 124, 126, 127])
def test_smartctl_launcher_failures_are_unknown_not_disk_failures(
    tmp_path: Path, returncode: int
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_run"] = lambda argv: namespace["subprocess"].CompletedProcess(
        args=argv,
        returncode=returncode,
        stdout="SMART overall-health self-assessment test result: PASSED\n",
        stderr="smartctl could not execute",
    )

    payload = namespace["_smartctl_health"]("/dev/sda")

    assert payload["ok"] is None
    assert payload["health_known"] is False
    assert payload["health_failed"] is False
    assert "smartctl could not execute" in payload["error"]


@pytest.mark.parametrize("returncode", [-9, 124])
def test_smartctl_observed_failure_survives_unusable_exit_status(
    tmp_path: Path, returncode: int
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_run"] = lambda argv: namespace["subprocess"].CompletedProcess(
        args=argv,
        returncode=returncode,
        stdout="SMART overall-health self-assessment test result: FAILED!\n",
        stderr="smartctl ended abnormally",
    )

    payload = namespace["_smartctl_health"]("/dev/sda")

    assert payload["ok"] is False
    assert payload["health_known"] is True
    assert payload["health_failed"] is True
    assert payload["smartctl_exit_status"] == returncode


def test_observed_smart_failure_with_probe_error_remains_cacheable(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    assert namespace["_disk_sample_cacheable"](
        {
            "ok": False,
            "health_known": True,
            "health_failed": True,
            "error": "smartctl ended abnormally",
        }
    )
    assert not namespace["_disk_sample_cacheable"](
        {"ok": None, "health_known": False, "error": "smartctl unavailable"}
    )
    assert not namespace["_disk_sample_cacheable"](
        {"ok": True, "health_known": True, "skipped": True}
    )


def test_cached_dataset_payload_backfills_new_schema_keys(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    payload = namespace["_cached_dataset_payload"](
        "archive",
        "tank/archive",
        {
            "datasets": {
                "archive": {
                    "ts": 100,
                    "sample": {
                        "dataset": "tank/archive",
                        "ok": True,
                        "available_bytes": 2048,
                    },
                }
            }
        },
        101,
    )

    assert payload["dataset"] == "tank/archive"
    assert payload["metrics_known"] is True
    assert payload["available_bytes"] == 2048
    assert payload["used_by_snapshots_bytes"] is None


def test_cached_payloads_reject_retargeted_identity(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    probe_cache = {
        "disks": {
            "archive-disk": {
                "ts": 100,
                "sample": {"device": "/dev/old", "ok": True},
            }
        },
        "datasets": {
            "archive": {
                "ts": 100,
                "sample": {
                    "dataset": "tank/old-archive",
                    "ok": True,
                    "available_bytes": 2048,
                },
            }
        },
    }

    assert (
        namespace["_cached_disk_payload"](
            "archive-disk", "/dev/replacement", probe_cache, 101
        )
        is None
    )
    assert (
        namespace["_cached_dataset_payload"](
            "archive", "tank/new-archive", probe_cache, 101
        )
        is None
    )


def test_cached_probe_payload_rejects_stale_evidence(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    now_ts = 1_700_000_000
    stale_ts = now_ts - namespace["QUIET_CACHE_MAX_AGE_SEC"] - 1
    probe_cache = {
        section: {"sample-name": {"sample": {"ok": True}, "ts": stale_ts}}
        for section in ("pools", "disks", "datasets")
    }

    for section in probe_cache:
        assert (
            namespace["_cached_probe_payload"](
                section, "sample-name", probe_cache, now_ts
            )
            is None
        )


def test_edac_status_separates_counter_availability_from_observed_errors(
    tmp_path: Path, monkeypatch: Any
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    base = "/sys/devices/system/edac/mc"

    def fake_open(path: str, *_args: Any, **_kwargs: Any) -> io.StringIO:
        if path == "/proc/modules":
            return io.StringIO("amd64_edac 1 0 - Live 0x0\n")
        if path == f"{base}/mc0/ce_count":
            return io.StringIO("2\n")
        if path == f"{base}/mc0/ue_count":
            return io.StringIO("0\n")
        raise OSError(path)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(namespace["os"].path, "isdir", lambda path: path == base)
    monkeypatch.setattr(namespace["os"], "listdir", lambda path: ["mc0"])

    payload = namespace["_edac_status"]()

    assert payload == {
        "loaded": True,
        "counters_available": True,
        "ce": 2,
        "ue": 0,
        "correctable_ok": False,
        "uncorrectable_ok": True,
    }


def test_edac_status_requires_complete_evidence_from_every_controller(
    tmp_path: Path, monkeypatch: Any
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    base = "/sys/devices/system/edac/mc"

    def fake_open(path: str, *_args: Any, **_kwargs: Any) -> io.StringIO:
        if path == "/proc/modules":
            return io.StringIO("amd64_edac 1 0 - Live 0x0\n")
        if path.startswith(f"{base}/mc0/"):
            return io.StringIO("0\n")
        if path == f"{base}/mc1/ce_count":
            return io.StringIO("0\n")
        raise OSError(path)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(namespace["os"].path, "isdir", lambda path: path == base)
    monkeypatch.setattr(namespace["os"], "listdir", lambda path: ["mc0", "mc1"])

    payload = namespace["_edac_status"]()

    assert payload["counters_available"] is False
    assert payload["ce"] == 0
    assert payload["ue"] == 0
    assert payload["correctable_ok"] is True
    assert payload["uncorrectable_ok"] is True


def test_edac_status_never_hides_observed_error_behind_incomplete_evidence(
    tmp_path: Path, monkeypatch: Any
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    base = "/sys/devices/system/edac/mc"

    def fake_open(path: str, *_args: Any, **_kwargs: Any) -> io.StringIO:
        if path == "/proc/modules":
            return io.StringIO("amd64_edac 1 0 - Live 0x0\n")
        if path.startswith(f"{base}/mc0/"):
            return io.StringIO("1\n")
        if path == f"{base}/mc1/ce_count":
            return io.StringIO("0\n")
        raise OSError(path)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(namespace["os"].path, "isdir", lambda path: path == base)
    monkeypatch.setattr(namespace["os"], "listdir", lambda path: ["mc0", "mc1"])

    payload = namespace["_edac_status"]()

    assert payload["counters_available"] is False
    assert payload["ce"] == 1
    assert payload["ue"] == 1
    assert payload["correctable_ok"] is False
    assert payload["uncorrectable_ok"] is False


def test_main_round_trips_pool_disk_and_dataset_cache(
    tmp_path: Path, capsys: Any
) -> None:
    configs = {
        "pools": ["tank"],
        "disks": [{"name": "tank-hdd-1", "device": "/dev/sda", "type": "sat"}],
        "zfs_datasets": [{"name": "archive", "dataset": "tank/archive"}],
    }
    namespace = _load_exporter_namespace(tmp_path, **configs)
    namespace["_now_ts"] = lambda: 1_700_000_000
    namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    namespace["_edac_status"] = lambda: {"loaded": True, "ce": 0, "ue": 0}

    zfs_values = {
        "used": "1024",
        "available": "2048",
        "referenced": "1024",
        "usedbysnapshots": "0",
        "usedbydataset": "1024",
        "usedbychildren": "0",
        "usedbyrefreservation": "0",
        "quota": "none",
        "refquota": "none",
        "reservation": "0",
        "refreservation": "0",
    }

    def active_run(argv: list[str]) -> Any:
        if argv[:2] == ["zpool", "list"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="tank\tONLINE\t10000\t4000\t6000\t40\n",
                stderr="",
            )
        if argv == ["zpool", "status", "tank"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )
        if argv[0] == "smartctl":
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="SMART overall-health self-assessment test result: PASSED\n",
                stderr="",
            )
        if argv[:2] == ["zfs", "get"]:
            return namespace["subprocess"].CompletedProcess(
                args=argv,
                returncode=0,
                stdout="".join(
                    f"{key}\t{value}\n" for key, value in zfs_values.items()
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    namespace["_run"] = active_run
    assert namespace["main"]() == 0
    capsys.readouterr()

    cache = json.loads((tmp_path / "pool-cache.json").read_text(encoding="utf-8"))
    assert set(cache) >= {"pools", "disks", "datasets"}
    assert cache["disks"]["tank-hdd-1"]["sample"]["ok"] is True
    assert cache["disks"]["tank-hdd-1"]["sample"]["health_known"] is True
    assert cache["disks"]["tank-hdd-1"]["sample"]["health_failed"] is False
    assert cache["datasets"]["archive"]["sample"]["available_bytes"] == 2048

    quiet_namespace = _load_exporter_namespace(tmp_path, **configs)
    quiet_namespace["QUIET_SKIP_POOLS"] = ["tank"]
    quiet_namespace["QUIET_SKIP_DISK_TYPES"] = ["sat"]
    quiet_namespace["_in_quiet_hours"] = lambda: True
    quiet_namespace["_now_ts"] = lambda: 1_700_000_100
    quiet_namespace["_run"] = lambda argv: (_ for _ in ()).throw(
        AssertionError(f"quiet-hours probe must not run: {argv}")
    )
    quiet_namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    quiet_namespace["_edac_status"] = lambda: {
        "loaded": True,
        "ce": 0,
        "ue": 0,
    }

    assert quiet_namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pools"]["tank"]["cached"] is True
    assert payload["disks_by_name"]["tank-hdd-1"]["ok"] is True
    assert payload["disks_by_name"]["tank-hdd-1"]["health_known"] is True
    assert payload["disks_by_name"]["tank-hdd-1"]["health_failed"] is False
    assert payload["zfs_datasets_by_name"]["archive"]["available_bytes"] == 2048

    namespace["_now_ts"] = lambda: 1_700_000_200
    assert namespace["main"]() == 0
    capsys.readouterr()
    cache = json.loads((tmp_path / "pool-cache.json").read_text(encoding="utf-8"))
    assert set(cache) >= {"pools", "disks", "datasets"}
    assert cache["pools"]["tank"]["sample"]["free_bytes"] == 6000
    assert cache["disks"]["tank-hdd-1"]["sample"]["temp_c"] is None
    assert cache["datasets"]["archive"]["sample"]["available_bytes"] == 2048


def test_zpool_list_uses_cached_pool_metrics_for_skipped_pool(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_now_ts"] = lambda: 1_700_000_100
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
    assert payload["tank"]["health_known"] is True
    assert payload["tank"]["health_failed"] is False
    assert payload["tank"]["skipped"] is True
    assert payload["tank"]["reason"] == "quiet_hours"
    assert payload["tank"]["cached"] is True
    assert payload["tank"]["cache_timestamp"] == 1_700_000_000
    assert payload["tank"]["cache_age_seconds"] >= 0


def test_zpool_list_discovers_names_before_skipping_pools(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    namespace["_now_ts"] = lambda: 1_700_000_100
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
        if argv == [
            "zpool",
            "list",
            "-H",
            "-p",
            "-o",
            "name,health,size,alloc,free,cap",
        ]:
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


def test_zpool_list_preserves_skipped_payload_when_no_cache_exists(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    payload = namespace["_zpool_list"](["tank"], {"tank"})

    assert payload["tank"]["health"] is None
    assert payload["tank"]["health_known"] is False
    assert payload["tank"]["health_failed"] is False
    assert payload["tank"]["cap_ratio"] is None
    assert payload["tank"]["skipped"] is True


def test_zpool_list_ignores_malformed_pool_cache_for_skipped_pool(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    (tmp_path / "pool-cache.json").write_text("not json", encoding="utf-8")

    payload = namespace["_zpool_list"](["tank"], {"tank"})

    assert payload["tank"]["health"] is None
    assert payload["tank"]["health_known"] is False
    assert payload["tank"]["health_failed"] is False
    assert payload["tank"]["cap_ratio"] is None
    assert payload["tank"]["skipped"] is True


def test_zpool_list_rejects_expired_pool_cache_with_stable_unknown_schema(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    now_ts = 1_700_000_000
    namespace["_now_ts"] = lambda: now_ts
    stale_ts = now_ts - namespace["QUIET_CACHE_MAX_AGE_SEC"] - 1
    (tmp_path / "pool-cache.json").write_text(
        json.dumps(
            {
                "pools": {
                    "tank": {
                        "ts": stale_ts,
                        "sample": {"health": "ONLINE", "cap_ratio": 0.9},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    payload = namespace["_zpool_list"](["tank"], {"tank"})

    assert payload["tank"]["health"] is None
    assert payload["tank"]["health_known"] is False
    assert payload["tank"]["health_failed"] is False
    assert payload["tank"]["cap_ratio"] is None
    assert payload["tank"]["skipped"] is True


def test_zpool_list_writes_successful_pool_sample_to_cache(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    def fake_run(argv: list[str]) -> Any:
        if argv[:6] == [
            "zpool",
            "list",
            "-H",
            "-p",
            "-o",
            "name,health,size,alloc,free,cap",
        ]:
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
                stdout=(
                    "  scan: scrub repaired 0B in 00:00:01 on "
                    "Sun Dec 14 07:24:50 2025\n"
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    namespace["_run"] = fake_run

    payload = namespace["_zpool_list"](["tank"], set())

    assert payload["tank"]["cached"] is False
    assert payload["tank"]["cap_ratio"] == pytest.approx(9.8 / 10.9)
    assert payload["tank"]["last_scrub_ts"] == _local_timestamp(
        "Sun Dec 14 07:24:50 2025"
    )

    cache = json.loads((tmp_path / "pool-cache.json").read_text(encoding="utf-8"))
    sample = cache["pools"]["tank"]["sample"]
    assert sample["cap_ratio"] == pytest.approx(9.8 / 10.9)
    assert sample["health"] == "ONLINE"
    assert not {
        "cached",
        "cache_age_seconds",
        "cache_timestamp",
        "cache_write_error",
        "reason",
        "skipped",
    }.intersection(sample)


def test_zpool_list_parses_active_scrub_timestamp(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    for scan_line in [
        "  scan: scrub in progress since Mon Jun  1 02:59:51 2026\n",
        "  scan: scrub paused since Mon Jun  1 02:59:51 2026\n",
    ]:

        def fake_run(argv: list[str]) -> Any:
            if argv[:6] == [
                "zpool",
                "list",
                "-H",
                "-p",
                "-o",
                "name,health,size,alloc,free,cap",
            ]:
                return namespace["subprocess"].CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout=(
                        "fast\tONLINE\t7996794994688\t4947802324992\t"
                        "3048992669696\t62\n"
                    ),
                    stderr="",
                )
            if argv == ["zpool", "status", "fast"]:
                return namespace["subprocess"].CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout=scan_line,
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {argv}")

        namespace["_run"] = fake_run

        payload = namespace["_zpool_list"](["fast"], set())

        assert payload["fast"]["size_bytes"] == 7996794994688
        assert payload["fast"]["alloc_bytes"] == 4947802324992
        assert payload["fast"]["free_bytes"] == 3048992669696
        assert payload["fast"]["last_scrub_ts"] == _local_timestamp(
            "Mon Jun  1 02:59:51 2026"
        )
        assert payload["fast"]["last_scrub_age_days"] is not None


def test_zpool_list_marks_successful_pool_when_cache_write_fails(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)

    def fake_run(argv: list[str]) -> Any:
        if argv[:6] == [
            "zpool",
            "list",
            "-H",
            "-p",
            "-o",
            "name,health,size,alloc,free,cap",
        ]:
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


BAND_SIZE = 1610612736
NOW_TS = 1_787_664_000  # 2026-08-25T13:20:00Z


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    # plistlib stores dates as UTC and returns them as naive datetimes.
    return datetime(year, month, day, hour, minute)


def _write_plist(path: Path, data: dict[str, Any]) -> None:
    with open(path, "wb") as f:
        plistlib.dump(data, f)


def _make_bundle(
    root: Path,
    basename: str,
    *,
    bands: int = 3,
    results: dict[str, Any] | None = None,
    snapshots: list[datetime] | None = None,
    info: dict[str, Any] | None = None,
) -> Path:
    bundle = root / basename
    (bundle / "bands").mkdir(parents=True)
    for index in range(bands):
        (bundle / "bands" / format(index, "x")).write_bytes(b"")
    if info is None:
        info = {
            "CFBundleInfoDictionaryVersion": "6.0",
            "band-size": BAND_SIZE,
            "bundle-backingstore-version": 2,
            "diskimage-bundle-type": "com.apple.diskimage.sparsebundle",
            "size": 16000000000000,
        }
    _write_plist(bundle / "Info.plist", info)
    if results is not None:
        _write_plist(bundle / "com.apple.TimeMachine.Results.plist", results)
    if snapshots is not None:
        _write_plist(
            bundle / "com.apple.TimeMachine.SnapshotHistory.plist",
            {
                "Snapshots": [
                    {
                        "com.apple.backupd.SnapshotCompletionDate": completed,
                        "com.apple.backupd.SnapshotName": completed.strftime(
                            "%Y-%m-%d-%H%M%S.backup"
                        ),
                    }
                    for completed in snapshots
                ]
            },
        )
    return bundle


def _completed_results(bytes_used: int, bytes_to_copy: int) -> dict[str, Any]:
    return {
        "BackupStrategy": 2,
        "BytesAvailable": 436476051456,
        "BytesToCopy": bytes_to_copy,
        "BytesUsed": bytes_used,
        "ClientID": "com.apple.backupd",
        "Running": False,
    }


def test_timemachine_bundle_name_is_jsonpath_safe(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    bundle_name = namespace["_timemachine_bundle_name"]

    assert bundle_name("studio.sparsebundle") == "studio"
    assert bundle_name("MacBook Pro von Example.sparsebundle") == "MacBook Pro von Example"
    assert bundle_name("laptop.local.sparsebundle") == "laptop_local"


def test_timemachine_bundle_stats_reads_plists_and_counts_bands(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    oldest = _utc(2025, 12, 13, 4, 54)
    newest = _utc(2026, 8, 24, 13, 20)
    bundle = _make_bundle(
        tmp_path,
        "studio.sparsebundle",
        bands=4,
        results=_completed_results(3034285142016, 2782527946752),
        snapshots=[newest, oldest, _utc(2026, 3, 1, 1, 0)],
    )

    payload = namespace["_timemachine_bundle_stats"](str(bundle), NOW_TS)

    assert payload["ok"] is True
    assert payload["metrics_known"] is True
    assert "error" not in payload
    assert payload["name"] == "studio"
    assert payload["bundle"] == "studio.sparsebundle"
    assert payload["path"] == str(bundle)
    assert payload["bytes_used"] == 3034285142016
    assert payload["last_bytes_to_copy"] == 2782527946752
    assert payload["client_bytes_available"] == 436476051456
    assert payload["running"] is False
    assert payload["band_count"] == 4
    assert payload["band_size_bytes"] == BAND_SIZE
    assert payload["bands_bytes"] == 4 * BAND_SIZE
    assert payload["backup_count"] == 3
    assert payload["oldest_backup_ts"] == int(
        oldest.replace(tzinfo=timezone.utc).timestamp()
    )
    assert payload["newest_backup_ts"] == int(
        newest.replace(tzinfo=timezone.utc).timestamp()
    )
    assert payload["newest_backup_age_days"] == 1.0
    assert payload["history_days"] == pytest.approx(254.35, abs=0.01)
    assert payload["cached"] is False


def test_timemachine_bundle_stats_marks_missing_results_plist_as_failure(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    bundle = _make_bundle(
        tmp_path,
        "atlas.sparsebundle",
        bands=2,
        results=None,
        snapshots=[_utc(2026, 8, 20, 12, 0)],
    )

    payload = namespace["_timemachine_bundle_stats"](str(bundle), NOW_TS)

    assert payload["ok"] is False
    assert payload["metrics_known"] is False
    assert "com.apple.TimeMachine.Results.plist" in payload["error"]
    assert payload["bytes_used"] is None
    assert payload["last_bytes_to_copy"] is None
    assert payload["running"] is None
    # Evidence that could be read is still reported for diagnostics.
    assert payload["band_count"] == 2
    assert payload["backup_count"] == 1


def test_timemachine_bundle_stats_reports_in_progress_backup(tmp_path: Path) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    results = _completed_results(1190128427008, 901507817472)
    results["Running"] = True
    results["Progress"] = {"Percent": 0.65, "bytes": 45013037056}
    bundle = _make_bundle(
        tmp_path,
        "atlas.sparsebundle",
        results=results,
        snapshots=[_utc(2026, 8, 24, 13, 20)],
    )

    payload = namespace["_timemachine_bundle_stats"](str(bundle), NOW_TS)

    assert payload["ok"] is True
    assert payload["running"] is True
    assert payload["last_bytes_to_copy"] == 901507817472
    assert payload["bytes_used"] == 1190128427008


def test_timemachine_bundle_stats_handles_unparsable_and_empty_history(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    broken = _make_bundle(
        tmp_path,
        "broken.sparsebundle",
        results=_completed_results(10, 5),
        snapshots=[_utc(2026, 8, 24)],
    )
    (broken / "com.apple.TimeMachine.Results.plist").write_bytes(b"not a plist")
    payload = namespace["_timemachine_bundle_stats"](str(broken), NOW_TS)
    assert payload["ok"] is False
    assert "Results.plist" in payload["error"]
    assert payload["bytes_used"] is None

    (broken / "com.apple.TimeMachine.Results.plist").write_bytes(
        b'<?xml version="1.0"?><plist version="1.0"><dict><key>BytesUsed'
    )
    payload = namespace["_timemachine_bundle_stats"](str(broken), NOW_TS)
    assert payload["ok"] is False
    assert "Results.plist" in payload["error"]
    assert payload["backup_count"] == 1

    fresh = _make_bundle(
        tmp_path,
        "fresh.sparsebundle",
        bands=0,
        results=_completed_results(0, 0),
        snapshots=[],
    )
    payload = namespace["_timemachine_bundle_stats"](str(fresh), NOW_TS)
    assert payload["ok"] is True
    assert payload["band_count"] == 0
    assert payload["bands_bytes"] == 0
    assert payload["backup_count"] == 0
    assert payload["oldest_backup_ts"] is None
    assert payload["newest_backup_ts"] is None
    assert payload["newest_backup_age_days"] is None
    assert payload["history_days"] == 0.0

    no_band_size = _make_bundle(
        tmp_path,
        "nobandsize.sparsebundle",
        results=_completed_results(10, 5),
        snapshots=[_utc(2026, 8, 24)],
        info={"size": 16000000000000},
    )
    payload = namespace["_timemachine_bundle_stats"](str(no_band_size), NOW_TS)
    assert payload["ok"] is False
    assert "band-size" in payload["error"]
    assert payload["bands_bytes"] is None


def test_scan_timemachine_bundle_dirs_reports_empty_and_missing_dirs(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    populated = tmp_path / "timemachine"
    populated.mkdir()
    _make_bundle(populated, "b.sparsebundle", results={}, snapshots=[])
    _make_bundle(populated, "a.sparsebundle", results={}, snapshots=[])
    (populated / "notabundle").mkdir()
    (populated / "file.sparsebundle").write_bytes(b"")

    scan, paths = namespace["_scan_timemachine_bundle_dirs"](
        [str(empty), str(populated), str(tmp_path / "missing")]
    )

    assert paths == [
        str(populated / "a.sparsebundle"),
        str(populated / "b.sparsebundle"),
    ]
    assert scan["ok"] is False
    assert scan["bundle_count"] == 2
    assert [entry["ok"] for entry in scan["dirs"]] == [True, True, False]
    assert scan["dirs"][0]["bundle_count"] == 0
    assert scan["dirs"][1]["bundle_count"] == 2
    assert "error" in scan["dirs"][2]


def test_main_exports_timemachine_bundles_by_name(tmp_path: Path, capsys: Any) -> None:
    bundle_dir = tmp_path / "fast" / "timemachine"
    bundle_dir.mkdir(parents=True)
    _make_bundle(
        bundle_dir,
        "studio.sparsebundle",
        bands=2,
        results=_completed_results(100, 10),
        snapshots=[_utc(2026, 8, 24, 13, 20)],
    )
    _make_bundle(
        bundle_dir,
        "MacBook Pro von Example.sparsebundle",
        bands=1,
        results=None,
        snapshots=[_utc(2026, 8, 20)],
    )
    namespace = _load_exporter_namespace(
        tmp_path, timemachine_bundle_dirs=[str(bundle_dir)]
    )
    namespace["_now_ts"] = lambda: NOW_TS
    namespace["_zpool_list"] = lambda _pools, _skip: {}
    namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    namespace["_edac_status"] = lambda: {"loaded": True, "ce": 0, "ue": 0}

    assert namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["timemachine_bundle_scan"]["ok"] is True
    assert payload["timemachine_bundle_scan"]["bundle_count"] == 2
    by_name = payload["timemachine_bundles_by_name"]
    assert set(by_name) == {"studio", "MacBook Pro von Example"}
    assert by_name["studio"]["ok"] is True
    assert by_name["studio"]["metrics_known"] is True
    assert by_name["studio"]["bands_bytes"] == 2 * BAND_SIZE
    assert by_name["studio"]["newest_backup_age_days"] == 1.0
    assert by_name["MacBook Pro von Example"]["ok"] is False
    assert by_name["MacBook Pro von Example"]["metrics_known"] is False
    assert payload["timemachine_bundles"] == [
        by_name["MacBook Pro von Example"],
        by_name["studio"],
    ]

    cache = json.loads((tmp_path / "pool-cache.json").read_text(encoding="utf-8"))
    assert set(cache["timemachine_bundles"]) == {"studio"}
    assert cache["timemachine_bundles"]["studio"]["sample"]["bytes_used"] == 100
    assert "cached" not in cache["timemachine_bundles"]["studio"]["sample"]


def test_main_uses_cached_timemachine_bundle_during_quiet_hours(
    tmp_path: Path, capsys: Any
) -> None:
    bundle_dir = tmp_path / "tank" / "timemachine"
    bundle_dir.mkdir(parents=True)
    bundle = _make_bundle(
        bundle_dir,
        "studio.sparsebundle",
        results=_completed_results(100, 10),
        snapshots=[_utc(2026, 8, 24, 13, 20)],
    )
    namespace = _load_exporter_namespace(
        tmp_path, timemachine_bundle_dirs=[str(bundle_dir)]
    )
    namespace["_now_ts"] = lambda: NOW_TS
    namespace["_zpool_list"] = lambda _pools, _skip: {}
    namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    namespace["_edac_status"] = lambda: {"loaded": True, "ce": 0, "ue": 0}
    assert namespace["main"]() == 0
    capsys.readouterr()

    quiet_namespace = _load_exporter_namespace(
        tmp_path, timemachine_bundle_dirs=[str(bundle_dir)]
    )
    # The pool name is the first path component of the bundle directory.
    quiet_namespace["QUIET_SKIP_POOLS"] = [
        str(bundle_dir).strip("/").split("/", maxsplit=1)[0]
    ]
    quiet_namespace["_in_quiet_hours"] = lambda: True
    quiet_namespace["_now_ts"] = lambda: NOW_TS + 86400
    quiet_namespace["_zpool_list"] = lambda _pools, _skip: {}
    quiet_namespace["_timemachine_bundle_stats"] = lambda _path, _now: (
        _ for _ in ()
    ).throw(AssertionError("quiet-hours bundle probe must not run"))
    quiet_namespace["_run_quiet_hours_spindown"] = lambda _quiet: {"enabled": False}
    quiet_namespace["_edac_status"] = lambda: {"loaded": True, "ce": 0, "ue": 0}

    assert quiet_namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)
    cached = payload["timemachine_bundles_by_name"]["studio"]
    assert cached["cached"] is True
    assert cached["skipped"] is True
    assert cached["reason"] == "quiet_hours"
    assert cached["ok"] is True
    assert cached["metrics_known"] is True
    assert cached["path"] == str(bundle)
    assert cached["bytes_used"] == 100
    assert cached["cache_age_seconds"] == 86400
    # Age keeps advancing against the cached completion timestamp.
    assert cached["newest_backup_age_days"] == 2.0

    # Without usable cache the schema stays stable and fails closed.
    (tmp_path / "pool-cache.json").unlink()
    assert quiet_namespace["main"]() == 0
    payload = json.loads(capsys.readouterr().out)
    unknown = payload["timemachine_bundles_by_name"]["studio"]
    assert unknown["ok"] is None
    assert unknown["metrics_known"] is False
    assert unknown["bytes_used"] is None
    assert unknown["newest_backup_age_days"] is None
    assert unknown["skipped"] is True


def test_cached_timemachine_bundle_payload_rejects_retargeted_path(
    tmp_path: Path,
) -> None:
    namespace = _load_exporter_namespace(tmp_path)
    probe_cache = {
        "timemachine_bundles": {
            "studio": {
                "ts": 100,
                "sample": {"path": "/old/studio.sparsebundle", "ok": True},
            }
        }
    }
    assert (
        namespace["_cached_timemachine_bundle_payload"](
            "studio", "/new/studio.sparsebundle", probe_cache, 101
        )
        is None
    )
    cached = namespace["_cached_timemachine_bundle_payload"](
        "studio", "/old/studio.sparsebundle", probe_cache, 101
    )
    assert cached is not None
    assert cached["metrics_known"] is True
    assert cached["band_count"] is None
