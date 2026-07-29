#!/usr/bin/env python3
"""Attest a managed forwarding account and remove only its pinned canonical home."""

from __future__ import annotations

import argparse
import ctypes
import grp
import json
import os
import pwd
import re
import stat
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


class AccountRemovalError(RuntimeError):
    """The live account no longer matches its managed contract."""


VANISHED_PROCESS_ERRORS = (FileNotFoundError, ProcessLookupError)


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino, stat.S_IFMT(first.st_mode)) == (
        second.st_dev,
        second.st_ino,
        stat.S_IFMT(second.st_mode),
    )


def _validate_paths(user: str, home: Path, contract: Path) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", user):
        raise AccountRemovalError("invalid managed account name")
    if home != Path("/home") / user or not home.is_absolute():
        raise AccountRemovalError("managed home is not canonical")
    expected_contract = Path("/var/lib/ssh-restricted-forwarding") / (
        f"{user}.account.json"
    )
    if contract != expected_contract:
        raise AccountRemovalError("managed account contract path is not canonical")


def _open_home_parent() -> int:
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        home_fd = os.open(
            "home",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=root_fd,
        )
    finally:
        os.close(root_fd)
    info = os.fstat(home_fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        os.close(home_fd)
        raise AccountRemovalError("/home hierarchy is not canonical root-owned state")
    return home_fd


def _open_optional(
    parent_fd: int,
    name: str,
    flags: int,
) -> tuple[int, os.stat_result] | None:
    try:
        descriptor = os.open(
            name,
            flags | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AccountRemovalError(f"managed home entry is unsafe: {name}") from exc
    return descriptor, os.fstat(descriptor)


def _require_directory(
    info: os.stat_result,
    *,
    uid: int,
    gid: int,
    mode: int,
    label: str,
) -> None:
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != uid
        or info.st_gid != gid
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise AccountRemovalError(f"{label} metadata does not match managed contract")


def _attest_home_contents(home_fd: int, uid: int, gid: int) -> None:
    opened_ssh = _open_optional(home_fd, ".ssh", os.O_RDONLY | os.O_DIRECTORY)
    if opened_ssh is None:
        return
    ssh_fd, ssh_info = opened_ssh
    try:
        _require_directory(
            ssh_info,
            uid=uid,
            gid=gid,
            mode=0o700,
            label="managed SSH directory",
        )
        opened_key = _open_optional(ssh_fd, "authorized_keys", os.O_RDONLY)
        if opened_key is None:
            return
        key_fd, key_info = opened_key
        try:
            if (
                not stat.S_ISREG(key_info.st_mode)
                or key_info.st_nlink != 1
                or key_info.st_uid != uid
                or key_info.st_gid != gid
                or stat.S_IMODE(key_info.st_mode) != 0o600
            ):
                raise AccountRemovalError(
                    "managed authorized_keys metadata does not match contract"
                )
        finally:
            os.close(key_fd)
    finally:
        os.close(ssh_fd)


def _attest_home(user: str, uid: int, gid: int) -> os.stat_result | None:
    parent_fd = _open_home_parent()
    try:
        opened_home = _open_optional(parent_fd, user, os.O_RDONLY | os.O_DIRECTORY)
        if opened_home is None:
            return None
        home_fd, home_info = opened_home
        try:
            _require_directory(
                home_info, uid=uid, gid=gid, mode=0o700, label="managed home"
            )
            _attest_home_contents(home_fd, uid, gid)
            return home_info
        finally:
            os.close(home_fd)
    finally:
        os.close(parent_fd)


def _current_identity(user: str, group: str) -> tuple[Any | None, Any | None]:
    try:
        passwd = pwd.getpwnam(user)
    except KeyError:
        passwd = None
    try:
        group_record = grp.getgrnam(group)
    except KeyError:
        group_record = None
    return passwd, group_record


def _identity_payload(user: str, group: str, home: Path, shell: str) -> dict[str, Any]:
    passwd, group_record = _current_identity(user, group)
    if passwd is None or group_record is None:
        raise AccountRemovalError("managed account and primary group must both exist")
    try:
        gid_record = grp.getgrgid(passwd.pw_gid)
    except KeyError as exc:
        raise AccountRemovalError("managed primary group ID is ambiguous") from exc
    if (
        passwd.pw_name != user
        or passwd.pw_uid == 0
        or passwd.pw_gid != group_record.gr_gid
        or gid_record.gr_name != group
        or passwd.pw_dir != str(home)
        or passwd.pw_shell != shell
    ):
        raise AccountRemovalError(
            "live passwd/group identity does not match managed account"
        )
    if _attest_home(user, passwd.pw_uid, passwd.pw_gid) is None:
        raise AccountRemovalError("managed home is missing")
    return {
        "version": 1,
        "user": user,
        "uid": passwd.pw_uid,
        "group": group,
        "gid": passwd.pw_gid,
        "home": str(home),
        "shell": shell,
    }


def _read_contract(path: Path) -> tuple[dict[str, Any], os.stat_result]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise AccountRemovalError(
            "managed account contract is missing or unsafe"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != 0
            or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise AccountRemovalError("managed account contract is not canonical")
        with os.fdopen(descriptor, encoding="utf-8") as source:
            descriptor = -1
            payload = json.load(source)
    except (OSError, ValueError, TypeError) as exc:
        raise AccountRemovalError("managed account contract is invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "user",
        "uid",
        "group",
        "gid",
        "home",
        "shell",
    }:
        raise AccountRemovalError("managed account contract has invalid fields")
    if (
        payload.get("version") != 1
        or type(payload.get("uid")) is not int
        or payload["uid"] <= 0
        or type(payload.get("gid")) is not int
        or payload["gid"] < 0
    ):
        raise AccountRemovalError("managed account contract has invalid identity")
    return payload, info


def _write_contract(path: Path, payload: dict[str, Any]) -> bool:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or parent_info.st_uid != 0
        or parent_info.st_gid != 0
        or stat.S_IMODE(parent_info.st_mode) != 0o700
    ):
        raise AccountRemovalError("managed account contract directory is unsafe")
    try:
        prior, _prior_info = _read_contract(path)
    except AccountRemovalError:
        try:
            path_info = path.lstat()
        except FileNotFoundError:
            path_info = None
        if path_info is not None:
            raise
    else:
        if prior != payload:
            raise AccountRemovalError(
                "managed account contract conflicts with live identity"
            )
        return False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            descriptor = -1
            json.dump(payload, destination, sort_keys=True, separators=(",", ":"))
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return True


def _uid_processes(uid: int) -> list[int]:
    """Return processes whose real/effective/saved/fs UID matches ``uid``."""
    proc = Path("/proc")
    if not proc.is_dir():
        raise AccountRemovalError("cannot attest managed account process ownership")
    try:
        entries = list(proc.iterdir())
    except OSError as exc:
        raise AccountRemovalError(
            "cannot enumerate managed account process ownership"
        ) from exc
    matches: list[int] = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            lines = (entry / "status").read_text(encoding="utf-8").splitlines()
        except VANISHED_PROCESS_ERRORS:
            # The numeric proc entry was positively observed and then vanished.
            continue
        except OSError as exc:
            raise AccountRemovalError("cannot read one process owner") from exc
        uid_line = next((line for line in lines if line.startswith("Uid:")), None)
        if uid_line is None:
            raise AccountRemovalError("cannot attest one process owner")
        try:
            process_uids = {int(value) for value in uid_line.split()[1:]}
        except ValueError as exc:
            raise AccountRemovalError("cannot parse one process owner") from exc
        if uid in process_uids:
            matches.append(int(entry.name))
    return sorted(matches)


def _require_no_uid_processes(uid: int) -> None:
    if _uid_processes(uid):
        raise AccountRemovalError("managed account still owns a running process")


def _require_contracted_numeric_identity(
    payload: dict[str, Any], *, defer_uid_processes: bool = False
) -> list[int]:
    """Reject numeric identity reuse while the durable contract still exists."""
    try:
        uid_record = pwd.getpwuid(payload["uid"])
    except KeyError:
        uid_record = None
    if uid_record is not None and uid_record.pw_name != payload["user"]:
        raise AccountRemovalError("managed UID was reassigned to another account")
    try:
        gid_record = grp.getgrgid(payload["gid"])
    except KeyError:
        gid_record = None
    if gid_record is not None and gid_record.gr_name != payload["group"]:
        raise AccountRemovalError("managed GID was reassigned to another group")
    if defer_uid_processes:
        return _uid_processes(payload["uid"])
    _require_no_uid_processes(payload["uid"])
    return []


def attest(
    user: str,
    group: str,
    home: Path,
    shell: str,
    contract: Path,
    *,
    attest_home_tree: bool = True,
    defer_uid_processes: bool = False,
) -> dict[str, Any]:
    passwd, group_record = _current_identity(user, group)
    home_parent_fd = _open_home_parent()
    try:
        try:
            home_info = os.stat(user, dir_fd=home_parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            home_info = None
    finally:
        os.close(home_parent_fd)
    contract_present = contract.exists() or contract.is_symlink()
    if (
        passwd is None
        and group_record is None
        and home_info is None
        and not contract_present
    ):
        if defer_uid_processes:
            return {
                "status": "absent",
                "deferred_uid_processes": [],
                "process_gate": "deferred-post-shutdown",
            }
        return {"status": "absent"}

    payload, _contract_info = _read_contract(contract)
    if (payload["user"], payload["group"], payload["home"], payload["shell"]) != (
        user,
        group,
        str(home),
        shell,
    ):
        raise AccountRemovalError(
            "managed account contract does not match configuration"
        )
    if defer_uid_processes:
        deferred_processes = _require_contracted_numeric_identity(
            payload, defer_uid_processes=True
        )
    else:
        deferred_processes = _require_contracted_numeric_identity(payload)
    if passwd is not None and (
        passwd.pw_name != user
        or passwd.pw_uid != payload["uid"]
        or passwd.pw_gid != payload["gid"]
        or passwd.pw_dir != str(home)
        or passwd.pw_shell != shell
    ):
        raise AccountRemovalError("live passwd identity drifted from managed contract")
    if group_record is not None and (
        group_record.gr_name != group or group_record.gr_gid != payload["gid"]
    ):
        raise AccountRemovalError("live primary group drifted from managed contract")
    if passwd is not None and group_record is None:
        raise AccountRemovalError("managed primary group is missing")
    if passwd is not None:
        try:
            gid_record = grp.getgrgid(passwd.pw_gid)
        except KeyError as exc:
            raise AccountRemovalError("live primary group ID is ambiguous") from exc
        if gid_record.gr_name != group:
            raise AccountRemovalError("live primary group identity is ambiguous")
    if home_info is not None and attest_home_tree:
        _attest_home(user, payload["uid"], payload["gid"])
    result: dict[str, Any] = {
        "status": (
            "absent"
            if passwd is None and group_record is None and home_info is None
            else "attested"
        ),
        "uid": payload["uid"],
        "gid": payload["gid"],
    }
    if defer_uid_processes:
        result["deferred_uid_processes"] = deferred_processes
        result["process_gate"] = "deferred-post-shutdown"
    return result


class _StatxTimestamp(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_int64),
        ("tv_nsec", ctypes.c_uint32),
        ("reserved", ctypes.c_int32),
    ]


class _Statx(ctypes.Structure):
    _fields_ = [
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("spare0", ctypes.c_uint16),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", _StatxTimestamp),
        ("stx_btime", _StatxTimestamp),
        ("stx_ctime", _StatxTimestamp),
        ("stx_mtime", _StatxTimestamp),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("stx_mnt_id", ctypes.c_uint64),
        ("stx_dio_mem_align", ctypes.c_uint32),
        ("stx_dio_offset_align", ctypes.c_uint32),
        ("spare3", ctypes.c_uint64 * 12),
    ]


def _mount_id_fd(descriptor: int) -> int:
    """Read Linux's mount ID for an already-pinned descriptor with statx."""
    if sys.platform != "linux":
        raise AccountRemovalError("mount identity attestation requires Linux statx")
    try:
        statx = ctypes.CDLL(None, use_errno=True).statx
    except AttributeError as exc:
        raise AccountRemovalError("Linux statx mount identity is unavailable") from exc
    statx.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_Statx),
    )
    statx.restype = ctypes.c_int
    result = _Statx()
    statx_mount_id = 0x00001000
    if (
        statx(
            descriptor,
            b"",
            0x1000
            | 0x0800
            | 0x0100,  # AT_EMPTY_PATH|AT_NO_AUTOMOUNT|AT_SYMLINK_NOFOLLOW
            0x000007FF | statx_mount_id,
            ctypes.byref(result),
        )
        != 0
    ):
        error_number = ctypes.get_errno()
        raise AccountRemovalError(
            "cannot read managed home mount identity"
        ) from OSError(error_number, os.strerror(error_number))
    if not result.stx_mask & statx_mount_id or result.stx_mnt_id <= 0:
        raise AccountRemovalError("Linux statx did not return a mount identity")
    return int(result.stx_mnt_id)


def _open_entry_for_mount(directory_fd: int, name: str) -> int:
    path_flag = getattr(os, "O_PATH", None)
    if not isinstance(path_flag, int):
        raise AccountRemovalError("mount-safe removal requires Linux O_PATH")
    try:
        return os.open(
            name,
            path_flag | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        raise AccountRemovalError(
            "managed home changed during mount attestation"
        ) from exc


def _require_entry_mount(
    directory_fd: int,
    name: str,
    expected_info: os.stat_result,
    home_mount_id: int,
) -> None:
    entry_fd = _open_entry_for_mount(directory_fd, name)
    try:
        opened = os.fstat(entry_fd)
        if not _same_identity(expected_info, opened):
            raise AccountRemovalError("managed home changed during mount attestation")
        if _mount_id_fd(entry_fd) != home_mount_id:
            raise AccountRemovalError("managed home contains a nested mount")
    finally:
        os.close(entry_fd)


def _require_pinned_home_entry(
    parent_fd: int,
    user: str,
    expected_info: os.stat_result,
    parent_mount_id: int,
) -> None:
    if _mount_id_fd(parent_fd) != parent_mount_id:
        raise AccountRemovalError("/home mount identity changed")
    try:
        current = os.stat(user, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise AccountRemovalError(
            "managed home changed during mount attestation"
        ) from exc
    if not _same_identity(expected_info, current):
        raise AccountRemovalError("managed home changed during mount attestation")
    _require_entry_mount(parent_fd, user, current, parent_mount_id)


def _preflight_contents(
    directory_fd: int,
    home_mount_id: int,
    root_guard: Callable[[], None] | None = None,
) -> None:
    """Reject every existing nested mount before the first unlink/rmdir."""
    if root_guard is not None:
        root_guard()
    if _mount_id_fd(directory_fd) != home_mount_id:
        raise AccountRemovalError("managed home mount identity changed")
    for name in sorted(os.listdir(directory_fd)):
        if root_guard is not None:
            root_guard()
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require_entry_mount(directory_fd, name, before, home_mount_id)
        if not stat.S_ISDIR(before.st_mode):
            continue
        child_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(child_fd)
            if not _same_identity(before, opened):
                raise AccountRemovalError("managed home changed during mount preflight")
            _preflight_contents(child_fd, home_mount_id, root_guard)
            if root_guard is not None:
                root_guard()
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not _same_identity(opened, current):
                raise AccountRemovalError("managed home changed during mount preflight")
            _require_entry_mount(directory_fd, name, current, home_mount_id)
        finally:
            os.close(child_fd)
    if root_guard is not None:
        root_guard()
    if _mount_id_fd(directory_fd) != home_mount_id:
        raise AccountRemovalError("managed home mount identity changed")


def _remove_contents(
    directory_fd: int,
    home_mount_id: int,
    root_guard: Callable[[], None] | None = None,
) -> None:
    if root_guard is not None:
        root_guard()
    if _mount_id_fd(directory_fd) != home_mount_id:
        raise AccountRemovalError("managed home mount identity changed")
    for name in sorted(os.listdir(directory_fd)):
        if root_guard is not None:
            root_guard()
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require_entry_mount(directory_fd, name, before, home_mount_id)
        if stat.S_ISDIR(before.st_mode):
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            try:
                opened = os.fstat(child_fd)
                if not _same_identity(before, opened):
                    raise AccountRemovalError(
                        "managed home changed during bounded removal"
                    )
                if _mount_id_fd(child_fd) != home_mount_id:
                    raise AccountRemovalError("managed home contains a nested mount")
                _remove_contents(child_fd, home_mount_id, root_guard)
                if root_guard is not None:
                    root_guard()
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not _same_identity(opened, current):
                    raise AccountRemovalError(
                        "managed home changed during bounded removal"
                    )
                _require_entry_mount(directory_fd, name, current, home_mount_id)
                if root_guard is not None:
                    root_guard()
                os.rmdir(name, dir_fd=directory_fd)
            finally:
                os.close(child_fd)
        else:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not _same_identity(before, current):
                raise AccountRemovalError("managed home changed during bounded removal")
            _require_entry_mount(directory_fd, name, current, home_mount_id)
            if root_guard is not None:
                root_guard()
            os.unlink(name, dir_fd=directory_fd)
    if root_guard is not None:
        root_guard()
    if _mount_id_fd(directory_fd) != home_mount_id:
        raise AccountRemovalError("managed home mount identity changed")
    os.fsync(directory_fd)


def remove_home(
    user: str, group: str, home: Path, shell: str, contract: Path
) -> dict[str, Any]:
    result = attest(user, group, home, shell, contract, attest_home_tree=False)
    if result["status"] == "absent":
        return result
    try:
        pwd.getpwnam(user)
    except KeyError:
        pass
    else:
        raise AccountRemovalError("managed account must be removed before its home")
    parent_fd = _open_home_parent()
    try:
        parent_mount_id = _mount_id_fd(parent_fd)
        opened = _open_optional(parent_fd, user, os.O_RDONLY | os.O_DIRECTORY)
        if opened is None:
            return {"status": "home-absent"}
        home_fd, before = opened
        try:
            _require_directory(
                before,
                uid=result["uid"],
                gid=result["gid"],
                mode=0o700,
                label="managed home",
            )

            def require_pinned_home() -> None:
                _require_pinned_home_entry(parent_fd, user, before, parent_mount_id)

            require_pinned_home()
            _attest_home_contents(home_fd, result["uid"], result["gid"])
            _preflight_contents(home_fd, parent_mount_id, require_pinned_home)
            require_pinned_home()
            _remove_contents(home_fd, parent_mount_id, require_pinned_home)
            require_pinned_home()
            os.rmdir(user, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(home_fd)
    finally:
        os.close(parent_fd)
    return {"status": "home-removed"}


def attest_home_mounts(
    user: str,
    group: str,
    home: Path,
    shell: str,
    contract: Path,
    *,
    defer_uid_processes: bool = False,
) -> dict[str, Any]:
    """Run the exact removal mount preflight without mutating the managed home."""
    result = attest(
        user,
        group,
        home,
        shell,
        contract,
        attest_home_tree=False,
        defer_uid_processes=defer_uid_processes,
    )
    if result["status"] == "absent":
        return result
    parent_fd = _open_home_parent()
    try:
        parent_mount_id = _mount_id_fd(parent_fd)
        opened = _open_optional(parent_fd, user, os.O_RDONLY | os.O_DIRECTORY)
        if opened is None:
            return {"status": "home-absent"}
        home_fd, home_info = opened
        try:
            _require_directory(
                home_info,
                uid=result["uid"],
                gid=result["gid"],
                mode=0o700,
                label="managed home",
            )

            def require_pinned_home() -> None:
                _require_pinned_home_entry(parent_fd, user, home_info, parent_mount_id)

            require_pinned_home()
            _attest_home_contents(home_fd, result["uid"], result["gid"])
            _preflight_contents(home_fd, parent_mount_id, require_pinned_home)
            require_pinned_home()
        finally:
            os.close(home_fd)
    finally:
        os.close(parent_fd)
    response: dict[str, Any] = {"status": "mounts-attested"}
    if defer_uid_processes:
        response["deferred_uid_processes"] = result.get("deferred_uid_processes", [])
        response["process_gate"] = "deferred-post-shutdown"
    return response


def remove_contract(
    user: str, group: str, home: Path, shell: str, contract: Path
) -> dict[str, Any]:
    result = attest(user, group, home, shell, contract)
    if result["status"] != "absent":
        raise AccountRemovalError("managed account remnants remain")
    try:
        _payload, before = _read_contract(contract)
    except AccountRemovalError:
        if not contract.exists() and not contract.is_symlink():
            return {"status": "contract-absent"}
        raise
    current = contract.lstat()
    if not _same_identity(before, current):
        raise AccountRemovalError("managed account contract changed during cleanup")
    contract.unlink()
    directory_fd = os.open(contract.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return {"status": "contract-removed"}


def manage(args: argparse.Namespace) -> dict[str, Any]:
    home = Path(args.home)
    contract = Path(args.contract)
    _validate_paths(args.user, home, contract)
    if os.geteuid() != 0:
        raise AccountRemovalError("managed account operations require root")
    if args.action == "record":
        payload = _identity_payload(args.user, args.group, home, args.shell)
        changed = _write_contract(contract, payload)
        return {
            "status": "recorded" if changed else "unchanged",
            "uid": payload["uid"],
            "gid": payload["gid"],
        }
    if args.action == "attest":
        return attest(
            args.user,
            args.group,
            home,
            args.shell,
            contract,
            defer_uid_processes=args.defer_uid_processes,
        )
    if args.action == "remove-home":
        return remove_home(args.user, args.group, home, args.shell, contract)
    if args.action == "attest-home-mounts":
        return attest_home_mounts(
            args.user,
            args.group,
            home,
            args.shell,
            contract,
            defer_uid_processes=args.defer_uid_processes,
        )
    if args.action == "remove-contract":
        return remove_contract(args.user, args.group, home, args.shell, contract)
    raise AccountRemovalError("unsupported action")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--action",
        choices=(
            "record",
            "attest",
            "attest-home-mounts",
            "remove-home",
            "remove-contract",
        ),
        required=True,
    )
    parser.add_argument("--user", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--shell", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument(
        "--defer-uid-processes",
        action="store_true",
        help=(
            "report contracted-UID processes as a deferred post-shutdown gate; "
            "read-only check mode only"
        ),
    )
    args = parser.parse_args()
    try:
        print(json.dumps(manage(args), sort_keys=True))
    except (AccountRemovalError, OSError, KeyError) as exc:
        print(f"account removal refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
