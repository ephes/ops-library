"""Guard the scheduled deletion boundary and age-filter rendering."""
import shlex
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROLE = Path(__file__).resolve().parents[1] / "roles" / "docker_cache_cleanup"


class DockerCacheCleanupTests(unittest.TestCase):
    def test_all_role_yaml_parses(self):
        for path in ROLE.rglob("*.yml"):
            with self.subTest(path=path):
                self.assertIsNotNone(yaml.safe_load(path.read_text()))

    def test_disable_only_stops_an_existing_timer(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        systemd_tasks = [task for task in tasks if "ansible.builtin.systemd_service" in task]
        self.assertEqual(len(systemd_tasks), 2)
        enabled, disabled = systemd_tasks
        self.assertEqual(enabled["when"], [
            "docker_cache_cleanup_enabled",
            "not ansible_check_mode or _docker_cache_cleanup_timer.stat.exists"
        ])
        self.assertTrue(enabled["ansible.builtin.systemd_service"]["enabled"])
        self.assertEqual(disabled["when"], [
            "not docker_cache_cleanup_enabled", "_docker_cache_cleanup_timer.stat.exists"
        ])
        self.assertEqual(disabled["ansible.builtin.systemd_service"], {
            "name": "docker-cache-cleanup.timer", "enabled": False, "state": "stopped"
        })

    def test_cleanup_only_targets_aged_build_cache(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        env = Environment(undefined=StrictUndefined)
        template = env.from_string(
            (ROLE / "templates/docker-cache-cleanup.service.j2").read_text()
        )
        for hours in (168, 24):
            with self.subTest(hours=hours):
                config = template.render(
                    **{**defaults, "docker_cache_cleanup_unused_hours": hours}
                )
                commands = [
                    line.split("=", 1)[1]
                    for line in config.splitlines()
                    if line.startswith("Exec")
                ]
                self.assertEqual(len(commands), 1)
                self.assertEqual(
                    shlex.split(commands[0]),
                    ["/usr/bin/docker", "builder", "prune", "--all", "--force",
                     "--filter", f"until={hours}h"],
                )

    def test_timer_uses_host_calendar_and_catches_up(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        template = Environment(undefined=StrictUndefined).from_string(
            (ROLE / "templates/docker-cache-cleanup.timer.j2").read_text()
        )
        config = template.render(**defaults)
        self.assertIn("OnCalendar=*-*-* 03:30:00", config)
        self.assertIn("Persistent=true", config)
        self.assertIn("RandomizedDelaySec=30m", config)


if __name__ == "__main__":
    unittest.main()
