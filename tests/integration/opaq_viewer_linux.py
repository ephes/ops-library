"""Real lifecycle fixture: only explicitly marked, network-none disposable Linux."""

import base64
import hashlib
import http.client
import json
import os
import shutil
import ssl
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from urllib.parse import urlsplit


def command(*args, check=True, **kwargs):
    return subprocess.run(args, check=check, capture_output=True, text=True, **kwargs)


def supervised_probe(host, expected_page, *, authenticated, port=443, budget=10):
    """Cancel/reap one descendant-free worker for the whole response/retry budget."""
    try:
        subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--https-probe",
                host,
                str(expected_page),
                "auth" if authenticated else "anon",
                str(port),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=budget,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            "Whole HTTPS probe budget expired; worker killed/reaped"
        ) from error


def probe_worker(host, expected_page, authenticated, port):
    """Single process, no descendants; parent owns total cancellation."""
    if not __debug__:
        raise SystemExit("Assertions must remain enabled")
    expected = Path(expected_page).read_bytes()
    while True:
        connection = http.client.HTTPSConnection(
            host, port, context=ssl.create_default_context(), timeout=5
        )
        try:
            headers = (
                {
                    "Authorization": "Basic "
                    + base64.b64encode(b"fixture:invented-only").decode()
                }
                if authenticated
                else {}
            )
            connection.request("GET", "/index.html", headers=headers)
            response = connection.getresponse()
            body = response.read()
            assert response.status == (200 if authenticated else 401)
            assert response.getheader("Cache-Control") == "private, no-store"
            if authenticated:
                assert body == expected
            return
        except (AssertionError, OSError, http.client.HTTPException) as _error:
            if not authenticated:
                raise
            time.sleep(0.1)
        finally:
            connection.close()


def main():
    if not __debug__:
        raise SystemExit("Assertions must remain enabled")
    if (
        os.environ.get("OPAQ_DISPOSABLE_TEST") != "1"
        or not Path("/.dockerenv").exists()
    ):
        raise SystemExit("Disposable marked container required")
    if os.uname().machine != "aarch64" or os.getuid() != 0:
        raise SystemExit("Root ARM64 disposable fixture required")
    archive = Path("/fixture/traefik.tar.gz")
    if (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        != "c8d942f80be27c76a55ff483927b36e3be5b0b88299a177ec0882a1fa1c24374"  # pragma: allowlist secret -- public release checksum
    ):
        raise SystemExit("Pinned archive mismatch")
    with tarfile.open(archive) as stream:
        member = stream.getmember("traefik")
        if not member.isfile():
            raise SystemExit("Regular Traefik binary required")
        Path("/usr/local/bin/traefik").write_bytes(stream.extractfile(member).read())
    Path("/usr/local/bin/traefik").chmod(0o755)
    bundle = Path("/fixture/bundle")
    manifest = json.loads((bundle / "manifest.json").read_text())
    host = manifest["hostname"]
    ingress = json.loads((bundle / "opaq-company.traefik.yml").read_text())
    initial_port = urlsplit(
        ingress["http"]["services"]["opaq-company"]["loadBalancer"]["servers"][0]["url"]
    ).port
    if initial_port == 10065:
        raise SystemExit("Fixture update must change port")
    with Path("/etc/hosts").open("a") as file:
        file.write(f"\n127.0.0.1 {host}\n")
    for directory in (
        "/etc/traefik/dynamic",
        "/etc/opaq-company",
        "/usr/local/libexec",
        "/srv",
        "/run/opaq-fixture",
    ):
        Path(directory).mkdir(parents=True, exist_ok=True)
    command("groupadd", "--system", "synthetic-proxy")
    auth = Path("/etc/opaq-company/viewer.htpasswd")
    auth.write_text(
        "fixture:"
        + command("openssl", "passwd", "-apr1", "invented-only").stdout.strip()
        + "\n"
    )
    shutil.chown(auth, group="synthetic-proxy")
    auth.chmod(0o640)
    auth_before = (
        auth.read_bytes(),
        auth.stat().st_uid,
        auth.stat().st_gid,
        auth.stat().st_mode,
    )
    tls = Path("/run/opaq-fixture")
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=Disposable Fixture CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout",
        str(tls / "ca.key"),
        "-out",
        str(tls / "ca.crt"),
    )
    command(
        "openssl",
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        f"/CN={host}",
        "-keyout",
        str(tls / "leaf.key"),
        "-out",
        str(tls / "leaf.csr"),
    )
    (tls / "extensions").write_text(
        f"subjectAltName=DNS:{host}\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
    )
    command(
        "openssl",
        "x509",
        "-req",
        "-in",
        str(tls / "leaf.csr"),
        "-CA",
        str(tls / "ca.crt"),
        "-CAkey",
        str(tls / "ca.key"),
        "-CAcreateserial",
        "-days",
        "1",
        "-extfile",
        str(tls / "extensions"),
        "-out",
        str(tls / "leaf.crt"),
    )
    os.environ["SSL_CERT_FILE"] = str(tls / "ca.crt")
    preserved = Path("/etc/traefik/dynamic/fixture-tls.yml")
    preserved.write_text(
        json.dumps(
            {
                "tls": {
                    "certificates": [
                        {
                            "certFile": str(tls / "leaf.crt"),
                            "keyFile": str(tls / "leaf.key"),
                        }
                    ]
                }
            }
        )
    )
    previous_tls = preserved.read_bytes()
    Path("/run/opaq-fixture/traefik.json").write_text(
        json.dumps(
            {
                "global": {"checkNewVersion": False, "sendAnonymousUsage": False},
                "entryPoints": {
                    "web": {"address": "127.0.0.1:80"},
                    "web-secure": {"address": "127.0.0.1:443"},
                },
                "providers": {
                    "file": {"directory": "/etc/traefik/dynamic", "watch": True}
                },
            }
        )
    )
    with Path("/run/opaq-fixture/proxy.log").open("w") as proxy_log:
        proxy = subprocess.Popen(
            ["/usr/local/bin/traefik", "--configFile=/run/opaq-fixture/traefik.json"],
            stdout=proxy_log,
            stderr=subprocess.STDOUT,
        )
        results = []
        try:
            for _ in range(30):
                if command(
                    "systemctl", "is-system-running", check=False
                ).stdout.strip() in ("running", "degraded"):
                    break
                time.sleep(0.2)

            def play(action, supplied=bundle, success=True):
                payload = [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "roles": [
                            {
                                "role": "/fixture/roles/opaq_company_viewer_deploy",
                                "opaq_viewer_action": action,
                                "opaq_viewer_bundle": str(supplied),
                                "opaq_viewer_proxy_group": "synthetic-proxy",
                            }
                        ],
                    }
                ]
                Path("/run/opaq-fixture/play.json").write_text(json.dumps(payload))
                result = command(
                    "ansible-playbook",
                    "-i",
                    "localhost,",
                    "/run/opaq-fixture/play.json",
                    check=False,
                )
                Path("/run/opaq-fixture/last-play.log").write_text(
                    result.stdout + result.stderr
                )
                if (result.returncode == 0) != success:
                    raise RuntimeError(
                        "Role action failed expectation: "
                        + action
                        + "\n"
                        + result.stdout[-6000:]
                    )
                results.append({"action": action, "expected_success": success})

            # Required auth refuses before dedicated identity creation.
            auth.chmod(0o600)
            play("install", success=False)
            assert (
                command(
                    "getent", "passwd", "opaq-company-viewer", check=False
                ).returncode
                != 0
            )
            auth.chmod(0o640)
            play("install")
            record = Path("/var/lib/opaq-company-viewer-installer/record.json")
            before = record.read_bytes()
            pid = command(
                "systemctl",
                "show",
                "opaq-company-viewer",
                "--property=MainPID",
                "--value",
            ).stdout
            play("install")
            assert record.read_bytes() == before
            assert (
                command(
                    "systemctl",
                    "show",
                    "opaq-company-viewer",
                    "--property=MainPID",
                    "--value",
                ).stdout
                == pid
            )
            play("verify", Path("/not-required"))

            def check_ingress():
                for authenticated in (False, True):
                    supervised_probe(
                        host, bundle / "view/index.html", authenticated=authenticated
                    )

            check_ingress()
            bad = Path("/run/opaq-fixture/bad")
            shutil.copytree(bundle, bad)
            (bad / "view/index.html").write_text("invented tamper")
            play("install", bad, success=False)
            assert record.read_bytes() == before
            play("verify", Path("/not-required"))
            # First-install rollback removes only owned artifacts.
            play("rollback", Path("/not-required"))
            assert not record.exists() and not Path("/srv/opaq-company").exists()
            assert not Path("/etc/traefik/dynamic/opaq-company.yml").exists()
            assert preserved.read_bytes() == previous_tls
            assert (
                auth.read_bytes(),
                auth.stat().st_uid,
                auth.stat().st_gid,
                auth.stat().st_mode,
            ) == auth_before
            play("install")
            # Independently admitted update changes only explicit loopback port.
            import runpy

            package = runpy.run_path("/fixture/offline/opaq-company-viewer/package.py")
            candidate = Path("/run/opaq-fixture/candidate")
            source = candidate / package["CURATED"]
            source.mkdir(parents=True)
            for name in package["SOURCES"]:
                shutil.copyfile(
                    "/fixture/tests/fixtures/opaq_company_viewer/" + name, source / name
                )
            updated = Path("/run/opaq-fixture/updated")
            package["build"](
                candidate,
                json.dumps(
                    {
                        "synthetic_only": True,
                        "company": "synthetic-opaq",
                        "hostname": host,
                        "domain_assigned": False,
                        "port": 10065,
                    }
                ),
                updated,
            )
            play("install", updated)
            assert record.read_bytes() != before
            play("verify", Path("/not-required"))
            check_ingress()
            owned_page = Path("/srv/opaq-company/view/index.html")
            admitted_page = owned_page.read_bytes()
            owned_page.write_bytes(b"invented external modification")
            play("rollback", Path("/not-required"), success=False)
            assert owned_page.read_bytes() == b"invented external modification"
            owned_page.write_bytes(admitted_page)
            play("rollback", Path("/not-required"))
            assert json.loads(record.read_text())["scope"]["port"] == initial_port
            play("verify", Path("/not-required"))
            check_ingress()
            assert preserved.read_bytes() == previous_tls
            assert (
                auth.read_bytes(),
                auth.stat().st_uid,
                auth.stat().st_gid,
                auth.stat().st_mode,
            ) == auth_before
            assert not list(Path("/tmp").glob("opaq-viewer-*"))
            print(
                json.dumps(
                    {
                        "cases": results,
                        "no_op_pid_and_record_unchanged": True,
                        "authenticated_and_401_no_store": True,
                        "first_install_removal_and_update_restore": True,
                        "unrelated_tls_auth_preserved": True,
                        "transport_cleanup": True,
                    }
                )
            )
        finally:
            proxy.terminate()
            proxy.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--https-probe":
        probe_worker(sys.argv[2], sys.argv[3], sys.argv[4] == "auth", int(sys.argv[5]))
    else:
        main()
