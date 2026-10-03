# Redis optional validator regression

Run from this repository root on macOS with a local Docker Linux VM:

```sh
python3 tests/redis_validation/run.py
python3 -m unittest discover -s tests/redis_validation -p 'test_*.py'
```

The runner pins a validated local Unix socket and refuses remote transports and
native Linux host execution. It stages only allowlisted role/fixture files and
builds a focused Ansible-only image. Redis is actually installed by the role from
an image-local offline Debian package repository. The disposable privileged
container boots real systemd PID1 with a private cgroup namespace and ephemeral
run/tmp filesystems, execution network disabled, no published ports, and no host
namespace/cgroup/home/device/socket mounts. Privileged guest access is broader
than an unprivileged sandbox; this is a local-VM regression setup, not a
production deployment recipe. Images/cache remain; containers and staged files
are removed on exit.

Assertions reproduce the old no-listener failure with a real Redis process and
retained synthetic logfile, then exercise the changed role: valid validation,
valid change/restart, invalid configuration rejection preserving running PID and
PING and prior file/metadata/backups, corrected recovery, validated no-op,
metadata-only repair, check-mode prediction, controlled TERM interruption after
a real validator instance starts, and no leftover validator process,
socket, log or temporary subdirectory. The invalid test directive must not appear
in Ansible output. Authentication is disabled; there are no production inventories,
secret files or SSH connections. The pass-through interruption wrapper exists
only inside the disposable guest and calls the actual Redis binary.
Local rendered-validator regressions also send repeated INT/TERM during EXIT
cleanup against an owned slow-terminating synthetic process, covering both
initial success and initial failure, with both shell-directed signals and
process-group signals sent only to the fixture's own session. These fixtures stay under the checkout
and work with deep review paths without relaxing the runner safety guards.
Paused owned `cat`/`rm` wrappers exercise cleanup operations under group signals;
a permanent removal-failure case checks the three-attempt bound and failure
status.
See `EVIDENCE.md` for the historical validator repair and
[`TRANSACTIONAL_EVIDENCE.md`](TRANSACTIONAL_EVIDENCE.md) for the subsequent
candidate-install boundary and measured checks.
