from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import time

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parents[2]


def _render_script(
    tmp_path: Path,
    *,
    snapshot_retention: list[dict[str, object]] | None = None,
    wait_for_async_destroy: bool = False,
    devices: list[dict[str, str]] | None = None,
    anchor_mode: str = "sync_snapshot",
    jobs: list[dict[str, object]] | None = None,
    syncoid_path: str = "/bin/true",
) -> Path:
    template_dir = ROOT / "roles/zfs_usb_replication/templates"
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["bool"] = bool
    environment.filters["ternary"] = lambda value, yes, no: yes if value else no
    template = environment.get_template("zfs-usb-replication.sh.j2")

    device = tmp_path / "usb-device"
    device.touch()
    state_writer = tmp_path / "state-writer.py"
    shutil.copy(
        ROOT / "roles/zfs_usb_replication/files/zfs_usb_replication_state.py",
        state_writer,
    )
    state_writer.chmod(0o755)
    script = tmp_path / "replicate.sh"
    script.write_text(
        template.render(
            zfs_usb_replication_device=str(device),
            zfs_usb_replication_devices=devices or [],
            zfs_usb_replication_anchor_mode=anchor_mode,
            zfs_usb_replication_anchor_helper_path=str(tmp_path / "bin" / "anchors"),
            zfs_usb_replication_anchor_state_path=str(tmp_path / "anchors.json"),
            zfs_usb_replication_bookmark_prune=True,
            zfs_usb_replication_bookmark_prune_prefixes=["autosnap_", "syncoid_"],
            zfs_usb_replication_default_args=["--no-rollback"],
            zfs_usb_replication_pool="vault",
            zfs_usb_replication_key_path=str(tmp_path / "key"),
            zfs_usb_replication_syncoid_path=syncoid_path,
            zfs_usb_replication_force_export=True,
            zfs_usb_replication_spindown_enabled=False,
            zfs_usb_replication_spindown_script_path="/bin/true",
            zfs_usb_replication_state_path=str(tmp_path / "status.json"),
            zfs_usb_replication_state_writer_path=str(state_writer),
            zfs_usb_replication_exportfs_lock_dir=str(tmp_path / "exports.d"),
            zfs_usb_replication_set_canmount_off_for_readonly_recursive_targets=False,
            zfs_usb_replication_snapshot_retention=snapshot_retention or [],
            zfs_usb_replication_retention_script_path="/bin/true",
            zfs_usb_replication_wait_for_async_destroy=wait_for_async_destroy,
            zfs_usb_replication_jobs=jobs or [],
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _fake_commands(tmp_path: Path) -> Path:
    """Stateful zpool/zfs fakes: imports record the drive in $FAKE_ZFS_STATE/imported."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_dir = tmp_path / "fake-zfs"
    state_dir.mkdir()
    (bin_dir / "logger").write_text(
        '#!/bin/bash\nshift 2\nprintf "%s\\n" "$*" >> "$FAKE_ZFS_STATE/log"\n',
        encoding="utf-8",
    )
    (bin_dir / "zpool").write_text(
        """#!/bin/bash
state="${FAKE_ZFS_STATE}"
printf 'zpool %s\\n' "$*" >> "$state/calls"
if [[ "$1" == "list" && "$2" == "-Hp" ]]; then
  printf '1000\\t970\\t30\\n'
  exit 0
fi
if [[ "$1" == "list" && "$2" == "-v" ]]; then
  [[ -f "$state/imported" ]] || exit 1
  printf 'vault\\t1000\\t970\\t30\\n'
  printf '\\t%s\\t1000\\n' "$(cat "$state/imported")"
  exit 0
fi
if [[ "$1" == "list" ]]; then
  [[ -f "$state/imported" ]] && printf 'vault\\n'
  exit 0
fi
if [[ "$1" == "import" ]]; then
  [[ -f "$state/imported" ]] && exit 1
  device=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-d" ]]; then device="$2"; shift; fi
    shift
  done
  printf '%s' "$device" > "$state/imported"
  printf '%s\\n' "$device" >> "$state/imports"
  exit "${FAKE_IMPORT_RC:-0}"
fi
if [[ "$1" == "get" ]]; then
  device="$(cat "$state/imported")"
  guid_file="${device}.guid"
  if [[ -f "$guid_file" ]]; then cat "$guid_file"; else printf '111\\n'; fi
  exit 0
fi
if [[ "$1" == "export" ]]; then
  if [[ "${FAKE_EXPORT_RC:-0}" == "0" ]]; then
    rm -f "$state/imported"
  fi
  exit "${FAKE_EXPORT_RC:-0}"
fi
exit 0
""",
        encoding="utf-8",
    )
    (bin_dir / "zfs").write_text(
        """#!/bin/bash
printf 'zfs %s\\n' "$*" >> "${FAKE_ZFS_STATE}/calls"
if [[ "$1" == "get" ]]; then
  printf 'available\\n'
  exit 0
fi
if [[ "$1" == "mount" ]]; then
  if [[ -n "${FAKE_REPLICATION_MARKER:-}" ]]; then
    touch "${FAKE_REPLICATION_MARKER}"
  fi
  if [[ -n "${FAKE_REPLICATION_SLEEP:-}" ]]; then
    sleep "${FAKE_REPLICATION_SLEEP}"
  fi
  exit "${FAKE_REPLICATION_RC:-0}"
fi
exit 0
""",
        encoding="utf-8",
    )
    (bin_dir / "syncoid").write_text(
        '#!/bin/bash\nprintf "syncoid %s\\n" "$*" >> "$FAKE_ZFS_STATE/calls"\n'
        'printf "%s\\n" "$(cat "$FAKE_ZFS_STATE/imported")" >> "$FAKE_ZFS_STATE/synced"\n',
        encoding="utf-8",
    )
    (bin_dir / "anchors").write_text(
        '#!/bin/bash\nprintf "anchors %s\\n" "$*" >> "$FAKE_ZFS_STATE/calls"\n'
        'exit "${FAKE_ANCHOR_RC:-0}"\n',
        encoding="utf-8",
    )
    for path in bin_dir.iterdir():
        path.chmod(0o755)
    return bin_dir


def _environment(tmp_path: Path, bin_dir: Path, **extra: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "FAKE_ZFS_STATE": str(tmp_path / "fake-zfs"),
            **extra,
        }
    )
    return environment


def _run(tmp_path: Path, *, replication_rc: int, export_rc: int) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = _render_script(tmp_path)
    bin_dir = _fake_commands(tmp_path)
    environment = _environment(
        tmp_path,
        bin_dir,
        FAKE_REPLICATION_RC=str(replication_rc),
        FAKE_EXPORT_RC=str(export_rc),
    )
    result = subprocess.run([script], check=False, text=True, capture_output=True, env=environment)
    state = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    return result, state


def test_export_failure_turns_otherwise_successful_run_into_failure(tmp_path: Path) -> None:
    result, state = _run(tmp_path, replication_rc=0, export_rc=9)

    assert result.returncode == 1
    assert state["last_present_attempt_result"] == "failed"
    assert state["last_present_attempt_exit_code"] == 1


def test_export_failure_preserves_original_replication_error(tmp_path: Path) -> None:
    result, state = _run(tmp_path, replication_rc=7, export_rc=9)

    assert result.returncode == 7
    assert state["last_present_attempt_result"] == "failed"
    assert state["last_present_attempt_exit_code"] == 7


def test_retention_command_does_not_consume_async_free_assignment(tmp_path: Path) -> None:
    script = _render_script(
        tmp_path,
        snapshot_retention=[
            {
                "source": "tank/source",
                "target": "vault/target",
                "keep_days": 60,
                "prefixes": ["autosnap_", "syncoid_usb_"],
            },
            {
                "source": "tank/second",
                "target": "vault/second",
                "keep_days": 30,
                "prefixes": ["managed_"],
            },
        ],
        wait_for_async_destroy=True,
    )
    lines = script.read_text(encoding="utf-8").splitlines()

    retention_line = next(line for line in lines if ' --source "tank/source"' in line)
    freeing_index = next(i for i, line in enumerate(lines) if line.strip().startswith("freeing_bytes="))
    assert retention_line.endswith('--prefix "syncoid_usb_"')
    assert lines.index(retention_line) < freeing_index
    assert any(line.strip().startswith('"${retention_script}" --source "tank/second"') for line in lines)
    assert not any("syncoid_usb_\"logger" in line for line in lines)
    subprocess.run(["bash", "-n", script], check=True)


def test_termination_records_failed_present_attempt(tmp_path: Path) -> None:
    script = _render_script(tmp_path)
    bin_dir = _fake_commands(tmp_path)
    marker = tmp_path / "mount-started"
    environment = _environment(
        tmp_path,
        bin_dir,
        FAKE_REPLICATION_RC="0",
        FAKE_EXPORT_RC="0",
        FAKE_REPLICATION_SLEEP="30",
        FAKE_REPLICATION_MARKER=str(marker),
    )
    process = subprocess.Popen(
        [script],
        env=environment,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.exists()
    os.killpg(process.pid, signal.SIGTERM)
    process.communicate(timeout=5)
    state = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))

    assert process.returncode == 143
    assert state["last_present_attempt_result"] == "failed"
    assert state["last_present_attempt_exit_code"] == 143


JOBS = [
    {"source": "tank/replica/fast", "target": "vault/replica/fast", "recursive": True, "readonly": True, "no_rollback": False},
    {"source": "tank/photos", "target": "vault/photos", "readonly": True, "no_rollback": False},
]


def _rotation(tmp_path: Path, *, present: tuple[str, ...], guids: dict[str, str] | None = None) -> list[dict[str, str]]:
    devices = []
    for name in ("a", "b"):
        device = tmp_path / f"usb-drive-{name}"
        if name in present:
            device.touch()
        entry = {"name": name, "device": str(device)}
        if guids and name in guids:
            entry["pool_guid"] = guids[name]
        devices.append(entry)
    return devices


def _run_rotation(
    tmp_path: Path,
    devices: list[dict[str, str]],
    **extra: str,
) -> tuple[subprocess.CompletedProcess[str], dict, str]:
    script = _render_script(
        tmp_path,
        devices=devices,
        anchor_mode="bookmark",
        jobs=JOBS,
        syncoid_path=str(tmp_path / "bin" / "syncoid"),
    )
    bin_dir = _fake_commands(tmp_path)
    result = subprocess.run(
        [script], check=False, text=True, capture_output=True,
        env=_environment(tmp_path, bin_dir, **extra),
    )
    state = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    calls_path = tmp_path / "fake-zfs" / "calls"
    calls = calls_path.read_text(encoding="utf-8") if calls_path.exists() else ""
    return result, state, calls


def test_rotation_replicates_the_present_drive_and_records_the_absent_one(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=("b",))

    result, state, calls = _run_rotation(tmp_path, devices)

    assert result.returncode == 0, result.stderr
    assert state["last_attempt_result"] == "success"
    assert state["device_name"] == "b"
    assert state["device_path"] == devices[1]["device"]
    assert state["pool_guid"] == "111"
    assert state["devices"]["a"]["last_attempt_result"] == "skipped_absent"
    assert "last_success_at" not in state["devices"]["a"]
    assert state["devices"]["b"]["last_success_at"] == state["last_success_at"]
    assert (tmp_path / "fake-zfs" / "imports").read_text().splitlines() == [devices[1]["device"]]
    assert not (tmp_path / "fake-zfs" / "imported").exists()
    syncoid_calls = [line for line in calls.splitlines() if line.startswith("syncoid ")]
    assert len(syncoid_calls) == 2
    assert all("--no-sync-snap" in line and "--identifier" not in line for line in syncoid_calls)
    anchor_call = next(line for line in calls.splitlines() if line.startswith("anchors "))
    assert "--device-name b" in anchor_call
    assert "--rotation-device a --rotation-device b" in anchor_call
    assert "--job tank/replica/fast vault/replica/fast true" in anchor_call
    assert "--job tank/photos vault/photos false" in anchor_call
    assert "--prune-prefix autosnap_ --prune-prefix syncoid_" in anchor_call
    assert "--no-prune" not in anchor_call


def test_rotation_with_no_drive_present_skips_every_drive(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=())
    (tmp_path / "status.json").write_text(
        json.dumps({"last_success_at": "2026-09-26T04:34:20+00:00", "last_present_attempt_result": "success"}),
        encoding="utf-8",
    )

    result, state, calls = _run_rotation(tmp_path, devices)

    assert result.returncode == 0
    assert state["last_attempt_result"] == "skipped_absent"
    assert state["last_present_attempt_result"] == "success"
    assert state["last_success_at"] == "2026-09-26T04:34:20+00:00"
    assert "device_name" not in state
    assert {name: entry["last_attempt_result"] for name, entry in state["devices"].items()} == {
        "a": "skipped_absent",
        "b": "skipped_absent",
    }
    assert "syncoid" not in calls


def test_rotation_replicates_two_attached_drives_one_after_the_other(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=("a", "b"))

    result, state, _calls = _run_rotation(tmp_path, devices)

    assert result.returncode == 0, result.stderr
    fake = tmp_path / "fake-zfs"
    assert fake.joinpath("imports").read_text().splitlines() == [devices[0]["device"], devices[1]["device"]]
    assert sorted(set(fake.joinpath("synced").read_text().splitlines())) == sorted(d["device"] for d in devices)
    assert state["devices"]["a"]["last_attempt_result"] == "success"
    assert state["devices"]["b"]["last_attempt_result"] == "success"
    assert state["device_name"] == "b"


def test_rotation_refuses_a_drive_whose_pool_guid_does_not_match(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=("b",), guids={"b": "999"})
    Path(devices[1]["device"] + ".guid").write_text("111\n", encoding="utf-8")

    result, state, calls = _run_rotation(tmp_path, devices)

    assert result.returncode == 1
    assert state["last_present_attempt_result"] == "failed"
    assert state["devices"]["b"]["last_present_attempt_result"] == "failed"
    assert state["devices"]["b"]["pool_guid"] == "111"
    assert "syncoid" not in calls
    assert "zpool import -d " + devices[1]["device"] + " -o cachefile=none 999" in calls
    assert not (tmp_path / "fake-zfs" / "imported").exists()


def test_rotation_refuses_when_the_pool_is_imported_from_another_drive(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=("b",))
    other = tmp_path / "usb-drive-a"
    other.touch()
    bin_dir_state = tmp_path / "fake-zfs"
    script = _render_script(
        tmp_path, devices=[devices[1]], anchor_mode="bookmark", jobs=JOBS,
        syncoid_path=str(tmp_path / "bin" / "syncoid"),
    )
    bin_dir = _fake_commands(tmp_path)
    bin_dir_state.joinpath("imported").write_text(str(other), encoding="utf-8")

    result = subprocess.run([script], check=False, text=True, capture_output=True, env=_environment(tmp_path, bin_dir))
    state = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))

    assert result.returncode == 1
    assert state["devices"]["b"]["last_present_attempt_result"] == "failed"
    assert bin_dir_state.joinpath("imported").read_text() == str(other)
    assert "already imported from another device" in bin_dir_state.joinpath("log").read_text()


def test_rotation_anchor_failure_fails_the_drive(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=("a",))

    result, state, _calls = _run_rotation(tmp_path, devices, FAKE_ANCHOR_RC="1")

    assert result.returncode == 1
    assert state["devices"]["a"]["last_present_attempt_result"] == "failed"
    assert not (tmp_path / "fake-zfs" / "imported").exists()


def test_rotation_prefers_partition_members_for_import(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=("a",))
    Path(devices[0]["device"] + "-part1").touch()

    result, _state, calls = _run_rotation(tmp_path, devices)

    assert result.returncode == 0, result.stderr
    assert f"zpool import -d {devices[0]['device']}-part1 -o cachefile=none vault" in calls


def test_single_device_sync_snapshot_mode_keeps_identifier(tmp_path: Path) -> None:
    script = _render_script(tmp_path, jobs=JOBS)
    text = script.read_text(encoding="utf-8")

    assert "--no-sync-snap" not in text
    assert "anchor_helper" not in text
    subprocess.run(["bash", "-n", script], check=True)


def test_rotation_failure_on_one_drive_still_replicates_the_next(tmp_path: Path) -> None:
    devices = _rotation(tmp_path, present=("a", "b"), guids={"a": "999"})

    result, state, _calls = _run_rotation(tmp_path, devices)

    assert result.returncode == 1
    assert state["devices"]["a"]["last_present_attempt_result"] == "failed"
    assert state["devices"]["b"]["last_present_attempt_result"] == "success"
    assert set((tmp_path / "fake-zfs" / "synced").read_text().splitlines()) == {devices[1]["device"]}
    assert not (tmp_path / "fake-zfs" / "imported").exists()
