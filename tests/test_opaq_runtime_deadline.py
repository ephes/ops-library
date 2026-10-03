"""Real TLS streaming/cumulative regressions through the supervised worker caller."""

import http.client
import http.server
import importlib.util
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "runtime_fixture", Path(__file__).parent / "integration/opaq_viewer_linux.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
BODY = b"invented response"


@pytest.fixture
def server(tmp_path, monkeypatch):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,digitalSignature,keyEncipherment",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    page = tmp_path / "expected.html"
    page.write_bytes(BODY)
    state = {"mode": "ok", "requests": 0, "wrong_header": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["requests"] += 1
            authenticated = (
                self.headers.get("Authorization")
                == "Basic Zml4dHVyZTppbnZlbnRlZC1vbmx5"
            )
            status = 200 if authenticated else 401
            if state["mode"] == "retry" or (
                state["mode"] == "once" and state["requests"] == 1
            ):
                status = 502
            self.send_response(status)
            self.send_header(
                "Content-Length",
                str(len(BODY) + (1 if state["mode"] == "truncated" else 0)),
            )
            self.send_header(
                "Cache-Control",
                "public" if state["wrong_header"] else "private, no-store",
            )
            self.end_headers()
            try:
                if state["mode"] == "stream":
                    for byte in BODY:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.06)
                else:
                    self.wfile.write(BODY)
                    if state["mode"] == "truncated":
                        self.close_connection = True
            except (OSError, ssl.SSLError) as _error:
                pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = False
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    processes = []
    original = subprocess.Popen

    def observed(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(fixture.subprocess, "Popen", observed)
    try:
        yield httpd.server_port, page, state, processes
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert all(p.returncode is not None for p in processes)


def test_stream_reproduces_socket_timeout_gap_then_cancels_reaps(server):
    port, page, state, processes = server
    state["mode"] = "stream"
    started = time.monotonic()
    # Same complete-body read as pre-escalation probe: every byte arrives before
    # inactivity timeout, yet total read exceeds the intended response budget.
    connection = http.client.HTTPSConnection(
        "localhost", port, context=ssl.create_default_context(), timeout=0.15
    )
    connection.request("GET", "/index.html")
    assert connection.getresponse().read() == BODY
    connection.close()
    assert time.monotonic() - started > 0.7
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        fixture.supervised_probe(
            "localhost", page, authenticated=True, port=port, budget=0.3
        )
    assert time.monotonic() - started < 0.8
    assert processes[-1].returncode is not None
    assert processes[-1].poll() is not None


def test_cumulative_retries_share_one_deadline(server):
    port, page, state, processes = server
    state["mode"] = "retry"
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        fixture.supervised_probe(
            "localhost", page, authenticated=True, port=port, budget=0.5
        )
    assert state["requests"] >= 2
    assert time.monotonic() - started < 1.5
    assert processes[-1].returncode is not None


@pytest.mark.parametrize("authenticated", [False, True])
def test_timely_response_and_authentication(server, authenticated):
    port, page, state, _ = server
    if authenticated:
        state["mode"] = "once"
    fixture.supervised_probe(
        "localhost", page, authenticated=authenticated, port=port, budget=2
    )


@pytest.mark.parametrize("fault", ["header", "body", "hostname", "untrusted"])
def test_acceptance_and_tls_checks_not_weakened(server, monkeypatch, fault):
    port, page, state, _ = server
    host = "localhost"
    if fault == "header":
        state["wrong_header"] = True
    if fault == "body":
        page.write_bytes(b"wrong synthetic bytes")
    if fault == "hostname":
        host = "127.0.0.1"
    if fault == "untrusted":
        monkeypatch.delenv("SSL_CERT_FILE")
    with pytest.raises(TimeoutError):
        fixture.supervised_probe(host, page, authenticated=True, port=port, budget=0.5)


@pytest.mark.parametrize("authenticated", [False, True])
def test_incomplete_response_cannot_pass(server, authenticated):
    port, page, state, _ = server
    state["mode"] = "truncated"
    error = TimeoutError if authenticated else subprocess.CalledProcessError
    with pytest.raises(error):
        fixture.supervised_probe(
            "localhost", page, authenticated=authenticated, port=port, budget=0.5
        )
