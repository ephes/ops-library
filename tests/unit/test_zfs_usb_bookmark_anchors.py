from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "roles/zfs_usb_replication/files/zfs_usb_bookmark_anchors.py"
SPEC = importlib.util.spec_from_file_location("zfs_usb_bookmark_anchors", MODULE_PATH)
assert SPEC and SPEC.loader
anchors = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = anchors
SPEC.loader.exec_module(anchors)


class FakeZfs:
    """In-memory datasets with snapshots and bookmarks as (name, guid, createtxg)."""

    def __init__(self) -> None:
        self.snapshots: dict[str, list[tuple[str, str, int]]] = {}
        self.bookmarks: dict[str, list[tuple[str, str, int]]] = {}
        self.calls: list[list[str]] = []

    def dataset(self, name: str, snapshots=(), bookmarks=()) -> None:
        self.snapshots[name] = list(snapshots)
        self.bookmarks[name] = list(bookmarks)

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:2] == ["list", "-H"] and "-t" in args and args[args.index("-t") + 1] in {"snapshot", "bookmark"}:
            kind = args[args.index("-t") + 1]
            dataset = args[-1]
            store = self.snapshots if kind == "snapshot" else self.bookmarks
            separator = "@" if kind == "snapshot" else "#"
            return "".join(
                f"{dataset}{separator}{name}\t{guid}\t{txg}\n" for name, guid, txg in store.get(dataset, [])
            )
        if args[:2] == ["list", "-H"]:
            root = args[-1]
            recursive = "-r" in args
            return "".join(
                f"{name}\n"
                for name in sorted(self.snapshots)
                if name == root or (recursive and name.startswith(root + "/"))
            )
        if args[0] == "bookmark":
            source, target = args[1], args[2]
            dataset, snapshot = source.split("@")
            _, bookmark = target.split("#")
            guid, txg = next((g, t) for n, g, t in self.snapshots[dataset] if n == snapshot)
            if any(n == bookmark for n, _g, _t in self.bookmarks[dataset]):
                raise AssertionError("bookmark exists")
            self.bookmarks[dataset].append((bookmark, guid, txg))
            return ""
        if args[0] == "destroy":
            dataset, bookmark = args[1].split("#")
            self.bookmarks[dataset] = [b for b in self.bookmarks[dataset] if b[0] != bookmark]
            return ""
        raise AssertionError(f"unexpected zfs call {args}")


def _sync(zfs: FakeZfs, state: Path, device: str, jobs=(("tank/photos", "vault/photos", False),), **kwargs):
    return anchors.sync_anchors(
        state_path=state,
        device_name=device,
        rotation=["a", "b"],
        jobs=list(jobs),
        prune_prefixes=("autosnap_", "syncoid_"),
        runner=zfs,
        now="2026-09-28T04:00:00+00:00",
        **kwargs,
    )


def test_bookmarks_the_newest_replicated_snapshot_and_records_it(tmp_path: Path) -> None:
    zfs = FakeZfs()
    zfs.dataset("tank/photos", snapshots=[("autosnap_1", "g1", 1), ("autosnap_2", "g2", 2)])
    zfs.dataset("vault/photos", snapshots=[("autosnap_1", "g1", 10), ("autosnap_2", "g2", 11)])
    state_path = tmp_path / "anchors.json"

    _sync(zfs, state_path, "a")

    assert zfs.bookmarks["tank/photos"] == [("autosnap_2", "g2", 2)]
    recorded = json.loads(state_path.read_text())["devices"]["a"]["datasets"]["tank/photos"]
    assert recorded["guid"] == "g2"
    assert recorded["bookmark"] == "autosnap_2"
    assert recorded["target"] == "vault/photos"


def test_reuses_an_existing_bookmark_with_the_same_guid(tmp_path: Path) -> None:
    zfs = FakeZfs()
    zfs.dataset("tank/photos", snapshots=[], bookmarks=[("autosnap_2", "g2", 2)])
    zfs.dataset("vault/photos", snapshots=[("autosnap_2", "g2", 11)])

    _sync(zfs, tmp_path / "anchors.json", "a")

    assert not any(call[0] == "bookmark" for call in zfs.calls)


def test_suffixes_the_name_when_a_bookmark_of_another_snapshot_holds_it(tmp_path: Path) -> None:
    zfs = FakeZfs()
    zfs.dataset("tank/photos", snapshots=[("autosnap_2", "g2abcdef", 2)], bookmarks=[("autosnap_2", "other", 1)])
    zfs.dataset("vault/photos", snapshots=[("autosnap_2", "g2abcdef", 11)])

    state = _sync(zfs, tmp_path / "anchors.json", "a", prune=False)

    assert ("autosnap_2_g2abcd", "g2abcdef", 2) in zfs.bookmarks["tank/photos"]
    assert state["devices"]["a"]["datasets"]["tank/photos"]["bookmark"] == "autosnap_2_g2abcd"


def test_fails_when_no_target_snapshot_is_known_on_the_source(tmp_path: Path) -> None:
    zfs = FakeZfs()
    zfs.dataset("tank/photos", snapshots=[("autosnap_3", "g3", 3)])
    zfs.dataset("vault/photos", snapshots=[("target_only", "gx", 11)])

    with pytest.raises(anchors.AnchorError, match="has a snapshot or bookmark"):
        _sync(zfs, tmp_path / "anchors.json", "a")


def test_anchors_the_newest_common_snapshot_below_newer_target_only_ones(tmp_path: Path) -> None:
    # A parent dataset that gets no new source snapshots: syncoid has nothing to
    # send, so the drive keeps an older target-only sync snapshot on top.
    zfs = FakeZfs()
    zfs.dataset("tank/replica/fast", snapshots=[("syncoid_fractal_old", "g1", 1)])
    zfs.dataset(
        "vault/replica/fast",
        snapshots=[("syncoid_fractal_old", "g1", 5), ("syncoid_usb_fractal_may", "gm", 6)],
    )

    state = _sync(zfs, tmp_path / "anchors.json", "b", jobs=(("tank/replica/fast", "vault/replica/fast", False),))

    assert state["devices"]["b"]["datasets"]["tank/replica/fast"]["guid"] == "g1"
    assert zfs.bookmarks["tank/replica/fast"] == [("syncoid_fractal_old", "g1", 1)]


def test_keeps_all_bookmarks_until_every_drive_has_an_anchor(tmp_path: Path) -> None:
    zfs = FakeZfs()
    zfs.dataset(
        "tank/photos",
        snapshots=[("autosnap_5", "g5", 5)],
        bookmarks=[("autosnap_1", "g1", 1), ("autosnap_2", "g2", 2)],
    )
    zfs.dataset("vault/photos", snapshots=[("autosnap_5", "g5", 11)])

    _sync(zfs, tmp_path / "anchors.json", "a")

    assert [name for name, _g, _t in zfs.bookmarks["tank/photos"]] == ["autosnap_1", "autosnap_2", "autosnap_5"]


def test_prunes_only_bookmarks_no_drive_needs(tmp_path: Path) -> None:
    zfs = FakeZfs()
    zfs.dataset(
        "tank/photos",
        snapshots=[("autosnap_5", "g5", 5)],
        bookmarks=[("autosnap_1", "g1", 1), ("autosnap_2", "g2", 2), ("manual_keep", "gm", 3)],
    )
    zfs.dataset("vault/photos", snapshots=[("autosnap_5", "g5", 11)])
    state_path = tmp_path / "anchors.json"
    state_path.write_text(
        json.dumps({"version": 1, "devices": {"b": {"datasets": {"tank/photos": {"guid": "g2"}}}}})
    )

    _sync(zfs, state_path, "a")

    assert [name for name, _g, _t in zfs.bookmarks["tank/photos"]] == ["autosnap_2", "manual_keep", "autosnap_5"]


def test_recursive_jobs_anchor_every_child_dataset(tmp_path: Path) -> None:
    zfs = FakeZfs()
    zfs.dataset("tank/replica/fast", snapshots=[])
    zfs.dataset("tank/replica/fast/general", snapshots=[("autosnap_1", "g1", 1)])
    zfs.dataset("vault/replica/fast", snapshots=[])
    zfs.dataset("vault/replica/fast/general", snapshots=[("autosnap_1", "g1", 9)])

    state = _sync(zfs, tmp_path / "anchors.json", "b", jobs=(("tank/replica/fast", "vault/replica/fast", True),))

    assert set(state["devices"]["b"]["datasets"]) == {"tank/replica/fast/general"}


def test_refuses_an_unreadable_anchor_record(tmp_path: Path) -> None:
    state_path = tmp_path / "anchors.json"
    state_path.write_text("[]")

    with pytest.raises(anchors.AnchorError, match="not a valid anchor record"):
        _sync(FakeZfs(), state_path, "a")


def test_refuses_a_drive_outside_the_rotation(tmp_path: Path) -> None:
    with pytest.raises(anchors.AnchorError, match="not part of the rotation"):
        _sync(FakeZfs(), tmp_path / "anchors.json", "c")
