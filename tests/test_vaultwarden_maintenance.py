"""Safety contracts for the Vaultwarden maintenance (ingress deny) switch.

The switch runs inside a maintenance window and its whole value rests on two
properties: it must never write the router file the Echoport backup archives,
and it must not do anything to packages or services while it is on.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "vaultwarden_maintenance"

HOSTNAME = "vault.example.invalid"
ALLOW_RANGES = ["127.0.0.1/32", "::1/128"]


def render_router(**overrides: object) -> dict:
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    context: dict[str, object] = {
        "vaultwarden_maintenance_hostname": HOSTNAME,
        "vaultwarden_maintenance_router_priority": 100000,
        "vaultwarden_maintenance_traefik_entrypoint": "web-secure",
        "vaultwarden_maintenance_allow_source_ranges": ALLOW_RANGES,
        "vaultwarden_maintenance_websocket_enabled": True,
    }
    context.update(overrides)
    rendered = environment.get_template(
        "traefik-vaultwarden-maintenance.yml.j2"
    ).render(**context)
    return yaml.safe_load(rendered)


def load_yaml(relative: str) -> object:
    return yaml.safe_load((ROLE / relative).read_text(encoding="utf-8"))


def flatten(tasks: list[dict]) -> list[dict]:
    """Expand block/rescue/always so task lookups are structure-independent."""
    flat: list[dict] = []
    for task in tasks:
        nested = False
        for section in ("block", "rescue", "always"):
            if section in task:
                flat.extend(flatten(task[section]))
                nested = True
        if not nested:
            flat.append(task)
    return flat


def task_modules(tasks: list[dict]) -> set[str]:
    reserved = {
        "name",
        "when",
        "loop",
        "loop_control",
        "register",
        "changed_when",
        "failed_when",
        "check_mode",
        "become",
        "become_user",
        "delegate_to",
        "retries",
        "delay",
        "until",
        "notify",
        "tags",
        "vars",
        "args",
        "no_log",
        "environment",
        "ignore_errors",
    }
    modules: set[str] = set()
    for task in tasks:
        modules.update(key for key in task if key not in reserved)
    return modules


class RouterContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = render_router()

    def test_router_outranks_the_deploy_roles_routers(self) -> None:
        router = self.router["http"]["routers"]["vaultwarden-maintenance"]
        # The deploy role's routers use Traefik's default priority, which is the
        # rule length; its websocket rule is the longest.
        self.assertGreater(router["priority"], 1000)
        self.assertEqual(router["rule"], f"Host(`{HOSTNAME}`)")

    def test_denial_is_an_allow_list_not_an_error_page(self) -> None:
        middlewares = self.router["http"]["middlewares"]
        allow_list = middlewares["vaultwarden-maintenance-deny"]["ipAllowList"]
        self.assertEqual(allow_list["sourceRange"], ALLOW_RANGES)
        router = self.router["http"]["routers"]["vaultwarden-maintenance"]
        self.assertEqual(router["middlewares"], ["vaultwarden-maintenance-deny"])

    def test_allowed_sources_still_reach_the_real_service(self) -> None:
        # This is the operator verification path during a freeze.
        router = self.router["http"]["routers"]["vaultwarden-maintenance"]
        self.assertEqual(router["service"], "vaultwarden")

    def test_allow_listed_clients_keep_websocket_live_sync(self) -> None:
        # Without a mirrored websocket router the Host-only router above would
        # swallow /notifications/hub and send it to the HTTP service.
        routers = self.router["http"]["routers"]
        websocket = routers["vaultwarden-maintenance-ws"]
        self.assertEqual(websocket["service"], "vaultwarden-ws")
        self.assertIn("/notifications/hub", websocket["rule"])
        self.assertGreater(
            websocket["priority"], routers["vaultwarden-maintenance"]["priority"]
        )
        self.assertEqual(websocket["middlewares"], ["vaultwarden-maintenance-deny"])

    def test_websocket_router_can_be_disabled(self) -> None:
        router = render_router(vaultwarden_maintenance_websocket_enabled=False)
        self.assertNotIn(
            "vaultwarden-maintenance-ws", router["http"]["routers"]
        )

    def test_router_declares_no_service_or_middleware_of_the_deploy_role(self) -> None:
        # Redefining the deploy role's objects would make the merged Traefik
        # configuration order-dependent.
        self.assertEqual(
            set(self.router["http"]["routers"]),
            {"vaultwarden-maintenance", "vaultwarden-maintenance-ws"},
        )
        self.assertEqual(
            set(self.router["http"]["middlewares"]), {"vaultwarden-maintenance-deny"}
        )
        self.assertNotIn("services", self.router["http"])

    def test_allow_ranges_are_rendered_verbatim(self) -> None:
        router = render_router(
            vaultwarden_maintenance_allow_source_ranges=["10.1.2.3/32"]
        )
        allow_list = router["http"]["middlewares"]["vaultwarden-maintenance-deny"]
        self.assertEqual(allow_list["ipAllowList"]["sourceRange"], ["10.1.2.3/32"])


class HostnameDerivationTests(unittest.TestCase):
    """Evaluate the derivation, not just its presence.

    A string-matching test cannot catch a pattern that Python's `re` rejects at
    runtime, which is exactly how an inline-flag bug reached a live run.
    """

    @staticmethod
    def _expressions() -> tuple[list[str], str]:
        tasks = load_yaml("tasks/validate.yml")
        derive = next(
            task for task in tasks if "Derive hostname" in task["name"]
        )
        expression = derive["ansible.builtin.set_fact"][
            "vaultwarden_maintenance_hostname"
        ]
        patterns = re.findall(r"regex_replace\('([^']*)',\s*'([^']*)'\)", expression)
        guard = next(task for task in tasks if "bare hostname" in task["name"])
        accept = re.search(
            r"is match\(\s*'([^']*)'", " ".join(guard["ansible.builtin.assert"]["that"])
        )
        assert accept is not None
        return patterns, accept.group(1).replace("\\\\", "\\")

    def derive(self, domain: str) -> str:
        patterns, _ = self._expressions()
        value = domain
        for pattern, replacement in patterns:
            value = re.sub(pattern, replacement, value)
        return value.strip()

    def accepted(self, domain: str) -> bool:
        _, accept = self._expressions()
        return bool(re.match(accept, self.derive(domain)))

    def test_patterns_compile(self) -> None:
        patterns, accept = self._expressions()
        for pattern, _ in patterns:
            re.compile(pattern)
        re.compile(accept)

    def test_ordinary_domain_yields_its_hostname(self) -> None:
        self.assertEqual(
            self.derive("https://vault.home.xn--wersdrfer-47a.de"),
            "vault.home.xn--wersdrfer-47a.de",
        )
        self.assertTrue(self.accepted("https://vault.home.xn--wersdrfer-47a.de"))

    def test_uppercase_scheme_is_stripped(self) -> None:
        self.assertEqual(self.derive("HTTPS://vault.example.com"), "vault.example.com")

    def test_only_https_domains_are_accepted(self) -> None:
        # The maintenance router always terminates TLS, so an http:// probe
        # would test a redirect rather than the maintenance rule.
        guard = next(
            task
            for task in load_yaml("tasks/validate.yml")
            if "bare https host URL" in task["name"]
        )
        condition = " ".join(guard["ansible.builtin.assert"]["that"])
        self.assertIn("^https://", condition)
        self.assertNotIn("https?", condition)

    def test_a_host_that_would_not_match_traefik_is_refused(self) -> None:
        # Each of these would render a Host rule matching nothing, so the freeze
        # would deny nothing while appearing applied.
        for domain in (
            "https://vault.example.com:8443",
            "HTTPS://Vault.example.com",
            "https://",
        ):
            self.assertFalse(self.accepted(domain), domain)


class SwitchSafetyTests(unittest.TestCase):
    def test_default_file_is_not_the_archived_router_file(self) -> None:
        defaults = load_yaml("defaults/main.yml")
        self.assertNotEqual(
            defaults["vaultwarden_maintenance_filename"].strip(),
            defaults["vaultwarden_maintenance_archived_router_filename"].strip(),
        )

    def test_paths_are_built_from_filenames_not_caller_paths(self) -> None:
        # Filenames only, so no caller value can normalise into the archived
        # router file via "./", "//", or "..".
        defaults = load_yaml("defaults/main.yml")
        for key in (
            "vaultwarden_maintenance_filename",
            "vaultwarden_maintenance_archived_router_filename",
        ):
            self.assertNotIn("/", defaults[key])
        text = (ROLE / "tasks" / "validate.yml").read_text(encoding="utf-8")
        self.assertIn("path_join", text)
        self.assertIn("'..' not in item", text)

    def test_default_state_is_off(self) -> None:
        defaults = load_yaml("defaults/main.yml")
        self.assertEqual(defaults["vaultwarden_maintenance_state"], "absent")

    def test_validation_guards_the_archived_router_file(self) -> None:
        text = (ROLE / "tasks" / "validate.yml").read_text(encoding="utf-8")
        self.assertIn("vaultwarden_maintenance_archived_router_filename", text)
        self.assertIn("!=", text)

    def test_boolean_switches_and_port_list_are_validated(self) -> None:
        tasks = load_yaml("tasks/validate.yml")
        booleans = next(
            task for task in tasks if "boolean switches" in task["name"]
        )
        checked = {entry["key"] for entry in booleans["loop"]}
        self.assertIn("vaultwarden_maintenance_verify_external", checked)
        self.assertIn("vaultwarden_maintenance_probe_expects_denial", checked)
        self.assertIn("vaultwarden_maintenance_accept_unverified_denial", checked)
        ports = next(
            task for task in tasks if "at least one port" in task["name"]
        )
        self.assertIn(
            "vaultwarden_maintenance_loopback_ports | length > 0",
            ports["ansible.builtin.assert"]["that"],
        )

    def test_a_changed_configuration_settles_before_the_probe(self) -> None:
        # Otherwise a probe fired immediately can be answered by the old router.
        tasks = load_yaml("tasks/verify.yml")
        names = [task["name"] for task in tasks]
        settle_index = next(
            index for index, name in enumerate(names) if "Let Traefik load" in name
        )
        probe_index = next(
            index for index, task in enumerate(tasks) if "ansible.builtin.uri" in task
        )
        self.assertLess(settle_index, probe_index)
        settle = tasks[settle_index]
        self.assertIn(
            "vaultwarden_maintenance_settle_seconds",
            settle["ansible.builtin.wait_for"]["timeout"],
        )

    def test_probe_url_is_built_from_validated_parts(self) -> None:
        # Never from the raw domain: an accepted path would probe elsewhere.
        probe = next(
            task
            for task in load_yaml("tasks/verify.yml")
            if "ansible.builtin.uri" in task
        )
        self.assertEqual(
            probe["ansible.builtin.uri"]["url"],
            "{{ vaultwarden_maintenance_probe_url }}",
        )
        build = next(
            task
            for task in load_yaml("tasks/validate.yml")
            if "probe URL" in task["name"]
        )
        expression = build["ansible.builtin.set_fact"][
            "vaultwarden_maintenance_probe_url"
        ]
        self.assertIn("vaultwarden_maintenance_hostname", expression)
        self.assertIn("/alive", expression)

    def test_a_domain_that_is_not_a_bare_hostname_is_refused(self) -> None:
        # A non-matching Host rule is a freeze that denies nothing.
        guard = next(
            task
            for task in load_yaml("tasks/validate.yml")
            if "bare hostname" in task["name"]
        )
        self.assertIn(
            "vaultwarden_maintenance_hostname",
            " ".join(guard["ansible.builtin.assert"]["that"]),
        )

    def test_check_mode_previews_rather_than_failing_a_pending_change(self) -> None:
        probe = next(
            task
            for task in load_yaml("tasks/verify.yml")
            if "ansible.builtin.uri" in task
        )
        self.assertIn(
            "not vaultwarden_maintenance_pending_change | bool",
            [str(condition) for condition in probe["when"]],
        )

    def test_pending_change_is_content_aware_not_existence_only(self) -> None:
        # An existing file whose hostname or allow list changed is still pending.
        resolve = next(
            task
            for task in load_yaml("tasks/main.yml")
            if "check mode left a change unapplied" in task["name"]
        )
        expression = resolve["ansible.builtin.set_fact"][
            "vaultwarden_maintenance_pending_change"
        ]
        self.assertIn("vaultwarden_maintenance_applied.changed", expression)
        self.assertIn("vaultwarden_maintenance_removed.changed", expression)
        self.assertNotIn("stat", expression)

    def test_report_admits_when_nothing_was_verified(self) -> None:
        text = (ROLE / "tasks" / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("NOTHING was verified", text)

    def test_role_touches_no_packages_services_or_repositories(self) -> None:
        modules: set[str] = set()
        for name in ("main.yml", "validate.yml", "verify.yml"):
            modules.update(task_modules(flatten(load_yaml(f"tasks/{name}"))))
        forbidden = {
            "ansible.builtin.apt",
            "ansible.builtin.apt_repository",
            "ansible.builtin.apt_key",
            "ansible.builtin.package",
            "ansible.builtin.systemd",
            "ansible.builtin.service",
            "ansible.builtin.dpkg_selections",
        }
        self.assertEqual(modules & forbidden, set())

    def test_role_defines_no_handlers(self) -> None:
        # A restart during a maintenance window is risk without benefit.
        self.assertFalse((ROLE / "handlers").exists())

    def test_both_states_are_implemented_and_verified(self) -> None:
        tasks = load_yaml("tasks/main.yml")
        conditions = [str(task.get("when", "")) for task in tasks]
        self.assertTrue(any("== 'present'" in item for item in conditions))
        self.assertTrue(any("== 'absent'" in item for item in conditions))
        imports = [
            task.get("ansible.builtin.import_tasks")
            for task in tasks
            if "ansible.builtin.import_tasks" in task
        ]
        self.assertIn("verify.yml", imports)
        # Verification is unconditional: every run proves the resulting state.
        verify_task = next(
            task
            for task in tasks
            if task.get("ansible.builtin.import_tasks") == "verify.yml"
        )
        self.assertNotIn("when", verify_task)

    def test_an_unobservable_freeze_is_refused(self) -> None:
        defaults = load_yaml("defaults/main.yml")
        self.assertTrue(defaults["vaultwarden_maintenance_probe_expects_denial"])
        self.assertFalse(defaults["vaultwarden_maintenance_accept_unverified_denial"])
        guard = next(
            task
            for task in load_yaml("tasks/validate.yml")
            if "Refuse an unobservable freeze" in task["name"]
        )
        self.assertIn(
            "vaultwarden_maintenance_state == 'present'",
            [str(condition) for condition in guard["when"]],
        )

    def test_probe_expectation_follows_the_declared_vantage_point(self) -> None:
        resolve = next(
            task
            for task in load_yaml("tasks/verify.yml")
            if "Resolve the expected probe status" in task["name"]
        )
        expression = resolve["ansible.builtin.set_fact"][
            "vaultwarden_maintenance_expected_status"
        ]
        self.assertIn("vaultwarden_maintenance_probe_expects_denial", expression)
        self.assertIn("vaultwarden_maintenance_denied_status", expression)

    def test_verification_probes_externally_and_checks_listeners(self) -> None:
        tasks = load_yaml("tasks/verify.yml")
        text = (ROLE / "tasks" / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("ss", str(tasks))
        self.assertIn("vaultwarden_maintenance_denied_status", text)
        probe = next(
            task for task in tasks if "ansible.builtin.uri" in task
        )
        self.assertIn("vaultwarden_maintenance_probe_delegate", probe["delegate_to"])
        self.assertEqual(
            probe["ansible.builtin.uri"]["url"],
            "{{ vaultwarden_maintenance_probe_url }}",
        )


class DeployPinningTests(unittest.TestCase):
    """Gate 20: the deploy role must be able to pin and hold its packages."""

    def setUp(self) -> None:
        self.deploy = ROOT / "roles" / "vaultwarden_deploy"
        self.defaults = yaml.safe_load(
            (self.deploy / "defaults" / "main.yml").read_text(encoding="utf-8")
        )
        self.packages_raw = yaml.safe_load(
            (self.deploy / "tasks" / "packages.yml").read_text(encoding="utf-8")
        )
        self.packages = flatten(self.packages_raw)

    def test_pinning_is_off_by_default(self) -> None:
        self.assertEqual(self.defaults["vaultwarden_package_version"], "")
        self.assertEqual(self.defaults["vaultwarden_web_vault_package_version"], "")

    def test_hold_is_unmanaged_by_default(self) -> None:
        # An externally applied hold must survive an ordinary deploy run.
        self.assertIsNone(self.defaults["vaultwarden_packages_hold"])
        converge = next(
            task
            for task in self.packages
            if "Converge apt hold state" in task["name"]
        )
        self.assertIn(
            "vaultwarden_packages_hold is not none",
            [str(condition) for condition in converge["when"]],
        )

    def test_the_hold_is_never_released_to_install_a_pinned_version(self) -> None:
        # No unhold/re-hold window: apt is permitted to move a held package
        # only when an exact version was requested.
        names = [task["name"] for task in self.packages]
        self.assertFalse(any("Release apt hold" in name for name in names))
        install = next(
            task for task in self.packages if "Install Vaultwarden packages" in task["name"]
        )
        apt = install["ansible.builtin.apt"]
        self.assertEqual(
            apt["allow_change_held_packages"], "{{ vaultwarden_packages_pinned | bool }}"
        )
        self.assertEqual(
            apt["allow_downgrade"], "{{ vaultwarden_packages_pinned | bool }}"
        )

    def test_hold_is_converged_in_both_directions_when_owned(self) -> None:
        converge = next(
            task
            for task in self.packages
            if "Converge apt hold state" in task["name"]
        )
        selection = converge["ansible.builtin.dpkg_selections"]["selection"]
        self.assertIn("hold", selection)
        self.assertIn("install", selection)

    def test_a_non_boolean_hold_flag_is_refused(self) -> None:
        validate = yaml.safe_load(
            (self.deploy / "tasks" / "validate.yml").read_text(encoding="utf-8")
        )
        guard = next(
            task for task in validate if "apt hold flag" in task["name"]
        )
        condition = " ".join(guard["ansible.builtin.assert"]["that"])
        self.assertIn("is none", condition)
        self.assertIn("is boolean", condition)

    def test_a_mixed_pin_is_refused(self) -> None:
        validate = yaml.safe_load(
            (self.deploy / "tasks" / "validate.yml").read_text(encoding="utf-8")
        )
        guard = next(
            task
            for task in validate
            if "pinned together" in task["name"]
        )
        condition = " ".join(guard["ansible.builtin.assert"]["that"])
        self.assertIn("vaultwarden_package_version | length > 0", condition)
        self.assertIn("vaultwarden_web_vault_package_version | length > 0", condition)
        self.assertIn("==", condition)

    def test_an_incomplete_version_query_fails(self) -> None:
        # The report is what a gate records; an empty list must not pass as it.
        names = [task["name"] for task in self.packages]
        self.assertTrue(
            any("Require a version for every managed package" in n for n in names)
        )
        read = next(
            task
            for task in self.packages
            if "Read installed package versions" in task["name"]
        )
        self.assertNotIn("failed_when", read)

    def test_installed_versions_are_reported_for_the_gate_record(self) -> None:
        names = [task["name"] for task in self.packages]
        self.assertTrue(any("Read installed package versions" in n for n in names))
        self.assertTrue(any("Report installed package versions" in n for n in names))

    def test_pins_are_verified_after_the_hold_is_applied(self) -> None:
        # Closes the window where a concurrent apt could upgrade between the
        # install and the hold, leaving an unrequested version held.
        names = [task["name"] for task in self.packages]
        self.assertLess(
            names.index("packages | Converge apt hold state"),
            names.index("packages | Verify the held versions are the requested pins"),
        )
        verify = next(
            task
            for task in self.packages
            if "Verify the held versions" in task["name"]
        )
        self.assertIn(
            "vaultwarden_packages_pinned | bool",
            [str(condition) for condition in verify["when"]],
        )


if __name__ == "__main__":
    unittest.main()
