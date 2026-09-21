"""Linux scheduler and privilege-drop contracts, without a systemd dependency."""

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment

ROLE = Path(__file__).resolve().parents[1] / "roles/software_estate_publisher_linux"


def render(name, **values):
    env = Environment()
    env.filters["quote"] = shlex.quote
    return env.from_string((ROLE / "templates" / name).read_text()).render(**values)


class LinuxPublisherTests(unittest.TestCase):
    def test_timer_checks_cadence_at_boot_and_after_missed_calendar_events(self):
        text = render("publisher.timer.j2", software_estate_publisher_linux_minute=3)
        self.assertIn("OnBootSec=2min", text)
        self.assertIn("OnCalendar=*-*-* *:03:00", text)
        self.assertIn("Persistent=true", text)
        self.assertIn("WakeSystem=false", text)
        self.assertNotIn("OnUnitActiveSec", text)

    def test_service_runs_unprivileged_with_only_state_writable(self):
        text = render(
            "publisher.service.j2",
            software_estate_publisher_linux_python="/usr/bin/python3",
            software_estate_publisher_linux_release="/usr/local/lib/publisher/release",
        )
        self.assertIn("User=software-estate-publisher", text)
        self.assertIn("NoNewPrivileges=true", text)
        self.assertIn("CapabilityBoundingSet=\n", text)
        self.assertIn("ProtectSystem=strict", text)
        self.assertIn("ReadWritePaths=/var/lib/software-estate-publisher\n", text)
        self.assertIn("TimeoutStartSec=300", text)
        self.assertNotIn("SupplementaryGroups", text)
        self.assertNotIn("Restart=", text)

    def test_manual_wrapper_preserves_flags_and_always_requests_privilege_drop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recorder = root / "record.py"
            output = root / "arguments.json"
            recorder.write_text(
                "import json,sys; from pathlib import Path; "
                "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))"
            )
            wrapper = render(
                "run.j2",
                software_estate_publisher_linux_python="/usr/bin/python3",
                software_estate_publisher_linux_release="/usr/local/lib/publisher/release",
            )
            self.assertEqual(wrapper.count("/usr/sbin/runuser"), 1)
            wrapper = wrapper.replace(
                "/usr/sbin/runuser",
                " ".join(
                    shlex.quote(str(x)) for x in [sys.executable, recorder, output]
                ),
            )
            script = root / "run"
            script.write_text(wrapper)
            subprocess.run(
                ["/bin/sh", str(script), "--send-only", "--retry-now"], check=True
            )
            self.assertEqual(
                json.loads(output.read_text()),
                [
                    "-u",
                    "software-estate-publisher",
                    "--",
                    "/usr/bin/python3",
                    "/usr/local/lib/publisher/release/publish.py",
                    "--config",
                    "/etc/software-estate-publisher/config.json",
                    "--send-only",
                    "--retry-now",
                ],
            )


if __name__ == "__main__":
    unittest.main()
