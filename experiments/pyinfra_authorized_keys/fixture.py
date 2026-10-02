"""Real engine integration assertions, not mocked convergence."""
import copy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

HERE = Path(__file__).resolve().parent
if os.environ.get("PYINFRA_TRIAL_CONTAINER") != "1" or not Path("/.dockerenv").exists():
    raise RuntimeError("Refusing host execution")

BASE = dict(
    enabled=True,
    user="root",
    group="root",
    home="/tmp/trial-home",
    entries=[
        dict(key="generated-in-container", comment="first"),
        dict(
            key="generated-in-container",
            key_options='from="192.0.2.0/24",no-agent-forwarding',
            comment="second",
        ),
    ],
)
PLAY = Path("/tmp/trial-play.json")


def snapshot(home):
    directory = Path(home) / ".ssh"
    file = directory / "authorized_keys"
    if not directory.exists():
        return None
    return dict(
        content=file.read_text(),
        directory_mode=stat.S_IMODE(directory.stat().st_mode),
        file_mode=stat.S_IMODE(file.stat().st_mode),
        uid=file.stat().st_uid,
        gid=file.stat().st_gid,
        directory_uid=directory.stat().st_uid,
        directory_gid=directory.stat().st_gid,
    )


def execute(engine, config, *, fail=False, dry=False):
    Path("/tmp/trial-config.json").write_text(json.dumps(config))
    if engine == "ansible":
        variables = {"ssh_authorized_keys_manage_" + k: v for k, v in config.items()}
        PLAY.write_text(
            json.dumps(
                [
                    dict(
                        hosts="localhost",
                        gather_facts=False,
                        vars=variables,
                        roles=["/repo/roles/ssh_authorized_keys_manage"],
                    )
                ]
            )
        )
        command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(PLAY)]
        if dry:
            command.append("--check")
    else:
        command = ["pyinfra", "@local", str(HERE / "deploy.py"), "-y"]
        if dry:
            command.extend(["--dry", "--diff"])
    started = time.monotonic()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    elapsed = time.monotonic() - started
    output = completed.stdout + completed.stderr
    if bool(completed.returncode) != fail:
        raise AssertionError(
            f"{engine}: unexpected rc={completed.returncode}\n{output}"
        )
    changed = None
    if not fail:
        if engine == "ansible":
            changed = int(re.search(r"changed=(\d+)", output).group(1))
        else:
            changed = len(re.findall(r"\[@local\] Success(?:\n|$)", output))
    return dict(
        seconds=round(elapsed, 3), changed=changed, returncode=completed.returncode
    )


def main():
    result = dict(
        engines={},
        scope="Debian 12 Docker local connectors; actual unchanged Ansible role",
    )
    for index in range(3):
        key_path = f"/tmp/synthetic-{index}"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "", "-f", key_path],
            check=True,
        )
    public_keys = [
        Path(f"/tmp/synthetic-{index}.pub").read_text().strip() for index in range(3)
    ]
    BASE["entries"][0]["key"] = public_keys[0]
    BASE["entries"][1]["key"] = public_keys[1]
    initial_states = {}
    final_states = {}
    for engine in ("ansible", "pyinfra"):
        cfg = copy.deepcopy(BASE)
        cfg["home"] = "/tmp/" + engine + "-home"
        Path(cfg["home"]).mkdir()
        rows = {}
        rows["first"] = execute(engine, cfg)
        good = snapshot(cfg["home"])
        initial_states[engine] = good
        expected = (
            "# Managed by Ansible - local.ops_library.ssh_authorized_keys_manage\n"
            + public_keys[0]
            + " first\n"
            + 'from="192.0.2.0/24",no-agent-forwarding '
            + public_keys[1]
            + " second\n"
        )
        assert good["content"] == expected
        assert rows["first"]["changed"] == 2
        assert good["directory_mode"] == 0o700 and good["file_mode"] == 0o600
        assert all(
            good[k] == 0 for k in ("uid", "gid", "directory_uid", "directory_gid")
        )
        rows["noop"] = execute(engine, cfg)
        assert rows["noop"]["changed"] == 0 and snapshot(cfg["home"]) == good
        file = Path(cfg["home"]) / ".ssh/authorized_keys"
        file.write_text("rogue unauthorized entry\n")
        file.chmod(0o644)
        os.chown(file, 65534, 65534)
        file.parent.chmod(0o755)
        os.chown(file.parent, 65534, 65534)
        drift = snapshot(cfg["home"])
        rows["dry_drift"] = execute(engine, cfg, dry=True)
        assert snapshot(cfg["home"]) == drift
        rows["repair"] = execute(engine, cfg)
        assert rows["repair"]["changed"] == 2 and snapshot(cfg["home"]) == good
        cfg["entries"] = [dict(key=public_keys[2], comment="rotated")]
        rows["rotation"] = execute(engine, cfg)
        rotated = snapshot(cfg["home"])
        assert rows["rotation"]["changed"] == 1 and "first" not in rotated["content"]
        invalids = [
            {"entries": []},
            {"entries": [{"comment": "missing"}]},
            {"user": " "},
        ]
        for index, invalid in enumerate(invalids):
            broken = dict(cfg, **invalid)
            rows[f"invalid_{index}"] = execute(engine, broken, fail=True)
            assert snapshot(cfg["home"]) == rotated
        rows["recovery"] = execute(engine, cfg)
        assert rows["recovery"]["changed"] == 0 and snapshot(cfg["home"]) == rotated
        rows["disabled"] = execute(engine, dict(cfg, enabled=False, entries=[]))
        assert rows["disabled"]["changed"] == 0 and snapshot(cfg["home"]) == rotated
        final_states[engine] = rotated
        result["engines"][engine] = rows
    assert initial_states["ansible"] == initial_states["pyinfra"]
    assert final_states["ansible"] == final_states["pyinfra"]
    result["final_state_equal"] = True
    print(json.dumps(result))


if __name__ == "__main__":
    main()
