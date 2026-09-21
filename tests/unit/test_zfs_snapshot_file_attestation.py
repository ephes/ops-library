from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import unicodedata

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "roles/zfs_usb_replication/files/zfs_snapshot_file_attestation.py"
SPEC = importlib.util.spec_from_file_location(
    "zfs_snapshot_file_attestation", MODULE_PATH
)
assert SPEC and SPEC.loader
attestation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = attestation
SPEC.loader.exec_module(attestation)

SOURCE = "sourcepool/archive"
TARGET = "targetpool/archive"
ALLOWED_ROOT = "application/packages"
FILE_ID = "asset-1"
CREATED_AT = "2026-08-09T10:00:00+00:00"


def request_document(
    *, digest: str, relative_path: str | None = None, expected_bytes: int = 9
) -> dict:
    return {
        "schema_version": 1,
        "kind": attestation.REQUEST_KIND,
        "request_id": "request-1",
        "created_at": CREATED_AT,
        "source_dataset": SOURCE,
        "target_dataset": TARGET,
        "files": [
            {
                "id": FILE_ID,
                "relative_path": relative_path or f"{ALLOWED_ROOT}/asset/manifest.json",
                "expected_bytes": expected_bytes,
                "sha256": digest,
            }
        ],
    }


def encode_request(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def parse(document: dict) -> attestation.AttestationRequest:
    return attestation.parse_request(
        encode_request(document),
        expected_source=SOURCE,
        expected_target=TARGET,
        allowed_relative_root=ALLOWED_ROOT,
    )


class FakeRunner:
    def __init__(
        self,
        mountpoint: Path,
        *,
        source_pool_guid: str = "101",
        target_pool_guid: str = "202",
        readonly: str = "on",
        receive_token: str = "-",
        source_snapshots: str | None = None,
        target_snapshots: str | None = None,
        mounted: str = "yes",
    ) -> None:
        self.mountpoint = mountpoint
        self.source_pool_guid = source_pool_guid
        self.target_pool_guid = target_pool_guid
        self.readonly = readonly
        self.receive_token = receive_token
        self.source_snapshots = source_snapshots or (
            f"{SOURCE}@old\t301\t100\t10\n" f"{SOURCE}@source-new\t777\t200\t20\n"
        )
        self.target_snapshots = target_snapshots or (
            f"{TARGET}@target-new\t777\t200\t25\n"
            f"{TARGET}@target-only\t888\t300\t30\n"
        )
        self.mounted = mounted
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...]) -> str:
        self.calls.append(argv)
        assert argv[0] in {"zfs", "zpool"}
        assert argv[1] not in {
            "destroy",
            "set",
            "snapshot",
            "receive",
            "send",
            "mount",
            "unmount",
        }
        if argv[:2] == ("zpool", "get"):
            pool = argv[-1]
            return f"{self.source_pool_guid if pool == 'sourcepool' else self.target_pool_guid}\n"
        if argv[:3] == ("zfs", "list", "-H"):
            return (
                self.source_snapshots if argv[-1] == SOURCE else self.target_snapshots
            )
        if argv[:2] == ("zfs", "get") and argv[-1] == TARGET:
            return f"readonly\t{self.readonly}\nreceive_resume_token\t{self.receive_token}\n"
        if argv[:2] == ("zfs", "get") and argv[-1] == SOURCE:
            return f"mounted\t{self.mounted}\nmountpoint\t{self.mountpoint}\n"
        raise AssertionError(f"unexpected command: {argv}")


def prepare_snapshot(
    tmp_path: Path, content: bytes = b"manifest\n"
) -> tuple[Path, bytes, Path]:
    mountpoint = (tmp_path / "source-mount").resolve()
    relative = Path(ALLOWED_ROOT) / "asset/manifest.json"
    manifest = mountpoint / ".zfs/snapshot/source-new" / relative
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(content)
    return mountpoint, content, manifest


def assert_error(code: str, function, *args, **kwargs) -> None:
    with pytest.raises(attestation.AttestationError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code


def test_parse_request_accepts_closed_bounded_document() -> None:
    digest = "a" * 64
    request = parse(request_document(digest=digest))

    assert request.request_id == "request-1"
    assert request.source_dataset == SOURCE
    assert request.files == (
        attestation.RequestedFile(
            FILE_ID, f"{ALLOWED_ROOT}/asset/manifest.json", 9, digest
        ),
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "/application/packages/file",
        "application/packages/../secret",
        "application//packages/file",
        "application/packages/file/",
        "application\\packages\\file",
        "application/packages",
        "application/packages-other/file",
    ],
)
def test_parse_request_rejects_unsafe_or_outside_paths(relative_path: str) -> None:
    assert_error(
        (
            "request_unsafe"
            if relative_path
            in {"application/packages", "application/packages-other/file"}
            else "request_invalid"
        ),
        parse,
        request_document(digest="a" * 64, relative_path=relative_path),
    )


def test_parse_request_rejects_extra_and_duplicate_fields() -> None:
    extra = request_document(digest="a" * 64)
    extra["claim"] = "offsite"
    assert_error("request_invalid", parse, extra)

    duplicate_raw = (
        b'{"schema_version":1,"schema_version":1,"kind":"'
        + attestation.REQUEST_KIND.encode()
        + b'","request_id":"request-1","created_at":"2026-08-09T10:00:00Z",'
        b'"source_dataset":"sourcepool/archive","target_dataset":"targetpool/archive",'
        b'"files":[]}'
    )
    assert_error(
        "request_invalid",
        attestation.parse_request,
        duplicate_raw,
        expected_source=SOURCE,
        expected_target=TARGET,
        allowed_relative_root=ALLOWED_ROOT,
    )


def test_parse_request_rejects_duplicate_ids_and_paths() -> None:
    document = request_document(digest="a" * 64)
    document["files"].append(dict(document["files"][0]))
    assert_error("request_invalid", parse, document)

    document["files"][1]["id"] = "asset-2"
    assert_error("request_invalid", parse, document)


def test_parse_request_rejects_wrong_topology_and_oversize() -> None:
    document = request_document(digest="a" * 64)
    document["target_dataset"] = "otherpool/archive"
    assert_error("topology_mismatch", parse, document)

    assert_error(
        "request_too_large",
        attestation.parse_request,
        b" " * (attestation.MAX_REQUEST_BYTES + 1),
        expected_source=SOURCE,
        expected_target=TARGET,
        allowed_relative_root=ALLOWED_ROOT,
    )


@pytest.mark.parametrize(
    "expected_bytes", [True, 0, -1, attestation.MAX_ATTESTED_FILE_BYTES + 1]
)
def test_parse_request_rejects_invalid_expected_bytes(expected_bytes: int) -> None:
    assert_error(
        "request_invalid",
        parse,
        request_document(digest="a" * 64, expected_bytes=expected_bytes),
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "application/packages/control\u0001/file",
        "application/packages/" + "/".join("part" for _ in range(64)),
        "application/packages/" + "x" * 256,
        "application/packages/" + unicodedata.normalize("NFD", "café"),
    ],
)
def test_parse_request_rejects_control_non_nfc_depth_and_component_bounds(
    relative_path: str,
) -> None:
    assert_error(
        "request_invalid",
        parse,
        request_document(digest="a" * 64, relative_path=relative_path),
    )


def test_newest_common_snapshot_matches_guid_not_name() -> None:
    source = [
        attestation.Snapshot(f"{SOURCE}@one", "one", "11", 100, "1"),
        attestation.Snapshot(f"{SOURCE}@two", "two", "22", 200, "2"),
    ]
    target = [
        attestation.Snapshot(f"{TARGET}@renamed", "renamed", "22", 190, "9"),
        attestation.Snapshot(f"{TARGET}@one", "one", "99", 300, "10"),
    ]

    selected_source, selected_target = attestation.newest_common_snapshot(
        source, target
    )

    assert selected_source.name == "two"
    assert selected_target.name == "renamed"
    assert selected_source.guid == selected_target.guid == "22"


def test_attest_proves_source_file_and_common_replica_guid(tmp_path: Path) -> None:
    mountpoint, content, _manifest = prepare_snapshot(tmp_path)
    digest = hashlib.sha256(content).hexdigest()
    runner = FakeRunner(mountpoint)

    source, target, files = attestation.attest(
        parse(request_document(digest=digest, expected_bytes=len(content))),
        runner=runner,
    )

    assert source == {
        "dataset": SOURCE,
        "pool": "sourcepool",
        "pool_guid": "101",
        "snapshot": f"{SOURCE}@source-new",
        "snapshot_guid": "777",
        "creation_epoch": 200,
        "createtxg": "20",
    }
    assert target["snapshot"] == f"{TARGET}@target-new"
    assert target["snapshot_guid"] == source["snapshot_guid"]
    assert target["pool_guid"] == "202"
    assert files[0]["observed_sha256"] == digest
    assert runner.calls


@pytest.mark.parametrize(
    ("runner_kwargs", "code"),
    [
        ({"target_pool_guid": "101"}, "pool_guid_not_distinct"),
        ({"readonly": "off"}, "target_not_readonly"),
        ({"receive_token": "resume-token"}, "receive_incomplete"),
        ({"mounted": "no"}, "source_not_mounted"),
        (
            {"target_snapshots": (f"{TARGET}@different\t999\t200\t20\n")},
            "no_common_snapshot",
        ),
    ],
)
def test_attest_fails_closed_on_invalid_zfs_state(
    tmp_path: Path, runner_kwargs: dict[str, str], code: str
) -> None:
    mountpoint, content, _manifest = prepare_snapshot(tmp_path)
    request = parse(
        request_document(
            digest=hashlib.sha256(content).hexdigest(), expected_bytes=len(content)
        )
    )

    assert_error(
        code,
        attestation.attest,
        request,
        runner=FakeRunner(mountpoint, **runner_kwargs),
    )


def test_attest_rejects_digest_mismatch_and_symlink(tmp_path: Path) -> None:
    mountpoint, content, manifest = prepare_snapshot(tmp_path)
    request = parse(request_document(digest="0" * 64, expected_bytes=len(content)))
    assert_error(
        "file_digest_mismatch",
        attestation.attest,
        request,
        runner=FakeRunner(mountpoint),
    )

    manifest.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(content)
    manifest.symlink_to(outside)
    request = parse(
        request_document(
            digest=hashlib.sha256(content).hexdigest(), expected_bytes=len(content)
        )
    )
    assert_error(
        "file_missing", attestation.attest, request, runner=FakeRunner(mountpoint)
    )


def test_attest_rejects_wrong_size_fifo_hardlink_and_oversize(tmp_path: Path) -> None:
    mountpoint, content, manifest = prepare_snapshot(tmp_path)
    digest = hashlib.sha256(content).hexdigest()
    wrong_size = parse(request_document(digest=digest, expected_bytes=len(content) + 1))
    assert_error(
        "file_size_mismatch",
        attestation.attest,
        wrong_size,
        runner=FakeRunner(mountpoint),
    )

    manifest.unlink()
    os.mkfifo(manifest)
    request = parse(request_document(digest=digest, expected_bytes=len(content)))
    assert_error(
        "file_not_regular", attestation.attest, request, runner=FakeRunner(mountpoint)
    )

    manifest.unlink()
    outside = tmp_path / "hardlink-source"
    outside.write_bytes(content)
    os.link(outside, manifest)
    assert_error(
        "file_not_regular", attestation.attest, request, runner=FakeRunner(mountpoint)
    )

    manifest.unlink()
    with manifest.open("wb") as handle:
        handle.truncate(attestation.MAX_ATTESTED_FILE_BYTES + 1)
    snapshot_root = mountpoint / ".zfs/snapshot/source-new"
    root_fd = attestation._open_absolute_directory(str(snapshot_root))
    try:
        assert_error(
            "file_too_large",
            attestation.hash_regular_file,
            root_fd,
            f"{ALLOWED_ROOT}/asset/manifest.json",
            expected_bytes=1,
        )
    finally:
        os.close(root_fd)


def test_attest_rejects_same_name_with_unequal_guid_and_old_common_without_file(
    tmp_path: Path,
) -> None:
    mountpoint = (tmp_path / "source-mount").resolve()
    mountpoint.mkdir()
    request = parse(request_document(digest="a" * 64, expected_bytes=9))
    runner = FakeRunner(
        mountpoint,
        source_snapshots=f"{SOURCE}@same\t111\t100\t10\n",
        target_snapshots=f"{TARGET}@same\t222\t100\t20\n",
    )
    assert_error("no_common_snapshot", attestation.attest, request, runner=runner)

    old_root = mountpoint / ".zfs/snapshot/old-common"
    old_root.mkdir(parents=True)
    runner = FakeRunner(
        mountpoint,
        source_snapshots=(
            f"{SOURCE}@old-common\t333\t100\t10\n"
            f"{SOURCE}@new-source-only\t444\t200\t20\n"
        ),
        target_snapshots=f"{TARGET}@old-common\t333\t100\t30\n",
    )
    assert_error("file_missing", attestation.attest, request, runner=runner)


class ChangingSnapshotRunner(FakeRunner):
    def __init__(self, mountpoint: Path, *, change_target: bool) -> None:
        super().__init__(mountpoint)
        self.change_target = change_target
        self.source_lists = 0
        self.target_lists = 0

    def __call__(self, argv: tuple[str, ...]) -> str:
        if argv[:3] == ("zfs", "list", "-H"):
            if argv[-1] == SOURCE:
                self.source_lists += 1
                if self.source_lists > 1 and not self.change_target:
                    return f"{SOURCE}@source-new\t999\t200\t20\n"
            else:
                self.target_lists += 1
                if self.target_lists > 1 and self.change_target:
                    return f"{TARGET}@target-new\t999\t200\t25\n"
        return super().__call__(argv)


@pytest.mark.parametrize(
    ("change_target", "code"),
    [(False, "source_snapshot_changed"), (True, "target_snapshot_changed")],
)
def test_attest_requeries_selected_snapshot_after_hashing(
    tmp_path: Path, change_target: bool, code: str
) -> None:
    mountpoint, content, _manifest = prepare_snapshot(tmp_path)
    request = parse(
        request_document(
            digest=hashlib.sha256(content).hexdigest(), expected_bytes=len(content)
        )
    )
    assert_error(
        code,
        attestation.attest,
        request,
        runner=ChangingSnapshotRunner(mountpoint, change_target=change_target),
    )


def test_list_snapshots_rejects_descendants_duplicates_and_bad_numbers(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        tmp_path,
        source_snapshots=f"{SOURCE}/child@snap\t1\t2\t3\n",
    )
    assert_error(
        "zfs_output_invalid", attestation.list_snapshots, SOURCE, runner=runner
    )

    runner.source_snapshots = f"{SOURCE}@one\t1\t2\t3\n{SOURCE}@two\t1\t3\t4\n"
    assert_error(
        "zfs_output_invalid", attestation.list_snapshots, SOURCE, runner=runner
    )

    runner.source_snapshots = f"{SOURCE}@one\tnot-a-guid\t2\t3\n"
    assert_error(
        "zfs_output_invalid", attestation.list_snapshots, SOURCE, runner=runner
    )


def test_property_and_pool_queries_reject_extra_or_malformed_rows(
    tmp_path: Path,
) -> None:
    class ExtraRowsRunner(FakeRunner):
        def __call__(self, argv: tuple[str, ...]) -> str:
            value = super().__call__(argv)
            if argv[:2] == ("zfs", "get") and argv[-1] == TARGET:
                return value + "extra\tvalue\n"
            return value

    assert_error(
        "zfs_output_invalid",
        attestation.target_receive_state,
        TARGET,
        runner=ExtraRowsRunner(tmp_path),
    )

    class ExtraPoolRowsRunner(FakeRunner):
        def __call__(self, argv: tuple[str, ...]) -> str:
            value = super().__call__(argv)
            return value + "303\n" if argv[:2] == ("zpool", "get") else value

    assert_error(
        "zfs_output_invalid",
        attestation.pool_guid,
        "sourcepool",
        runner=ExtraPoolRowsRunner(tmp_path),
    )


def private_directory(tmp_path: Path) -> Path:
    directory = (tmp_path / "attestations").resolve()
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def test_private_request_reader_rejects_permissions_and_symlink(tmp_path: Path) -> None:
    directory = private_directory(tmp_path)
    request = directory / "request.json"
    request.write_bytes(b"{}")
    request.chmod(0o644)
    directory_fd = attestation._open_private_directory(directory)
    try:
        assert_error(
            "request_unsafe",
            attestation.read_private_request,
            directory_fd,
            request.name,
        )
        request.unlink()
        outside = tmp_path / "outside.json"
        outside.write_bytes(b"{}")
        request.symlink_to(outside)
        assert_error(
            "request_unavailable",
            attestation.read_private_request,
            directory_fd,
            request.name,
        )
        request.unlink()
        outside.chmod(0o600)
        os.link(outside, request)
        assert_error(
            "request_unsafe",
            attestation.read_private_request,
            directory_fd,
            request.name,
        )
    finally:
        os.close(directory_fd)


def cli_args(directory: Path) -> argparse.Namespace:
    return argparse.Namespace(
        attestation_dir=str(directory),
        request=str(directory / "request.json"),
        response=str(directory / "response.json"),
        expected_source=SOURCE,
        expected_target=TARGET,
        allowed_relative_root=ALLOWED_ROOT,
    )


def test_run_cli_writes_atomic_private_verified_response(tmp_path: Path) -> None:
    mountpoint, content, _manifest = prepare_snapshot(tmp_path)
    directory = private_directory(tmp_path)
    raw = encode_request(
        request_document(
            digest=hashlib.sha256(content).hexdigest(), expected_bytes=len(content)
        )
    )
    request = directory / "request.json"
    request.write_bytes(raw)
    request.chmod(0o600)

    result = attestation.run_cli(cli_args(directory), runner=FakeRunner(mountpoint))

    assert result == 0
    response_path = directory / "response.json"
    response = json.loads(response_path.read_text())
    attestation.validate_response(response)
    assert response["status"] == "verified"
    assert response["request_sha256"] == hashlib.sha256(raw).hexdigest()
    assert response["target_readonly"] == "on"
    assert response["target_receive_resume_token"] is None
    assert stat.S_IMODE(response_path.stat().st_mode) == 0o600
    assert sorted(path.name for path in directory.iterdir()) == [
        "request.json",
        "response.json",
    ]


def test_run_cli_writes_closed_blocked_response_on_evidence_failure(
    tmp_path: Path,
) -> None:
    mountpoint, _content, _manifest = prepare_snapshot(tmp_path)
    directory = private_directory(tmp_path)
    request = directory / "request.json"
    request.write_bytes(
        encode_request(request_document(digest="0" * 64, expected_bytes=9))
    )
    request.chmod(0o600)

    result = attestation.run_cli(cli_args(directory), runner=FakeRunner(mountpoint))

    assert result == 1
    response = json.loads((directory / "response.json").read_text())
    assert response["status"] == "blocked"
    assert response["reason_code"] == "file_digest_mismatch"
    assert response["source"] is None
    assert response["target"] is None
    assert response["files"] == []
    attestation.validate_response(response)


def test_response_validator_rejects_unknown_claims_and_false_lineage(
    tmp_path: Path,
) -> None:
    mountpoint, content, _manifest = prepare_snapshot(tmp_path)
    request = parse(
        request_document(
            digest=hashlib.sha256(content).hexdigest(), expected_bytes=len(content)
        )
    )
    source, target, files = attestation.attest(request, runner=FakeRunner(mountpoint))
    response = attestation.build_response(
        request_id=request.request_id,
        request_sha256="a" * 64,
        status_value="verified",
        reason_code=None,
        observed_at=CREATED_AT,
        observer_host="storage-host",
        source=source,
        target=target,
        target_readonly="on",
        target_receive_resume_token=None,
        files=files,
    )
    response["offsite"] = True
    assert_error("response_invalid", attestation.validate_response, response)
    response.pop("offsite")
    response["files"][0]["observed_bytes"] += 1
    assert_error("response_invalid", attestation.validate_response, response)
    response["files"][0]["observed_bytes"] -= 1
    response["request_id"] = None
    assert_error("response_invalid", attestation.validate_response, response)
    response["request_id"] = request.request_id
    response["target"]["snapshot_guid"] = "999"
    assert_error("response_invalid", attestation.validate_response, response)


def test_response_validator_requires_exact_byte_evidence_and_closed_reason() -> None:
    blocked = attestation.build_response(
        request_id="request-1",
        request_sha256="a" * 64,
        status_value="blocked",
        reason_code="file_missing",
        observed_at=CREATED_AT,
        observer_host="storage-host",
        source=None,
        target=None,
        target_readonly=None,
        target_receive_resume_token=None,
        files=(),
    )
    blocked["reason_code"] = "trust-me"
    assert_error("response_invalid", attestation.validate_response, blocked)


def make_executable(tmp_path: Path, body: str) -> Path:
    executable = (tmp_path / f"command-{len(list(tmp_path.iterdir()))}").resolve()
    executable.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_command_adapter_uses_absolute_argv_and_minimal_environment(
    tmp_path: Path,
) -> None:
    command = make_executable(
        tmp_path,
        'printf \'%s|%s|%s|%s\\n\' "$LC_ALL" "$LANG" "$PATH" "${UNSAFE-unset}"',
    )
    adapter = attestation.ReadOnlyCommandAdapter(
        zfs_path=str(command), zpool_path=str(command)
    )

    assert adapter(("zfs", "get")) == "C|C|/usr/sbin:/usr/bin:/sbin:/bin|unset\n"
    assert_error(
        "request_invalid",
        attestation.ReadOnlyCommandAdapter,
        zfs_path="relative/zfs",
        zpool_path=str(command),
    )


@pytest.mark.parametrize(
    ("body", "timeout", "limit", "code"),
    [
        ("sleep 1", 0.02, 1024, "zfs_command_timeout"),
        ("exit 7", 1, 1024, "zfs_query_failed"),
        ("echo warning >&2", 1, 1024, "zfs_query_failed"),
        ("head -c 2048 /dev/zero", 1, 1024, "zfs_command_output_too_large"),
        ("head -c 2048 /dev/zero >&2", 1, 1024, "zfs_command_output_too_large"),
    ],
)
def test_command_adapter_fails_closed_on_timeout_nonzero_and_oversized_output(
    tmp_path: Path, body: str, timeout: float, limit: int, code: str
) -> None:
    command = make_executable(tmp_path, body)
    adapter = attestation.ReadOnlyCommandAdapter(
        zfs_path=str(command),
        zpool_path=str(command),
        timeout_seconds=timeout,
        max_output_bytes=limit,
    )
    assert_error(code, adapter, ("zfs", "list"))


def test_role_installs_private_directory_and_non_world_executable_helper() -> None:
    defaults = (ROOT / "roles/zfs_usb_replication/defaults/main.yml").read_text()
    tasks = (ROOT / "roles/zfs_usb_replication/tasks/main.yml").read_text()
    role_readme = (ROOT / "roles/zfs_usb_replication/README.md").read_text()

    assert "zfs_usb_replication_attestation_dir" in defaults
    assert "zfs_usb_replication_attestation_helper_path" in defaults
    assert "zfs_usb_replication_attestation_zfs_path" not in defaults
    assert "zfs_usb_replication_attestation_zpool_path" not in defaults
    assert "zfs_usb_replication_attestation_zfs_path" not in tasks
    assert "zfs_usb_replication_attestation_zpool_path" not in tasks
    directory_task = tasks.split(
        "Ensure snapshot-file attestation directory exists", 1
    )[1]
    directory_task = directory_task.split("- name:", 1)[0]
    helper_task = tasks.split("Install read-only snapshot-file attestation helper", 1)[
        1
    ]
    helper_task = helper_task.split("- name:", 1)[0]
    assert 'mode: "0700"' in directory_task
    assert 'mode: "0750"' in helper_task
    assert "zfs_snapshot_file_attestation.py" in helper_task
    assert "notify:" not in helper_task
    assert "external attended caller must pin and pass" in role_readme

    parser = attestation.argument_parser()
    assert parser._option_string_actions["--zfs-path"].required
    assert parser._option_string_actions["--zpool-path"].required
