"""The Daybook operations backup registration issues revocable FastDeploy tokens.

Tokens come from FastDeploy's ``commands.py issueservicetoken`` (recorded, with
``jti``) instead of ``deploy.auth.create_access_token``, and only when the token
stored in Echoport has to be replaced.
"""

import base64
import importlib.util
import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/daybook_operations_api_backup"
SPEC = importlib.util.spec_from_file_location("service_token_status", ROLE / "files/service_token_status.py")
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)

NOW = 1_800_000_000
DAY = 86400
SERVICE = "daybook-operations-backup"


def jwt(claims):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256'})}.{part(claims)}.signature"


def claims(**overrides):
    return {"type": "service", "service": SERVICE, "user": "admin", "jti": "abc123", "exp": NOW + 60 * DAY, **overrides}


def jwt_patterns(text):
    """Every JWT format pattern in a task file, exactly as written.

    Ansible passes backslashes in these YAML/Jinja strings through unchanged
    (``\\\\.`` stays a literal backslash), so the patterns must not rely on
    escapes: separators are written as ``[.]``.
    """
    import re

    return re.findall(r"'(\^\[A-Za-z0-9_-\][^']*)'", text)


class RotationDecisionTests(unittest.TestCase):
    def reason(self, token):
        return status.rotation_reason(token, SERVICE, 30, NOW)

    def test_recorded_token_valid_beyond_the_renewal_window_is_reused(self):
        self.assertIsNone(self.reason(jwt(claims())))

    def test_legacy_token_without_jti_is_rotated(self):
        legacy = claims()
        del legacy["jti"]
        self.assertEqual(self.reason(jwt(legacy)), "legacy_without_jti")
        self.assertEqual(self.reason(jwt(claims(jti=""))), "legacy_without_jti")

    def test_expiring_wrong_scope_missing_and_garbage_tokens_are_rotated(self):
        self.assertEqual(self.reason(jwt(claims(exp=NOW + 30 * DAY))), "expiring")
        self.assertEqual(self.reason(jwt(claims(exp=NOW - DAY))), "expiring")
        self.assertEqual(self.reason(jwt(claims(service="other"))), "wrong_scope")
        self.assertEqual(self.reason(jwt(claims(type="user"))), "wrong_scope")
        self.assertEqual(self.reason(jwt({k: v for k, v in claims().items() if k != "exp"})), "no_expiry")
        self.assertEqual(self.reason(""), "missing")
        self.assertEqual(self.reason(None), "missing")
        for garbage in ("not-a-jwt", "a.!!!.c", "a." + base64.urlsafe_b64encode(b"[1]").decode() + ".c"):
            self.assertEqual(self.reason(garbage), "undecodable")

    def test_truncated_or_unsigned_tokens_are_not_reused(self):
        header, payload, _signature = jwt(claims()).split(".")
        for broken in (f"{header}.{payload}", f"{header}.{payload}.", f".{payload}.sig", f"{header}.{payload}.sig.extra", f"{header}.{payload}.sig\n", f"{header}.{payload}.s g"):
            with self.subTest(token=broken):
                self.assertEqual(self.reason(broken), "undecodable")

    def test_status_never_contains_the_token(self):
        token = jwt(claims())
        report = status.token_status(token, SERVICE, 30, NOW)
        self.assertNotIn(token, json.dumps(report))
        self.assertEqual(report["previous_jti"], "abc123")
        self.assertFalse(report["requires_rotation"])
        self.assertTrue(status.token_status("", SERVICE, 30, NOW)["requires_rotation"])


class RegistrationTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROLE / "tasks/register_echoport.yml").read_text()
        cls.tasks = yaml.safe_load(cls.text)
        cls.by_name = {task["name"]: task for task in cls.tasks}
        cls.names = [task["name"] for task in cls.tasks]
        cls.defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())

    def test_no_role_mints_tokens_with_create_access_token(self):
        offenders = [str(path.relative_to(ROOT)) for path in (ROOT / "roles").rglob("*") if path.is_file() and "create_access_token" in path.read_text(errors="ignore")]
        self.assertEqual(offenders, [])

    def test_token_is_issued_through_the_registry_with_argv_and_no_log(self):
        issue = self.by_name["register_echoport | Issue a revocable token scoped to the backup bridge"]
        argv = issue["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[1:3], ["commands.py", "issueservicetoken"])
        for flag in ("--service", "--user", "--days", "--origin"):
            self.assertIn(flag, argv)
        self.assertTrue(issue["no_log"])
        self.assertEqual(issue["become_user"], "fastdeploy")
        self.assertIn("requires_rotation", issue["when"])
        self.assertIn("daybook_operations_api_backup_rotate_service_token", issue["when"])

    def test_every_task_that_reads_the_token_has_no_log(self):
        readers = [task for task in self.tasks if "daybook_operations_api_backup_service_token.stdout" in yaml.safe_dump(task)]
        self.assertGreaterEqual(len(readers), 2)
        for task in readers:
            with self.subTest(task=task["name"]):
                self.assertTrue(task.get("no_log"))

    def test_stored_token_is_inspected_before_issuing_and_kept_when_valid(self):
        self.assertLess(
            self.names.index("register_echoport | Inspect the FastDeploy token stored in Echoport"),
            self.names.index("register_echoport | Issue a revocable token scoped to the backup bridge"),
        )
        self.assertLess(
            self.names.index("register_echoport | Require exactly one JWT from issueservicetoken"),
            self.names.index("register_echoport | Register the backup schedule and retention in Echoport"),
        )
        inspect = self.by_name["register_echoport | Inspect the FastDeploy token stored in Echoport"]
        self.assertFalse(inspect.get("no_log", False))
        self.assertIn("service_token_status.py", inspect["ansible.builtin.command"]["stdin"])
        upsert = self.by_name["register_echoport | Register the backup schedule and retention in Echoport"]["ansible.builtin.command"]["stdin"]
        self.assertIn("if issued_token:", upsert)

    def test_lifetime_over_90_days_is_refused_before_any_change(self):
        validate = self.by_name["register_echoport | Validate the FastDeploy service token settings"]
        self.assertIn("daybook_operations_api_backup_token_days | int <= 90", validate["ansible.builtin.assert"]["that"])
        self.assertLess(
            self.names.index(validate["name"]),
            self.names.index("register_echoport | Create root-controlled runner and upload directories"),
        )

    def test_lifetime_defaults_stay_within_the_fastdeploy_cap(self):
        self.assertLessEqual(self.defaults["daybook_operations_api_backup_token_days"], 90)
        self.assertLess(
            self.defaults["daybook_operations_api_backup_token_renewal_days"],
            self.defaults["daybook_operations_api_backup_token_days"],
        )
        self.assertEqual(self.defaults["daybook_operations_api_backup_token_user"], "")
        self.assertFalse(self.defaults["daybook_operations_api_backup_rotate_service_token"])

    def test_jwt_format_checks_accept_a_jwt_after_jinja_unescaping(self):
        import re

        patterns = jwt_patterns(self.text)
        self.assertTrue(patterns)
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertNotIn("\\", pattern)
                self.assertIsNotNone(re.match(pattern, "aGVhZA.cGF5bG9hZA.c2ln-_x"))
                self.assertIsNone(re.match(pattern, "aGVhZAXcGF5bG9hZAXc2ln"))
                self.assertIsNone(re.match(pattern, "a.b.c\nd.e.f"))


if __name__ == "__main__":
    unittest.main()
