# gotosocial_deploy

Deploys [GoToSocial](https://docs.gotosocial.org/) from a pinned upstream
release: checksum-verified binary under `/opt/gotosocial/releases/<version>`,
SQLite database and local media storage in `/var/lib/gotosocial`, a hardened
systemd unit, a loopback listener and a Traefik route.

Written for a single-user instance (the Takahē successor for
`@show@python-podcast.de`); see ops-control `docs/GOTOSOCIAL.md` for the
runbook and the migration plan.

## What it does

1. Validates inputs (DNS-name host that is the account domain or a subdomain
   of it, loopback listener, exact version and sha256 checksums, no secrets
   and no guarded settings in `gotosocial_extra_config`).
2. Installs `sqlite3` (for consistent `.backup` snapshots by the backup runner).
3. Creates the system user `gotosocial`, `/etc/gotosocial` (root:gotosocial
   0750) and `/var/lib/gotosocial` (0700, the only writable path of the unit).
4. **Guards the domain layout**: the first deploy records `host account-domain`
   in `/var/lib/gotosocial/.ops-domain-layout`; a later deploy with a different
   pair fails. GoToSocial cannot change its layout once it has federated.
5. Downloads the release archive only if that version is not installed yet,
   verifies its sha256, unpacks it and points `/opt/gotosocial/current` at it.
6. Renders `/etc/gotosocial/config.yaml` (0640), the systemd unit and the admin
   wrapper `/usr/local/sbin/gotosocial-admin`.
7. Starts the service and waits for `GET /readyz` on loopback.
8. Renders `/etc/traefik/dynamic/gotosocial.yml`, or removes it when
   `gotosocial_traefik_enabled: false`.

## Key variables

| Variable | Default | Notes |
|---|---|---|
| `gotosocial_version` | `0.22.2` | Bump together with `gotosocial_release_checksums` (from the release's `checksums.txt`). |
| `gotosocial_release_checksums` | amd64 + arm64 | `sha256:<hex>` per architecture. |
| `gotosocial_host` | `CHANGEME` | DNS name the instance is served on (required). |
| `gotosocial_account_domain` | `""` | Handle domain (`@user@<domain>`); empty = host. |
| `gotosocial_allow_domain_layout_change` | `false` | Only for a wiped data directory. |
| `gotosocial_bind_address` / `gotosocial_port` | `127.0.0.1` / `10070` | Loopback only (validated). |
| `gotosocial_accounts_registration_open` | `false` | Accounts are created with `gotosocial-admin`. |
| `gotosocial_instance_languages` | `[]` | BCP47 tags. |
| `gotosocial_media_remote_cache_duration` | `7 days` | Remote media is pruned by GoToSocial's own cron. |
| `gotosocial_smtp_*` | disabled | `gotosocial_smtp_password` belongs in SOPS. |
| `gotosocial_extra_config` | `{}` | Further config keys, merged last. Refused: keys containing password/secret/key, and every key in `gotosocial_guarded_config_keys` (host, account-domain, protocol, bind-address, port, trusted-proxies, database and storage settings, web asset paths, registrations) — set those through their `gotosocial_*` variables. |
| `gotosocial_service_state` | `started` | `stopped` prepares an instance without running it. |
| `gotosocial_traefik_enabled` | `true` | `false` removes the route (instance runs but is not reachable from outside). |
| `gotosocial_traefik_cert_resolver` | `""` | Set `letsencrypt` on hosts without an entrypoint default resolver (staging). |
| `gotosocial_systemd_memory_max` | `1G` | Empty string removes the limit. |

## Traefik exposure: exception to the dual-router policy

The route is a single public router (`Host()` only, HTTPS redirect, HSTS,
`X-Frame-Options: DENY` matching what GoToSocial sends itself). It has **no
Basic Auth**: ActivityPub peers and fediverse client apps cannot pass a
shared Basic Auth credential, exactly as for Takahē and Mastodon. Protection
comes from the application: registrations are closed, accounts are created by
an admin, and the owner account should enable two-factor authentication in the
settings panel (`/settings`). Recorded per ops-control
`docs/TRAEFIK_SECURITY.md` ("Exception Handling", explicitly documented risk).

## Accounts and admin commands

```bash
gotosocial-admin account create --username show --email you@example.org --password '<pw>'
gotosocial-admin account promote --username show && systemctl restart gotosocial
```

The CLI takes the password as an argument (visible in the process list for
the moment the command runs); run it on the host, not from a shared session.
Commands marked "restart required" in the GoToSocial CLI docs need
`systemctl restart gotosocial`.

## Upgrades

Bump `gotosocial_version` and both checksums, read the release notes for
migrations (they run on start and can take minutes on large databases), take a
backup first, then deploy. The previous release stays in `releases/` for a
quick rollback of the binary; a database migrated by a newer version is not
guaranteed to work with the old binary, so roll back with the backup.

## Testing

- `just test-gotosocial-deploy`: validation and rendered config/route/unit.
- `just test-gotosocial-molecule`: real install in a systemd container
  (download, start, `/readyz`, WebFinger for a created account, loopback-only
  listener, file modes, idempotence, refusal of a changed domain layout).
