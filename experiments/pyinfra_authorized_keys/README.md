# Fresh Pyinfra economics trial

This experiment compares the unchanged `ssh_authorized_keys_manage` role with a
small Pyinfra implementation in a disposable Debian 12 container. It does not
change collection roles or the production orchestration interface.

The role is a useful leaf contract: complete authorized-key replacement,
per-key options/comments, owner and directory/file modes, validation before
mutation, and recovery after invalid inputs. It avoids an uninformative single
hostname operation while keeping systemd, package management and secrets out of
scope. Ephemeral public keys are generated inside the container. Private keys stay
inside it until removal. Neither
implementation validates key cryptography or SSH authentication.

Run from the repository root:

```sh
python3 experiments/pyinfra_authorized_keys/run.py
```

The runner resolves and validates a local Docker Unix socket, pins that daemon
for every Docker command, builds its own image, and executes
both engines inside a uniquely named container removed even after failure.
It refuses SSH/TCP endpoints and strips Docker/BuildKit/builder environment
overrides after resolution. Legacy Docker build (`DOCKER_BUILDKIT=0`) avoids an
independently selected remote buildx builder. An allowlist stages only the two
fixture/deploy scripts and unchanged role defaults/tasks/template under ignored
worktree `tmp/`; only that staged directory is mounted read-only. Source symlinks
are rejected. There are no host ports, SSH connections, production inventories,
or home/key mounts. Dependencies, role execution and all mutations happen inside the
container. Docker image/cache storage is the only persistent Docker side effect.
The script refuses to execute the inner fixture on the host.
Run safety regression checks with:

```sh
python3 -m unittest discover -s experiments/pyinfra_authorized_keys -p 'test_*.py'
```

The Docker runner outputs JSON containing scenario durations and change counts. Build time is reported
separately; initial dependency acquisition needs internet access.

See `EVIDENCE.md` for measured results and remaining decision costs. This is a
trial artifact, not a supported alternate deploy entrypoint or a released role;
therefore the collection version stays unchanged.
