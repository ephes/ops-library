"""Exercise the trust copy against a real vendor keytool, not a fake parser."""

import importlib.util
import json
import os
import plistlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from jinja2 import Environment

SCRIPT = (
    Path(__file__).resolve().parents[1] / "roles/macos_java_trust/files/manage_trust.py"
)
JDK = Path(
    os.environ.get(
        "JAVA_TRUST_TEST_JDK",
        "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home",
    )
)


@unittest.skipUnless((JDK / "bin/keytool").exists(), "requires a real test JDK")
class TrustCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "external-cacerts"
        self.options = self.root / "custom.vmoptions"
        self.defaults = self.root / "default.vmoptions"
        self.defaults.write_text("-Xmx2048m\n")

    def invoke(self, *extra, success=True):
        result = subprocess.run(
            [
                shutil.which("python3"),
                str(SCRIPT),
                "--jdk",
                str(JDK),
                "--output",
                str(self.output),
                *extra,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return json.loads(result.stdout) if success else result

    def test_real_copy_rejects_roots_and_preserves_all_other_aliases(self):
        args = ["--options", str(self.options), "--default-options", str(self.defaults)]
        original = (JDK / "lib/security/cacerts").read_bytes()
        first = self.invoke(*args)
        self.assertTrue(first["changed"])
        # Independently pin the expected affected aliases, including Sectigo AAA
        # because it cross-signs compromised eMudhra intermediates (Ubuntu notice).
        self.assertEqual(
            set(first["removed_aliases"]),
            {"comodoaaaca [jdk]", "emsigneccrootcag3 [jdk]"},
        )
        self.assertTrue(first["restart_required"])
        spec = importlib.util.spec_from_file_location("trust_helper", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def certs(path):
            text = subprocess.check_output(
                [
                    str(JDK / "bin/keytool"),
                    "-J-Duser.language=en",
                    "-list",
                    "-rfc",
                    "-keystore",
                    str(path),
                    "-storepass",
                    "changeit",
                ],
                text=True,
            )
            return module.certificates(text)

        before = certs(JDK / "lib/security/cacerts")
        after = certs(self.output)
        self.assertEqual(
            after,
            {
                key: value
                for key, value in before.items()
                if value not in module.BLOCKED
            },
        )
        self.assertFalse(self.invoke(*args)["changed"])
        self.assertEqual((JDK / "lib/security/cacerts").read_bytes(), original)
        self.assertEqual(
            self.options.read_text(),
            "-Xmx2048m\n-Djavax.net.ssl.trustStore=" + str(self.output) + "\n",
        )
        self.output.write_bytes(self.output.read_bytes() + b"drift")
        self.invoke(*args, success=False)

    def test_check_mode_and_conflicting_option_make_no_changes(self):
        self.invoke("--check")
        self.assertFalse(self.output.exists())
        self.invoke("--options", str(self.options), success=False)
        self.options.write_text(
            "-Xmx32000m\n-Djavax.net.ssl.trustStore=/custom/store\n"
        )
        self.invoke(
            "--options",
            str(self.options),
            "--default-options",
            str(self.defaults),
            success=False,
        )
        self.assertFalse(self.output.exists())
        self.assertIn("-Xmx32000m", self.options.read_text())

    def test_existing_custom_options_bytes_and_mode_survive(self):
        original = b"-Xmx32000m  \r\n\r\n"
        self.options.write_bytes(original)
        self.options.chmod(0o600)
        self.invoke(
            "--options", str(self.options), "--default-options", str(self.defaults)
        )
        self.assertTrue(self.options.read_bytes().startswith(original))
        self.assertEqual(self.options.stat().st_mode & 0o777, 0o600)

    def test_absent_ide_config_is_not_created_or_migration_suppressed(self):
        options = self.root / "PyCharm2026.2" / "pycharm.vmoptions"
        self.invoke(
            "--options",
            str(options),
            "--default-options",
            str(self.defaults),
            success=False,
        )
        self.assertFalse(options.parent.exists())
        self.assertFalse(self.output.exists())


class LaunchAgentTests(unittest.TestCase):
    def test_external_options_are_one_escaped_native_gui_argument(self):
        template = (SCRIPT.parents[1] / "templates/pycharm-env.plist.j2").read_text()
        path = "/Users/test/Library/Application Support/a&b/external.vmoptions"
        rendered = (
            Environment()
            .from_string(template)
            .render(macos_java_trust_pycharm_vm_options=path)
        )
        data = plistlib.loads(rendered.encode())
        self.assertEqual(
            data["ProgramArguments"],
            ["/bin/launchctl", "setenv", "PYCHARM_VM_OPTIONS", path],
        )
        self.assertEqual(data["LimitLoadToSessionType"], "Aqua")
        self.assertTrue(data["RunAtLoad"])
        self.assertNotIn("EnvironmentVariables", data)
