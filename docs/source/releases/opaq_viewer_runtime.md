# Opaq disposable runtime fixture

Adds an opt-in Linux/systemd/Traefik lifecycle acceptance fixture for the reviewed
synthetic viewer. Production installer and role behavior are unchanged. It reuses
the existing macOS local Docker Linux VM isolation pattern, a cached immutable
Debian/systemd/Ansible image, and checksum-pinned official Traefik3.7.12 ARM64
archive. No image build, pull or package installation occurs.

Provide the exact staged public bundle from the private controller rehearsal and
an already verified archive:

```sh
python3 scripts/run-opaq-viewer-runtime.py \
  --archive /canonical/scratch/traefik_v3.7.12_linux_arm64.tar.gz \
  --bundle /canonical/staged-synthetic-bundle

```

Run only in an explicitly allocated heavy slot. The fixture is privileged inside
an existing local Linux VM, with private cgroup namespace, no external container
network, no published ports, no Docker socket/global cgroup mounts, and only a
fresh explicit fixture staging directory mounted read-only. Do not run on native
Linux or a remote Docker daemon. Existing containers are untouched; unique owned
container removal is mandatory even on failure.

Inside the disposable container, invented auth and a one-day local CA/certificate
exercise real Traefik TLS, the generated middleware, loopback viewer and systemd.
They are not owner credentials or domain enrollment. The unchanged role exercises
install, no-op, verify, admitted port update, auth/content refusal, first-install
owned removal and update restoration. Rollback restores its recorded predecessor;
it is not a general uninstall or arbitrary historical rollback. No private
inventory, Echoport, financial ingestion or real host/auth/TLS acceptance follows.

Official dependency provenance:
<https://github.com/traefik/traefik/releases/tag/v3.7.12>
Archive SHA256:
``c8d942f80be27c76a55ff483927b36e3be5b0b88299a177ec0882a1fa1c24374``.
A mismatch refuses execution. Runtime success must be recorded separately from
controller/mock checks and from actual homelab deployment readiness.

The full HTTPS response and authenticated retry operation runs in a dedicated
child with a ten-second whole-command cancellation budget. The worker spawns no
descendants; the parent kills and reaps it on timeout. Socket inactivity timeouts
are not the total deadline. Cancellation/cleanup adds scheduling overhead; this
is not an exact real-time return guarantee. Slow-stream and cumulative retry
regressions use controller-local synthetic TLS.
