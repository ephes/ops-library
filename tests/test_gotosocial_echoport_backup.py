"""Contracts of the Echoport GoToSocial runner (target `gotosocial`).

The runner is rendered from its Jinja template with every host path inside a
temporary directory. Remote commands run locally through bash with fake
`runuser`, `chown`, `systemctl` and `curl`; scp/rsync are local copies and
`mc` is a fake bucket. sqlite3 is real.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"
TEMPLATE = "gotosocial_backup.py.j2"
LAYOUT = "fedi.example.org example.org"

FAKE_BIN = {
    "runuser": """#!/bin/bash
# runuser -u USER -- CMD...
shift 3
exec "$@"
""",
    "chown": "#!/bin/bash\nexit 0\n",
    "curl": "#!/bin/bash\n[ -e \"$FAKE_ROOT/service.running\" ]\n",
    "systemctl": """#!/bin/bash
echo "$*" >> "$FAKE_ROOT/systemctl.log"
case "$1" in
  stop) rm -f "$FAKE_ROOT/service.running" ;;
  start) touch "$FAKE_ROOT/service.running" ;;
esac
""",
    "mc": f"""#!{sys.executable}
import json, os, shutil, sys
store = os.path.join(os.environ["FAKE_ROOT"], "bucket")
args = [a for a in sys.argv[1:] if a != "--quiet"]
def path(ref):
    return os.path.join(store, ref.split("/", 1)[1])
if args[0] == "cp":
    src, dst = args[1], args[2]
    if src.startswith("backup-gotosocial/"):
        if not os.path.exists(path(src)):
            sys.exit("missing object")
        shutil.copyfile(path(src), dst)
    else:
        os.makedirs(os.path.dirname(path(dst)), exist_ok=True)
        shutil.copyfile(src, path(dst))
elif args[0] == "stat":
    ref = args[-1]
    if not os.path.exists(path(ref)):
        sys.exit(1)
    print(json.dumps({{"size": os.path.getsize(path(ref))}}))
else:
    sys.exit("unexpected mc call")
""",
}


def make_db(path: Path, statuses: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY, domain TEXT)")
    con.execute("CREATE TABLE statuses (id TEXT PRIMARY KEY, local INTEGER)")
    con.executemany("INSERT INTO accounts VALUES (?, ?)", [("a1", None), ("a2", "mastodon.example")])
    con.executemany("INSERT INTO statuses VALUES (?, 1)", [(f"s{i}",) for i in range(statuses)])
    con.commit()
    con.close()


def count_statuses(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT count(*) FROM statuses").fetchone()[0]
    finally:
        con.close()


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.host = root / "host"
        self.data = self.host / "var/lib/gotosocial"
        self.db = self.data / "sqlite.db"
        self.storage = self.data / "storage"
        self.config = self.host / "etc/gotosocial/config.yaml"
        self.marker = self.data / ".ops-domain-layout"
        self.tmp_parent = self.host / "var/tmp"
        self.bin = root / "bin"
        for d in (self.storage / "acct1/attachment/original", self.config.parent, self.tmp_parent, self.bin, root / "runner-tmp"):
            d.mkdir(parents=True, exist_ok=True)
        make_db(self.db, statuses=3)
        (self.storage / "acct1/attachment/original/img.png").write_bytes(b"\x89PNG fake")
        self.config.write_text("host: fedi.example.org\n")
        self.marker.write_text(LAYOUT + "\n")
        (root / "service.running").touch()
        for name, body in FAKE_BIN.items():
            p = self.bin / name
            p.write_text(body)
            p.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_ROOT=str(root))
        self.fail_rsync_to = False
        self.fail_storage_move = False
        self.fail_move_of: str | None = None
        self.lose_reply_of: str | None = None
        self.module = self._render()

    def _render(self) -> types.ModuleType:
        env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=False)
        variables: dict[str, Any] = {
            "echoport_backup_mc_install_path": str(self.bin / "mc"),
            "echoport_backup_minio_alias": "backup-gotosocial",
            "echoport_backup_default_bucket": "backups",
            "echoport_backup_temp_dir": str(self.root / "runner-tmp"),
            "gotosocial_backup_remote_host": "fedi.example.org",
            "gotosocial_backup_data_dir": str(self.data),
            "gotosocial_backup_db_path": str(self.db),
            "gotosocial_backup_storage_dir": str(self.storage),
            "gotosocial_backup_config_path": str(self.config),
            "gotosocial_backup_layout_marker": str(self.marker),
            "gotosocial_backup_remote_tmp_parent": str(self.tmp_parent),
            "gotosocial_backup_target_name": "gotosocial",
        }
        source = env.get_template(TEMPLATE).render(**variables)
        module = types.ModuleType("gotosocial_backup_test")
        module.__file__ = str(TEMPLATE_DIR / TEMPLATE)
        exec(compile(source, module.__file__, "exec"), module.__dict__)

        harness = self

        def remote(script: str, check: bool = True) -> subprocess.CompletedProcess:
            if harness.fail_storage_move and script.startswith(f"mv {harness.storage} "):
                script = "echo 'mv: simulated failure' >&2; false"
            if harness.fail_move_of and script.startswith(f"mv {harness.fail_move_of} "):
                script = "echo 'mv: simulated failure' >&2; false"
            cmd = ["bash", "-c", "set -euo pipefail; " + script]
            result = subprocess.run(cmd, capture_output=True, text=True, env=harness.env)
            if harness.lose_reply_of and script.startswith(f"mv {harness.lose_reply_of} "):
                # The rename happened, but the SSH connection dropped before the reply.
                result = subprocess.CompletedProcess(cmd, 255, "", "ssh: connection reset")
            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
            return result

        def scp_from(remote_path: str, local_path: Path) -> None:
            shutil.copy2(remote_path, local_path)

        def scp_to(local_path: Path, remote_path: str) -> None:
            shutil.copy2(local_path, remote_path)

        def rsync_from(remote_dir: str, local_dir: Path) -> None:
            shutil.copytree(remote_dir, local_dir, dirs_exist_ok=True)

        def rsync_to(local_dir: Path, remote_dir: str) -> None:
            if harness.fail_rsync_to:
                raise subprocess.CalledProcessError(23, ["rsync"], "", "rsync: simulated failure")
            shutil.copytree(local_dir, remote_dir, dirs_exist_ok=True)

        module.remote = remote
        module.scp_from = scp_from
        module.scp_to = scp_to
        module.rsync_from = rsync_from
        module.rsync_to = rsync_to
        module.time.sleep = lambda _s: None
        return module

    def run(self, env: dict[str, str]) -> tuple[int, list[dict]]:
        os.environ["CONTEXT"] = json.dumps({"env": env})
        # mc and sqlite3 run through the runner's own subprocess calls.
        os.environ["FAKE_ROOT"] = str(self.root)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rc = self.module.main()
        finally:
            sys.stdout = old
            os.environ.pop("CONTEXT", None)
            os.environ.pop("FAKE_ROOT", None)
        events = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
        return rc, events

    @staticmethod
    def result(events: list[dict]) -> dict:
        msg = [e for e in events if e.get("name") == "result"][-1]["message"]
        return json.loads(msg.split("ECHOPORT_RESULT:", 1)[1])

    def systemctl_calls(self) -> list[str]:
        log = self.root / "systemctl.log"
        return log.read_text().split("\n")[:-1] if log.exists() else []


class GoToSocialRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def backup(self) -> dict:
        rc, events = self.h.run({"ECHOPORT_ACTION": "backup", "ECHOPORT_KEY_PREFIX": "gotosocial/2026-10-15T01-00-00",
                                 "ECHOPORT_TIMESTAMP": "2026-10-15T01-00-00"})
        self.assertEqual(rc, 0, events)
        return self.h.result(events)

    def test_backup_is_online_and_complete(self) -> None:
        res = self.backup()
        self.assertTrue(res["success"])
        self.assertEqual(res["key"], "gotosocial/2026-10-15T01-00-00.tar.gz")
        obj = self.h.root / "bucket" / "backups" / res["key"]
        self.assertEqual(res["size_bytes"], obj.stat().st_size)
        with tarfile.open(obj) as tar:
            names = set(tar.getnames())
            manifest = json.load(tar.extractfile("manifest.json"))
        self.assertTrue({"sqlite.db", "config.yaml", "domain-layout", "manifest.json", "manifest.sha256",
                         "storage/acct1/attachment/original/img.png"} <= names)
        self.assertEqual(manifest["domain_layout"], LAYOUT)
        self.assertEqual(manifest["database"]["local_accounts"], 1)
        self.assertEqual(manifest["database"]["local_statuses"], 3)
        self.assertEqual(manifest["storage"]["files"], 1)
        # No downtime and no leftovers on the host.
        self.assertEqual(self.h.systemctl_calls(), [])
        self.assertEqual(list(self.h.tmp_parent.iterdir()), [])

    def test_backup_refuses_foreign_key_prefix(self) -> None:
        rc, events = self.h.run({"ECHOPORT_ACTION": "backup", "ECHOPORT_KEY_PREFIX": "vaultwarden/x"})
        self.assertEqual(rc, 1)
        self.assertIn("outside gotosocial/", self.h.result(events)["error"])

    def test_restore_replaces_data_and_keeps_previous(self) -> None:
        res = self.backup()
        self.h.db.unlink()
        make_db(self.h.db, statuses=7)
        (self.h.storage / "new.bin").write_bytes(b"later")
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                                 "ECHOPORT_CHECKSUM": res["checksum_sha256"]})
        self.assertEqual(rc, 0, events)
        self.assertEqual(count_statuses(self.h.db), 3)
        self.assertTrue((self.h.storage / "acct1/attachment/original/img.png").exists())
        asides = sorted(p.name for p in self.h.data.iterdir() if "pre-restore" in p.name)
        self.assertTrue(any(n.startswith("sqlite.db.pre-restore-") for n in asides), asides)
        self.assertTrue(any(n.startswith("storage.pre-restore-") for n in asides), asides)
        self.assertEqual(self.h.systemctl_calls(), ["stop gotosocial", "start gotosocial"])

    def test_restore_refuses_other_layout_before_stopping(self) -> None:
        res = self.backup()
        self.h.marker.write_text("social.other.org other.org\n")
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                                 "ECHOPORT_CHECKSUM": res["checksum_sha256"]})
        self.assertEqual(rc, 1)
        self.assertIn("layout", self.h.result(events)["error"])
        self.assertEqual(self.h.systemctl_calls(), [])

    def test_restore_refuses_checksum_mismatch(self) -> None:
        res = self.backup()
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                                 "ECHOPORT_CHECKSUM": "0" * 64})
        self.assertEqual(rc, 1)
        self.assertIn("checksum mismatch", self.h.result(events)["error"])
        self.assertEqual(self.h.systemctl_calls(), [])

    def test_restore_rolls_back_on_failure(self) -> None:
        res = self.backup()
        self.h.db.unlink()
        make_db(self.h.db, statuses=7)
        self.h.fail_rsync_to = True
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                                 "ECHOPORT_CHECKSUM": res["checksum_sha256"]})
        self.assertEqual(rc, 1)
        self.assertEqual(count_statuses(self.h.db), 7)  # previous database back
        self.assertTrue((self.h.root / "service.running").exists())
        self.assertTrue(any(".failed-restore-" in p.name for p in self.h.data.iterdir()))
        rollback = [e for e in events if e.get("name") == "rollback"]
        self.assertEqual(rollback[-1]["state"], "success")

    def test_restore_recovers_when_only_the_database_was_moved(self) -> None:
        res = self.backup()
        self.h.db.unlink()
        make_db(self.h.db, statuses=7)
        self.h.fail_storage_move = True
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                                 "ECHOPORT_CHECKSUM": res["checksum_sha256"]})
        self.assertEqual(rc, 1)
        self.assertEqual(count_statuses(self.h.db), 7)  # database moved back
        self.assertTrue(self.h.storage.is_dir())
        self.assertTrue((self.h.root / "service.running").exists())
        self.assertEqual([e for e in events if e.get("name") == "rollback"][-1]["state"], "success")

    def test_restore_keeps_an_unmoved_wal_with_its_database(self) -> None:
        res = self.backup()
        wal = Path(str(self.h.db) + "-wal")
        wal.write_bytes(b"original wal")  # stands in for committed, uncheckpointed pages
        original_db = self.h.db.read_bytes()
        self.h.fail_move_of = str(wal)
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                                 "ECHOPORT_CHECKSUM": res["checksum_sha256"]})
        self.assertEqual(rc, 1)
        self.assertEqual(self.h.db.read_bytes(), original_db)
        self.assertEqual(wal.read_bytes(), b"original wal")
        self.assertFalse(any(".failed-restore-" in p.name and p.name.startswith("sqlite.db-wal")
                             for p in self.h.data.iterdir()))
        self.assertEqual([e for e in events if e.get("name") == "rollback"][-1]["state"], "success")

    def test_restore_moves_a_new_wal_away_from_the_old_database(self) -> None:
        res = self.backup()
        wal = Path(str(self.h.db) + "-wal")
        # macOS' sqlite keeps empty WAL/SHM files after the backup's read; this
        # case is about a database that had none.
        for suffix in ("-wal", "-shm"):
            Path(str(self.h.db) + suffix).unlink(missing_ok=True)
        self.h.fail_rsync_to = True
        # The restored database "ran" and left a WAL before the failure.
        orig_scp_to = self.h.module.scp_to

        def scp_to_and_grow_wal(local_path, remote_path):
            orig_scp_to(local_path, remote_path)
            wal.write_bytes(b"wal of the restored database")

        self.h.module.scp_to = scp_to_and_grow_wal
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                            "ECHOPORT_CHECKSUM": res["checksum_sha256"]})
        self.assertEqual(rc, 1)
        self.assertFalse(wal.exists(), sorted(p.name for p in self.h.data.iterdir()))
        self.assertTrue(any(p.name.startswith("sqlite.db-wal.failed-restore-") for p in self.h.data.iterdir()))

    def test_restore_recovers_a_move_whose_reply_was_lost(self) -> None:
        res = self.backup()
        original_db = self.h.db.read_bytes()
        self.h.lose_reply_of = str(self.h.db)
        rc, events = self.h.run({"ECHOPORT_ACTION": "restore", "ECHOPORT_KEY": res["key"],
                                 "ECHOPORT_CHECKSUM": res["checksum_sha256"]})
        self.assertEqual(rc, 1)
        self.assertEqual(self.h.db.read_bytes(), original_db)
        self.assertEqual([e for e in events if e.get("name") == "rollback"][-1]["state"], "success")
        self.assertTrue((self.h.root / "service.running").exists())

    def test_backup_timestamp_cannot_choose_the_local_path(self) -> None:
        outside = self.h.root / "outside"
        rc, events = self.h.run({"ECHOPORT_ACTION": "backup", "ECHOPORT_KEY_PREFIX": "gotosocial/x",
                                 "ECHOPORT_TIMESTAMP": str(outside)})
        self.assertEqual(rc, 0, events)
        self.assertFalse(Path(str(outside) + ".tar.gz").exists())
        self.assertEqual(list((self.h.root / "runner-tmp").iterdir()), [])

    def test_safe_extract_rejects_traversal(self) -> None:
        bad = self.h.root / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            info = tarfile.TarInfo("../escape")
            data = b"x"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        dest = self.h.root / "extract"
        dest.mkdir()
        with self.assertRaises(ValueError):
            self.h.module.safe_extract(bad, dest)


if __name__ == "__main__":
    unittest.main()
