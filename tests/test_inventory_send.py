import ast
import json
import os
from pathlib import Path
import subprocess
import ssl
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from uuid import uuid4

FILES = Path(__file__).resolve().parents[1] / "roles/software_estate/files"
sys.path.insert(0, str(FILES))
try:
    import emit
    import outbox
    import send
finally:
    sys.path.pop(0)


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.spool = self.root / "outbox"
        self.spool.mkdir(mode=0o700)
        self.credential = self.root / "writer"
        self.credential.write_text("synthetic-writer.secret\n")
        self.credential.chmod(0o600)
        self.requests = []
        self.reply_status = 200
        self.reply = None
        self.content_type = "application/json"
        self.retry_after = "3601"
        self.delay_reply = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                report = json.loads(body)
                owner.requests.append((report, dict(self.headers)))
                if owner.delay_reply:
                    time.sleep(2)
                    return
                reply = owner.reply
                if reply is None:
                    reply = json.dumps(
                        {
                            "status": "stored",
                            "snapshot_id": report["snapshot_id"],
                            "duplicate": False,
                        }
                    ).encode()
                self.send_response(owner.reply_status)
                self.send_header("Content-Type", owner.content_type)
                self.send_header("Retry-After", owner.retry_after)
                self.send_header("Location", "/redirect-must-not-be-followed")
                self.end_headers()
                self.wfile.write(reply)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/inventory"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)
        self.assertFalse(self.worker.is_alive())

    def report(self):
        data = {"snapshot_id": str(uuid4()), "host": "test", "example": "Größe"}
        return emit.write_report(data, self.spool)

    def run_sender(self, *args):
        return subprocess.run(
            [
                sys.executable,
                str(FILES / "send.py"),
                "--spool",
                str(self.spool),
                "--endpoint",
                self.endpoint,
                "--credential-file",
                str(self.credential),
                "--allow-loopback-http",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_actual_cli_sends_and_removes_only_acknowledged_reports(self):
        path = self.report()
        data = json.loads(path.read_text())
        with patch.dict(
            os.environ,
            {"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"},
        ):
            result = self.run_sender()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(path.exists())
        self.assertEqual(self.requests[0][0], data)
        self.assertEqual(
            self.requests[0][1]["Authorization"], "Bearer synthetic-writer.secret"
        )
        self.assertNotIn("synthetic-writer", result.stdout + result.stderr)

    def test_unconfirmed_http_and_invalid_ack_never_delete_or_blindly_retry(self):
        cases = [
            (302, None),
            (401, None),
            (403, None),
            (409, None),
            (201, None),
            (200, b"private peer diagnostic"),
            (200, b'{"status":"stored","snapshot_id":"wrong","duplicate":false}'),
            (200, b"x" * (send.MAX_REPLY + 1)),
        ]
        for status, reply in cases:
            with self.subTest(status=status, reply_size=len(reply or b"")):
                path = self.report()
                self.reply_status, self.reply = status, reply
                before = len(self.requests)
                result = self.run_sender()
                self.assertEqual(result.returncode, 1)
                self.assertTrue(path.exists())
                self.assertNotIn(
                    "private peer diagnostic", result.stdout + result.stderr
                )
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(self.run_sender().returncode, 1)
                self.assertEqual(len(self.requests), before + 1)
                # Reset only this test fixture, never production evidence.
                path.unlink()

    def test_ack_requires_boolean_duplicate_and_json_content_type(self):
        for duplicate, content_type in [(0, "application/json"), (False, "text/html")]:
            path = self.report()
            self.reply = json.dumps(
                {"status": "stored", "snapshot_id": path.stem, "duplicate": duplicate}
            ).encode()
            self.content_type = content_type
            self.assertEqual(self.run_sender().returncode, 1)
            self.assertTrue(path.exists())
            path.unlink()

    def test_rejection_recovery_requires_explicit_action_and_does_not_block_other_report(
        self,
    ):
        blocked = self.report()
        self.reply_status = 401
        self.assertEqual(self.run_sender().returncode, 1)
        valid = self.report()
        self.reply_status = 200
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertTrue(blocked.exists())
        self.assertFalse(valid.exists())
        self.assertEqual(self.run_sender("--retry-blocked").returncode, 0)
        self.assertFalse(blocked.exists())

    def test_transient_failures_persist_retry_after_across_process_restart(self):
        for status in (429, 503):
            path = self.report()
            self.reply_status = status
            before = len(self.requests)
            now = time.time()
            self.assertEqual(self.run_sender().returncode, 1)
            state = json.loads((self.spool / ".delivery.json").read_text())
            self.assertGreaterEqual(state[path.stem]["retry_at"], now + 3601)
            self.assertEqual(self.run_sender().returncode, 1)
            self.assertEqual(len(self.requests), before + 1)
            self.assertTrue(path.exists())
            path.unlink()

    def test_retry_after_bounds_and_dates(self):
        self.assertEqual(send.retry_delay("999999999", 0), 86400)
        self.assertEqual(send.retry_delay("-1", 0), 3600)
        self.assertEqual(send.retry_delay("invalid", 0), 3600)
        self.assertEqual(send.retry_delay("Thu, 01 Jan 1970 02:00:00 GMT", 0), 7200)

    def test_changed_credential_releases_previous_rejection(self):
        path = self.report()
        self.reply_status = 401
        self.assertEqual(self.run_sender().returncode, 1)
        self.credential.write_text("replacement.secret")
        self.reply_status = 200
        self.assertEqual(self.run_sender().returncode, 0)
        self.assertFalse(path.exists())

    def test_crash_after_ack_before_unlink_keeps_report_for_replay(self):
        path = self.report()
        with patch.object(Path, "unlink", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                send.send_reports(
                    self.spool, self.endpoint, self.credential, allow_loopback_http=True
                )
        self.assertTrue(path.exists())
        self.assertEqual(self.run_sender().returncode, 0)
        self.assertEqual(len(self.requests), 2)
        self.assertFalse(path.exists())

    def test_lock_excludes_another_sender_and_emitter(self):
        self.report()
        with outbox.locked(self.spool):
            self.assertEqual(self.run_sender().returncode, 1)
            with self.assertRaises(ValueError):
                self.report()
        self.assertEqual(self.requests, [])

    def test_full_outbox_preserves_reports_and_internal_files_do_not_consume_capacity(
        self,
    ):
        paths = [self.report() for _ in range(32)]
        outbox.atomic_state(self.spool, {})
        with self.assertRaises(ValueError):
            self.report()
        self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual(self.run_sender().returncode, 0)
        self.assertTrue(self.report().exists())

    def test_private_files_and_symlinks_rejected_without_request(self):
        path = self.report()
        self.credential.chmod(0o644)
        self.assertEqual(self.run_sender().returncode, 1)
        self.credential.chmod(0o600)
        original = self.root / "original"
        path.rename(original)
        path.symlink_to(original)
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertTrue(original.exists())
        self.assertEqual(self.requests, [])

    def test_malformed_state_and_oversize_report_fail_closed(self):
        path = self.report()
        (self.spool / ".delivery.json").write_text("invalid")
        (self.spool / ".delivery.json").chmod(0o600)
        self.assertEqual(self.run_sender().returncode, 1)
        (self.spool / ".delivery.json").unlink()
        path.write_bytes(b"x" * (outbox.MAX_BYTES + 1))
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertTrue(path.exists())
        self.assertEqual(self.requests, [])

    def test_total_deadline_releases_lock_and_retains_report(self):
        path = self.report()
        self.delay_reply = True
        started = time.monotonic()
        result = self.run_sender("--run-timeout", "1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("run_deadline_exceeded", result.stdout)
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(path.exists())
        with outbox.locked(self.spool):
            pass

    def test_no_implicit_plain_http_or_credentials_in_endpoint(self):
        for endpoint in [
            self.endpoint,
            "http://remote.example/v1/inventory",
            "https://secret@receiver.example/v1/inventory",
            "https://receiver.example/v1/inventory?key=secret",
        ]:
            with self.assertRaises(ValueError):
                send.endpoint_url(endpoint)
        self.assertEqual(send.endpoint_url(self.endpoint, True).hostname, "127.0.0.1")

    def test_https_verifies_certificate_and_delivers_with_explicit_trust(self):
        cert, key = self.root / "test-cert.pem", self.root / "test-key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tls = ThreadingHTTPServer(("127.0.0.1", 0), self.server.RequestHandlerClass)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        tls.socket = context.wrap_socket(tls.socket, server_side=True)
        worker = threading.Thread(target=tls.serve_forever, daemon=True)
        worker.start()
        try:
            self.endpoint = f"https://127.0.0.1:{tls.server_port}/v1/inventory"
            path = self.report()
            result = self.run_sender()
            self.assertIn("tls_verification_failed", result.stdout)
            self.assertTrue(path.exists())
            self.assertEqual(self.requests, [])
            with patch.dict(os.environ, {"SSL_CERT_FILE": str(cert)}):
                result = self.run_sender("--retry-blocked")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(path.exists())
        finally:
            tls.shutdown()
            tls.server_close()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())

    def test_killed_sender_retains_report_and_restart_can_deliver(self):
        path = self.report()
        self.delay_reply = True
        command = [
            sys.executable,
            str(FILES / "send.py"),
            "--spool",
            str(self.spool),
            "--endpoint",
            self.endpoint,
            "--credential-file",
            str(self.credential),
            "--allow-loopback-http",
        ]
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            until = time.monotonic() + 5
            while not self.requests and time.monotonic() < until:
                time.sleep(0.01)
            self.assertTrue(self.requests)
            process.kill()
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        self.assertTrue(path.exists())
        self.delay_reply = False
        self.assertEqual(self.run_sender().returncode, 0)
        self.assertFalse(path.exists())

    def test_stray_crash_file_does_not_wedge_full_queue(self):
        paths = [self.report() for _ in range(32)]
        leftover = self.spool / ".state-interrupted"
        leftover.write_text("unfinished state")
        result = self.run_sender()
        self.assertEqual(result.returncode, 1)  # unknown file remains visible
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertTrue(leftover.exists())

    def test_manual_retry_now_overrides_persisted_transient_delay(self):
        path = self.report()
        self.reply_status = 503
        self.assertEqual(self.run_sender().returncode, 1)
        self.reply_status = 200
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertTrue(path.exists())
        self.assertEqual(self.run_sender("--retry-now").returncode, 0)
        self.assertFalse(path.exists())

    def test_base64_bearer_characters_supported(self):
        self.credential.write_text("test+credential/withpadding==")
        path = self.report()
        self.assertEqual(self.run_sender().returncode, 0)
        self.assertFalse(path.exists())
        self.assertEqual(
            self.requests[0][1]["Authorization"], "Bearer test+credential/withpadding=="
        )

    def test_invalid_report_identity_and_hard_link_retained(self):
        path = self.report()
        path.write_text(json.dumps({"snapshot_id": str(uuid4())}))
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertTrue(path.exists())
        self.assertEqual(self.requests, [])
        path.unlink()
        path = self.report()
        linked = self.root / "report-link"
        os.link(path, linked)
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertTrue(path.exists())
        self.assertEqual(self.requests, [])

    def test_structurally_invalid_state_fails_closed(self):
        path = self.report()
        good = {
            "fingerprint": "a" * 64,
            "status": "retry",
            "reason": "network_error",
            "retry_at": 0,
        }
        for changes in (
            {"fingerprint": 7},
            {"reason": []},
            {"retry_at": "later"},
            {"retry_at": 10**1000},
            {"retry_at": float("inf")},
        ):
            with self.subTest(field=list(changes)):
                state_file = self.spool / ".delivery.json"
                state_file.write_text(json.dumps({path.stem: {**good, **changes}}))
                state_file.chmod(0o600)
                self.assertEqual(self.run_sender().returncode, 1)
                self.assertTrue(path.exists())
        state_file.write_text(json.dumps({"bad-uuid": good}))
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertEqual(self.requests, [])

    def test_duplicate_ack_is_successful_retirement(self):
        path = self.report()
        self.reply = json.dumps(
            {"status": "stored", "snapshot_id": path.stem, "duplicate": True}
        ).encode()
        result = self.run_sender()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["reports"][0]["reason"], "duplicate")
        self.assertFalse(path.exists())

    def test_33_canonical_reports_are_rejected_before_any_upload(self):
        paths = [self.report() for _ in range(32)]
        identifier = str(uuid4())
        extra = self.spool / outbox.report_name(identifier)
        extra.write_text(json.dumps({"snapshot_id": identifier}))
        extra.chmod(0o600)
        self.assertEqual(self.run_sender().returncode, 1)
        self.assertEqual(self.requests, [])
        self.assertTrue(all(path.exists() for path in paths + [extra]))

    def test_python_310_compatibility(self):
        for name in ("outbox.py", "send.py", "emit.py"):
            ast.parse((FILES / name).read_text(), feature_version=(3, 10))


if __name__ == "__main__":
    unittest.main()
