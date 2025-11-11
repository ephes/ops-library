# Postgres Install Role

Install and configure PostgreSQL from the official PGDG repository (or distro packages) with managed databases, roles, and config overrides.

## Features

- Installs PostgreSQL server/client/contrib packages for a specific major version
- Optionally configures the official `apt.postgresql.org` repository
- Renders a drop-in `conf.d` file for `listen_addresses`, `port`, and arbitrary overrides
- Templates `pg_hba.conf` from structured rules
- Ensures the systemd service is enabled and running
- Creates databases, roles, extensions, and updates the `public` schema owner
- Designed to be reusable across services (Paperless, FastDeploy, etc.)

## Requirements

- Ansible `2.15+`
- Debian 11+/Ubuntu 20.04+ with systemd
- Target host must allow the `postgres_install_admin_user` (default `postgres`) to manage databases via peer auth or password
- Ansible collection `community.postgresql` (install via `ansible-galaxy collection install community.postgresql`)

## Variables

Full list in `defaults/main.yml`. Key knobs:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `postgres_install_version` | `17` | PostgreSQL major version to install |
| `postgres_install_use_pgdg_repo` | `true` | Toggle the official PGDG apt repo |
| `postgres_install_packages` | Server/client/contrib/libpq-dev | Package list to install |
| `postgres_install_listen_addresses` | `['localhost']` | Addresses for `listen_addresses` |
| `postgres_install_port` | `5432` | TCP port |
| `postgres_install_manage_conf_d` | `true` | Render `conf.d/20-ops-library.conf` overrides |
| `postgres_install_config_overrides` | `{}` | Extra `key = value` lines in the drop-in file |
| `postgres_install_manage_pg_hba` | `true` | Render `pg_hba.conf` from `postgres_install_pg_hba_rules` |
| `postgres_install_databases` | `[]` | Databases to create (name/owner/encoding/locale) |
| `postgres_install_users` | `[]` | Roles to create (name/password/flags) |
| `postgres_install_extensions` | `[]` | Extensions to enable per database |

> Provide passwords via SOPS/Ansible Vault and avoid committing plaintext secrets. The role redacts password changes automatically.
> The `postgres_install_users[].encrypted` flag controls whether the provided password is pre-hashed; leave it unset/false for plaintext values that PostgreSQL should hash itself (SCRAM by default).

### pg_hba.conf rules

Each entry in `postgres_install_pg_hba_rules` maps directly to a pg_hba line and supports an optional `comment` field:

```yaml
postgres_install_pg_hba_rules:
  - type: local
    database: all
    user: postgres
    auth_method: peer
    comment: "Peer access for admin user"
  - type: host
    database: paperless
    user: paperless
    address: "127.0.0.1/32"
    auth_method: scram-sha-256
```

### Configuration overrides

`postgres_install_config_overrides` writes additional `key = value` pairs into `conf.d/20-ops-library.conf`. String values are automatically quoted:

```yaml
postgres_install_config_overrides:
  max_connections: 200
  shared_buffers: 1GB
  effective_cache_size: 4GB
```

## Examples

### Localhost-only database for Paperless

```yaml
- hosts: homelab
  become: true
  roles:
    - role: local.ops_library.postgres_install
      vars:
        postgres_install_version: "17"
        postgres_install_databases:
          - name: paperless
            owner: paperless
        postgres_install_users:
          - name: paperless
            password: "{{ sops_secrets.paperless_postgres_password }}"
```

### Custom config + extension

```yaml
- hosts: analytics
  become: true
  roles:
    - role: local.ops_library.postgres_install
      vars:
        postgres_install_use_pgdg_repo: false  # use distro packages
        postgres_install_listen_addresses:
          - 0.0.0.0
          - ::1
        postgres_install_config_overrides:
          max_connections: 200
          shared_buffers: "1GB"
        postgres_install_databases:
          - name: analytics
            owner: analytics
        postgres_install_users:
          - name: analytics
            password: "{{ vault.analytics_password }}"
        postgres_install_extensions:
          - name: postgis
            database: analytics
```

## Verification

1. `psql -U postgres -c "SELECT version();"`
2. `systemctl status {{ postgres_install_service_name }}`
3. `ss -lntp | grep {{ postgres_install_port }}` to confirm the port is listening

## Security & Privileges

- The role updates `pg_hba.conf` from `postgres_install_pg_hba_rules`. Be explicit about every access path (local, loopback, Tailscale, etc.) to avoid silently inheriting distro defaults.
- When you define a database `owner`, the role automatically alters the `public` schema owner to match. This mirrors the upstream recommendation to prevent unprivileged accounts from creating objects in `public`.
- Passwords passed via `postgres_install_users` are treated as plaintext (SCRAM hashed server-side) unless you set `encrypted: true`, which allows supplying pre-hashed strings for advanced setups.

Documented expectations:
1. After convergence, `public` belongs to the same owner as the database.
2. Application users can authenticate over `localhost` using SCRAM (the default `postgres_install_pg_hba_rules` grant loopback access with `scram-sha-256`).

## Testing

### Automated Molecule scenario

```bash
cd roles/postgres_install
molecule test
```

The scenario provisions PostgreSQL 17 on Ubuntu 24.04, creates a `molecule` database/user, enables the `pg_trgm` extension, and reruns the role to assert idempotency. Verification checks the service status, schema ownership, and password authentication.

### Manual smoke test

```bash
ansible-playbook -i localhost, tests/postgres.yml --connection=local
psql -U postgres -c "SELECT version();"
```

## Troubleshooting

| Issue | Steps |
| ----- | ----- |
| Role fails while templating configs | Ensure `/etc/postgresql/{{ version }}/{{ cluster }}` exists (package install should create it); rerun with `-vvv` for details |
| Cannot connect using password | Confirm `pg_hba.conf` allows the client IP and auth method, then reload via `systemctl reload postgresql` |
| Databases/users not created | Verify the `postgres_install_admin_user` has peer access or provide `postgres_install_admin_password` |
