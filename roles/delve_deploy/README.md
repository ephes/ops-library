# delve_deploy

Deploy the **Delve backend service** — a single static Go binary (`delved`) — as
a systemd unit behind Traefik on an Ubuntu/Debian host.

Delve is the player's shared backend (placeholder name; `apps/delve-backend` in
the podcast repo). It hosts the accounts, entitlements, StoreKit, and Discovery
modules behind one principal-resolution middleware (ADR 0012). State lives in
SQLite on disk; there is no object store or live path, so this role is a stripped
sibling of `recorder_deploy`: no frontend build, no MinIO, no LiveKit, no mail.

The role installs a **locally cross-compiled** `linux/amd64` binary copied from
the control node rather than an upstream release.

## What it does

1. Creates a system user/group (`delve`) and the install, config, and data dirs
   (`/opt/delve`, `/etc/delve`, `/var/lib/delve`).
2. Installs the cross-compiled `delved` binary to `/opt/delve/delved`.
3. Renders `/etc/delve/delve.env` (mode 0640, `no_log`) from the passed config.
4. Installs a hardened systemd unit and (optionally) a Traefik dynamic route for
   the public host.
5. Enables/starts the service and runs a loopback `/health` check.

## Required variables

- `delve_binary_src` — path to the cross-compiled `delved` on the control node.
- `delve_session_secret` — HMAC session secret, **≥16 chars** (the binary refuses
  to boot otherwise). Pass from SOPS.

## Notable optional variables

- `delve_public_url` / `delve_traefik_host` — default to
  `delve.home.xn--wersdrfer-47a.de` (the IDNA/punycode form of
  `delve.home.wersdörfer.de`, so the Traefik router and TLS SNI match).
- `delve_port` — loopback port Traefik proxies to (default `10026`).
- `delve_dogfood_token` — enables the interim `dogfoodGrant` path.
- `delve_apple_client_id` — enables `POST /v1/accounts/apple` (the app bundle id).
- `delve_storekit_root_certs_path` + `delve_storekit_bundle_id` +
  `delve_storekit_product_ids` — enable StoreKit verification. The certs path must
  point at a PEM file on the host; when the path is set, the bundle id and product
  ids are required (validated, and enforced by the binary at startup).

See `defaults/main.yml` for the full list. Secrets are passed by the playbook
(`ops-control/playbooks/delve/deploy.yml`), never defaulted here.
