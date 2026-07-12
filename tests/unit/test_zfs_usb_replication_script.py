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
            zfs_usb_replication_pool="vault",
            zfs_usb_replication_key_path=str(tmp_path / "key"),
            zfs_usb_replication_syncoid_path="/bin/true",
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
            zfs_usb_replication_jobs=[],
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _fake_commands(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "logger").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "zpool").write_text(
        """#!/bin/bash
if [[ "$1" == "list" && "$2" == "-Hp" ]]; then
  printf '1000\\t970\\t30\\n'
  exit 0
fi
if [[ "$1" == "list" ]]; then
  printf 'vault\\n'
  exit 0
fi
if [[ "$1" == "export" ]]; then
  exit "${FAKE_EXPORT_RC:-0}"
fi
exit 0
""",
        encoding="utf-8",
    )
    (bin_dir / "zfs").write_text(
        """#!/bin/bash
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
    for path in bin_dir.iterdir():
        path.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, *, replication_rc: int, export_rc: int) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = _render_script(tmp_path)
    bin_dir = _fake_commands(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "FAKE_REPLICATION_RC": str(replication_rc),
            "FAKE_EXPORT_RC": str(export_rc),
        }
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
    freeing_index = next(i for i, line in enumerate(lines) if line.startswith("freeing_bytes="))
    assert retention_line.endswith('--prefix "syncoid_usb_"')
    assert lines.index(retention_line) < freeing_index
    assert any(line.startswith('"${retention_script}" --source "tank/second"') for line in lines)
    assert not any("syncoid_usb_\"logger" in line for line in lines)
    subprocess.run(["bash", "-n", script], check=True)


def test_termination_records_failed_present_attempt(tmp_path: Path) -> None:
    script = _render_script(tmp_path)
    bin_dir = _fake_commands(tmp_path)
    environment = os.environ.copy()
    marker = tmp_path / "mount-started"
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "FAKE_REPLICATION_RC": "0",
            "FAKE_EXPORT_RC": "0",
            "FAKE_REPLICATION_SLEEP": "30",
            "FAKE_REPLICATION_MARKER": str(marker),
        }
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
