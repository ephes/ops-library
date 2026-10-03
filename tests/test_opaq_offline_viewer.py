"""Synthetic-only package admission and loopback presentation boundary checks."""

from functools import partial
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import stat
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "offline/opaq-company-viewer" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = load("package")
viewer = load("viewer")


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "candidate"
    directory = root / package.CURATED
    directory.mkdir(parents=True)
    for name in package.SOURCES:
        shutil.copyfile(
            ROOT / "tests/fixtures/opaq_company_viewer" / name, directory / name
        )
    # Unrelated company source or personal data is never copied into the viewer.
    (root / "personal.sqlite").write_bytes(b"SYNTHETIC DO NOT COPY")
    (directory / "source.sqlite").write_bytes(b"SYNTHETIC DO NOT COPY")
    return root


@pytest.fixture
def config():
    return dict(
        synthetic_only=True,
        company="synthetic-opaq",
        hostname="opaq.home.wersdörfer.de",
        domain_assigned=False,
        port=10063,
    )


def test_exact_curated_admission_and_package_provenance(candidate, config, tmp_path):
    output = tmp_path / "bundle"
    result = package.build(candidate, json.dumps(config), output)
    assert result["hostname"] == "opaq.home.xn--wersdrfer-47a.de"
    assert (
        result["deployment_authorized"] is False and result["domain_assigned"] is False
    )
    assert sorted(p.name for p in (output / "view").iterdir()) == [
        "index.html",
        "no-accepted.html",
        "retained-last-good.html",
    ]
    for name, digest in result["content"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert (output / "view/index.html").read_bytes() == (
        candidate / package.CURATED / "accepted.html"
    ).read_bytes()
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(p.stat().st_mode) == 0o600
        for p in output.rglob("*")
        if p.is_file()
    )
    draft = json.loads((output / "fastdeploy-registration.draft.json").read_text())
    assert draft["status"] == "disabled-draft-not-registered"
    assert draft["vars"]["fd_sync_services"] is False
    assert not any("sqlite" in name or "htpasswd" in name for name in result["content"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("company", "synthetic-personal"),
        ("synthetic_only", False),
        ("domain_assigned", True),
        ("port", "CHANGEME"),
        ("port", True),
        ("port", 443),
        ("port", 65536),
        ("hostname", "https://opaq.example.test"),
        ("hostname", "a`) || Host(`evil.test"),
        ("hostname", "opaq.example.test\n"),
        ("hostname", "-bad.example.test"),
    ],
)
def test_invalid_scope_and_injected_configuration_never_publish(
    candidate, config, tmp_path, field, value
):
    config[field] = value
    output = tmp_path / "bundle"
    with pytest.raises(ValueError):
        package.build(candidate, json.dumps(config), output)
    assert not output.exists()


def test_unknown_and_duplicate_configuration_rejected(config):
    with pytest.raises(ValueError):
        package.configuration(json.dumps(dict(config, unknown="SYNTHETIC")))
    with pytest.raises(ValueError, match="duplicate"):
        package.configuration(
            '{"company":"synthetic-opaq","company":"synthetic-personal"}'
        )


@pytest.mark.parametrize("mutation", ["missing", "modified", "symlink"])
def test_wrong_or_missing_content_refused_before_output(
    candidate, config, tmp_path, mutation
):
    source = candidate / package.CURATED / "accepted.html"
    if mutation == "missing":
        source.unlink()
    elif mutation == "modified":
        source.write_text("<html>SYNTHETIC other-company snapshot</html>")
    else:
        source.unlink()
        source.symlink_to(candidate / "personal.sqlite")
    with pytest.raises((ValueError, OSError)):
        package.build(candidate, json.dumps(config), tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_existing_output_and_source_preserved(candidate, config, tmp_path):
    output = tmp_path / "bundle"
    package.build(candidate, json.dumps(config), output)
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        package.build(candidate, json.dumps(config), output)
    assert (output / "manifest.json").read_bytes() == before


def test_all_content_routes_use_auth_and_no_store(config):
    http = package.traefik(config)["http"]
    for router in http["routers"].values():
        assert "ClientIP" not in router["rule"]
        if router["service"] != "noop@internal":
            assert "opaq-company-auth" in router["middlewares"]
            assert "opaq-company-headers" in router["middlewares"]
            # Headers must wrap BasicAuth, including its early 401 responses.
            assert router["middlewares"].index("opaq-company-headers") < router[
                "middlewares"
            ].index("opaq-company-auth")
            assert router["tls"] == {}
    assert http["middlewares"]["opaq-company-auth"]["basicAuth"] == {
        "usersFile": "/etc/opaq-company/viewer.htpasswd",
        "removeHeader": True,
    }
    assert (
        http["middlewares"]["opaq-company-headers"]["headers"]["customResponseHeaders"][
            "Cache-Control"
        ]
        == "private, no-store"
    )
    assert http["services"]["opaq-company"]["loadBalancer"]["servers"] == [
        {"url": "http://127.0.0.1:10063"}
    ]
    unit = package.unit(config)
    assert "ProtectHome=true" in unit and "ProtectSystem=strict" in unit
    assert "ReadWritePaths" not in unit and "EnvironmentFile" not in unit


def test_loopback_exact_routes_and_private_headers(candidate, config, tmp_path, capsys):
    output = tmp_path / "bundle"
    package.build(candidate, json.dumps(config), output)
    root = output / "view"
    (root / "source.sqlite").write_bytes(b"SYNTHETIC MUST NOT SERVE")
    with ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(viewer.Viewer, root=root)
    ) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            client = HTTPConnection(*server.server_address)
            for method, path, status in [
                ("GET", "/", 200),
                ("HEAD", "/retained-last-good.html", 200),
                ("GET", "/no-accepted.html", 200),
                ("GET", "/source.sqlite", 404),
                ("GET", "/manifest.json", 404),
                ("GET", "/.env", 404),
                ("GET", "/../manifest.json", 404),
                ("GET", "/%2e%2e/manifest.json", 404),
                ("POST", "/", 501),
            ]:
                client.request(
                    method,
                    path,
                    headers={"Authorization": "SYNTHETIC HEADER DO NOT LOG"},
                )
                response = client.getresponse()
                raw = response.read()
                assert response.status == status
                assert response.getheader("Cache-Control") == "private, no-store"
                assert b"MUST NOT SERVE" not in raw
            # Even an allowlisted path cannot point at arbitrary state.
            (root / "index.html").unlink()
            (root / "index.html").symlink_to(root / "source.sqlite")
            client.request("GET", "/")
            response = client.getresponse()
            assert response.status == 404
            response.read()
            client.close()
        finally:
            server.shutdown()
            thread.join()
    assert capsys.readouterr().out == ""
