"""Original Ansible auto-detection: regex regression and actual conditional tasks."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/homeassistant_deploy/tasks"
FILES = ("assist_pipelines.yml", "assist_pipeline_stt.yml")
OLD_EXPRESSION_SHA = {
    # pragma: allowlist nextline secret -- public original expression digest
    "stt": "12afb518c9a66cc376e27022a83968d43feca65c27d6671ae84d892a17737b7b",
    # pragma: allowlist nextline secret -- public original expression digest
    "tts": "c13d34dcd86c2fef22f8206b9c2069628bc8f0bd245ebee51093298ae225f83f",
}


def selected_tasks(filename):
    return [
        task
        for task in yaml.safe_load((TASKS / filename).read_text())
        if "Resolve" in task["name"] and "engine entity" in task["name"]
    ]


def variables(entities, selected="owned-entry"):
    return {
        "_ha_assist_registry_entities": entities,
        "_ha_entity_registry_raw": {
            "content": base64.b64encode(
                json.dumps({"data": {"entities": entities}}).encode()
            ).decode()
        },
        "_ha_assist_pipeline_entry_id": selected,
        "_ha_entity_registry_stat": {"stat": {"exists": True}},
        "homeassistant_assist_pipelines": [{"name": "Owned", "language": "en"}],
        "homeassistant_manage_assist_pipeline_stt_engine": True,
        "homeassistant_manage_assist_pipeline_tts_engine": True,
        "_ha_assist_default_stt_engine_id": "",
        "_ha_assist_default_tts_engine_id": "",
        "_ha_assist_pipeline_desired_stt_engine_id": "",
        "_ha_assist_pipeline_desired_tts_engine_id": "",
    }


def entities():
    return [
        {"platform": platform, "config_entry_id": entry, "entity_id": entity}
        for kind in ("stt", "tts")
        for platform, entry, entity in (
            ("other", "owned-entry", kind + ".other_platform"),
            ("wyoming", "other-entry", kind + ".other_entry"),
            ("wyoming", "owned-entry", kind + "x.not_a_domain"),
            ("wyoming", "owned-entry", kind + ".owned"),
            ("wyoming", "owned-entry", kind + ".later"),
        )
    ]


class AssistAutodetection(unittest.TestCase):
    def test_original_negative_and_corrected_literal_domain_match(self):
        for filename in FILES:
            tasks = selected_tasks(filename)
            self.assertEqual(len(tasks), 2)
            for kind, task in zip(("stt", "tts"), tasks):
                expression = next(iter(task["ansible.builtin.set_fact"].values()))
                frozen = yaml.safe_load(
                    (
                        ROOT
                        / "tests/fixtures/homeassistant_assist_registry_original.yml"
                    ).read_text()
                )
                original_task = frozen[filename]["tasks"][0 if kind == "stt" else 1]
                original_expression = next(
                    iter(original_task["ansible.builtin.set_fact"].values())
                )
                legacy = original_expression.replace("\\.", "\\\\.")
                self.assertEqual(
                    hashlib.sha256(legacy.encode()).hexdigest(),
                    OLD_EXPRESSION_SHA[kind],
                )
                for values, expected in (
                    (variables(entities()), kind + ".owned"),
                    (variables([]), ""),
                    (variables(entities(), "absent"), ""),
                ):
                    with self.subTest(filename=filename, kind=kind, expected=expected):
                        loader = DataLoader()
                        templar = Templar(
                            loader=loader,
                            variables=loader.load(
                                trust_as_template(json.dumps(values)),
                                show_content=False,
                            ),
                        )
                        self.assertEqual(
                            templar.template(trust_as_template(legacy)), ""
                        )
                        self.assertEqual(
                            templar.template(trust_as_template(expression)), expected
                        )

    def test_actual_tasks_preserve_automatic_and_explicit_selection(self):
        plays = []
        for filename in FILES:
            for mode in ("automatic", "explicit", "missing-entry"):
                values = variables(
                    entities(), "absent" if mode == "missing-entry" else "owned-entry"
                )
                if mode == "explicit":
                    values["homeassistant_assist_pipelines"][0].update(
                        stt_engine_id="stt.explicit", tts_engine_id="tts.explicit"
                    )
                    for key in tuple(values):
                        if key.endswith("_engine_id"):
                            values[key] = (
                                "stt.explicit" if "stt" in key else "tts.explicit"
                            )
                tasks = selected_tasks(filename)
                keys = [next(iter(task["ansible.builtin.set_fact"])) for task in tasks]
                expected = [
                    ""
                    if mode == "missing-entry"
                    else kind + (".explicit" if mode == "explicit" else ".owned")
                    for kind in ("stt", "tts")
                ]
                plays.append(
                    {
                        "name": filename + ":" + mode,
                        "hosts": "localhost",
                        "gather_facts": False,
                        "tasks": [
                            {
                                "name": "Reset owned scenario",
                                "ansible.builtin.set_fact": values,
                            },
                            *tasks,
                            {
                                "name": "Assert selected original engines",
                                "ansible.builtin.assert": {
                                    "that": [
                                        key + " == " + repr(value)
                                        for key, value in zip(keys, expected)
                                    ]
                                },
                            },
                        ],
                    }
                )
        with tempfile.TemporaryDirectory(prefix="ha-assist-regex-") as directory:
            root = Path(directory)
            play = root / "owned.yml"
            play.write_text(yaml.safe_dump(plays, sort_keys=False))
            config = root / "ansible.cfg"
            config.write_text(
                "[defaults]\nretry_files_enabled=False\nlog_path=/dev/null\nfact_caching=memory\n"
            )
            env = {
                key: os.environ[key]
                for key in ("PATH", "HOME", "LANG", "OPS_LIBRARY_PATH")
                if key in os.environ
            }
            env.update(
                ANSIBLE_CONFIG=str(config),
                ANSIBLE_LOCAL_TEMP=str(root / "local"),
                PYTHONDONTWRITEBYTECODE="1",
            )
            result = subprocess.run(
                [
                    str(Path(sys.executable).parent / "ansible-playbook"),
                    "-i",
                    "localhost,",
                    "-c",
                    "local",
                    str(play),
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("failed=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
