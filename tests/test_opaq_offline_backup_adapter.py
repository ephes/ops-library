"""Controller-local transport failures and optional pinned real-validator proof."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

PATH = Path(__file__).parents[1] / "offline/opaq-company-backup/adapter.py"
spec = importlib.util.spec_from_file_location("offline_backup", PATH)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


@pytest.fixture
def roots(tmp_path):
    paths = [tmp_path / name for name in ("objects", "scratch")]
    for path in paths:
        path.mkdir(mode=0o700)
    return paths


@pytest.fixture
def package(tmp_path):
    # Minimal envelope for transport unit tests only, not a valid Daybook package.
    path = tmp_path / "unit.zip"
    doc = {
        "format": a.FORMAT,
        "synthetic": True,
        "company": "synthetic-opaq",
        "account": "synthetic-company-bank",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name in sorted(a.MEMBERS):
            archive.writestr(
                name,
                json.dumps(doc) if name == "manifest.json" else b"invented unit bytes",
            )
    return path


class EnvelopeValidator:
    """Fake only isolates transport behavior; deep acceptance tested separately."""

    def __init__(self):
        self.calls = 0

    def restore(self, package, scratch):
        self.calls += 1
        a.scope(package)
        path = Path(scratch) / f"unit-inactive-{self.calls}"
        path.mkdir(mode=0o700)
        (path / "RECOVERY.json").write_text('{"state":"inactive-scratch"}')
        return path


def test_full_readback_success_restore_and_unique_retry(package, roots):
    objects, scratch = roots
    validator = EnvelopeValidator()
    fake = a.LocalFake(objects)
    result = a.backup(package, a.digest(package), validator, fake, scratch)
    assert validator.calls == 2
    assert result["checksum_sha256"] == a.digest(package)
    assert fake.path(result["key"]).read_bytes() == package.read_bytes()
    assert not list(scratch.iterdir())
    restored = a.restore(result, validator, fake, scratch)
    assert (
        json.loads((restored / "RECOVERY.json").read_text())["state"]
        == "inactive-scratch"
    )
    retry = a.backup(package, a.digest(package), validator, fake, scratch)
    assert retry["key"] != result["key"]
    assert len(list(objects.iterdir())) == 2


@pytest.mark.parametrize(
    "mutation",
    ["checksum", "schema", "company", "account", "missing", "duplicate", "symlink"],
)
def test_input_refusal_before_upload(package, roots, mutation, tmp_path):
    objects, scratch = roots
    expected = a.digest(package)
    if mutation in {"schema", "company", "account", "missing", "duplicate"}:
        with zipfile.ZipFile(package) as archive:
            entries = [(r.filename, archive.read(r)) for r in archive.infolist()]
        with zipfile.ZipFile(package, "w") as archive:
            for name, raw in entries:
                if name == "manifest.json" and mutation in {
                    "schema",
                    "company",
                    "account",
                }:
                    doc = json.loads(raw)
                    doc[
                        {
                            "schema": "format",
                            "company": "company",
                            "account": "account",
                        }[mutation]
                    ] = "wrong"
                    raw = json.dumps(doc).encode()
                if not (mutation == "missing" and name == "bound.sqlite"):
                    archive.writestr(name, raw)
            if mutation == "duplicate":
                archive.writestr("bound.sqlite", b"duplicate")
        expected = a.digest(package)
    if mutation == "symlink":
        link = tmp_path / "link"
        link.symlink_to(package)
        package = link
    if mutation == "checksum":
        expected = "0" * 64
    with pytest.raises(ValueError):
        a.backup(package, expected, EnvelopeValidator(), a.LocalFake(objects), scratch)
    assert not list(objects.iterdir()) and not list(scratch.iterdir())


@pytest.mark.parametrize("failure", ["truncated", "same-size-corrupt", "interrupt"])
def test_upload_failure_retains_orphan_and_prior_object(package, roots, failure):
    objects, scratch = roots
    prior = objects / "prior-owner-artifact"
    prior.write_bytes(b"do not delete")

    class Broken(a.LocalFake):
        def upload(self, source, key):
            path = self.path(key)
            path.write_bytes(Path(source).read_bytes()[:12])
            if failure == "interrupt":
                raise KeyboardInterrupt()
            if failure == "same-size-corrupt":
                raw = bytearray(Path(source).read_bytes())
                raw[-1] ^= 1
                path.write_bytes(raw)
            return path

    with pytest.raises((ValueError, KeyboardInterrupt)):
        a.backup(
            package, a.digest(package), EnvelopeValidator(), Broken(objects), scratch
        )
    assert prior.read_bytes() == b"do not delete"
    assert len(list(objects.iterdir())) == 2  # Orphan is deliberately NOT swept.
    assert not list(scratch.iterdir())


def test_exclusive_objects_and_fixed_namespace(package, roots):
    objects, _ = roots
    fake = a.LocalFake(objects)
    key = a.TARGET + "/" + "a" * 32 + ".zip"
    fake.upload(package, key)
    before = fake.path(key).read_bytes()
    with pytest.raises(FileExistsError):
        fake.upload(package, key)
    assert fake.path(key).read_bytes() == before
    for value in ["../x", "/x", "other/" + "a" * 32 + ".zip"]:
        with pytest.raises(ValueError):
            fake.path(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("bucket", "other"),
        ("success", False),
        ("key", "../other"),
        ("checksum_sha256", "0" * 64),
        ("size_bytes", 1),
        ("manifest", {"format": "wrong"}),
    ],
)
def test_restore_refuses_wrong_identity_and_bytes(package, roots, field, value):
    objects, scratch = roots
    validator = EnvelopeValidator()
    fake = a.LocalFake(objects)
    result = a.backup(package, a.digest(package), validator, fake, scratch)
    result[field] = value
    with pytest.raises(ValueError):
        a.restore(result, validator, fake, scratch)
    assert not list(scratch.iterdir())


def test_deep_refusal_never_uploads(package, roots):
    class Refused:
        def restore(self, *_):
            raise ValueError("deep journal inconsistency")

    objects, scratch = roots
    with pytest.raises(ValueError):
        a.backup(package, a.digest(package), Refused(), a.LocalFake(objects), scratch)
    assert not list(objects.iterdir()) and not list(scratch.iterdir())


def test_cli_refusal_result_no_raw_diagnostics(package, roots, tmp_path):
    # Wrong pinned source archive fails closed, without exposing source/error bodies.
    repository = tmp_path / "repo"
    repository.write_bytes(b"not the pinned source archive")
    command = [
        sys.executable,
        str(PATH),
        "backup",
        "--validator-source",
        str(repository),
        "--objects",
        str(roots[0]),
        "--scratch",
        str(roots[1]),
        "--package",
        str(package),
        "--sha256",
        a.digest(package),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    # CLI preflight must also be inside the fail-closed result boundary.
    assert (
        result.stdout
        == 'ECHOPORT_RESULT:{"success":false,"error":"offline adapter refused"}\n'
    )
    assert result.stderr == ""


@pytest.mark.skipif(
    not os.environ.get("OPAQ_PINNED_PACKAGE"),
    reason="explicit synthetic P handoff required",
)
def test_real_pinned_validator_roundtrip_and_source_isolation(
    roots, tmp_path, monkeypatch
):
    package = Path(os.environ["OPAQ_PINNED_PACKAGE"])
    source = Path(os.environ["OPAQ_VALIDATOR_SOURCE"])
    expected = os.environ["OPAQ_PINNED_SHA256"]
    python = os.environ.get("OPAQ_VALIDATOR_PYTHON", sys.executable)
    assert a.digest(package) == expected
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "adapter.py").write_text(
        "raise AssertionError('untrusted module executed')"
    )
    (poison / "sitecustomize.py").write_text(
        "raise AssertionError('site hook executed')"
    )
    monkeypatch.setenv("PYTHONPATH", str(poison))
    validator = a.Validator(source, python)
    fake = a.LocalFake(roots[0])
    result = a.backup(package, expected, validator, fake, roots[1])
    restored = a.restore(result, validator, fake, roots[1])
    with zipfile.ZipFile(package) as archive:
        for name in a.MEMBERS:
            assert (restored / name).read_bytes() == archive.read(name)
    marker = json.loads((restored / "RECOVERY.json").read_bytes())
    assert marker["import"] == marker["register"] == marker["decide"] == "disabled"
    assert marker["state"] == "inactive-scratch"
    # New hash cannot excuse a coherent envelope with corrupt bound schema.
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(bad, "w") as dest:
        for row in source.infolist():
            dest.writestr(
                row,
                b"not SQLite" if row.filename == "bound.sqlite" else source.read(row),
            )
    before = sorted(p.name for p in roots[0].iterdir())
    with pytest.raises(ValueError, match="pinned validator refused"):
        a.backup(bad, a.digest(bad), validator, fake, roots[1])
    assert sorted(p.name for p in roots[0].iterdir()) == before


@pytest.mark.parametrize(
    "mutation",
    ["missing-key", "nested-result", "encrypted-manifest", "nested-manifest"],
)
def test_malformed_cli_inputs_emit_only_failure_result(
    package, roots, tmp_path, monkeypatch, capsys, mutation
):
    objects, scratch = roots
    fake = a.LocalFake(objects)
    validator = EnvelopeValidator()
    result = a.backup(package, a.digest(package), validator, fake, scratch)
    result_file = tmp_path / "result.json"
    if mutation == "missing-key":
        del result["key"]
        result_file.write_text(json.dumps(result))
    elif mutation == "nested-result":
        result_file.write_text("[" * 2000 + "0" + "]" * 2000)
    elif mutation == "nested-manifest":
        with zipfile.ZipFile(package) as archive:
            entries = [(row.filename, archive.read(row)) for row in archive.infolist()]
        with zipfile.ZipFile(package, "w") as archive:
            for name, raw in entries:
                archive.writestr(
                    name,
                    "[" * 2000 + "0" + "]" * 2000 if name == "manifest.json" else raw,
                )
    else:
        raw = bytearray(package.read_bytes())
        offset = 0
        while True:
            offset = raw.find(b"PK\x01\x02", offset)
            if offset < 0:
                break
            # Central directory encryption flag makes archive.read require a key.
            raw[offset + 8] |= 1
            offset += 4
        package.write_bytes(raw)
    monkeypatch.setattr(a, "Validator", lambda *_: validator)
    arguments = [
        "adapter",
        "restore" if mutation in {"missing-key", "nested-result"} else "backup",
        "--validator-source",
        "unused-unit-source",
        "--objects",
        str(objects),
        "--scratch",
        str(scratch),
    ]
    arguments += (
        ["--result", str(result_file)]
        if mutation in {"missing-key", "nested-result"}
        else ["--package", str(package), "--sha256", a.digest(package)]
    )
    monkeypatch.setattr(sys, "argv", arguments)
    assert a.main() == 1
    output = capsys.readouterr()
    assert (
        output.out
        == 'ECHOPORT_RESULT:{"success":false,"error":"offline adapter refused"}\n'
    )
    assert output.err == ""
    assert not list(scratch.iterdir())
