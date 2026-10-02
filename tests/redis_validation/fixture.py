"""Actual Ansible/Redis regression in an isolated systemd container."""
import json
import os
from pathlib import Path
import re
import subprocess
import time

import yaml

ROLE = Path("/repo/roles/redis_install")


def command(args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=60)


def deploy(config, fail=False):
    config = dict(config, ansible_python_interpreter="/usr/bin/python3")
    Path("/tmp/role-play.json").write_text(
        json.dumps(
            [
                dict(
                    hosts="localhost",
                    gather_facts=False,
                    vars=config,
                    roles=[str(ROLE)],
                )
            ]
        )
    )
    started = time.monotonic()
    result = command(
        ["ansible-playbook", "-i", "localhost,", "-c", "local", "/tmp/role-play.json"],
        check=False,
    )
    if bool(result.returncode) != fail:
        raise AssertionError(result.stdout + result.stderr)
    if fail:
        assert "invalid-test-value" not in result.stdout + result.stderr
        assert (
            "Redis validation rejected the configuration."
            in result.stdout + result.stderr
        )
    return dict(
        seconds=round(time.monotonic() - started, 3),
        rc=result.returncode,
        changed=None
        if fail
        else int(re.search(r"changed=(\d+)", result.stdout).group(1)),
    )


def pid():
    return int(
        command(
            ["systemctl", "show", "redis-server", "-p", "MainPID", "--value"]
        ).stdout
    )


def clean_validator():
    after = command(["pgrep", "-x", "redis-server"], check=False).stdout.splitlines()
    assert after == [str(pid())], after
    root = Path("/tmp/redis-config-test")
    assert not root.exists() or not list(root.iterdir()), list(root.iterdir())


def main():
    assert (
        os.environ.get("REDIS_VALIDATION_FIXTURE") == "1"
        and Path("/.dockerenv").exists()
    )
    for _ in range(100):
        if Path("/proc/1/comm").read_text().strip() == "systemd" and command(
            ["systemctl", "is-system-running"], check=False
        ).stdout.strip() in ("running", "degraded"):
            break
        time.sleep(0.1)
    else:
        raise AssertionError("Real systemd PID1 required")
    assert (
        command(
            ["dpkg-query", "-W", "-f=${db:Status-Status}", "redis-server"], check=False
        ).stdout
        != "installed"
    )
    config = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    config.update(
        redis_install_bind_addresses=["127.0.0.1"],
        redis_install_logfile="/var/log/redis/redis-server.log",
        redis_install_save_rules=[],
        redis_install_validate_config=False,
    )
    checks = {"baseline_service": deploy(config)}
    running = pid()
    assert running > 0 and command(["redis-cli", "PING"]).stdout.strip() == "PONG"
    probe = Path("/tmp/old-validator")
    probe.mkdir()
    old = command(
        [
            "redis-server",
            "/etc/redis/redis.conf",
            "--port",
            "0",
            "--pidfile",
            str(probe / "pid"),
            "--logfile",
            str(probe / "log"),
            "--dir",
            str(probe),
            "--save",
            "",
            "--appendonly",
            "no",
            "--daemonize",
            "no",
        ],
        check=False,
    )
    log = (probe / "log").read_text()
    assert "Configured to not listen anywhere, exiting." in log, log
    assert not (probe / "pid").exists() and pid() == running
    checks["old_no_listener"] = {
        "rc": old.returncode,
        "diagnosis": "Configured to not listen anywhere, exiting.",
    }
    config["redis_install_validate_config"] = True
    checks["valid_validation"] = deploy(config)
    assert pid() == running
    clean_validator()
    config["redis_install_maxmemory"] = "32mb"
    checks["valid_change_restart"] = deploy(config)
    clean_validator()
    updated = pid()
    assert updated != running
    assert (
        command(
            ["redis-cli", "--raw", "CONFIG", "GET", "maxmemory"]
        ).stdout.splitlines()[-1]
        == "33554432"
    )
    checks["invalid_validation"] = deploy(
        dict(config, redis_install_loglevel="invalid-test-value"), fail=True
    )
    assert pid() == updated and command(["redis-cli", "PING"]).stdout.strip() == "PONG"
    assert "invalid-test-value" in Path("/etc/redis/redis.conf").read_text()
    clean_validator()
    checks["corrected_recovery"] = deploy(config)
    clean_validator()
    recovered = pid()
    assert recovered != updated
    checks["validated_noop"] = deploy(config)
    assert pid() == recovered and checks["validated_noop"]["changed"] == 0
    clean_validator()
    print(
        json.dumps(
            dict(
                checks=checks,
                package=command(
                    ["dpkg-query", "-W", "-f=${Version}", "redis-server"]
                ).stdout,
                real_systemd_pid1=True,
                invalid_preserved_running_service=True,
                no_leftover_validator_process=True,
            )
        )
    )


if __name__ == "__main__":
    main()
