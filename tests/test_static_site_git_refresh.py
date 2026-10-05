import os
import shlex
import shutil
import stat
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/static_site_git_refresh"
STATIC_ROLE = ROOT / "roles/static_site_deploy"


def _quote(value: object) -> str:
    return shlex.quote(str(value))


def _render(template: Path, **context: object) -> str:
    env = Environment(keep_trailing_newline=True)
    env.filters["quote"] = _quote
    return env.from_string(template.read_text()).render(**context)


def _gnu_tools_available() -> bool:
    if shutil.which("flock") is None:
        return False
    result = subprocess.run(
        ["stat", "-c", "%s", __file__], capture_output=True, text=True, check=False
    )
    return result.returncode == 0


def _write_shims(directory: Path) -> None:
    """Provide flock and GNU-style stat on hosts without util-linux (macOS)."""
    flock = directory / "flock"
    flock.write_text("#!/bin/sh\nexit 0\n")
    stat_shim = directory / "stat"
    stat_shim.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os, sys
            args = [a for a in sys.argv[1:] if a not in ("-c", "%s", "--")]
            print(os.stat(args[-1]).st_size)
            """
        )
    )
    for path in (flock, stat_shim):
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "requires git")
class RefreshScriptBehaviourTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.base = base
        self.home = base / "state"
        self.home.mkdir()
        self.publish = base / "site"
        self.publish.mkdir()
        self.source = base / "source"
        self.source.mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        if not _gnu_tools_available():
            _write_shims(self.bin)
        self._git("init", "-q", "-b", "main", cwd=self.source)
        (self.source / "build.sh").write_text(
            "set -e\nmkdir -p dashboard/dist\ncp page.html dashboard/dist/index.html\n"
        )
        self.commit("<html>work ledger v1</html>")

        self.script = base / "refresh.sh"
        self.render_script(marker="work ledger")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _git(self, *args: str, cwd: Path) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
        )

    def commit(self, page: str) -> None:
        (self.source / "page.html").write_text(page)
        self._git("add", "-A", cwd=self.source)
        self._git("commit", "-q", "-m", "update", cwd=self.source)

    def render_script(self, marker: str = "", build=None) -> None:
        self.script.write_text(
            _render(
                ROLE / "templates/refresh.sh.j2",
                static_site_git_refresh_name="work-dashboard-refresh",
                static_site_git_refresh_repo=str(self.source),
                static_site_git_refresh_branch="main",
                static_site_git_refresh_checkout_path=str(self.home / "checkout"),
                static_site_git_refresh_home=str(self.home),
                static_site_git_refresh_output_path="dashboard/dist/index.html",
                static_site_git_refresh_output_max_bytes=4096,
                static_site_git_refresh_output_marker=marker,
                static_site_git_refresh_publish_path=str(self.publish),
                static_site_git_refresh_publish_name="index.html",
                static_site_git_refresh_build_timeout_seconds=60,
                static_site_git_refresh_build_command=build or ["/bin/sh", "build.sh"],
                static_site_git_refresh_build_environment={"UV_NO_PROGRESS": "1"},
                static_site_git_refresh_deploy_key_path=str(self.home / ".ssh/key"),
                static_site_git_refresh_known_hosts_path=str(
                    self.home / ".ssh/known_hosts"
                ),
            )
        )
        self.script.chmod(0o755)

    def run_refresh(self) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
        }
        return subprocess.run(
            ["bash", str(self.script)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def published(self) -> str:
        return (self.publish / "index.html").read_text()

    def test_publishes_then_skips_unchanged_commit_then_follows_new_commit(
        self,
    ) -> None:
        first = self.run_refresh()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.published(), "<html>work ledger v1</html>")
        self.assertEqual((self.publish / "index.html").stat().st_mode & 0o777, 0o640)
        self.assertTrue((self.home / "published-rev").read_text().strip())

        second = self.run_refresh()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("is current", second.stdout)

        self.commit("<html>work ledger v2</html>")
        third = self.run_refresh()
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertEqual(self.published(), "<html>work ledger v2</html>")
        self.assertEqual(list(self.publish.glob(".publish.*")), [])

    def test_changed_repository_url_is_followed(self) -> None:
        self.assertEqual(self.run_refresh().returncode, 0)
        other = self.base / "other"
        shutil.copytree(self.source, other)
        self.source = other
        self.commit("<html>work ledger other repo</html>")
        self.render_script(marker="work ledger")
        (self.home / "published-rev").unlink()

        result = self.run_refresh()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.published(), "<html>work ledger other repo</html>")

    def test_failed_build_keeps_last_good_page(self) -> None:
        self.assertEqual(self.run_refresh().returncode, 0)
        (self.source / "build.sh").write_text("exit 3\n")
        self.commit("<html>work ledger broken</html>")

        result = self.run_refresh()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.published(), "<html>work ledger v1</html>")

    def test_missing_marker_is_not_published(self) -> None:
        self.commit("<html>something else</html>")

        result = self.run_refresh()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("marker", result.stderr)
        self.assertFalse((self.publish / "index.html").exists())

    def test_output_symlink_is_rejected(self) -> None:
        secret = self.base / "outside.html"
        secret.write_text("<html>work ledger outside</html>")
        (self.source / "build.sh").write_text(
            f"set -e\nmkdir -p dashboard/dist\nln -s {secret} dashboard/dist/index.html\n"
        )
        self.commit("<html>work ledger v1</html>")

        result = self.run_refresh()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.publish / "index.html").exists())

    def test_oversized_output_is_rejected(self) -> None:
        self.commit("<html>work ledger " + "x" * 5000 + "</html>")

        result = self.run_refresh()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside 1..4096", result.stderr)
        self.assertFalse((self.publish / "index.html").exists())


class RefreshRoleContractTests(unittest.TestCase):
    def test_ssh_is_pinned_and_non_interactive(self) -> None:
        script = (ROLE / "templates/refresh.sh.j2").read_text()
        access = (ROLE / "tasks/access.yml").read_text()
        for text in (script, access):
            self.assertIn("StrictHostKeyChecking=yes", text)
            self.assertIn("BatchMode=yes", text)
            self.assertIn("IdentitiesOnly=yes", text)
        self.assertNotIn("accept_hostkey", access)

    def test_default_known_host_matches_githubs_published_ed25519_key(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(
            defaults["static_site_git_refresh_known_hosts"],
            [
                (
                    "github.com ssh-ed25519 "
                    "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
                )
            ],
        )

    def test_deploy_key_is_generated_on_target_and_never_read_back_privately(
        self,
    ) -> None:
        account = (ROLE / "tasks/account.yml").read_text()
        access = (ROLE / "tasks/access.yml").read_text()
        self.assertIn(
            'creates: "{{ static_site_git_refresh_deploy_key_path }}"', account
        )
        self.assertIn('mode: "0600"', account)
        self.assertIn(
            'src: "{{ static_site_git_refresh_deploy_key_path }}.pub"', access
        )
        self.assertEqual(access.count("slurp"), 1)
        self.assertIn("Allow write access' unchecked", access)

    def test_service_is_hardened_and_writes_only_state_and_document_root(self) -> None:
        unit = (ROLE / "templates/refresh.service.j2").read_text()
        self.assertIn("User={{ static_site_git_refresh_user }}", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ProtectHome=true", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn(
            "ReadWritePaths={{ static_site_git_refresh_home }} "
            "{{ static_site_git_refresh_publish_path }}",
            unit,
        )
        self.assertIn("\nCapabilityBoundingSet=\n", unit)

    def test_document_root_is_setgid_and_not_world_readable(self) -> None:
        account = (ROLE / "tasks/account.yml").read_text()
        start = account.index(
            "Ensure document root is writable only by the refresh user"
        )
        self.assertIn('mode: "2750"', account[start:])

    def test_timer_uses_configured_interval(self) -> None:
        timer = (ROLE / "templates/refresh.timer.j2").read_text()
        self.assertIn("OnUnitInactiveSec={{ static_site_git_refresh_interval }}", timer)
        self.assertIn("WantedBy=timers.target", timer)


class StaticSiteAllowlistTests(unittest.TestCase):
    def render_route(self, networks: list[str]) -> dict:
        rendered = _render(
            STATIC_ROLE / "templates/static-site.traefik.yml.j2",
            static_site_service_name="work-dashboard",
            static_site_host="work.example.internal",
            static_site_traefik_entrypoints=["web-secure"],
            static_site_traefik_http_entrypoint="web",
            static_site_traefik_cert_resolver="",
            static_site_allowed_networks=networks,
            static_site_bind_host="127.0.0.1",
            static_site_port=10064,
        )
        return yaml.safe_load(rendered)

    def test_allowlist_guards_https_and_redirect_routers(self) -> None:
        route = self.render_route(["100.64.0.0/10", "fd7a:115c:a1e0::/48"])
        routers = route["http"]["routers"]
        middlewares = route["http"]["middlewares"]

        self.assertEqual(
            routers["work-dashboard-secure"]["middlewares"][0],
            "work-dashboard-allowlist",
        )
        self.assertEqual(
            routers["work-dashboard-http"]["middlewares"][0], "work-dashboard-allowlist"
        )
        self.assertEqual(
            middlewares["work-dashboard-allowlist"]["ipAllowList"]["sourceRange"],
            ["100.64.0.0/10", "fd7a:115c:a1e0::/48"],
        )

    def test_empty_allowlist_keeps_previous_route_shape(self) -> None:
        route = self.render_route([])
        self.assertNotIn("work-dashboard-allowlist", route["http"]["middlewares"])
        self.assertEqual(
            route["http"]["routers"]["work-dashboard-secure"]["middlewares"],
            ["work-dashboard-headers", "work-dashboard-compress"],
        )


if __name__ == "__main__":
    unittest.main()
