"""Original helper/version defaults on synthetic data; no HA/provider calls."""

import ast
import asyncio
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROLE = Path(__file__).resolve().parents[1] / "roles/homeassistant_deploy"
OLD_SHA = "6397258af29908ffed7b0eaa79c332ddce7000cb9b9faec5e3bf0e399c020382"  # pragma: allowlist secret
NEW_SHA = "a81433682ab0da8439dddb3eb549ca57c4e5b20d64b6797b2568b524903a0d52"  # pragma: allowlist secret


def helper():
    tasks = yaml.safe_load(
        (ROLE / "tasks/custom_conversation_integration.yml").read_text()
    )
    block = next(task["block"] for task in tasks if "block" in task)
    command = next(
        task["ansible.builtin.command"]
        for task in block
        if task.get("name")
        == "Create, update, or remove the Custom Conversation config entry"
    )
    tree = ast.parse(command["argv"][2])
    assert isinstance(tree.body[-1], ast.Try)
    tree.body.pop()
    namespace = {"__name__": "owned_custom_helper"}
    environment = {
        "HA_API_URL": "http://owned.invalid",
        "HA_RESULT_PATH": "/unused-owned-result",
        "HA_STORAGE_PATH": "/unused-owned-storage",
        "HA_CC_ENABLED": "1",
        "HA_CC_VERSION": "1.7.0",
    }
    with (
        patch.dict(os.environ, environment),
        patch("sys.stdin", io.StringIO(json.dumps({"HA_TOKEN": "owned-synthetic"}))),
    ):
        exec(
            compile(tree, "<original-custom-helper>", "exec"), namespace
        )  # noqa: S102 -- exact owned original helper
    return namespace


class CustomConversationVersionTests(unittest.TestCase):
    def test_original_templar_default_pairs_and_explicit_overrides(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        cases = [
            ({}, "1.7.0", NEW_SHA),
            ({"homeassistant_custom_conversation_version": "1.6.1"}, "1.6.1", OLD_SHA),
            (
                {
                    "homeassistant_custom_conversation_version": "1.6.1",
                    "homeassistant_custom_conversation_sha256": "a" * 64,
                },
                "1.6.1",
                "a" * 64,
            ),
            (
                {
                    "homeassistant_custom_conversation_version": "owned-custom",
                    "homeassistant_custom_conversation_sha256": "b" * 64,
                },
                "owned-custom",
                "b" * 64,
            ),
        ]
        for overrides, version, checksum in cases:
            with self.subTest(
                version=version,
                explicit="homeassistant_custom_conversation_sha256" in overrides,
            ):
                values = {**defaults, **overrides}
                templar = Templar(loader=DataLoader(), variables=values)
                self.assertEqual(
                    values["homeassistant_custom_conversation_version"], version
                )
                self.assertEqual(
                    templar.template(
                        trust_as_template(
                            values["homeassistant_custom_conversation_sha256"]
                        )
                    ),
                    checksum,
                )
                self.assertIn(
                    "/" + version + ".tar.gz",
                    templar.template(
                        trust_as_template(
                            defaults["homeassistant_custom_conversation_download_url"]
                        )
                    ),
                )

    def test_actual_helper_options_preserve_legacy_and_new_empty_semantics(self):
        for version in ("1.6.1", "1.7.0", "owned-custom"):
            for ignored in (None, [], ["OwnedIntent"], "invalid"):
                with self.subTest(version=version, ignored=ignored):
                    namespace = helper()
                    namespace["COMPONENT_VERSION"] = version
                    current = {
                        "agents": {
                            "enable_home_assistant_agent": False,
                            "enable_llm_agent": True,
                        },
                        "langfuse": {
                            "enable_langfuse": True,
                            "host": "owned-private-host",
                        },
                    }
                    if ignored is not None:
                        current["ignored_intents_section"] = {
                            "ignored_intents": ignored
                        }
                    calls = []

                    async def rest(_session, _method, path, body, calls=calls):
                        calls.append((path, body))
                        return (
                            (
                                200,
                                {"type": "form", "step_id": "init", "flow_id": "owned"},
                            )
                            if len(calls) == 1
                            else (200, {"type": "create_entry"})
                        )

                    namespace["rest"] = rest
                    asyncio.run(
                        namespace["set_options"](object(), "owned-entry", current)
                    )
                    payload = calls[1][1]
                    expected = (
                        {"ignored_intents": ignored}
                        if isinstance(ignored, list)
                        else {}
                        if version == "1.7.0"
                        else {"ignored_intents": []}
                    )
                    self.assertEqual(payload["ignored_intents_section"], expected)
                    self.assertEqual(payload["agents"], current["agents"])
                    self.assertEqual(payload["langfuse"], current["langfuse"])

    def test_unknown_default_refuses_before_read_or_api_and_explicit_remains_supported(
        self,
    ):
        namespace = helper()
        namespace["COMPONENT_VERSION"] = "owned-custom"
        namespace["load_current"] = AsyncMock(
            side_effect=AssertionError("owned-read-boundary")
        )
        with self.assertRaisesRegex(RuntimeError, "empty instructions"):
            asyncio.run(namespace["main"]())
        namespace["load_current"].assert_not_called()
        namespace["INSTRUCTIONS"] = "owned explicit instructions"
        with self.assertRaisesRegex(AssertionError, "owned-read-boundary"):
            asyncio.run(namespace["main"]())

    def test_both_qualified_versions_restore_default_without_repeat_drift(self):
        for version in ("1.6.1", "1.7.0"):
            namespace = helper()
            namespace["COMPONENT_VERSION"] = version
            self.assertIn(version, namespace["DEFAULT_PROMPT_VERIFIED_VERSIONS"])
            current = {
                "options": {
                    "custom_prompts": {"instructions_prompt": "owned previous"},
                    "llm_hass_api": "none",
                }
            }
            self.assertTrue(namespace["options_drift"](current))
            current["options"]["custom_prompts"]["instructions_prompt"] = namespace[
                "DEFAULT_INSTRUCTIONS_PROMPT"
            ]
            self.assertFalse(namespace["options_drift"](current))


if __name__ == "__main__":
    unittest.main()
