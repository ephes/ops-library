"""Disposable filesystem + mocked service/proxy proof, never a host rollout."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = load("installer", ROOT / "roles/opaq_company_viewer_deploy/files/installer.py")
package = load("package", ROOT / "offline/opaq-company-viewer/package.py")


class Runtime:
    def __init__(self):
        self.service = dict(active=False, enabled=False)
        self.calls = []
        self.fail = None
        self.collision = False

    def identity(self):
        return os.getgid()

    def root_gid(self):
        return os.getgid()

    def proxy_gid(self, name):
        assert name == "synthetic-proxy"
        return os.getgid()

    def stop_owned(self):
        self.command("stop", engine.UNIT)

    def occupied(self, port):
        return self.collision

    def state(self):
        return dict(self.service)

    def command(self, *args):
        self.calls.append(args)
        if args[0] == "enable":
            self.service["enabled"] = True
        elif args[0] == "disable":
            self.service["enabled"] = False
        elif args[0] == "restart":
            self.service["active"] = True
        elif args[0] == "stop":
            self.service["active"] = False

    def restore_service(self, previous):
        self.calls.append(("restore",))
        self.service = dict(previous)

    def retry_verify(self, scope, content, ingress):
        self.calls.append(("verify", ingress))
        if self.fail == ingress:
            raise ValueError("synthetic verification failure")


@pytest.fixture
def setup(tmp_path):
    candidate = tmp_path / "candidate"
    source = candidate / package.CURATED
    source.mkdir(parents=True)
    for name in package.SOURCES:
        shutil.copyfile(
            ROOT / "tests/fixtures/opaq_company_viewer" / name, source / name
        )
    bundle = tmp_path / "bundle"
    package.build(
        candidate,
        json.dumps(
            dict(
                synthetic_only=True,
                company="synthetic-opaq",
                hostname="company.example.test",
                domain_assigned=False,
                port=12345,
            )
        ),
        bundle,
    )
    rules = engine.policy(ROOT / "offline/opaq-company-viewer/package.py")
    content, scope = engine.admit(bundle, rules)
    runtime = Runtime()
    installer = engine.Installer(
        runtime, tmp_path / "root", owner_uid=os.getuid(), rules=rules
    )
    for parent in (
        "/etc/traefik/dynamic",
        "/etc/systemd/system",
        "/usr/local/libexec",
        "/srv",
        "/var/lib",
        "/etc/opaq-company",
    ):
        installer.path(parent).mkdir(parents=True, exist_ok=True)
    auth = installer.path(engine.AUTH)
    auth.write_text("INVENTED AUTH METADATA FIXTURE; NOT A CREDENTIAL\n")
    auth.chmod(0o640)
    return installer, runtime, content, scope, bundle, rules


def install(setup):
    i, r, content, scope, _, _ = setup
    return i.execute("install", "synthetic-proxy", content, scope)


@pytest.mark.parametrize(
    "mutation", ["extra", "html", "code", "auth-bypass", "symlink", "draft"]
)
def test_manifest_cannot_authorize_changed_payload(setup, mutation):
    _, _, _, _, bundle, rules = setup
    member = "view/index.html"
    if mutation == "extra":
        (bundle / "personal.sqlite").write_text("invented forbidden data")
    elif mutation == "html":
        (bundle / member).write_text("unapproved financial contents")
    elif mutation == "code":
        member = "opaq-company-httpd.py"
        (bundle / member).write_text("print('not the admitted program')")
    elif mutation == "auth-bypass":
        member = engine.PROXY
        data = json.loads((bundle / member).read_text())
        data["http"]["routers"]["opaq-company-secure"]["middlewares"] = []
        (bundle / member).write_text(json.dumps(data))
    elif mutation == "symlink":
        (bundle / member).unlink()
        (bundle / member).symlink_to(bundle / "view/no-accepted.html")
    else:
        member = "fastdeploy-registration.draft.json"
        (bundle / member).write_text('{"status":"registered"}')
    if mutation not in ("extra", "symlink"):
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["content"][member] = engine.digest((bundle / member).read_bytes())
        (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        engine.admit(bundle, rules)


@pytest.mark.parametrize("bad", ["missing", "empty", "world-readable", "symlink"])
def test_auth_requirement_fails_before_owned_writes(setup, bad):
    i, r, *_ = setup
    path = i.path(engine.AUTH)
    if bad == "missing":
        path.unlink()
    elif bad == "empty":
        path.write_bytes(b"")
    elif bad == "world-readable":
        path.chmod(0o644)
    else:
        path.rename(path.with_suffix(".other"))
        path.symlink_to(path.with_suffix(".other"))
    with pytest.raises((ValueError, OSError)):
        install(setup)
    assert not any(i.capture().values())
    assert not r.calls


def test_install_verify_noop_and_scoped_first_rollback(setup):
    i, r, content, scope, *_ = setup
    unrelated = i.path("/etc/traefik/dynamic/other.yml")
    unrelated.write_bytes(b"independent route")
    auth = i.path(engine.AUTH).read_bytes()
    assert install(setup) is True
    original_record = i.path(engine.STATE + "/record.json").read_bytes()
    assert i.capture() == i.expected(content, os.getgid())
    assert r.calls.index(("verify", False)) < r.calls.index(("verify", True))
    r.calls.clear()
    assert install(setup) is False
    assert not any(call[0] in ("restart", "enable") for call in r.calls)
    assert i.path(engine.STATE + "/record.json").read_bytes() == original_record
    assert i.execute("verify", "synthetic-proxy") is False
    assert i.execute("rollback", "synthetic-proxy") is True
    assert not any(i.capture().values())
    assert unrelated.read_bytes() == b"independent route"
    assert i.path(engine.AUTH).read_bytes() == auth
    assert r.service == dict(active=False, enabled=False)
    assert not i.path("/srv/opaq-company").exists()


@pytest.mark.parametrize("ingress", [False, True])
def test_failed_verification_recovers_first_install(setup, ingress):
    i, r, *_ = setup
    r.fail = ingress
    with pytest.raises(ValueError):
        install(setup)
    assert not any(i.capture().values())
    assert r.service == dict(active=False, enabled=False)
    assert not i.path(engine.STATE + "/record.json").exists()


def test_update_failure_restores_prior_bytes_metadata_and_service(setup):
    i, r, content, scope, *_ = setup
    install(setup)
    before = i.capture()
    r.fail = True
    new_scope = dict(scope, port=12346)
    changed = dict(content)
    changed["opaq-company-viewer.service"] = package.unit(new_scope).encode()
    changed[engine.PROXY] = (
        json.dumps(package.traefik(new_scope), indent=2).encode() + b"\n"
    )
    with pytest.raises(ValueError):
        i.execute("install", "synthetic-proxy", changed, new_scope)
    assert i.capture() == before
    assert r.service == dict(active=True, enabled=True)
    assert i.read_record()["scope"] == scope


@pytest.mark.parametrize("collision", ["file", "directory", "port", "symlink"])
def test_unowned_collisions_are_not_adopted(setup, collision):
    i, r, *_ = setup
    if collision == "port":
        r.collision = True
    elif collision == "directory":
        i.path("/srv/opaq-company").mkdir()
    elif collision == "symlink":
        i.path("/srv/opaq-company").symlink_to(i.path("/srv"))
    else:
        i.path(engine.TARGETS[engine.PROXY][0]).write_text("independent file")
    before = i.capture()
    with pytest.raises(ValueError):
        install(setup)
    assert i.capture() == before
    assert not r.calls


def test_interrupted_partial_write_requires_explicit_recovery(setup):
    i, r, content, scope, *_ = setup
    i.path(engine.STATE).mkdir(mode=0o700)
    desired = i.expected(content, os.getgid())
    record = dict(
        format="opaq.synthetic.installer.v1",
        phase="prepared",
        previous=i.capture(),
        desired=desired,
        scope=scope,
        previous_scope=None,
        service=r.state(),
    )
    i.journal(record)
    i.path("/srv/opaq-company/view").mkdir(parents=True)
    member = "view/index.html"
    i.atomic(i.path(engine.TARGETS[member][0]), content[member], 0o640)
    with pytest.raises(ValueError, match="interrupted"):
        install(setup)
    i.execute("rollback", "synthetic-proxy")
    assert not any(i.capture().values())


def test_rollback_refuses_foreign_edit_without_touching_others(setup):
    i, r, *_ = setup
    install(setup)
    path = i.path(engine.TARGETS[engine.PROXY][0])
    path.write_text("external edit")
    before = i.capture()
    calls = list(r.calls)
    with pytest.raises(ValueError, match="externally"):
        i.execute("rollback", "synthetic-proxy")
    assert i.capture() == before
    assert r.calls == calls


def test_root_defaults_and_no_auth_content_copy(setup):
    assert engine.Installer(Runtime()).root == Path("/")
    assert engine.Installer(Runtime()).owner_uid == 0
    i, _, *_ = setup
    install(setup)
    record = i.path(engine.STATE + "/record.json")
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert "INVENTED AUTH" not in record.read_text()
    assert engine.AUTH not in engine.TARGETS


@pytest.mark.parametrize(
    "ingress,status,cache,body,valid",
    [
        (True, 401, "private, no-store", b"Unauthorized", True),
        (True, 401, None, b"Unauthorized", False),
        (True, 200, "private, no-store", b"visible without credentials", False),
        (False, 200, "private, no-store", b"expected", True),
        (False, 200, "public", b"expected", False),
        (False, 200, "private, no-store", b"wrong", False),
    ],
)
def test_probe_rejects_unauthenticated_content_and_missing_cache_policy(
    monkeypatch, ingress, status, cache, body, valid
):
    calls = []

    class Response:
        def read(self, bound):
            assert bound == 2 * 1024 * 1024 + 1
            return body

        def getheader(self, key):
            assert key == "Cache-Control"
            return cache

    Response.status = status

    class Connection:
        def __init__(self, *args, **kwargs):
            if ingress:
                assert kwargs["context"].check_hostname is True
                assert args == ("company.example.test",)
            else:
                assert args == ("127.0.0.1", 12345)

        def request(self, method, path):
            calls.append((method, path))  # No credentials or request headers.

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        engine.http.client,
        "HTTPSConnection" if ingress else "HTTPConnection",
        Connection,
    )
    content = {
        "view/" + name: b"expected"
        for name in ("index.html", "retained-last-good.html", "no-accepted.html")
    }
    runtime = engine.Runtime()
    scope = dict(hostname="company.example.test", port=12345)
    if valid:
        runtime.verify(scope, content, ingress)
        assert len(calls) == 3
    else:
        with pytest.raises(ValueError):
            runtime.verify(scope, content, ingress)


def test_service_state_handles_missing_unit_without_inventing_active_state(monkeypatch):
    class Result:
        stdout = "not-found\n"

    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: Result())
    assert engine.Runtime().state() == dict(active=False, enabled=False)


def test_service_dying_after_proxy_check_is_not_a_successful_install(setup):
    i, r, *_ = setup
    verify = r.retry_verify

    def die(scope, content, ingress):
        verify(scope, content, ingress)
        if ingress:
            r.service["active"] = False

    r.retry_verify = die
    with pytest.raises(ValueError, match="remain active"):
        install(setup)
    assert not any(i.capture().values())
    assert r.service == dict(active=False, enabled=False)


def test_process_interruption_before_replace_recovers_reserved_pending_file(setup):
    i, r, content, scope, *_ = setup
    i.path(engine.STATE).mkdir(mode=0o700)
    record = dict(
        format="opaq.synthetic.installer.v1",
        phase="prepared",
        previous=i.capture(),
        desired=i.expected(content, os.getgid()),
        scope=scope,
        previous_scope=None,
        service=r.state(),
    )
    i.journal(record)
    i.path("/srv/opaq-company/view").mkdir(parents=True)
    path = i.path(engine.TARGETS["view/index.html"][0])
    pid = os.fork()
    if pid == 0:
        # Abrupt process exit bypasses finally, reproducing interruption.
        engine.os.replace = lambda *args: os._exit(91)
        i.atomic(path, content["view/index.html"], 0o640)
        os._exit(92)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 91
    pending = path.with_name("." + path.name + ".opaq-pending")
    assert pending.exists()
    i.execute("rollback", "synthetic-proxy")
    assert not pending.exists()
    assert not i.path("/srv/opaq-company").exists()


def test_foreign_pending_file_is_not_removed(setup):
    i, _, *_ = setup
    install(setup)
    path = i.path(engine.TARGETS["view/index.html"][0])
    pending = path.with_name("." + path.name + ".opaq-pending")
    pending.write_text("foreign contents")
    pending.chmod(0o600)
    with pytest.raises(ValueError, match="foreign pending"):
        i.execute("rollback", "synthetic-proxy")
    assert pending.read_text() == "foreign contents"


def test_canonical_boolean_config_rejects_integer_alias_even_with_new_manifest(setup):
    _, _, _, _, bundle, rules = setup
    config = json.loads((bundle / engine.PROXY).read_text())
    config["http"]["middlewares"]["opaq-company-auth"]["basicAuth"]["removeHeader"] = 1
    (bundle / engine.PROXY).write_text(json.dumps(config, indent=2) + "\n")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["content"][engine.PROXY] = engine.digest(
        (bundle / engine.PROXY).read_bytes()
    )
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="exact hardened"):
        engine.admit(bundle, rules)


def test_corrupt_record_cannot_authorize_non_synthetic_pages(setup):
    i, _, *_ = setup
    install(setup)
    record = i.read_record()
    import base64

    record["desired"]["view/index.html"]["body"] = base64.b64encode(
        b"non-synthetic contents"
    ).decode()
    i.journal(record)
    before = i.capture()
    with pytest.raises(ValueError, match="recorded synthetic"):
        i.execute("verify", "synthetic-proxy")
    assert i.capture() == before


@pytest.mark.parametrize("action", ["install", "verify"])
def test_real_ansible_orchestration_reports_no_change_for_mocked_unchanged_run(
    tmp_path, action
):
    import subprocess
    import sys

    play = tmp_path / "play.yml"
    play.write_text(
        f"""---
- hosts: localhost
  connection: local
  gather_facts: false
  roles:
    - role: {ROOT / 'roles/opaq_company_viewer_deploy'}
      opaq_viewer_action: {action}
      opaq_viewer_bundle: /synthetic-bundle
      opaq_viewer_proxy_group: synthetic-proxy
"""
    )
    env = dict(
        os.environ,
        ANSIBLE_LOCAL_TEMP=str(tmp_path / "ansible-tmp"),
        ANSIBLE_LOG_PATH=str(tmp_path / "ansible.log"),
        ANSIBLE_NOCOLOR="1",
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/opaq_installer_mock_play.py"), str(play)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout


def test_actual_admission_cli_is_unprivileged_and_does_not_touch_controller_state(
    setup,
):
    import subprocess
    import sys

    _, _, _, _, bundle, _ = setup
    before = {
        str(p.relative_to(bundle)): p.read_bytes()
        for p in bundle.rglob("*")
        if p.is_file()
    }
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "roles/opaq_company_viewer_deploy/files/installer.py"),
            "--action",
            "admit",
            "--policy",
            str(ROOT / "offline/opaq-company-viewer/package.py"),
            "--bundle",
            str(bundle),
            "--proxy-group",
            "synthetic-proxy",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == dict(changed=False, action="admit")
    assert before == {
        str(p.relative_to(bundle)): p.read_bytes()
        for p in bundle.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("action", ["validate", "install", "verify", "rollback"])
def test_target_cli_passes_loaded_policy_to_engine(setup, monkeypatch, capsys, action):
    _, _, _, _, bundle, _ = setup
    monkeypatch.setattr(engine.os, "geteuid", lambda: 0)

    class Factory:
        def __init__(self, runtime, *, rules):
            assert rules.CANDIDATE == package.CANDIDATE
            assert rules.unique([("key", 1)]) == {"key": 1}

        def execute(self, actual, group, content, scope):
            assert actual == action and group == "synthetic-proxy"
            assert (content is not None) == (action in ("validate", "install"))
            return False

    monkeypatch.setattr(engine, "Installer", Factory)
    engine.main(
        [
            "--action",
            action,
            "--policy",
            str(ROOT / "offline/opaq-company-viewer/package.py"),
            "--bundle",
            str(bundle),
            "--proxy-group",
            "synthetic-proxy",
        ]
    )
    assert json.loads(capsys.readouterr().out) == dict(changed=False, action=action)
