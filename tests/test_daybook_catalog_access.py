"""Tests for the MinIO identity the Daybook vault catalogue writes with."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "catalog_writer",
    ROOT / "roles/daybook_catalog_access_deploy/files/provision_catalog.py",
)
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)


class FakeMC:
    def __init__(self):
        self.policy = None
        self.user = None
        self.policies = []
        self.calls = []

    def call(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command == "policy info":
            if self.policy is None:
                return None
            return {"status": "success", "policyInfo": {"Policy": copy.deepcopy(self.policy)}}
        if command == "user info":
            return copy.deepcopy(self.user)
        if command == "policy entities":
            return {"status": "success", "result": {"userMappings": [
                {"user": self.user["accessKey"], "policies": self.policies}
            ]}}
        if command == "policy create":
            self.policy = json.loads(kwargs["path"].read_text())
        elif command == "user add":
            access, _secret = kwargs["stdin"].splitlines()
            self.user = {"accessKey": access, "userStatus": "enabled", "policyName": ""}
        elif command == "policy attach":
            self.user["policyName"] = source.POLICY_NAME
            self.policies = [source.POLICY_NAME]
        else:
            raise AssertionError(command)
        return {"status": "success"}

    def mutations(self):
        return [name for name, _ in self.calls
                if name in ("policy create", "user add", "policy attach")]


class WorkSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name).resolve()
        self.state.chmod(0o700)
        self.request = {
            "access_key": "daybook-catalog-abcdefghijklmn",
            "secret_key": "synthetic-secret-" + "x" * 32,
            "mc_bin": "/usr/local/bin/mc",
            "alias": "local",
            "state_dir": str(self.state),
        }
        self.mc = FakeMC()

    def test_policy_reaches_only_the_catalogue_and_never_deletes(self):
        self.assertEqual(source.POLICY_NAME, "daybook-catalog-writer")
        self.assertEqual(source.POLICY, {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["s3:ListBucket"],
             "Resource": ["arn:aws:s3:::obsidian"],
             "Condition": {"StringEquals": {"s3:prefix": [
                 "Katalog/matters/", "Katalog/projects/", "Katalog/writing/"]}}},
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
             "Resource": ["arn:aws:s3:::obsidian/Katalog/*"]},
        ]})
        actions = {a for s in source.POLICY["Statement"] for a in s["Action"]}
        self.assertNotIn("s3:DeleteObject", actions)

    def test_a_policy_listing_more_prefixes_is_rejected(self):
        self.mc.policy = copy.deepcopy(source.POLICY)
        self.mc.policy["Statement"][0]["Condition"]["StringEquals"]["s3:prefix"].append("")
        with self.assertRaisesRegex(source.Refused, "policy_differs"):
            source.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_fresh_creation_is_idempotent_and_marker_has_no_credentials(self):
        self.assertTrue(source.provision(self.request, self.mc)["changed"])
        self.assertEqual(self.mc.mutations(), ["policy create", "user add", "policy attach"])
        marker = (self.state / "identity.json").read_text()
        self.assertNotIn(self.request["access_key"], marker)
        self.assertNotIn(self.request["secret_key"], marker)
        self.mc.calls.clear()
        self.assertFalse(source.provision(self.request, self.mc)["changed"])
        self.assertEqual(self.mc.mutations(), [])

    def test_existing_identity_is_not_adopted(self):
        self.mc.user = {"accessKey": self.request["access_key"], "userStatus": "enabled",
                        "policyName": source.POLICY_NAME}
        with self.assertRaisesRegex(source.Refused, "not_owned"):
            source.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_broader_policy_is_rejected(self):
        self.mc.policy = copy.deepcopy(source.POLICY)
        self.mc.policy["Statement"][1]["Action"].append("s3:DeleteObject")
        with self.assertRaisesRegex(source.Refused, "policy_differs"):
            source.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_changed_secret_is_rejected_without_mutation(self):
        source.provision(self.request, self.mc)
        self.mc.calls.clear()
        with self.assertRaisesRegex(source.Refused, "credentials_changed"):
            source.provision(dict(self.request, secret_key="y" * 48), self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_ansible_keeps_credential_tasks_private(self):
        tasks = yaml.safe_load((ROOT / "roles/daybook_catalog_access_deploy/tasks/server.yml").read_text())
        validation = tasks[0]
        provision = next(task for task in tasks if "ansible.builtin.command" in task)
        self.assertTrue(validation["no_log"])
        self.assertTrue(provision["no_log"])
        command = provision["ansible.builtin.command"]
        self.assertNotIn("access_key", repr(command["argv"]))
        self.assertNotIn("secret_key", repr(command["argv"]))
        self.assertIn("'access_key'", command["stdin"])
        self.assertIn("'secret_key'", command["stdin"])


    def test_the_client_installs_a_private_credentials_file_without_logging_it(self):
        role = ROOT / "roles/daybook_catalog_access_deploy"
        tasks = yaml.safe_load((role / "tasks/client.yml").read_text())
        self.assertTrue(tasks[0]["no_log"])
        install = next(t for t in tasks if "ansible.builtin.template" in t)
        self.assertEqual(install["ansible.builtin.template"]["mode"], "0600")
        self.assertTrue(install["no_log"])
        directories = next(t for t in tasks if "ansible.builtin.file" in t)
        self.assertEqual(directories["ansible.builtin.file"]["mode"], "0700")
        template = (role / "templates/aws-credentials.j2").read_text()
        self.assertIn("[{{ daybook_catalog_access_profile }}]", template)
        # Every path component is inspected without following links, before
        # anything is created, and the secret rule matches the provisioner's.
        inspect = next(t for t in tasks if "ansible.builtin.stat" in t)
        self.assertIs(inspect["ansible.builtin.stat"]["follow"], False)
        order = [next(iter(k for k in t if k.startswith("ansible."))) for t in tasks]
        self.assertLess(order.index("ansible.builtin.stat"), order.index("ansible.builtin.file"))
        self.assertIn("daybook_catalog_access_secret_key is not search('[\\x00-\\x1f\\x7f]')",
                      tasks[0]["ansible.builtin.assert"]["that"])
        defaults = yaml.safe_load((role / "defaults/main.yml").read_text())
        self.assertEqual(defaults["daybook_catalog_access_mode"], "server")
        self.assertEqual(defaults["daybook_catalog_access_profile"], "daybook-catalog")


if __name__ == "__main__":
    unittest.main()
