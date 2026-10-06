"""Actual Ansible/Redis regression in an isolated systemd container."""
import grp
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time

import yaml

ROLE = Path("/repo/roles/redis_install")


def command(args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=60)


def play(config):
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


def deploy(config, fail=False, check_mode=False):
    play(config)
    started = time.monotonic()
    result = command(
        ["ansible-playbook", "-i", "localhost,", "-c", "local", "/tmp/role-play.json"]
        + (["--check"] if check_mode else []),
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
    assert not list(Path("/tmp").glob("*.redis-validator"))


def disk_snapshot():
    path = Path("/etc/redis/redis.conf")
    metadata = path.stat()
    return dict(
        content=path.read_bytes(),
        mode=stat.S_IMODE(metadata.st_mode),
        uid=metadata.st_uid,
        gid=metadata.st_gid,
        inode=metadata.st_ino,
        mtime_ns=metadata.st_mtime_ns,
        backups={str(p): p.read_bytes() for p in path.parent.glob("redis.conf.*")},
    )


def interrupted_validation(config):
    """Pause after a real Redis launch, then interrupt the actual validator shell."""
    wrapper_dir = Path("/usr/local/bin")
    ready = Path("/tmp/redis-interrupt.ready")
    release = Path("/tmp/redis-interrupt.release")
    wrapper = wrapper_dir / "redis-server"
    assert not wrapper.exists()
    wrapper.write_text(
        "#!/bin/bash\n"
        '/usr/bin/redis-server "$@"\n'
        "result=$?\n"
        'printf \'%s %s\\n\' "$PPID" "$$" > /tmp/redis-interrupt.ready\n'
        "while [[ ! -f /tmp/redis-interrupt.release ]]; do sleep 0.05; done\n"
        'exit "$result"\n'
    )
    wrapper.chmod(0o700)
    play(config)
    before = disk_snapshot()
    running = pid()
    started = time.monotonic()
    process = subprocess.Popen(
        ["ansible-playbook", "-i", "localhost,", "-c", "local", "/tmp/role-play.json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(600):
            if ready.exists():
                break
            if process.poll() is not None:
                raise AssertionError(process.communicate())
            time.sleep(0.05)
        else:
            raise AssertionError("Validation did not reach the interruption boundary")
        validator_pid, _ = map(int, ready.read_text().split())
        # The wrapper has launched the real validation instance with its private socket.
        roots = list(Path("/tmp/redis-config-test").glob("redis-config.*"))
        assert len(roots) == 1 and (roots[0] / "v.sock").is_socket()
        validation_pid = int((roots[0] / "redis-config-test.pid").read_text())
        assert validation_pid != running
        os.kill(validation_pid, 0)
        assert (
            Path(f"/proc/{validation_pid}/exe").resolve()
            == Path("/usr/bin/redis-server").resolve()
        )
        scripts = list(Path("/tmp").glob("*.redis-validator"))
        assert len(scripts) == 1
        assert stat.S_IMODE(scripts[0].stat().st_mode) == 0o700
        assert scripts[0].stat().st_uid == scripts[0].stat().st_gid == 0
        assert stat.S_IMODE((scripts[0] / "validate.sh").stat().st_mode) == 0o700
        assert (scripts[0] / "validate.sh").stat().st_uid == 0
        assert stat.S_IMODE((scripts[0] / "redis.conf").stat().st_mode) == 0o600
        assert (
            (scripts[0] / "redis.conf").stat().st_uid
            == (scripts[0] / "redis.conf").stat().st_gid
            == 0
        )
        os.kill(validator_pid, signal.SIGTERM)
        release.touch()
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode != 0, stdout + stderr
        assert '"rc": 143' in stdout + stderr or "rc=143" in stdout + stderr, (
            stdout + stderr
        )
        assert disk_snapshot() == before
        assert (
            pid() == running and command(["redis-cli", "PING"]).stdout.strip() == "PONG"
        )
        clean_validator()
        return dict(seconds=round(time.monotonic() - started, 3), rc=process.returncode)
    finally:
        release.touch()
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=30)
        wrapper.unlink()
        ready.unlink(missing_ok=True)
        release.unlink(missing_ok=True)


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
    previous_config = disk_snapshot()
    assert previous_config["mode"] == 0o640
    assert previous_config["uid"] == 0
    assert previous_config["gid"] == grp.getgrnam("redis").gr_gid
    checks["invalid_validation"] = deploy(
        dict(config, redis_install_loglevel="invalid-test-value"), fail=True
    )
    assert pid() == updated and command(["redis-cli", "PING"]).stdout.strip() == "PONG"
    assert (
        disk_snapshot() == previous_config
    ), "Invalid candidate changed active configuration or backups"
    clean_validator()
    checks["rejected_retry_valid_noop"] = deploy(config)
    assert pid() == updated and checks["rejected_retry_valid_noop"]["changed"] == 0
    clean_validator()
    checks["interrupted_validation"] = interrupted_validation(
        dict(config, redis_install_maxmemory="48mb")
    )
    active_path = Path("/etc/redis/redis.conf")
    active_path.chmod(0o644)
    checks["interrupted_metadata_only"] = interrupted_validation(config)
    checks["metadata_only_repair"] = deploy(config)
    assert stat.S_IMODE(active_path.stat().st_mode) == 0o640
    assert active_path.stat().st_uid == 0
    assert active_path.stat().st_gid == grp.getgrnam("redis").gr_gid
    clean_validator()
    before_recovery = pid()
    config["redis_install_maxmemory"] = "48mb"
    checks["corrected_recovery"] = deploy(config)
    clean_validator()
    recovered = pid()
    assert recovered != before_recovery
    assert (
        command(
            ["redis-cli", "--raw", "CONFIG", "GET", "maxmemory"]
        ).stdout.splitlines()[-1]
        == "50331648"
    )
    checks["validated_noop"] = deploy(config)
    assert pid() == recovered and checks["validated_noop"]["changed"] == 0
    clean_validator()
    before_check = disk_snapshot()
    checks["check_mode_prediction"] = deploy(
        dict(config, redis_install_maxmemory="64mb"), check_mode=True
    )
    assert checks["check_mode_prediction"]["changed"] > 0
    assert disk_snapshot() == before_check and pid() == recovered
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
                invalid_preserved_disk_config_and_metadata=True,
                interrupted_preserved_disk_config_and_service=True,
                no_leftover_validator_process=True,
            )
        )
    )


if __name__ == "__main__":
    main()
