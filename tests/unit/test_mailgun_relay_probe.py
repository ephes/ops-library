"""Run the rendered relay probe and metrics templates against local stubs."""

import base64
import json
import os
import shlex
import shutil
import socket
import stat
import subprocess
import threading
import time
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jinja2
import pytest


ROOT = Path(__file__).resolve().parents[2]
PROBE_TEMPLATE = ROOT / "roles/mail_monitoring/templates/mailgun-relay-probe.sh.j2"
METRICS_TEMPLATE = ROOT / "roles/metrics_endpoint/templates/mail-metrics.sh.j2"
TOKEN = "0123456789abcdef" * 4


def render(template, **variables):
    # Ansible renders templates with trim_blocks and keeps the final newline.
    env = jinja2.Environment(
        undefined=jinja2.StrictUndefined, trim_blocks=True, keep_trailing_newline=True
    )
    env.filters["quote"] = lambda value: shlex.quote(str(value))
    return env.from_string(template.read_text()).render(**variables)


def parse_form(content_type, body):
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        fields.setdefault(name, []).append(part.get_payload(decode=True).decode())
    return fields


class Relay:
    """Records POSTs and answers with a fixed status."""

    def __init__(self, status=200):
        self.status = status
        self.requests = []
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                relay.requests.append(
                    {
                        "path": self.path,
                        "auth": self.headers.get("Authorization", ""),
                        "form": parse_form(self.headers["Content-Type"], body),
                    }
                )
                body = json.dumps({"id": "<probe@test>", "message": "ok"}).encode()
                self.send_response(relay.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def relay():
    server = Relay()
    yield server
    server.close()


@pytest.fixture
def probe(tmp_path):
    script = tmp_path / "mailgun-relay-probe"
    script.write_text(
        render(
            PROBE_TEMPLATE,
            mail_monitoring_relay_probe_service_name="mailgun-relay-probe",
            mail_monitoring_relay_probe_url="https://relay.invalid",
            mail_monitoring_relay_probe_domain="mg.example.org",
            mail_monitoring_relay_probe_from="probe@example.org",
            mail_monitoring_relay_probe_to="monitor@example.org",
            mail_monitoring_relay_probe_subject_prefix="[nyxmon-relay]",
            mail_monitoring_relay_probe_timeout=5,
            mail_monitoring_relay_probe_retries=2,
        )
    )
    script.chmod(0o755)
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN)
    token_file.chmod(0o600)

    # A curl wrapper that records its argv, to prove the token stays off it.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "curl-argv"
    wrapper = bin_dir / "curl"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" >> {shlex.quote(str(argv_log))}\n'
        f'exec {shlex.quote(shutil.which("curl"))} "$@"\n'
    )
    wrapper.chmod(0o755)

    def run(*args, env=None, token=token_file):
        environment = dict(os.environ)
        environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
        environment.update(env or {})
        token_args = ["--token-file", str(token)] if token else []
        return subprocess.run(
            [str(script), *token_args, *args],
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
        )

    run.argv_log = argv_log
    run.state = tmp_path / "state"
    return run


def read_state(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def test_successful_probe_posts_mailgun_form_and_records_state(probe, relay):
    result = probe("--url", relay.url, "--state-file", str(probe.state))

    assert result.returncode == 0, result.stderr
    [request] = relay.requests
    assert request["path"] == "/v3/mg.example.org/messages"
    assert request["auth"] == "Basic " + base64.b64encode(f"api:{TOKEN}".encode()).decode()
    form = request["form"]
    assert form["from"] == ["probe@example.org"]
    assert form["to"] == ["monitor@example.org"]
    [subject] = form["subject"]
    assert subject.startswith("[nyxmon-relay] ")
    nonce = subject.split(" ", 1)[1]
    assert nonce in form["text"][0]

    state = read_state(probe.state)
    assert state["last_status"] == "200"
    assert state["curl_exit"] == "0"
    assert abs(int(state["last_run"]) - time.time()) < 30
    assert stat.S_IMODE(probe.state.stat().st_mode) == 0o644

    assert "status=200" in result.stdout
    assert TOKEN not in result.stdout + result.stderr
    assert TOKEN not in probe.argv_log.read_text()


def test_policy_rejection_exits_nonzero_and_records_status(probe):
    rejecting = Relay(status=403)
    try:
        result = probe("--url", rejecting.url, "--state-file", str(probe.state))
    finally:
        rejecting.close()

    assert result.returncode == 1
    assert len(rejecting.requests) == 1
    assert read_state(probe.state)["last_status"] == "403"
    assert "status=403" in result.stdout


def test_unreachable_relay_records_status_zero(probe):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    result = probe(
        "--url", f"http://127.0.0.1:{port}", "--retries", "0", "--state-file", str(probe.state)
    )

    assert result.returncode == 1
    state = read_state(probe.state)
    assert state["last_status"] == "0"
    assert state["curl_exit"] == "7"


def test_manual_run_leaves_state_alone_and_passes_curl_arguments(probe, relay):
    result = probe(
        "--url",
        relay.url + "/",
        "--retries",
        "0",
        "--subject-suffix",
        "Grüße",
        "--",
        "--form-string",
        "html=<p>probe</p>",
    )

    assert result.returncode == 0, result.stderr
    assert not probe.state.exists()
    [request] = relay.requests
    assert request["path"] == "/v3/mg.example.org/messages"
    assert request["form"]["subject"][0].endswith(" Grüße")
    assert request["form"]["html"] == ["<p>probe</p>"]
    assert "--retry" not in probe.argv_log.read_text().splitlines()


@pytest.mark.parametrize("content", ["", 'abc"\nuser = "x', "token with space"])
def test_unusable_token_is_refused_before_any_request(probe, relay, tmp_path, content):
    token = tmp_path / "bad-token"
    token.write_text(content)

    result = probe("--url", relay.url, "--state-file", str(probe.state), token=token)

    assert result.returncode == 2
    assert relay.requests == []
    assert not probe.state.exists()
    assert not probe.argv_log.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--url", "ftp://relay.invalid"],
        ["--url"],
        ["--retries", "-1"],
        ["--bogus"],
    ],
)
def test_invalid_arguments_exit_with_usage_error(probe, relay, args):
    result = probe(*args)

    assert result.returncode == 2
    assert relay.requests == []


def test_missing_token_file_is_a_usage_error(probe, relay, tmp_path):
    result = probe("--url", relay.url, token=tmp_path / "absent")

    assert result.returncode == 2
    assert "token file not readable" in result.stderr


def render_metrics(tmp_path, probe_states):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "df").write_text("#!/bin/sh\nprintf 'Use%%\\n 42%%\\n'\n")
    (bin_dir / "systemctl").write_text("#!/bin/sh\necho active\n")
    for stub in ("df", "systemctl"):
        (bin_dir / stub).chmod(0o755)
    script = tmp_path / "mail-metrics.sh"
    script.write_text(
        render(
            METRICS_TEMPLATE,
            metrics_endpoint_queue_path=str(tmp_path / "queue"),
            metrics_endpoint_vmail_path=str(tmp_path),
            metrics_endpoint_services=["postfix"],
            metrics_endpoint_probe_states=probe_states,
        )
    )
    script.chmod(0o755)

    def run():
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    return script, run


def test_metrics_without_probe_states_has_no_probe_code(tmp_path):
    script, run = render_metrics(tmp_path, [])

    assert "probe_section" not in script.read_text()
    assert set(run()) == {"hostname", "timestamp", "mail", "disk", "services"}


def test_metrics_export_probe_state_with_age(tmp_path):
    state = tmp_path / "state"
    _, run = render_metrics(tmp_path, [{"name": "mailgun_relay", "path": str(state)}])

    assert "mailgun_relay" not in run()

    state.write_text(f"last_status=200\nlast_run={int(time.time()) - 120}\ncurl_exit=0\n")
    section = run()["mailgun_relay"]
    assert section["last_status"] == 200
    assert 115 <= section["age_seconds"] <= 150

    state.write_text("last_status=000\nlast_run=1\ncurl_exit=7\n")
    assert run()["mailgun_relay"]["last_status"] == 0


@pytest.mark.parametrize(
    "content",
    [
        "last_status=200\n",
        "last_status=ok\nlast_run=1\n",
        'last_status=200\nlast_run=1"}\n',
    ],
)
def test_metrics_omit_malformed_probe_state(tmp_path, content):
    state = tmp_path / "state"
    state.write_text(content)
    _, run = render_metrics(tmp_path, [{"name": "mailgun_relay", "path": str(state)}])

    assert "mailgun_relay" not in run()
