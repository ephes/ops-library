#!/usr/bin/env python3
"""Build and mutate an sshd candidate tree without following links."""

from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import stat
import sys
from collections.abc import Sequence
from pathlib import Path


class CandidateError(RuntimeError):
    """The source or candidate hierarchy is unsafe."""


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        os.close(descriptor)
        raise CandidateError(f"not a no-follow directory: {path}")
    return descriptor


def _require_candidate_root(path: Path) -> int:
    descriptor = _open_directory(path)
    info = os.fstat(descriptor)
    if (
        info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_nlink < 2
    ):
        os.close(descriptor)
        raise CandidateError("candidate root is not canonical owner-only state")
    return descriptor


def _temporary_file(parent_fd: int, name: str) -> tuple[int, str]:
    for _ in range(128):
        temporary_name = f".{name}.{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            continue
        return descriptor, temporary_name
    raise CandidateError("cannot allocate candidate temporary file")


def _copy_regular(source_fd: int, target_fd: int, name: str) -> None:
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd)
    try:
        before = os.fstat(source)
        if not stat.S_ISREG(before.st_mode):
            raise CandidateError(f"SSH source is not a regular file: {name}")
        temporary_fd, temporary_name = _temporary_file(target_fd, name)
        try:
            os.fchmod(temporary_fd, stat.S_IMODE(before.st_mode) & 0o777)
            while chunk := os.read(source, 1024 * 1024):
                view = memoryview(chunk)
                while view:
                    written = os.write(temporary_fd, view)
                    view = view[written:]
            after = os.fstat(source)
            if (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise CandidateError(f"SSH source changed while copied: {name}")
            os.fsync(temporary_fd)
            os.rename(
                temporary_name,
                name,
                src_dir_fd=target_fd,
                dst_dir_fd=target_fd,
            )
            os.fsync(target_fd)
        finally:
            os.close(temporary_fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=target_fd)
    finally:
        os.close(source)


def _copy_tree(source_fd: int, target_fd: int, display: str) -> None:
    for name in sorted(os.listdir(source_fd)):
        if name in {".", ".."} or "/" in name or "\0" in name:
            raise CandidateError("invalid SSH source entry name")
        info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        child_display = f"{display}/{name}"
        if stat.S_ISLNK(info.st_mode):
            raise CandidateError(f"SSH source contains a symlink: {child_display}")
        if stat.S_ISDIR(info.st_mode):
            os.mkdir(name, stat.S_IMODE(info.st_mode) & 0o777, dir_fd=target_fd)
            source_child = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
                dir_fd=source_fd,
            )
            target_child = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
                dir_fd=target_fd,
            )
            try:
                _copy_tree(source_child, target_child, child_display)
                os.fsync(target_child)
            finally:
                os.close(target_child)
                os.close(source_child)
        elif stat.S_ISREG(info.st_mode):
            _copy_regular(source_fd, target_fd, name)
        else:
            raise CandidateError(
                f"SSH source contains a non-file entry: {child_display}"
            )


def _open_candidate_parent(root_fd: int, relative: Path) -> tuple[int, str]:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise CandidateError("candidate target must be a normalized relative path")
    current = os.dup(root_fd)
    try:
        for component in relative.parts[:-1]:
            if component in {"", "."}:
                raise CandidateError("candidate target is not normalized")
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
        return current, relative.name
    except BaseException:
        os.close(current)
        raise


def _replace_candidate(root_fd: int, relative: Path, payload: bytes, mode: int) -> None:
    parent_fd, name = _open_candidate_parent(root_fd, relative)
    try:
        temporary_fd, temporary_name = _temporary_file(parent_fd, name)
        try:
            os.fchmod(temporary_fd, mode)
            view = memoryview(payload)
            while view:
                written = os.write(temporary_fd, view)
                view = view[written:]
            os.fsync(temporary_fd)
            os.rename(
                temporary_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
        finally:
            os.close(temporary_fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def prepare(source: Path, candidate: Path) -> None:
    source_fd = _open_directory(source)
    candidate_fd = _require_candidate_root(candidate)
    try:
        if os.listdir(candidate_fd):
            raise CandidateError("candidate root must be empty before SSH copy")
        _copy_tree(source_fd, candidate_fd, str(source))
        config_fd = os.open(
            "sshd_config", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=candidate_fd
        )
        try:
            info = os.fstat(config_fd)
            if not stat.S_ISREG(info.st_mode):
                raise CandidateError("candidate sshd_config is not regular")
            chunks: list[bytes] = []
            while chunk := os.read(config_fd, 1024 * 1024):
                chunks.append(chunk)
        finally:
            os.close(config_fd)
        payload = b"".join(chunks).replace(b"/etc/ssh/", os.fsencode(candidate) + b"/")
        _replace_candidate(candidate_fd, Path("sshd_config"), payload, 0o600)
    finally:
        os.close(candidate_fd)
        os.close(source_fd)


def install(candidate: Path, rendered: Path, target: Path) -> None:
    rendered_fd = os.open(rendered, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(rendered_fd)
        if not stat.S_ISREG(info.st_mode):
            raise CandidateError("rendered candidate policy is not regular")
        chunks: list[bytes] = []
        while chunk := os.read(rendered_fd, 1024 * 1024):
            chunks.append(chunk)
    finally:
        os.close(rendered_fd)
    candidate_fd = _require_candidate_root(candidate)
    try:
        _replace_candidate(candidate_fd, target, b"".join(chunks), 0o644)
    finally:
        os.close(candidate_fd)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("prepare", "install"), required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--rendered", type=Path)
    parser.add_argument("--target", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.action == "prepare":
            if args.source is None:
                raise CandidateError("prepare requires --source")
            prepare(args.source, args.candidate)
        else:
            if args.rendered is None or args.target is None:
                raise CandidateError("install requires --rendered and --target")
            install(args.candidate, args.rendered, args.target)
    except (CandidateError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
