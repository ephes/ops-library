# Paperless Deploy Role

Deploy [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) on bare metal hosts using uv-managed Python, encrypted storage, Redis, and systemd units.

## Features

- Installs prerequisite system packages and delegates PostgreSQL provisioning to the shared `postgres_install` role (PGDG repo enabled by default).
- Manages the `paperless` system user, directory layout, and symlinks to `/mnt/cryptdata/paperless`, with optional mount verification.
- Configures the scanner SFTP chroot (bind mount, ACLs, legacy cipher suites) so Brother devices can upload directly into the `consume/` directory.
- Creates a uv virtualenv, downloads the Paperless release, installs Python dependencies idempotently, and fetches the required NLTK datasets.
- Renders `.env`, `gunicorn.conf.py`, four systemd service units, Traefik config, and the SSH scanner drop-in; services are started and verified alongside an HTTP `/api/` health check.
- Integrates with existing `uv_install`, `redis_install`, and `postgres_install` roles. Redis authentication is optional (default: disabled per migration spec); when a password is provided the template emits `redis://:password@…`.

## Requirements

- `/mnt/cryptdata` (or whatever `paperless_external_storage_root | dirname` is set to) must be mounted before running the role. Set `paperless_verify_storage_mount: false` to skip the assertion (not recommended).
- SOPS secrets (see below) must provide non-`CHANGEME` values for the Django secret key, database password, admin password, and scanner password. `paperless_secret_key` must be at least 50 characters.
- Redis must be deployed first via `redis_install`; `paperless_deploy` only consumes the configured instance.
- The host needs outbound internet access the first time (to download the release tarball, uv packages, NLTK datasets, and the PostgreSQL apt key). Subsequent runs reuse the install marker unless `paperless_force_reinstall` is set.

## Key Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `paperless_version` | Paperless-ngx release to install | `2.18.2` |
| `paperless_external_storage_root` | Path to encrypted storage mount | `/mnt/cryptdata/paperless` |
| `paperless_postgres_version` | PostgreSQL major version | `17` |
| `paperless_postgres_repo_enabled` | Add the official PGDG repo | `true` |
| `paperless_secret_key` | Django secret key (**required via secrets**) | `"CHANGEME"` |
| `paperless_postgres_password` | DB password (**required via secrets**) | `"CHANGEME"` |
| `paperless_admin_user/email/password` | Admin bootstrap user | `admin / admin@example.com / "CHANGEME"` |
| `paperless_scanner_password` | Scanner SFTP password | `"CHANGEME"` |
| `paperless_redis_password` | Redis password (empty = no auth) | `""` |
| `paperless_force_reinstall` | Force uv/pip reinstall even if marker exists | `false` |
| `paperless_manage_symlinks` | Control creation of site→storage symlinks | `true` |
| `paperless_verify_storage_mount` | Assert encrypted volume mounted | `true` |

See `defaults/main.yml` for the full list including OCR options, Traefik knobs, scanner ACL toggles, and dataset controls.

> PostgreSQL-specific variables (version, repo toggles, database/user/password) are passed directly to `local.ops_library.postgres_install`, which now owns package installation, config management, and database/user creation.

## Example Usage

```yaml
- hosts: paperless
  roles:
    - role: local.ops_library.paperless_deploy
      vars:
        paperless_secret_key: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['paperless_secret_key'] }}"
        paperless_postgres_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['postgres_password'] }}"
        paperless_admin_user: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['paperless_admin_user'] }}"
        paperless_admin_email: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['paperless_admin_email'] }}"
        paperless_admin_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['paperless_admin_password'] }}"
        paperless_scanner_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['paperless_scanner_password'] }}"
        paperless_redis_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['redis_password'] }}"
```

## Scanner SFTP Workflow

1. The role creates a system `scanner` user (password defined in secrets) and chroots it into `paperless_sftp_chroot_dir` (default `/srv/sftp-scanner`).
2. `/srv/sftp-scanner/inbox` is bind-mounted to `paperless_consume_path`; uploaded files appear immediately in the Paperless `consume/` directory.
3. Legacy SSH cipher/KEX algorithms are enabled to satisfy older Brother firmware. Replace or tighten them once the hardware supports modern crypto.
4. The scanner user is added to the `paperless` group and granted ACLs so Paperless owns the files post-ingestion. Disable ACL management with `paperless_configure_scanner_acl: false`.

## Traefik Integration

Set `paperless_traefik_domain`, `paperless_traefik_entrypoint`, and `paperless_traefik_cert_resolver` to match your Traefik deployment. The template writes `/etc/traefik/dynamic/paperless.yml` and triggers a reload handler. Disable it entirely with `paperless_traefik_enabled: false` if another proxy manages the route.

## Redis Authentication Decision

By default `paperless_redis_password` is empty, matching the spec’s recommendation to avoid unauthenticated Redis mismatches during migration. When you later enable Redis auth:

```yaml
paperless_redis_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['redis_password'] }}"
paperless_redis_requirepass_enabled: true
```

The `.env` template automatically emits either `redis://localhost:6379/0` (no auth) or `redis://:password@localhost:6379/0`.

## Troubleshooting

- **PostgreSQL packages fail to install**: Ensure outbound network access to `apt.postgresql.org` or disable `paperless_postgres_repo_enabled` and adjust `paperless_postgres_version` to what the distro provides.
- **Encrypted storage assertion fails**: Mount `/mnt/cryptdata` (or change `paperless_external_storage_root`) before running the role, or temporarily set `paperless_verify_storage_mount: false` if you are running in a lab environment without the encrypted disk.
- **Scanner uploads fail**: Confirm `/srv/sftp-scanner` bind mount is active (`mount | grep sftp-scanner`) and that the ACLs grant `scanner` RWX permissions on `consume/`.
- **Redis auth errors**: Double-check the password stored in secrets matches what `redis_install` configured; the template now conditionally inserts the password exactly once.
- **Service unhealthy**: The role waits for `systemctl is-active` and for `http://127.0.0.1:10030/api/` to return 200. Inspect `journalctl -u paperless*` if the health check keeps retrying.

## Migration Notes

- The `paperless_current_symlink` replaces version-specific directories and keeps backups/restores path-stable (`/home/paperless/site/paperless-ngx/src`).
- After migrating from the legacy repository, keep the old host around until `paperless_backup` archives created via ops-control have been tested with `paperless_restore`.
- When upgrading Paperless: bump `paperless_version`, `paperless_release_url`, and run with `paperless_force_reinstall: true` to rebuild the uv environment; verify services, then clear the marker file if necessary.

## TODO

- Expand automated tests in `test_roles.py` (integration with paperless_backup/paperless_restore).
- Add optional key-based authentication for the scanner user.
