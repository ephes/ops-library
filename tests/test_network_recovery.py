from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]


def template_environment(directory: Path) -> Environment:
    environment = Environment(
        loader=FileSystemLoader(directory),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["bool"] = bool
    environment.filters["quote"] = shlex.quote
    return environment


class NetplanRouteGuardTemplateTests(unittest.TestCase):
    def test_managed_network_transitions_share_the_guard_lock(self) -> None:
        handlers = (ROOT / "roles/netplan_config/handlers/main.yml").read_text()
        tasks = (ROOT / "roles/netplan_config/tasks/main.yml").read_text()

        self.assertIn("Generate netplan under the route guard lock", handlers)
        self.assertIn("Apply netplan under the route guard lock", handlers)
        self.assertIn(
            "/run/{{ netplan_config_route_guard_service_name }}/lock", handlers
        )
        self.assertIn(
            "Reconfigure networkd-managed interfaces under the route guard lock",
            tasks,
        )
        self.assertIn("/run/{{ netplan_config_route_guard_service_name }}/lock", tasks)
        self.assertIn("_netplan_route_guard_timer.stat.exists", handlers)
        self.assertIn("_netplan_route_guard_timer.stat.exists", tasks)
        self.assertIn("Stop disabled default-route recovery service", tasks)
        self.assertIn("Inspect route guard installation targets", tasks)
        self.assertIn(
            "Refuse to overwrite unmanaged route guard installation targets",
            tasks,
        )
        self.assertIn("service_name is search('[A-Za-z0-9]')", tasks)
        self.assertIn("service_name not in ['.', '..']", tasks)
        self.assertIn("stat.exists | default(false)", handlers)
        self.assertIn("stat.exists | default(false)", tasks)

    def test_metrics_allow_list_rejects_world_open_and_invalid_prefixes(self) -> None:
        tasks = (ROOT / "roles/tailscale_metrics_endpoint/tasks/main.yml").read_text()
        argument_specs = yaml.safe_load(
            (
                ROOT
                / "roles/tailscale_metrics_endpoint/meta/argument_specs.yml"
            ).read_text()
        )["argument_specs"]["main"]["options"]

        self.assertIn("(item.split('/') | last | int) > 0", tasks)
        self.assertIn("(item.split('/') | last | int) <= 32", tasks)
        self.assertIn("(item.split('/') | last | int) <= 128", tasks)
        self.assertIn("ipaddress.ip_network", tasks)
        self.assertIn("minimum = 8 if network.version == 4 else 32", tasks)
        self.assertIn("delegate_to: localhost", tasks)
        self.assertIn("check_mode: false", tasks)
        self.assertIn("Require effective metrics endpoint cgroup IP filters", tasks)
        self.assertIn("'linux-tools-generic'", tasks)
        self.assertIn("cgroup_inet_ingress", tasks)
        self.assertIn("cgroup_inet_egress", tasks)
        self.assertEqual(
            argument_specs["tailscale_metrics_endpoint_timer_interval"]["type"],
            "int",
        )
        self.assertEqual(
            argument_specs[
                "tailscale_metrics_endpoint_require_default_ipv4_route"
            ]["type"],
            "bool",
        )
        self.assertEqual(
            argument_specs["tailscale_metrics_endpoint_require_self_online"]["type"],
            "bool",
        )

    def render_guard(
        self, confirmation_delay: int = 0, temp_dir: Path | None = None
    ) -> str:
        template_dir = ROOT / "roles/netplan_config/templates"
        context: dict[str, object] = {
            "netplan_config_route_guard_service_name": "netplan-route-guard",
            "netplan_config_route_guard_confirmation_delay_sec": confirmation_delay,
            "netplan_config_route_guard_recovery_delay_sec": 0,
            "netplan_config_route_guard_interfaces": ["enp1s0f1"],
        }
        rendered = (
            template_environment(template_dir)
            .get_template("netplan-route-guard.sh.j2")
            .render(**context)
        )
        if temp_dir is not None:
            rendered = rendered.replace(
                "/run/netplan-route-guard/lock", str(temp_dir / "lock")
            ).replace("/sys/class/net", str(temp_dir / "sys"))
        return rendered

    @staticmethod
    def install_fake_commands(bin_dir: Path, marker: Path) -> None:
        lock_marker = marker.with_suffix(".locks")
        (bin_dir / "flock").write_text(
            "#!/usr/bin/env python3\n"
            "import fcntl, pathlib, sys\n"
            "try:\n"
            "    fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except BlockingIOError:\n"
            "    raise SystemExit(1)\n"
            f"pathlib.Path({str(lock_marker)!r}).open('a').write('acquired\\n')\n"
        )
        (bin_dir / "networkctl").write_text(
            "#!/bin/sh\n"
            'if [ "$1" = status ]; then\n'
            "  printf '%s\\n' '{\"AdministrativeState\":\"configured\"}'\n"
            'elif [ "$1" = reconfigure ]; then\n'
            f"  printf 'reconfigure\\n' >> {shlex.quote(str(marker))}\n"
            '  sleep "${FAKE_RECONFIGURE_HOLD_SECONDS:-0.5}"\n'
            "fi\n"
        )
        (bin_dir / "ip").write_text(
            "#!/bin/sh\n"
            f"if [ -s {shlex.quote(str(marker))} ]; then\n"
            "  printf '%s\\n' 'default via 192.0.2.1 dev enp1s0f1'\n"
            "fi\n"
        )
        (bin_dir / "logger").write_text("#!/bin/sh\nexit 0\n")
        (bin_dir / "install").write_text(
            '#!/bin/sh\nfor target in "$@"; do :; done\nmkdir -p "$target"\n'
        )
        for command in bin_dir.iterdir():
            command.chmod(0o755)

    def guard_environment(self, temp_dir: Path, bin_dir: Path) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        }

    def test_route_guard_renders_valid_bash_and_sandbox_contract(self) -> None:
        template_dir = ROOT / "roles/netplan_config/templates"
        script = self.render_guard()
        completed = subprocess.run(
            ["bash", "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('networkctl reconfigure "${interface}"', script)
        self.assertIn('ip -4 route show default dev "$1"', script)
        self.assertIn("AdministrativeState", script)
        self.assertIn("Managed by local.ops_library.netplan_config", script)

        service = (
            template_environment(template_dir)
            .get_template("netplan-route-guard.service.j2")
            .render(
                netplan_config_route_guard_service_name="netplan-route-guard",
                netplan_config_route_guard_script_path="/usr/local/sbin/netplan-route-guard",
                netplan_config_route_guard_confirmation_delay_sec=5,
                netplan_config_route_guard_recovery_delay_sec=10,
                netplan_config_route_guard_interfaces=["enp1s0f1"],
            )
        )
        timer = (
            template_environment(template_dir)
            .get_template("netplan-route-guard.timer.j2")
            .render(
                netplan_config_route_guard_service_name="netplan-route-guard",
                netplan_config_route_guard_interval_sec=60,
            )
        )
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("RuntimeDirectory=netplan-route-guard", service)
        self.assertIn("RuntimeDirectoryMode=0700", service)
        self.assertIn("RuntimeDirectoryPreserve=yes", service)
        self.assertIn("Managed by local.ops_library.netplan_config", service)
        self.assertIn("TimeoutStartSec=75s", service)
        self.assertIn("/run/netplan-route-guard/lock", script)
        self.assertNotIn("Persistent=true", timer)
        self.assertIn("OnActiveSec=2min", timer)
        self.assertNotIn("OnBootSec=", timer)
        self.assertIn("Managed by local.ops_library.netplan_config", timer)

        two_interface_service = (
            template_environment(template_dir)
            .get_template("netplan-route-guard.service.j2")
            .render(
                netplan_config_route_guard_service_name="netplan-route-guard",
                netplan_config_route_guard_script_path="/usr/local/sbin/netplan-route-guard",
                netplan_config_route_guard_confirmation_delay_sec=5,
                netplan_config_route_guard_recovery_delay_sec=10,
                netplan_config_route_guard_interfaces=["eth0", "eth1"],
            )
        )
        self.assertIn("TimeoutStartSec=90s", two_interface_service)

        collector = (
            template_environment(ROOT / "roles/tailscale_metrics_endpoint/templates")
            .get_template("tailscale-metrics-collector.service.j2")
            .render(
                tailscale_metrics_endpoint_exporter_path="/usr/local/bin/exporter",
                tailscale_metrics_endpoint_json_path="/var/lib/tailscale-metrics/data.json",
                tailscale_metrics_endpoint_data_dir="/var/lib/tailscale-metrics",
                tailscale_metrics_endpoint_group="metrics",
            )
        )
        self.assertIn("AF_NETLINK", collector)

        endpoint = (
            template_environment(ROOT / "roles/tailscale_metrics_endpoint/templates")
            .get_template("tailscale-metrics-endpoint.service.j2")
            .render(
                tailscale_metrics_endpoint_user="metrics",
                tailscale_metrics_endpoint_group="metrics",
                tailscale_metrics_endpoint_server_path="/usr/local/bin/server",
                tailscale_metrics_endpoint_bind="127.0.0.1",
                tailscale_metrics_endpoint_port=9107,
                tailscale_metrics_endpoint_path="/.well-known/tailscale",
                tailscale_metrics_endpoint_json_path="/var/lib/tailscale-metrics/data.json",
                tailscale_metrics_endpoint_htpasswd_path="/etc/tailscale-metrics/htpasswd",
                tailscale_metrics_endpoint_ip_address_allow=[
                    "localhost",
                    "100.64.0.0/10",
                ],
                tailscale_metrics_endpoint_data_dir="/var/lib/tailscale-metrics",
                tailscale_metrics_endpoint_require_effective_ip_filter=True,
                tailscale_metrics_endpoint_bpftool_bin="/usr/sbin/bpftool",
            )
        )
        self.assertEqual(endpoint.count("IPAddressDeny=any"), 1)
        self.assertEqual(endpoint.count("IPAddressAllow="), 2)
        self.assertIn("IPAddressAllow=localhost", endpoint)
        self.assertIn("IPAddressAllow=100.64.0.0/10", endpoint)
        self.assertIn("ExecStartPre=+/bin/sh", endpoint)
        self.assertIn("cgroup_inet_ingress", endpoint)
        self.assertIn("cgroup_inet_egress", endpoint)

    def test_route_guard_task_graph_is_first_run_and_check_mode_safe(self) -> None:
        tasks = yaml.safe_load(
            (ROOT / "roles/netplan_config/tasks/main.yml").read_text()
        )
        handlers = yaml.safe_load(
            (ROOT / "roles/netplan_config/handlers/main.yml").read_text()
        )
        enable_task = next(
            task
            for task in tasks
            if task["name"] == "Enable and start default-route recovery timer"
        )
        self.assertIn("not ansible_check_mode", enable_task["when"])
        stop_task = next(
            task
            for task in tasks
            if task["name"] == "Stop and disable default-route recovery timer"
        )
        self.assertIn("not ansible_check_mode", stop_task["when"])
        inspect_handler = next(
            handler
            for handler in handlers
            if handler["name"] == "Inspect netplan route guard timer before restart"
        )
        self.assertEqual(
            inspect_handler["register"], "_netplan_route_guard_restart_timer"
        )
        restart_handler = next(
            handler
            for handler in handlers
            if handler["name"] == "Restart netplan route guard timer"
        )
        self.assertIn(
            "_netplan_route_guard_restart_timer.stat.exists",
            restart_handler["when"],
        )

    def test_route_guard_is_noop_without_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("0\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(marker.exists())

    def test_route_guard_reports_missing_interface_without_reconfigure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            bin_dir.mkdir()
            (temp_dir / "sys").mkdir()
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertFalse(marker.exists())

    def test_route_probe_error_does_not_reconfigure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "ip").write_text("#!/bin/sh\nexit 2\n")
            (bin_dir / "ip").chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertFalse(marker.exists())

    def test_transient_link_states_are_left_for_a_later_tick(self) -> None:
        for state in ("pending", "initialized", "configuring"):
            with (
                self.subTest(state=state),
                tempfile.TemporaryDirectory() as temp_dir_name,
            ):
                temp_dir = Path(temp_dir_name)
                bin_dir = temp_dir / "bin"
                carrier_dir = temp_dir / "sys/enp1s0f1"
                bin_dir.mkdir()
                carrier_dir.mkdir(parents=True)
                (carrier_dir / "carrier").write_text("1\n")
                marker = temp_dir / "reconfigured"
                self.install_fake_commands(bin_dir, marker)
                (bin_dir / "networkctl").write_text(
                    "#!/bin/sh\n"
                    f"printf '%s\\n' '{{\"AdministrativeState\":\"{state}\"}}'\n"
                )
                (bin_dir / "networkctl").chmod(0o755)
                script_path = temp_dir / "guard"
                script_path.write_text(self.render_guard(temp_dir=temp_dir))
                script_path.chmod(0o755)

                completed = subprocess.run(
                    [str(script_path)],
                    env=self.guard_environment(temp_dir, bin_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertFalse(marker.exists())

    def test_route_guard_serializes_overlapping_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)
            env = self.guard_environment(temp_dir, bin_dir)
            env["FAKE_RECONFIGURE_HOLD_SECONDS"] = "2"

            first = subprocess.Popen(
                [str(script_path)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            second = subprocess.run(
                [str(script_path)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            first_stdout, first_stderr = first.communicate(timeout=3)

            self.assertTrue(marker.exists(), first_stderr.decode())
            self.assertEqual(
                first.returncode, 0, first_stdout.decode() + first_stderr.decode()
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(marker.read_text().splitlines(), ["reconfigure"])
            self.assertEqual(
                marker.with_suffix(".locks").read_text().splitlines(), ["acquired"]
            )

    def test_route_guard_leaves_healthy_interface_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            marker.write_text("route-already-present\n")
            self.install_fake_commands(bin_dir, marker)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(marker.read_text(), "route-already-present\n")

    def test_route_guard_reports_reconfigure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "networkctl").write_text(
                "#!/bin/sh\n"
                'if [ "$1" = status ]; then\n'
                "  printf '%s\\n' '{\"AdministrativeState\":\"configured\"}'\n"
                "else\n"
                "  exit 1\n"
                "fi\n"
            )
            (bin_dir / "networkctl").chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)

    def test_failed_setup_state_triggers_reconfigure_with_route_present(self) -> None:
        for initial_state in ("failed",):
            with (
                self.subTest(initial_state=initial_state),
                tempfile.TemporaryDirectory() as temp_dir_name,
            ):
                temp_dir = Path(temp_dir_name)
                bin_dir = temp_dir / "bin"
                carrier_dir = temp_dir / "sys/enp1s0f1"
                bin_dir.mkdir()
                carrier_dir.mkdir(parents=True)
                (carrier_dir / "carrier").write_text("1\n")
                marker = temp_dir / "reconfigured"
                state_marker = temp_dir / "state-recovered"
                self.install_fake_commands(bin_dir, marker)
                (bin_dir / "ip").write_text(
                    "#!/bin/sh\nprintf '%s\\n' 'default via 192.0.2.1 dev enp1s0f1'\n"
                )
                (bin_dir / "networkctl").write_text(
                    "#!/bin/sh\n"
                    'if [ "$1" = status ]; then\n'
                    f"  if [ -e {shlex.quote(str(state_marker))} ]; then\n"
                    "    printf '%s\\n' "
                    '\'{"AdministrativeState":"configured"}\'\n'
                    "  else\n"
                    f"    printf '%s\\n' "
                    f'\'{{"AdministrativeState":"{initial_state}"}}\'\n'
                    "  fi\n"
                    "else\n"
                    f"  touch {shlex.quote(str(state_marker))}\n"
                    f"  printf 'reconfigure\\n' >> {shlex.quote(str(marker))}\n"
                    "fi\n"
                )
                for command in (bin_dir / "ip", bin_dir / "networkctl"):
                    command.chmod(0o755)
                script_path = temp_dir / "guard"
                script_path.write_text(self.render_guard(temp_dir=temp_dir))
                script_path.chmod(0o755)

                completed = subprocess.run(
                    [str(script_path)],
                    env=self.guard_environment(temp_dir, bin_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(marker.read_text().splitlines(), ["reconfigure"])

    def test_unmanaged_or_linger_with_route_present_is_untouched(self) -> None:
        for initial_state in ("unmanaged", "linger"):
            with (
                self.subTest(initial_state=initial_state),
                tempfile.TemporaryDirectory() as temp_dir_name,
            ):
                temp_dir = Path(temp_dir_name)
                bin_dir = temp_dir / "bin"
                carrier_dir = temp_dir / "sys/enp1s0f1"
                bin_dir.mkdir()
                carrier_dir.mkdir(parents=True)
                (carrier_dir / "carrier").write_text("1\n")
                marker = temp_dir / "reconfigured"
                self.install_fake_commands(bin_dir, marker)
                (bin_dir / "ip").write_text(
                    "#!/bin/sh\nprintf '%s\\n' 'default via 192.0.2.1 dev enp1s0f1'\n"
                )
                (bin_dir / "networkctl").write_text(
                    "#!/bin/sh\n"
                    f"printf '%s\\n' '{{\"AdministrativeState\":\"{initial_state}\"}}'\n"
                )
                for command in (bin_dir / "ip", bin_dir / "networkctl"):
                    command.chmod(0o755)
                script_path = temp_dir / "guard"
                script_path.write_text(self.render_guard(temp_dir=temp_dir))
                script_path.chmod(0o755)

                completed = subprocess.run(
                    [str(script_path)],
                    env=self.guard_environment(temp_dir, bin_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertFalse(marker.exists())

    def test_nonconverging_setup_state_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "ip").write_text(
                "#!/bin/sh\nprintf '%s\\n' 'default via 192.0.2.1 dev enp1s0f1'\n"
            )
            (bin_dir / "networkctl").write_text(
                "#!/bin/sh\n"
                'if [ "$1" = status ]; then\n'
                "  printf '%s\\n' '{\"AdministrativeState\":\"failed\"}'\n"
                "else\n"
                f"  printf 'reconfigure\\n' >> {shlex.quote(str(marker))}\n"
                "fi\n"
            )
            for command in (bin_dir / "ip", bin_dir / "networkctl"):
                command.chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(marker.read_text().splitlines(), ["reconfigure"])

    def test_recovery_incomplete_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "ip").write_text("#!/bin/sh\nexit 0\n")
            (bin_dir / "ip").chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(marker.read_text().splitlines(), ["reconfigure"])

    def test_transient_missing_route_is_confirmed_before_reconfigure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            probe_counter = temp_dir / "probe-counter"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "ip").write_text(
                "#!/bin/sh\n"
                f"if [ -e {shlex.quote(str(probe_counter))} ]; then\n"
                "  printf '%s\\n' 'default via 192.0.2.1 dev enp1s0f1'\n"
                "else\n"
                f"  touch {shlex.quote(str(probe_counter))}\n"
                "fi\n"
            )
            (bin_dir / "ip").chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(
                self.render_guard(confirmation_delay=1, temp_dir=temp_dir)
            )
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(marker.exists())

    def test_carrier_drop_during_confirmation_skips_reconfigure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            carrier_path = carrier_dir / "carrier"
            carrier_path.write_text("1\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "ip").write_text("#!/bin/sh\nexit 0\n")
            (bin_dir / "sleep").write_text(
                f"#!/bin/sh\nprintf '0\\n' > {shlex.quote(str(carrier_path))}\n"
            )
            for command in (bin_dir / "ip", bin_dir / "sleep"):
                command.chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(
                self.render_guard(confirmation_delay=1, temp_dir=temp_dir)
            )
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(marker.exists())

    def test_unreadable_carrier_state_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "cat").write_text("#!/bin/sh\nexit 1\n")
            (bin_dir / "cat").chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertFalse(marker.exists())

    def test_administratively_down_interface_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            (carrier_dir / "operstate").write_text("down\n")
            marker = temp_dir / "reconfigured"
            log = temp_dir / "guard.log"
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "cat").write_text(
                "#!/bin/sh\n"
                'case "$1" in\n'
                "  */carrier) exit 1 ;;\n"
                "  */operstate) printf 'down\\n' ;;\n"
                "esac\n"
            )
            (bin_dir / "cat").chmod(0o755)
            (bin_dir / "logger").write_text(
                f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {shlex.quote(str(log))}\n"
            )
            (bin_dir / "logger").chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(marker.exists())
            self.assertIn("carrier is absent", log.read_text())

    def test_missing_networkctl_state_is_reported_without_reconfigure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            bin_dir = temp_dir / "bin"
            carrier_dir = temp_dir / "sys/enp1s0f1"
            bin_dir.mkdir()
            carrier_dir.mkdir(parents=True)
            (carrier_dir / "carrier").write_text("1\n")
            marker = temp_dir / "reconfigured"
            marker.write_text("route-already-present\n")
            self.install_fake_commands(bin_dir, marker)
            (bin_dir / "networkctl").write_text("#!/bin/sh\nprintf '%s\\n' '{}'\n")
            (bin_dir / "networkctl").chmod(0o755)
            script_path = temp_dir / "guard"
            script_path.write_text(self.render_guard(temp_dir=temp_dir))
            script_path.chmod(0o755)

            completed = subprocess.run(
                [str(script_path)],
                env=self.guard_environment(temp_dir, bin_dir),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(marker.read_text(), "route-already-present\n")


class TailscaleMetricsExporterTemplateTests(unittest.TestCase):
    def run_exporter(
        self,
        *,
        online: bool,
        route_output: str,
        require_route: bool,
        route_rc: int = 0,
        require_self_online: bool = True,
    ) -> dict[str, object]:
        template_dir = ROOT / "roles/tailscale_metrics_endpoint/templates"
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            tailscale_bin = temp_dir / "tailscale"
            tailscale_bin.write_text(
                "#!/bin/sh\n"
                f'printf \'%s\\n\' \'{{"BackendState":"Running","Self":{{"Online":{str(online).lower()}}}}}\'\n'
            )
            tailscale_bin.chmod(0o755)
            ip_bin = temp_dir / "ip"
            ip_bin.write_text(
                f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(route_output)}\nexit {route_rc}\n"
            )
            ip_bin.chmod(0o755)

            exporter = (
                template_environment(template_dir)
                .get_template("tailscale_metrics_exporter.py.j2")
                .render(
                    tailscale_metrics_endpoint_tailscale_bin=str(tailscale_bin),
                    tailscale_metrics_endpoint_ip_bin=str(ip_bin),
                    tailscale_metrics_endpoint_default_route_interface="enp1s0f1",
                    tailscale_metrics_endpoint_require_default_ipv4_route=require_route,
                    tailscale_metrics_endpoint_require_self_online=require_self_online,
                    tailscale_metrics_endpoint_warning_days=3,
                    tailscale_metrics_endpoint_critical_days=1,
                )
            )
            exporter_path = temp_dir / "exporter.py"
            exporter_path.write_text(exporter)
            completed = subprocess.run(
                ["python3", str(exporter_path)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_offline_node_and_missing_route_are_reported(self) -> None:
        payload = self.run_exporter(online=False, route_output="", require_route=True)
        self.assertTrue(payload["summary"]["backend_running"])
        self.assertFalse(payload["summary"]["self_online"])
        self.assertFalse(payload["summary"]["default_ipv4_route_present"])
        self.assertFalse(payload["summary"]["overall_ok"])
        self.assertEqual(payload["network"]["default_ipv4_route_interface"], "enp1s0f1")

    def test_healthy_node_and_route_report_overall_ok(self) -> None:
        payload = self.run_exporter(
            online=True,
            route_output="default via 192.0.2.1 dev enp1s0f1",
            require_route=True,
        )
        self.assertTrue(payload["summary"]["default_ipv4_route_present"])
        self.assertTrue(payload["summary"]["overall_ok"])

    def test_disabled_route_requirement_skips_empty_route(self) -> None:
        payload = self.run_exporter(online=True, route_output="", require_route=False)
        self.assertFalse(payload["network"]["default_ipv4_route_required"])
        self.assertTrue(payload["summary"]["default_ipv4_route_present"])
        self.assertTrue(payload["summary"]["overall_ok"])

    def test_route_probe_command_error_is_unhealthy(self) -> None:
        payload = self.run_exporter(
            online=True,
            route_output="netlink unavailable",
            require_route=True,
            route_rc=2,
        )
        self.assertFalse(payload["summary"]["default_ipv4_route_present"])
        self.assertFalse(payload["summary"]["overall_ok"])

    def test_self_online_is_compatible_when_not_required(self) -> None:
        payload = self.run_exporter(
            online=False,
            route_output="",
            require_route=False,
            require_self_online=False,
        )
        self.assertFalse(payload["summary"]["self_online"])
        self.assertTrue(payload["summary"]["overall_ok"])

    def test_required_self_online_failure_controls_overall_health(self) -> None:
        payload = self.run_exporter(
            online=False,
            route_output="",
            require_route=False,
            require_self_online=True,
        )
        self.assertFalse(payload["summary"]["self_online"])
        self.assertFalse(payload["summary"]["overall_ok"])


if __name__ == "__main__":
    unittest.main()
