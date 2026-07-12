from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state_module = _load(
    "zfs_usb_replication_state",
    "roles/zfs_usb_replication/files/zfs_usb_replication_state.py",
)
health_module = _load(
    "backup_metrics_usb_health",
    "roles/backup_metrics_endpoint/files/backup_metrics_usb_health.py",
)


def test_absent_skip_preserves_last_present_result_and_success(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    state_module.record_state(
        path,
        result="success",
        exit_code=0,
        device_path="/dev/test",
        pool="vault",
        occurred_at="2026-07-01T04:00:00+00:00",
        size_bytes=1000,
        alloc_bytes=700,
        free_bytes=300,
    )
    state = state_module.record_state(
        path,
        result="skipped_absent",
        exit_code=0,
        device_path="/dev/test",
        pool="vault",
        occurred_at="2026-07-02T04:00:00+00:00",
    )

    assert state["last_attempt_result"] == "skipped_absent"
    assert state["last_present_attempt_result"] == "success"
    assert state["last_success_at"] == "2026-07-01T04:00:00+00:00"
    assert state["last_known_used_ratio"] == 0.7
    assert state["last_known_observed_iso"] == "2026-07-01T04:00:00+00:00"


def test_failed_present_attempt_is_durable_across_later_absent_skip(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    state_module.record_state(
        path,
        result="failed",
        exit_code=2,
        device_path="/dev/test",
        pool="vault",
        occurred_at="2026-07-03T04:00:00+00:00",
    )
    state = state_module.record_state(
        path,
        result="skipped_absent",
        exit_code=0,
        device_path="/dev/test",
        pool="vault",
        occurred_at="2026-07-04T04:00:00+00:00",
    )

    assert state["last_present_attempt_result"] == "failed"
    assert state["last_present_attempt_exit_code"] == 2


def test_health_combines_attempt_capacity_and_freshness() -> None:
    health = health_module.build_usb_replication_health(
        enabled=True,
        device_present=True,
        unit_ok=False,
        state={
            "last_present_attempt_result": "failed",
            "last_present_attempt_at": "2026-07-12T04:24:17+00:00",
            "last_success_at": "2026-06-25T04:42:30+00:00",
        },
        state_error=None,
        selected_usage={"last_known_used_ratio": 0.9923},
        warning_ratio=0.90,
        critical_ratio=0.95,
        protection_max_age_hours=1080,
        now_epoch=1783833600,
    )

    assert health["last_present_attempt_ok"] is False
    assert health["capacity_warning_ok"] is False
    assert health["capacity_critical_ok"] is False
    assert health["protection_fresh"] is True
    assert health["ok"] is False
    assert health["issues"] == [
        "last_present_attempt_not_successful",
        "capacity_critical_or_unknown",
    ]


def test_live_unit_failure_bootstraps_health_before_first_state_file() -> None:
    health = health_module.build_usb_replication_health(
        enabled=True,
        device_present=True,
        unit_ok=False,
        state={},
        state_error="state_file_missing",
        selected_usage={"last_known_used_ratio": 0.99},
        warning_ratio=0.90,
        critical_ratio=0.95,
        protection_max_age_hours=0,
        now_epoch=1783833600,
    )

    assert health["last_present_attempt_source"] == "live_unit_failure"
    assert health["last_present_attempt_ok"] is False
    assert health["ok"] is False


def test_live_attached_failure_overrides_stale_durable_success() -> None:
    health = health_module.build_usb_replication_health(
        enabled=True,
        device_present=True,
        unit_ok=False,
        state={
            "last_present_attempt_result": "success",
            "last_success_at": "2026-07-12T03:00:00+00:00",
            "last_known_used_ratio": 0.80,
        },
        state_error=None,
        selected_usage={"last_known_used_ratio": 0.80},
        warning_ratio=0.90,
        critical_ratio=0.95,
        protection_max_age_hours=1080,
        now_epoch=1783833600,
    )

    assert health["last_present_attempt_source"] == "live_unit_failure"
    assert health["last_present_attempt_ok"] is False
    assert health["ok"] is False


def test_durable_capacity_sample_wins_after_pool_export() -> None:
    health = health_module.build_usb_replication_health(
        enabled=True,
        device_present=False,
        unit_ok=True,
        state={
            "last_present_attempt_result": "success",
            "last_success_at": "2026-07-12T03:00:00+00:00",
            "last_known_used_ratio": 0.97,
            "last_known_size_bytes": 1000,
            "last_known_alloc_bytes": 970,
            "last_known_free_bytes": 30,
        },
        state_error=None,
        selected_usage={
            "last_known_used_ratio": 0.97,
            "last_known_size_bytes": 1000,
            "last_known_alloc_bytes": 970,
            "last_known_free_bytes": 30,
        },
        warning_ratio=0.90,
        critical_ratio=0.95,
        protection_max_age_hours=1080,
        now_epoch=1783833600,
    )

    assert health["last_known_used_ratio"] == 0.97
    assert health["capacity_critical_ok"] is False
    assert health["ok"] is False


def test_live_capacity_sample_wins_over_older_durable_state() -> None:
    selected = health_module.select_usb_usage(
        {
            "last_known_used_ratio": 0.97,
            "last_known_size_bytes": 1000,
            "last_known_alloc_bytes": 970,
            "last_known_free_bytes": 30,
            "last_known_observed_epoch": 200,
            "last_known_observed_iso": "live",
        },
        {
            "last_known_used_ratio": 0.80,
            "last_known_size_bytes": 1000,
            "last_known_alloc_bytes": 800,
            "last_known_free_bytes": 200,
            "last_known_observed_epoch": 100,
            "last_known_observed_iso": "durable",
        },
        live_observed=True,
    )
    health = health_module.build_usb_replication_health(
        enabled=True,
        device_present=True,
        unit_ok=True,
        state={"last_present_attempt_result": "success"},
        state_error=None,
        selected_usage=selected,
        warning_ratio=0.90,
        critical_ratio=0.95,
        protection_max_age_hours=0,
        now_epoch=300,
    )

    assert {
        field: health[field] for field in health_module.USB_USAGE_FIELDS
    } == {
        "last_known_used_ratio": 0.97,
        "last_known_size_bytes": 1000,
        "last_known_alloc_bytes": 970,
        "last_known_free_bytes": 30,
        "last_known_observed_epoch": 200,
        "last_known_observed_iso": "live",
    }


def test_newer_durable_capacity_wins_over_exporter_cache() -> None:
    selected = health_module.select_usb_usage(
        {
            "last_known_used_ratio": 0.70,
            "last_known_size_bytes": 1000,
            "last_known_alloc_bytes": 700,
            "last_known_free_bytes": 300,
            "last_known_observed_epoch": 100,
            "last_known_observed_iso": "cache",
        },
        {
            "last_known_used_ratio": 0.97,
            "last_known_size_bytes": 1000,
            "last_known_alloc_bytes": 970,
            "last_known_free_bytes": 30,
            "last_known_observed_epoch": 200,
            "last_known_observed_iso": "durable",
        },
        live_observed=False,
    )
    health = health_module.build_usb_replication_health(
        enabled=True,
        device_present=False,
        unit_ok=True,
        state={"last_present_attempt_result": "success"},
        state_error=None,
        selected_usage=selected,
        warning_ratio=0.90,
        critical_ratio=0.95,
        protection_max_age_hours=0,
        now_epoch=300,
    )

    assert {
        field: health[field] for field in health_module.USB_USAGE_FIELDS
    } == {
        "last_known_used_ratio": 0.97,
        "last_known_size_bytes": 1000,
        "last_known_alloc_bytes": 970,
        "last_known_free_bytes": 30,
        "last_known_observed_epoch": 200,
        "last_known_observed_iso": "durable",
    }


def test_disabled_usb_health_is_ok_without_state_or_capacity() -> None:
    health = health_module.build_usb_replication_health(
        enabled=False,
        device_present=None,
        unit_ok=None,
        state={},
        state_error="state_file_missing",
        selected_usage={},
        warning_ratio=0.90,
        critical_ratio=0.95,
        protection_max_age_hours=1080,
        now_epoch=1783833600,
    )

    assert health["ok"] is True
    assert health["issues"] == []
