"""Run real Ansible orchestration with inert task actions; never execute modules."""

import json
from pathlib import Path
import sys

from ansible import context
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.executor.task_executor import TaskExecutor
from ansible.inventory.manager import InventoryManager
from ansible.module_utils.common.collections import ImmutableDict
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.action import ActionBase
from ansible.plugins.loader import init_plugin_loader
from ansible.vars.manager import VariableManager

init_plugin_loader()

original = TaskExecutor._get_action_handler_with_module_context


class MockAction(ActionBase):
    _requires_connection = False

    def run(self, tmp=None, task_vars=None):
        name = self._task.action.rsplit(".", 1)[-1]
        result = {"changed": True}
        if name == "tempfile":
            result["path"] = "/synthetic-transport"
        elif name == "command":
            result.update(rc=0, stdout=json.dumps({"changed": False}))
        elif name == "group":
            result["changed"] = False
        elif name == "getent":
            result.update(
                changed=False,
                ansible_facts={
                    "getent_passwd": {
                        "opaq-company-viewer": [
                            "x",
                            "123",
                            "123",
                            "",
                            "/nonexistent",
                            "/usr/sbin/nologin",
                        ]
                    }
                },
            )
        return result


def handler(self, templar):
    if self._task.action == "ansible.builtin.assert":
        return original(self, templar)
    if self._task.action not in {
        "ansible.builtin.tempfile",
        "ansible.builtin.copy",
        "ansible.builtin.file",
        "ansible.builtin.command",
        "ansible.builtin.group",
        "ansible.builtin.getent",
    }:
        raise RuntimeError("unexpected action: no real module execution permitted")
    return (
        MockAction(
            task=self._task,
            connection=self._connection,
            play_context=self._play_context,
            loader=self._loader,
            templar=templar,
            shared_loader_obj=self._shared_loader_obj,
        ),
        None,
    )


TaskExecutor._get_action_handler_with_module_context = handler
context.CLIARGS = ImmutableDict(
    connection="local",
    module_path=None,
    forks=1,
    become=False,
    become_method="sudo",
    become_user=None,
    check=False,
    diff=False,
    verbosity=0,
    syntax=False,
    start_at_task=None,
    tags=(),
    skip_tags=(),
    listhosts=False,
    listtasks=False,
    listtags=False,
)
loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=["localhost,"])
variables = VariableManager(loader=loader, inventory=inventory)
play = Path(sys.argv[1])
executor = PlaybookExecutor(
    playbooks=[str(play)],
    inventory=inventory,
    variable_manager=variables,
    loader=loader,
    passwords={},
)
sys.exit(executor.run())
