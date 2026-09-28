from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "roles/zfs_usb_replication/files/zfs_usb_snapshot_retention.py"
SPEC = importlib.util.spec_from_file_location("zfs_usb_snapshot_retention", MODULE_PATH)
assert SPEC and SPEC.loader
retention = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = retention
SPEC.loader.exec_module(retention)


def test_select_prunes_only_old_managed_target_only_snapshots() -> None:
    snapshots = [
        retention.Snapshot("autosnap_old", 100, "1"),
        retention.Snapshot("syncoid_fractal_old", 110, "2"),
        retention.Snapshot("syncoid_usb_common", 120, "3"),
        retention.Snapshot("manual_keep", 90, "4"),
        retention.Snapshot("autosnap_recent", 300, "5"),
    ]

    selected = retention.select_prunable_snapshots(
        source_names={"syncoid_usb_common"},
        target_snapshots=snapshots,
        cutoff_epoch=200,
        prefixes=("autosnap_", "syncoid_fractal_", "syncoid_usb_"),
    )

    assert [snapshot.name for snapshot in selected] == [
        "autosnap_old",
        "syncoid_fractal_old",
    ]


def test_prune_refuses_when_replica_has_no_common_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list(dataset: str, kind: str = "snapshot"):
        if kind == "bookmark":
            return []
        if dataset == "source":
            return [retention.Snapshot("source_only", 100, "1")]
        return [retention.Snapshot("target_only", 100, "2")]

    monkeypatch.setattr(retention, "list_snapshots", fake_list)
    monkeypatch.setattr(retention, "dataset_exists", lambda dataset: True)

    with pytest.raises(RuntimeError, match="no common snapshot"):
        retention.prune(
            source="source",
            target="target",
            keep_days=60,
            prefixes=("autosnap_",),
            now_epoch=10_000_000,
        )


def test_dry_run_preserves_common_and_does_not_destroy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list(dataset: str, kind: str = "snapshot"):
        if kind == "bookmark":
            return []
        if dataset == "source":
            return [retention.Snapshot("syncoid_usb_common", 100, "7")]
        return [
            retention.Snapshot("autosnap_old", 50, "6"),
            retention.Snapshot("syncoid_usb_common", 100, "7"),
        ]

    monkeypatch.setattr(retention, "list_snapshots", fake_list)
    monkeypatch.setattr(retention, "dataset_exists", lambda dataset: True)
    calls = []
    monkeypatch.setattr(retention.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    selected = retention.prune(
        source="source",
        target="target",
        keep_days=1,
        prefixes=("autosnap_", "syncoid_usb_"),
        now_epoch=200_000,
        dry_run=True,
    )

    assert [snapshot.name for snapshot in selected] == ["autosnap_old"]
    assert calls == []


def test_prune_refuses_same_name_with_different_guid(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list(dataset: str, kind: str = "snapshot"):
        if kind == "bookmark":
            return []
        guid = "source-guid" if dataset == "source" else "target-guid"
        return [retention.Snapshot("syncoid_usb_same_name", 100, guid)]

    monkeypatch.setattr(retention, "list_snapshots", fake_list)
    monkeypatch.setattr(retention, "dataset_exists", lambda dataset: True)

    with pytest.raises(RuntimeError, match="no common snapshot"):
        retention.prune(
            source="source",
            target="target",
            keep_days=60,
            prefixes=("syncoid_usb_",),
            now_epoch=10_000_000,
        )


@pytest.mark.parametrize("prefixes", [(), ("",)])
def test_prune_refuses_empty_prefixes(prefixes: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="non-empty strings"):
        retention.prune(
            source="source",
            target="target",
            keep_days=60,
            prefixes=prefixes,
            now_epoch=10_000_000,
        )


def test_select_keeps_old_target_snapshot_held_by_a_source_bookmark() -> None:
    snapshots = [
        retention.Snapshot("syncoid_fractal_anchor", 100, "anchor-guid"),
        retention.Snapshot("autosnap_old", 110, "old-guid"),
    ]

    selected = retention.select_prunable_snapshots(
        source_names=set(),
        target_snapshots=snapshots,
        cutoff_epoch=200,
        prefixes=("autosnap_", "syncoid_fractal_"),
        anchor_guids=frozenset({"anchor-guid"}),
    )

    assert [snapshot.name for snapshot in selected] == ["autosnap_old"]


def test_prune_accepts_a_bookmark_as_the_only_common_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list(dataset: str, kind: str = "snapshot"):
        if dataset == "source":
            if kind == "bookmark":
                return [retention.Snapshot("syncoid_fractal_anchor", 100, "anchor-guid")]
            return [retention.Snapshot("autosnap_new", 900_000, "new-guid")]
        return [
            retention.Snapshot("autosnap_old", 50, "old-guid"),
            retention.Snapshot("syncoid_fractal_anchor", 100, "anchor-guid"),
        ]

    monkeypatch.setattr(retention, "list_snapshots", fake_list)
    monkeypatch.setattr(retention, "dataset_exists", lambda dataset: True)

    selected = retention.prune(
        source="source",
        target="target",
        keep_days=1,
        prefixes=("autosnap_", "syncoid_fractal_"),
        now_epoch=1_000_000,
        dry_run=True,
    )

    assert [snapshot.name for snapshot in selected] == ["autosnap_old"]


def test_prune_skips_a_target_that_does_not_exist_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retention, "dataset_exists", lambda dataset: False)

    def fail_list(*args, **kwargs):
        raise AssertionError("must not list snapshots of a missing target")

    monkeypatch.setattr(retention, "list_snapshots", fail_list)

    assert retention.prune(
        source="source", target="target", keep_days=60, prefixes=("autosnap_",), now_epoch=10
    ) == []
