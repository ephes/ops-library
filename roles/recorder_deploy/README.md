# recorder_deploy

Deploy the **Recorder** application backend — a single static Go binary
(`recorderd`) — as a systemd unit behind Traefik on an Ubuntu/Debian host.

The recorder is a remote podcast recording product: it records each participant
locally at full quality (the double-ender master), uploads chunks resumably to
object storage, finalizes per-track WAV masters plus an alignment manifest, and
(optionally) carries the live call over a self-hosted LiveKit, whose Egress
produces a subordinate fallback recording.

This role models on `navidrome_deploy` (Go binary + systemd + Traefik) but
installs a **locally cross-compiled** `linux/amd64` binary copied from the
control node rather than an upstream release. State lives in SQLite on disk;
media lives in MinIO; the live path is LiveKit. See the product docs and ADRs in
the podcast repo (`docs/recorder/`, `docs/decisions/0005`–`0009`).

## What it does

1. Creates a system user/group and the install, config, and data directories.
2. Copies the `recorderd` binary (`recorder_binary_src`) to `{{ recorder_bin_path }}`.
3. Renders the env file (`recorder.env`, root:recorder 0640) with all runtime
   configuration and secrets.
4. Renders a hardened systemd unit (loopback bind, `EnvironmentFile`,
   `ProtectSystem=strict` + `ReadWritePaths` for the data dir, `Restart=always`).
5. Renders a Traefik dynamic config (`Host(...)`, `tls: {}` using the loaded
   wildcard cert, loadBalancer to the loopback port).
6. Enables/starts the service and runs an HTTP health check against `/health`.

## Required variables

| Variable | Meaning |
| --- | --- |
| `recorder_binary_src` | Path on the control node to the cross-compiled `linux/amd64` `recorderd` binary (the playbook builds it first). |
| `recorder_public_url` | External base URL, e.g. `https://recorder.home.xn--wersdrfer-47a.de`. |
| `recorder_traefik_host` | Traefik host rule (punycode), when Traefik is enabled. |

## Notable optional variables

`recorder_port` (loopback port, default `10015`), `recorder_host_token`
(guards host/dashboard endpoints), the `recorder_s3_*` MinIO settings (when
empty the binary falls back to a local filesystem object store — not for
production), and the `recorder_livekit_*` settings (when empty the live path is
disabled and only the local-master path runs). See `defaults/main.yml`.

## Runtime contract satisfied

Loopback bind, env-only config, idempotent migrations on startup, `GET /health`
→ `200 {"status":"ok"}`, writes confined to the data dir, dedicated non-root
service user — the contract from the deployment research.
