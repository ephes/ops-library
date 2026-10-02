"""Native Pyinfra operations for the scoped distro-package/passwordless contract."""
import io
import json
import os
from pathlib import Path
import re
import shlex

from jinja2 import Environment
from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, server, systemd
import yaml

if (
    os.environ.get("PYINFRA_REDIS_TRIAL") != "1"
    or Path("/proc/1/comm").read_text().strip() != "systemd"
):
    raise RuntimeError("Disposable systemd container required")
cfg = json.loads(Path("/tmp/redis-trial.json").read_text())
# These are explicit scope limits, not support for all redis_install options.
if cfg["redis_install_add_official_repo"] or cfg["redis_install_requirepass_enabled"]:
    raise ValueError("Trial supports only distro packages and disabled authentication")
if (
    not cfg["redis_install_bind_addresses"]
    or not 1 <= int(cfg["redis_install_port"]) <= 65535
):
    raise ValueError("Invalid network settings")
if int(cfg["redis_install_databases"]) <= 0:
    raise ValueError("Invalid database count")
if not re.fullmatch(r"[0-9]+([kmgKMG]?[bB]?)?", str(cfg["redis_install_maxmemory"])):
    raise ValueError("Invalid memory limit")
if cfg["redis_install_maxmemory_policy"] not in (
    "noeviction",
    "allkeys-lru",
    "volatile-lru",
    "allkeys-lfu",
    "volatile-lfu",
    "allkeys-random",
    "volatile-random",
    "volatile-ttl",
) or cfg["redis_install_appendfsync"] not in ("always", "everysec", "no"):
    raise ValueError("Invalid enum")
if (
    int(cfg["redis_install_tcp_backlog"]) <= 0
    or int(cfg["redis_install_timeout"]) < 0
    or int(cfg["redis_install_tcp_keepalive"]) < 0
):
    raise ValueError("Invalid TCP settings")
apt.packages(packages=[cfg["redis_install_package_name"], "redis-tools"], update=True)
files.directory(
    path=cfg["redis_install_data_dir"],
    user=cfg["redis_install_user"],
    group=cfg["redis_install_group"],
    mode="750",
)
files.directory(
    path=cfg["redis_install_log_dir"],
    user=cfg["redis_install_user"],
    group=cfg["redis_install_group"],
    mode="755",
)
files.directory(
    path=str(Path(cfg["redis_install_config_path"]).parent),
    user="root",
    group="root",
    mode="755",
)
# Linux chmod preserves directory setgid unless the numeric mode has five digits.
# Pyinfra normalizes mode strings to ints, so native files ops lose this padding.
for directory, mode in (
    (cfg["redis_install_data_dir"], "750"),
    (cfg["redis_install_log_dir"], "755"),
    (str(Path(cfg["redis_install_config_path"]).parent), "755"),
):
    quoted = shlex.quote(directory)
    server.shell(
        commands=f"chmod 00{mode} {quoted}",
        _if=lambda path=quoted, wanted=mode: host.get_fact(
            Command, command=f"stat -c %a {path}"
        ).strip()
        != wanted,
    )
env = Environment(trim_blocks=True, keep_trailing_newline=True)
env.filters["string"] = str
role = Path("/repo/roles/redis_install")
rendered = env.from_string((role / "templates/redis.conf.j2").read_text()).render(**cfg)
config_upload = files.put(
    src=io.StringIO(rendered),
    dest=cfg["redis_install_config_path"],
    user="root",
    group="root",
    mode="644",
)
if cfg["redis_install_validate_config"]:
    tasks = yaml.safe_load((role / "tasks/configure.yml").read_text())
    validation = next(
        task["ansible.builtin.shell"]
        for task in tasks
        if "ansible.builtin.shell" in task
    )
    # Reuse existing validation shell; real short-lived Redis, not a mocked parser.
    server.shell(
        commands=env.from_string(validation).render(**cfg),
        _shell_executable="/bin/bash",
    )
if cfg["redis_install_restart_on_change"]:
    systemd.service(
        service=cfg["redis_install_service_name"],
        restarted=True,
        _if=config_upload.did_change,
    )
systemd.service(service=cfg["redis_install_service_name"], enabled=True, running=True)
server.shell(commands="redis-cli -p " + str(cfg["redis_install_port"]) + " PING")
