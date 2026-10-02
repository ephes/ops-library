"""Assertions against real apt, systemd and Redis in one disposable container."""
import json
import grp
import pwd
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

import yaml

ROLE = Path("/repo/roles/redis_install")
HERE = Path(__file__).resolve().parent


def command(args, *, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=60)


def state():
    pid = int(
        command(
            ["systemctl", "show", "redis-server", "-p", "MainPID", "--value"]
        ).stdout
    )
    config = Path("/etc/redis/redis.conf")
    directories = {}
    for path in ("/etc/redis", "/var/log/redis", "/var/lib/redis"):
        metadata = Path(path).stat()
        directories[path] = dict(
            mode=stat.S_IMODE(metadata.st_mode),
            uid=metadata.st_uid,
            gid=metadata.st_gid,
        )
    return dict(
        directories=directories,
        pid=pid,
        active=command(
            ["systemctl", "is-active", "redis-server"], check=False
        ).stdout.strip(),
        enabled=command(
            ["systemctl", "is-enabled", "redis-server"], check=False
        ).stdout.strip(),
        ping=command(["redis-cli", "PING"], check=False).stdout.strip(),
        memory=command(
            ["redis-cli", "--raw", "CONFIG", "GET", "maxmemory"], check=False
        ).stdout.splitlines()[-1],
        config=config.read_text(),
        mode=stat.S_IMODE(config.stat().st_mode),
        uid=config.stat().st_uid,
        gid=config.stat().st_gid,
        package=command(["dpkg-query", "-W", "-f=${Version}", "redis-server"]).stdout,
    )


def execute(engine, cfg, fail=False, expected_failure=None):
    Path("/tmp/redis-trial.json").write_text(json.dumps(cfg))
    if engine == "ansible":
        play = [
            dict(
                hosts="localhost",
                gather_facts=False,
                vars=dict(cfg, ansible_python_interpreter="/usr/bin/python3"),
                roles=[str(ROLE)],
            )
        ]
        Path("/tmp/play.json").write_text(json.dumps(play))
        args = ["ansible-playbook", "-i", "localhost,", "-c", "local", "/tmp/play.json"]
    else:
        args = ["pyinfra", "@local", str(HERE / "deploy.py"), "-y"]
    start = time.monotonic()
    completed = command(args, check=False)
    output = completed.stdout + completed.stderr
    if bool(completed.returncode) != fail:
        raise AssertionError(
            f"{engine}: unexpected rc={completed.returncode}\n{output}"
        )
    if expected_failure:
        assert expected_failure in output, output
    changed = (
        None
        if fail
        else (
            int(re.search(r"changed=(\d+)", output).group(1))
            if engine == "ansible"
            else len(re.findall(r"\[@local\] Success(?:\n|$)", output))
        )
    )
    successful_operations = []
    current_operation = None
    for line in output.splitlines():
        if line.startswith("--> Starting operation:"):
            current_operation = line.split(":", 1)[1].strip()
        if "[@local] Success" in line and current_operation:
            successful_operations.append(current_operation)
    return dict(
        successful_operations=successful_operations,
        seconds=round(time.monotonic() - start, 3),
        changed=changed,
        returncode=completed.returncode,
    )


def healthy(snapshot):
    assert snapshot["pid"] > 0 and snapshot["active"] == "active"
    assert snapshot["enabled"] == "enabled" and snapshot["ping"] == "PONG"
    for path, metadata in snapshot["directories"].items():
        assert metadata["mode"] == (0o750 if path == "/var/lib/redis" else 0o755), (
            path,
            metadata,
            snapshot,
        )
        assert metadata["uid"] == (
            0 if path == "/etc/redis" else pwd.getpwnam("redis").pw_uid
        )
        assert metadata["gid"] == (
            0 if path == "/etc/redis" else grp.getgrnam("redis").gr_gid
        )
    assert snapshot["mode"] == 0o644 and snapshot["uid"] == snapshot["gid"] == 0


def main():
    assert os.environ.get("PYINFRA_REDIS_TRIAL") == "1" and Path("/.dockerenv").exists()
    for _ in range(100):
        if Path("/proc/1/comm").read_text().strip() == "systemd" and command(
            ["systemctl", "is-system-running"], check=False
        ).stdout.strip() in ("running", "degraded"):
            break
        time.sleep(0.1)
    else:
        raise AssertionError("Real systemd PID1 unavailable")
    assert (
        command(
            ["dpkg-query", "-W", "-f=${db:Status-Status}", "redis-server"], check=False
        ).stdout
        != "installed"
    )
    cfg = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    cfg.update(
        redis_install_bind_addresses=["127.0.0.1"],
        redis_install_validate_config=False,
        redis_install_logfile="/var/log/redis/redis-server.log",
        redis_install_save_rules=[],
    )
    engine = sys.argv[1]
    rows = {}
    rows["first"] = execute(engine, cfg)
    first = state()
    healthy(first)
    assert first["memory"] == "0"
    command(["redis-cli", "SET", "trial", "retained"])
    rows["noop"] = execute(engine, cfg)
    noop = state()
    healthy(noop)
    assert noop == first
    assert command(["redis-cli", "GET", "trial"]).stdout.strip() == "retained"
    command(["systemctl", "disable", "--now", "redis-server"])
    rows["service_drift_repair"] = execute(engine, cfg)
    service_repaired = state()
    healthy(service_repaired)
    assert service_repaired["config"] == first["config"]
    assert service_repaired["pid"] != first["pid"]
    cfg["redis_install_maxmemory"] = "32mb"
    rows["config_restart"] = execute(engine, cfg)
    updated = state()
    healthy(updated)
    assert updated["pid"] != service_repaired["pid"] and updated["memory"] == "33554432"
    config = Path("/etc/redis/redis.conf")
    config.write_text(config.read_text().replace("maxmemory 32mb", "maxmemory 64mb"))
    for directory, metadata in updated["directories"].items():
        Path(directory).chmod(metadata["mode"] | 0o2000)
    config.chmod(0o600)
    os.chown(config, 65534, 65534)
    rows["drift_repair"] = execute(engine, cfg)
    repaired = state()
    healthy(repaired)
    assert repaired["pid"] != updated["pid"] and repaired["config"] == updated["config"]
    assert repaired["directories"] == updated["directories"]
    rows["optional_validation_failure"] = execute(
        engine,
        dict(cfg, redis_install_validate_config=True),
        fail=True,
        expected_failure="Redis validation failed to start test instance.",
    )
    validation_failed = state()
    assert validation_failed == repaired
    rows["optional_validation_recovery"] = execute(engine, cfg)
    assert state() == repaired
    invalid = dict(cfg, redis_install_loglevel="invalid-fixture-level")
    rows["invalid_config_restart_failure"] = execute(engine, invalid, fail=True)
    assert "invalid-fixture-level" in Path("/etc/redis/redis.conf").read_text()
    assert command(
        ["systemctl", "is-active", "redis-server"], check=False
    ).stdout.strip() in ("failed", "inactive", "activating")
    command(["systemctl", "stop", "redis-server"], check=False)
    command(["systemctl", "reset-failed", "redis-server"])
    rows["invalid_config_recovery"] = execute(engine, cfg)
    recovered = state()
    healthy(recovered)
    assert (
        recovered["config"] == repaired["config"]
        and recovered["pid"] != repaired["pid"]
    )
    override = Path("/etc/systemd/system/redis-server.service.d/trial-failure.conf")
    override.parent.mkdir(parents=True)
    override.write_text(
        "[Service]\nExecStart=\nExecStart=/nonexistent-trial-binary\nRestart=no\n"
    )
    command(["systemctl", "daemon-reload"])
    assert (
        "/nonexistent-trial-binary"
        in command(["systemctl", "show", "redis-server", "-p", "ExecStart"]).stdout
    )
    cfg["redis_install_maxmemory"] = "48mb"
    rows["restart_failure"] = execute(engine, cfg, fail=True)
    assert command(
        ["systemctl", "is-active", "redis-server"], check=False
    ).stdout.strip() in ("failed", "inactive")
    override.unlink()
    command(["systemctl", "daemon-reload"])
    command(["systemctl", "reset-failed", "redis-server"])
    rows["restart_recovery"] = execute(engine, cfg)
    final = state()
    healthy(final)
    assert final["memory"] == "50331648"
    rows["final_noop"] = execute(engine, cfg)
    assert state() == final
    final.pop("pid")
    print(
        json.dumps(
            dict(
                scenarios=rows,
                final_state=final,
                real_systemd_pid1=True,
                package_absent_before_first=True,
                noop_pid_stable=True,
            )
        )
    )


if __name__ == "__main__":
    main()
