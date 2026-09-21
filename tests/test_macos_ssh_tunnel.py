"""Exercise lifecycle failure paths and real TLS/HTTP through the checker."""

import contextlib
import importlib.util
import io
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "tunnel_control", ROOT / "roles/macos_ssh_tunnel/files/tunnel_control.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def configuration(port=18443):
    return dict(
        label="org.example.test-tunnel",
        local_port=port,
        plist="/tmp/agent.plist",
        stderr_log="/tmp/tunnel.log",
        https_host="backend.example.org",
        ignore_ssl_errors=False,
        health_path="/",
        health_status=200,
        ca_file="",
    )


class LifecycleTests(unittest.TestCase):
    def test_stop_disables_before_unloading(self):
        with (
            patch.object(module, "run") as run,
            patch.object(module.Tunnel, "loaded", side_effect=[True, False]),
        ):
            module.Tunnel(configuration()).stop()
            self.assertEqual(
                [c.args[1] for c in run.call_args_list], ["disable", "bootout"]
            )

    def test_restart_waits_for_asynchronous_unload_before_enabling(self):
        with (
            patch.object(module, "run") as run,
            patch.object(
                module.Tunnel, "loaded", side_effect=[True, True, False, False]
            ),
            patch.object(module.time, "sleep") as sleep,
        ):
            module.Tunnel(configuration(0)).restart()
            sleep.assert_called_once_with(0.1)
            self.assertEqual(
                [c.args[1] for c in run.call_args_list],
                ["disable", "bootout", "enable", "bootstrap"],
            )

    def test_stop_accepts_bootout_race_only_when_unloaded(self):
        with (
            patch.object(module, "run") as run,
            patch.object(module.Tunnel, "loaded", side_effect=[True, False]),
        ):
            run.return_value.returncode = 36
            module.Tunnel(configuration()).stop()
        with (
            patch.object(module, "run"),
            patch.object(module.Tunnel, "loaded", return_value=True),
            patch.object(module.time, "monotonic", side_effect=[0, 11]),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not unload"):
                module.Tunnel(configuration()).stop()

    def test_time_wait_from_previous_forward_does_not_block_start(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            listener.listen()
            with socket.create_connection(("127.0.0.1", port), 2) as client:
                server, _ = listener.accept()
                server.close()  # Server initiates close and enters TIME_WAIT.
                self.assertEqual(client.recv(1), b"")
        with (
            patch.object(module.Tunnel, "loaded", return_value=False),
            patch.object(module, "run") as run,
        ):
            module.Tunnel(configuration(port)).start()
            self.assertEqual(run.call_args.args[1], "bootstrap")

    def test_start_rejects_unknown_listener_without_launchctl_mutation(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with (
                patch.object(module.Tunnel, "loaded", return_value=False),
                patch.object(module, "run") as run,
            ):
                with self.assertRaises(OSError):
                    module.Tunnel(configuration(listener.getsockname()[1])).start()
                run.assert_not_called()

    def test_failed_bootstrap_restores_disabled_state(self):
        with (
            patch.object(module.Tunnel, "loaded", return_value=False),
            patch.object(module, "run") as run,
        ):
            run.side_effect = [
                None,
                subprocess.CalledProcessError(1, "bootstrap"),
                None,
            ]
            with self.assertRaises(subprocess.CalledProcessError):
                module.Tunnel(configuration(0)).start()
            self.assertEqual(
                [c.args[1] for c in run.call_args_list],
                ["enable", "bootstrap", "disable"],
            )

    def test_start_accepts_legacy_ansible_numeric_strings(self):
        config = configuration("0")
        config["health_status"] = "200"
        with (
            patch.object(module.Tunnel, "loaded", return_value=False),
            patch.object(module, "run") as run,
        ):
            module.Tunnel(config).start()
            self.assertEqual(run.call_args.args[1], "bootstrap")

    def test_string_false_cannot_silently_disable_tls_verification(self):
        config = configuration()
        config["ignore_ssl_errors"] = "false"
        with self.assertRaisesRegex(ValueError, "JSON boolean"):
            module.Tunnel(config)

    def test_already_loaded_start_is_idempotent(self):
        with (
            patch.object(module.Tunnel, "loaded", return_value=True),
            patch.object(module, "run") as run,
        ):
            module.Tunnel(configuration()).start()
            run.assert_called_once_with(
                "/bin/launchctl", "enable", module.Tunnel(configuration()).service
            )

    def test_bad_routing_fails_before_connecting(self):
        with (
            patch.object(module.Tunnel, "loaded", return_value=True),
            patch.object(
                socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("192.0.2.1", 0))]
            ),
            patch.object(socket, "create_connection") as connect,
        ):
            with self.assertRaisesRegex(RuntimeError, "Hostname routing"):
                module.Tunnel(configuration()).check()
            connect.assert_not_called()

    def test_missing_dns_explains_the_required_hostname_setup(self):
        with (
            patch.object(module.Tunnel, "loaded", return_value=True),
            patch.object(
                socket, "getaddrinfo", side_effect=socket.gaierror("no such name")
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Run hosts setup"):
                module.Tunnel(configuration()).check()

    def test_missing_config_cli_fails_cleanly(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SPEC.origin),
                "--config",
                "/nonexistent/tunnel.json",
                "start",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class HttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.cert = str(Path(cls.temp.name) / "cert.pem")
        cls.key = str(Path(cls.temp.name) / "key.pem")
        config = Path(cls.temp.name) / "openssl.cnf"
        config.write_text(
            "[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n"
            "[dn]\nCN=backend.example.org\n"
            "[ext]\nsubjectAltName=DNS:backend.example.org\n"
        )
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                cls.key,
                "-out",
                cls.cert,
                "-days",
                "1",
                "-config",
                str(config),
            ],
            check=True,
            capture_output=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def probe(
        self,
        *,
        trust=False,
        insecure=False,
        status=200,
        hostname="backend.example.org",
        legacy_numbers=False,
    ):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        observed = []
        context.set_servername_callback(lambda stream, name, ctx: observed.append(name))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(5)
            config = configuration(listener.getsockname()[1])
            config.update(
                ignore_ssl_errors=insecure,
                ca_file=self.cert if trust else "",
                https_host=hostname,
            )
            if legacy_numbers:
                config["local_port"] = str(config["local_port"])
                config["health_status"] = str(config["health_status"])

            def serve():
                raw, _ = listener.accept()
                with raw:
                    try:
                        with context.wrap_socket(raw, server_side=True) as stream:
                            request = b""
                            while b"\r\n\r\n" not in request:
                                chunk = stream.recv(4096)
                                if not chunk:
                                    return
                                request += chunk
                            observed.append(request.decode("ascii"))
                            stream.sendall(
                                (
                                    f"HTTP/1.1 {status} Test\r\n"
                                    "Content-Length: 0\r\n\r\n"
                                ).encode()
                            )
                    except ssl.SSLError:
                        pass

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            try:
                with patch.object(module.Tunnel, "loaded", return_value=True):
                    module.Tunnel(config).check(transport_only=True)
            finally:
                thread.join(timeout=6)
        return observed

    def test_verified_tls_uses_upstream_sni_and_host(self):
        observed = self.probe(trust=True)
        self.assertEqual(observed[0], "backend.example.org")
        self.assertRegex(observed[1], r"Host: backend\.example\.org:[0-9]+\r\n")

    def test_https_accepts_legacy_ansible_numeric_strings(self):
        self.probe(trust=True, legacy_numbers=True)

    def test_untrusted_certificate_is_rejected_by_default(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.probe()

    def test_hostname_mismatch_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.probe(trust=True, hostname="wrong.example.org")

    def test_explicit_insecure_mode_is_visible(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.probe(insecure=True)
        self.assertIn("verification DISABLED", output.getvalue())
        self.assertIn("routing was NOT checked", output.getvalue())

    def test_unexpected_http_status_fails(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            self.probe(trust=True, status=503)


if __name__ == "__main__":
    unittest.main()
