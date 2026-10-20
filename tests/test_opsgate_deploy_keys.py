"""Per-repository GitHub deploy keys for the opsgate ops workspaces.

Runs the role's own validation tasks, clone URL expression and SSH config
template through real Ansible on localhost.
"""

from __future__ import annotations

import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/opsgate_deploy"

REPOS = [
    {"name": "ops-control", "repo": "git@github.com:ephes/ops-control.git", "version": "main"},
    {"name": "ops-library", "repo": "ssh://git@github.com/ephes/ops-library.git", "version": "main"},
    {"name": "public", "repo": "https://github.com/ephes/public.git", "version": "main"},
]
PAIR = {"private_key": "PRIVATE-PLACEHOLDER", "public_key": "ssh-ed25519 AAAA opsgate-test"}


def task_named(path: Path, prefix: str) -> dict:
    tasks = yaml.safe_load(path.read_text())
    task = copy.deepcopy(next(t for t in tasks if t["name"].startswith(prefix)))
    task.pop("no_log", None)
    return task


def run_play(plays: list[dict]) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "play.yml"
        path.write_text(yaml.safe_dump(plays))
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)],
            cwd=ROOT,
            env=os.environ | {"ANSIBLE_NOCOLOR": "1"},
            capture_output=True,
            text=True,
            timeout=120,
        )


class OpsgateDeployKeyTests(unittest.TestCase):
    def test_validation(self) -> None:
        validate = ROLE / "tasks/validate.yml"
        selected = [
            task_named(validate, "validate | Ensure GitHub deploy keys are a mapping"),
            task_named(validate, "validate | Ensure workspace repo bootstrap inputs are coherent"),
            task_named(validate, "validate | Ensure each GitHub deploy key belongs"),
        ]
        both = {"ops-control": PAIR, "ops-library": PAIR}
        cases = [
            ({"opsgate_ops_github_deploy_keys": both}, True),
            ({"opsgate_ops_github_deploy_keys": {}, "opsgate_ops_github_ssh_private_key": "x",
              "opsgate_ops_github_ssh_public_key": "y"}, True),
            # one GitHub SSH repo without any key
            ({"opsgate_ops_github_deploy_keys": {"ops-control": PAIR}}, False),
            # key for a repo that is not a workspace repo, or not a GitHub SSH one
            ({"opsgate_ops_github_deploy_keys": both | {"other": PAIR}}, False),
            ({"opsgate_ops_github_deploy_keys": both | {"public": PAIR}}, False),
            ({"opsgate_ops_github_deploy_keys": {"ops-control": PAIR, "ops-library": {"private_key": "x"}}}, False),
            ({"opsgate_ops_github_deploy_keys": {"ops-control": PAIR, "ops-library": PAIR | {
                "public_key": "ssh-ed25519 AAAA\nssh-ed25519 BBBB"}}}, False),
            ({"opsgate_ops_github_deploy_keys": ["ops-control"]}, False),
        ]
        plays = []
        for index, (overrides, success) in enumerate(cases):
            plays.append({
                "name": f"case {index}",
                "hosts": "localhost",
                "gather_facts": False,
                "vars": {
                    "opsgate_ops_manage_workspace_repos": True,
                    "opsgate_ops_workspace_repositories": REPOS,
                    "opsgate_ops_github_ssh_private_key": "",
                    "opsgate_ops_github_ssh_public_key": "",
                } | overrides,
                "tasks": [
                    {"ansible.builtin.set_fact": {"passed": False}},
                    {"block": copy.deepcopy(selected) + [{"ansible.builtin.set_fact": {"passed": True}}],
                     "rescue": [{"ansible.builtin.debug": {"msg": "expected rejection"}}]},
                    {"ansible.builtin.assert": {"that": [f"passed == {str(success).lower()}"],
                                                "fail_msg": f"case {index} expected {success}"}},
                ],
            })
        result = run_play(plays)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clone_urls_and_ssh_config(self) -> None:
        clone = task_named(ROLE / "tasks/workspace_repos.yml", "workspace_repos | Clone or update")
        expression = clone["ansible.builtin.git"]["repo"]
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config"
            play = [{
                "hosts": "localhost",
                "gather_facts": False,
                "vars": {
                    "opsgate_ops_workspace_repositories": REPOS,
                    "opsgate_ops_github_deploy_keys": {"ops-library": PAIR, "ops-control": PAIR},
                    "opsgate_ops_github_deploy_key_path_prefix": "/Users/ops/.ssh/id_github_deploy_",
                    "opsgate_ops_github_ssh_private_key": "",
                    "opsgate_ops_github_ssh_private_key_path": "/Users/ops/.ssh/id_github_ed25519",
                },
                "tasks": [
                    {"ansible.builtin.set_fact": {"urls": "{{ urls | default([]) + [" + expression.strip()[2:-2] + "] }}"},
                     "loop": "{{ opsgate_ops_workspace_repositories }}"},
                    {"ansible.builtin.assert": {"that": [
                        "urls == ['git@github-ops-control:ephes/ops-control.git', "
                        "'ssh://git@github-ops-library/ephes/ops-library.git', "
                        "'https://github.com/ephes/public.git']"
                    ], "fail_msg": "{{ urls }}"}},
                    {"ansible.builtin.template": {"src": str(ROLE / "templates/ops.ssh.config.j2"),
                                                  "dest": str(config)}},
                ],
            }]
            result = run_play(play)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rendered = config.read_text()
        self.assertEqual(
            rendered,
            "Host github-ops-control\n"
            "  HostName github.com\n"
            "  HostKeyAlias github.com\n"
            "  User git\n"
            "  IdentityFile /Users/ops/.ssh/id_github_deploy_ops-control\n"
            "  IdentitiesOnly yes\n"
            "Host github-ops-library\n"
            "  HostName github.com\n"
            "  HostKeyAlias github.com\n"
            "  User git\n"
            "  IdentityFile /Users/ops/.ssh/id_github_deploy_ops-library\n"
            "  IdentitiesOnly yes\n",
        )
        self.assertNotIn("Host github.com", rendered)

    def test_private_keys_stay_out_of_logs(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks/ops_credentials.yml").read_text())
        for name in ("ops_credentials | Install ops GitHub deploy private keys",
                     "ops_credentials | Install ops GitHub deploy public keys"):
            task = next(t for t in tasks if t["name"] == name)
            self.assertIs(task["no_log"], True, name)
        validate = yaml.safe_load((ROLE / "tasks/validate.yml").read_text())
        per_key = next(t for t in validate if t["name"].startswith("validate | Ensure each GitHub deploy key belongs"))
        self.assertIs(per_key["no_log"], True)


if __name__ == "__main__":
    unittest.main()
