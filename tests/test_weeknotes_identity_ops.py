from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "roles/daybook_sessions_deploy/templates/weeknotes-identity-ops.py.j2"


def _install_daybook_stubs() -> type:
    class Client:
        calls = 0

        def __init__(self, _config):
            pass

        def read_post(self, post_id):
            type(self).calls += 1
            return {
                "id": post_id,
                "parent": {"id": 4},
                "latest_revision_id": 10,
                "previous_revision_id": 9,
                "title": "Weeknotes 2026-07-20",
                "slug": "weeknotes-2026-07-20",
                "type": "cast.Post",
                "status": "draft",
                "live": False,
            }

    cast = types.ModuleType("daybook.cast_client")
    cast.DeliveryConfig = type("DeliveryConfig", (), {"from_env": staticmethod(lambda: object())})
    cast.DjangoCastClient = Client
    cast.protected_post_fields_hash = lambda _post: "a" * 64

    weeknotes = types.ModuleType("daybook.weeknotes")
    weeknotes.normalized_week = lambda value: value
    weeknotes.weeknotes_title = lambda _week, audience: (
        "Weeknotes 2026-07-27" if audience == "public" else "Juli 2026-07-27"
    )
    weeknotes.weeknotes_slug = lambda _week, audience: (
        "weeknotes-2026-07-27" if audience == "public" else "juli-2026-07-27"
    )

    migration = types.ModuleType("daybook.weeknotes_identity_migration")

    def parse(raw):
        raw_bytes = raw if isinstance(raw, bytes) else raw.encode()
        payload = json.loads(raw_bytes)
        moves = [types.SimpleNamespace(**move) for move in payload["moves"]]
        return types.SimpleNamespace(
            moves=moves,
            plan_hash=hashlib.sha256(raw_bytes).hexdigest(),
        )

    migration.parse_identity_migration_plan = parse
    package = types.ModuleType("daybook")
    package.__path__ = []
    sys.modules.update(
        {
            "daybook": package,
            "daybook.cast_client": cast,
            "daybook.weeknotes": weeknotes,
            "daybook.weeknotes_identity_migration": migration,
        }
    )
    return Client


def _load_helper():
    source = TEMPLATE.read_text().removeprefix("{% raw %}").removesuffix("{% endraw %}\n")
    module = types.ModuleType("weeknotes_identity_ops_test")
    exec(compile(source, str(TEMPLATE), "exec"), module.__dict__)
    return module


class IdentityOpsTests(unittest.TestCase):
    def setUp(self):
        self.client = _install_daybook_stubs()
        self.helper = _load_helper()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.seed = self.root / "seed.json"
        self.plan = self.root / "plan.json"
        self.attestation = self.root / "attestation.json"
        self.seed_payload = {
            "schema_version": 1,
            "identity_epoch": "monday-after-v1",
            "moves": [
                {
                    "week": "2026-W30",
                    "audience": "public",
                    "blog_id": 4,
                    "post_id": 8,
                    "expected_revision_id": 10,
                    "from_title": "Weeknotes 2026-07-20",
                    "from_slug": "weeknotes-2026-07-20",
                }
            ],
        }
        self._write_private(self.seed, self.seed_payload)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write_private(path: Path, payload) -> None:
        path.write_text(json.dumps(payload) + "\n")
        path.chmod(0o600)

    def test_prepare_is_no_replace_and_reuses_exact_plan_without_network(self):
        first = self.helper.prepare(self.seed, self.plan)
        self.assertEqual(first["status"], "plan_prepared")
        self.assertEqual(self.plan.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.client.calls, 1)
        second = self.helper.prepare(self.seed, self.plan)
        self.assertEqual(second["status"], "existing_plan_reused")
        self.assertEqual(self.client.calls, 1)

    def test_existing_plan_with_different_seed_is_rejected(self):
        self.helper.prepare(self.seed, self.plan)
        payload = dict(self.seed_payload)
        payload["moves"] = [dict(self.seed_payload["moves"][0], post_id=99)]
        self._write_private(self.seed, payload)
        with self.assertRaises(ValueError):
            self.helper.prepare(self.seed, self.plan)

    def test_link_failure_never_exposes_partial_final_and_retry_succeeds(self):
        with mock.patch.object(self.helper.os, "link", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.helper.prepare(self.seed, self.plan)
        self.assertFalse(self.plan.exists())
        self.assertEqual(list(self.root.glob(".plan.json.daybook-*")), [])
        self.assertEqual(self.helper.prepare(self.seed, self.plan)["status"], "plan_prepared")

    def test_crash_after_durable_link_is_recovered_without_network(self):
        prepared = self.helper.prepare(self.seed, self.plan)
        leftover = self.root / ".plan.json.daybook-crash"
        os.link(self.plan, leftover)
        calls = self.client.calls
        reused = self.helper.prepare(self.seed, self.plan)
        self.assertEqual(reused["plan_hash"], prepared["plan_hash"])
        self.assertFalse(leftover.exists())
        self.assertEqual(self.plan.stat().st_nlink, 1)
        self.assertEqual(self.client.calls, calls)

    def test_symlink_and_truncated_plan_are_rejected(self):
        target = self.root / "target.json"
        self._write_private(target, {})
        self.plan.symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            self.helper.prepare(self.seed, self.plan)
        self.plan.unlink()
        self.plan.write_text("{")
        self.plan.chmod(0o600)
        with self.assertRaises((json.JSONDecodeError, ValueError)):
            self.helper.prepare(self.seed, self.plan)

    def test_verify_binds_seed_plan_hash_and_every_receipt(self):
        prepared = self.helper.prepare(self.seed, self.plan)
        receipt = {
            "week": "2026-W30",
            "audience": "public",
            "blog_id": 4,
            "post_id": 8,
            "new_revision_id": 11,
        }
        attestation = {
            "version": 1,
            "identity_epoch": "monday-after-v1",
            "plan_hash": prepared["plan_hash"],
            "moves": [receipt],
            "completed_at": "2026-07-20T10:00:00Z",
        }
        self._write_private(self.attestation, attestation)
        self.assertEqual(
            self.helper.verify(self.seed, self.plan, self.attestation)["plan_hash"],
            prepared["plan_hash"],
        )
        attestation["moves"][0]["post_id"] = 999
        self._write_private(self.attestation, attestation)
        with self.assertRaises(ValueError):
            self.helper.verify(self.seed, self.plan, self.attestation)


if __name__ == "__main__":
    unittest.main()
