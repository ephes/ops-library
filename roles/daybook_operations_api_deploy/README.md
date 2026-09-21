# daybook_operations_api_deploy

Install the separate Daybook JSON API and plain reconciliation loop on Linux.

Disabled by default. PostgreSQL, source, dependencies, schema, profile identities,
loopback systemd units and a private TLS router are installed; neither service
starts until `daybook_operations_api_enabled: true`. Binding activation is a
separate boolean in `daybook_operations_api_profiles`. The first adapter must
remain disabled through installation and restore rehearsal.

The host needs the shared PostgreSQL and Traefik infrastructure. PostgreSQL and
uv bootstrap roles are included. Traefik must already own the web-secure entry
point and matching certificate. Direct DB credentials stay on the server.
Development uses rsync; production git requires an exact reviewed 40-character
revision. The venv and credentials are outside the rsync tree.

Profiles are a list of `name`, `host`, `profile`, `binding`, `enabled`,
`binding_enabled`, and `tokens`. Keep `enabled` true and `binding_enabled` false
to drain results without admitting work. Token rotation must preserve principal
identity; signing key versions must be retained while any attempt references them.
All secrets come from the caller and are rendered with `no_log`, never command
arguments. The public role contains no inventory host identities or credentials.

Example (secret variables supplied by an encrypted private control repository):

```yaml
- role: local.ops_library.daybook_operations_api_deploy
  vars:
    daybook_operations_api_source_path: /local/daybook
    daybook_operations_api_enabled: false
    daybook_operations_api_secret_key: "{{ private_django_key }}"
    daybook_operations_api_database_password: "{{ private_db_password }}"
    daybook_operations_api_signing_keys: "{{ private_keyring }}"
    daybook_operations_api_signing_key_id: v1
    daybook_operations_api_profiles: "{{ private_profiles }}"
```

Status: `/healthz` proves DB connectivity only. Use `daybook operations status`
on the client for scan age, backlog, blocked/awaiting state and admission storage.
Inspect both `daybook-operations` and `daybook-operations-reconcile` units. No
source-health claim follows from the HTTP readiness check alone.

Use the sibling backup/restore/remove roles for lifecycle actions. Archives
contain credentials and must remain private. Restore requires quiesced clients
and leaves services stopped. Removal preserves the database, config and code.

## Defaults and variables

```yaml
---
ops_library_documentation_category: deployment
daybook_operations_api_enabled: false
daybook_operations_api_user: daybook-operations
daybook_operations_api_home: /home/daybook-operations
daybook_operations_api_site: "{{ daybook_operations_api_home }}/site"
daybook_operations_api_venv: "{{ daybook_operations_api_home }}/venv"
daybook_operations_api_config_dir: /etc/daybook-operations
daybook_operations_api_source_path: ""
daybook_operations_api_deploy_method: rsync
daybook_operations_api_git_repo: https://github.com/ephes/daybook.git
daybook_operations_api_git_revision: CHANGEME
daybook_operations_api_uv: /usr/local/bin/uv
daybook_operations_api_port: 10063
daybook_operations_api_domain: operations.home.example.com
daybook_operations_api_secret_key: CHANGEME
daybook_operations_api_signing_keys: {}
daybook_operations_api_signing_key_id: ""
daybook_operations_api_profiles: []
daybook_operations_api_record_limit: 100000
daybook_operations_api_postgres_version: "17"
daybook_operations_api_database: daybook_operations
daybook_operations_api_database_user: daybook_operations
daybook_operations_api_database_password: CHANGEME
daybook_operations_api_database_url: "postgresql://{{ daybook_operations_api_database_user }}:{{ daybook_operations_api_database_password | urlencode | replace('/', '%2F') }}@127.0.0.1:5432/{{ daybook_operations_api_database }}"
daybook_operations_api_allowed_networks:
  - 100.64.0.0/10
  - fd7a:115c:a1e0::/48
daybook_operations_api_traefik_path: /etc/traefik/dynamic/daybook-operations.yml
daybook_operations_api_backup_root: /opt/backups/daybook_operations
```

## Validation

Local contract tests exercise disabled defaults, rendered units/plists and lifecycle
safety. The Daybook suite exercises real PostgreSQL concurrency and dump/restore,
HTTP delivery recovery and importer regression fixtures. Live deployment and
attended import/rollback validation remain required before production acceptance.

At the fixed 300-second cadence, the 100000-record admission limit lasts roughly
87 days (four records/cycle). Review storage at 80% and raise the configured limit
only after checking DB/archive space and restore duration. Never delete replay
evidence or referenced signing keys. Automatic compaction is not provided.
