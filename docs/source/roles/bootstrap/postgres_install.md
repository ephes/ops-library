# Postgres Install Role

Bootstrap role for installing PostgreSQL with managed databases, users, and config drop-ins.

## Capabilities

- Installs PostgreSQL server/client/contrib packages for a chosen major version
- Optionally enables the official `apt.postgresql.org` repository
- Templates `conf.d/20-ops-library.conf` for `listen_addresses`, `port`, and extra overrides
- Renders `pg_hba.conf` from structured rules
- Ensures the systemd service is enabled and running
- Creates databases, roles, and extensions while updating the `public` schema owner

## Requirements

- Debian/Ubuntu host with systemd
- Ansible collection `community.postgresql` (install via `ansible-galaxy collection install community.postgresql`)

## Usage

```yaml
- hosts: db_hosts
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/paperless.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.postgres_install
      vars:
        postgres_install_version: "17"
        postgres_install_databases:
          - name: paperless
            owner: paperless
        postgres_install_users:
          - name: paperless
            password: "{{ secrets.postgres_password }}"
```

Expose PostgreSQL beyond localhost and add custom settings:

```yaml
- hosts: analytics
  become: true
  roles:
    - role: local.ops_library.postgres_install
      vars:
        postgres_install_listen_addresses:
          - 0.0.0.0
          - ::1
        postgres_install_port: 5433
        postgres_install_config_overrides:
          max_connections: 200
          shared_buffers: "512MB"
        postgres_install_pg_hba_rules:
          - {type: local, database: all, user: all, auth_method: peer}
          - {type: host, database: all, user: all, address: "10.0.0.0/24", auth_method: scram-sha-256}
```

## Key Variables

- `postgres_install_version`: PostgreSQL major version (default `17`)
- `postgres_install_use_pgdg_repo`: Enable the official PGDG apt repo (default `true`)
- `postgres_install_listen_addresses`: List of addresses for `listen_addresses`
- `postgres_install_port`: TCP port for PostgreSQL
- `postgres_install_databases`: Databases to create (name/owner/locale/template)
- `postgres_install_users`: Roles to create (name/password/role flags)
- `postgres_install_extensions`: Extensions per database
- `postgres_install_config_overrides`: Extra `key = value` pairs appended to the drop-in file

### pg_hba.conf rules

```yaml
postgres_install_pg_hba_rules:
  - type: local
    database: all
    user: postgres
    auth_method: peer
  - type: host
    database: paperless
    user: paperless
    address: "127.0.0.1/32"
    auth_method: scram-sha-256
    comment: "Paperless application access"
```

### Configuration overrides

```yaml
postgres_install_config_overrides:
  max_connections: 200
  shared_buffers: 1GB
```

Refer to `roles/postgres_install/defaults/main.yml` for the full list.
