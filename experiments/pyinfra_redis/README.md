# Disposable Redis package/service economics trial

This contrasts the earlier public-file trial with the unchanged `redis_install`
role: real Debian package installation, Redis configuration, systemd enable/start,
change-triggered restart, runtime health, drift and failure recovery.

Run `python3 experiments/pyinfra_redis/run.py` from the repository root. It needs
local Docker on macOS backed by its Linux VM. The runner pins a validated local
Unix-socket daemon and stages only allowlisted public role/fixture files. Image
build downloads Debian packages into a local offline repository; execution has
no network or published ports. Two separate disposable containers boot real
systemd as PID 1, using private cgroup namespaces and privileged mode inside the
Docker VM, with no host namespace or host cgroup/home/device/socket mounts.
Privilege isolation is weaker than an unprivileged container; this fixture is
not intended for an existing Linux infrastructure host.

`EVIDENCE.md` records measured behavior, limitations and decision costs. This
experiment adds no production deployment entrypoint and makes no collection
version change. Authentication is disabled and Redis binds localhost inside the
container; no private secrets or SOPS integration are used.

Run runner-safety regression checks with:

```sh
python3 -m unittest discover -s experiments/pyinfra_redis -p 'test_*.py'
```

The optional existing Redis config validation is probed separately and fails to
produce a pidfile with valid config in this fixture. Normal convergence uses its
default disabled setting. Invalid config consequently causes real restart
failure/downtime before recovery; this is not a safe rollback demonstration.
