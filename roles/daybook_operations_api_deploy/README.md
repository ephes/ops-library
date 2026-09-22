# daybook_operations_api_deploy

Install the separate Daybook JSON API and plain reconciliation loop on Linux.

Disabled by default. PostgreSQL, source, dependencies, schema, profile identities,
loopback systemd units and a private TLS router are installed; neither service
starts until `daybook_operations_api_enabled: true`.

The host needs the shared PostgreSQL and Traefik infrastructure. PostgreSQL and
uv bootstrap roles are included. Traefik must already own the web-secure entry
point and matching certificate. Direct DB credentials stay on the server.
Development uses rsync; production git requires an exact reviewed 40-character
revision. The venv and credentials are outside the rsync tree.

Profiles are a list of **schema 4** entries, each exactly `schema`, `name`,
`host`, `profile`, `enabled`, `tokens` and `monitor_tokens` -- the machine's
identity and credentials, and **no sources at all**:

```yaml
- name: studio-importer
  schema: 4
  host: studio
  profile: voice-memo-importer
  enabled: true
  tokens: ["{{ executor_token }}"]
  monitor_tokens: ["{{ monitor_token }}"]
```

Tokens in `tokens` receive **executor** authority; tokens in `monitor_tokens`
receive **monitor** authority, which reaches only the read-only aggregate status
route and is refused on every mutating route. A token may not appear in both
lists, and an existing credential's purpose is immutable -- rotate to a new token
instead of promoting or demoting one in place. Token rotation must preserve
principal identity; signing key versions must be retained while any attempt
references them. All secrets come from the caller and are rendered with `no_log`,
never command arguments. The public role contains no inventory host identities or
credentials.

Sources are rows on the server, and a source belongs to no machine: it declares
what it requires, a machine what it offers, and the server hands a source only to
a machine offering all of it. They are managed on the server, with no redeploy or
restart:

```
manage.py sources add NAME --adapter A --cadence S --lease S [--requires a,b] [--enabled]
manage.py sources set NAME [--cadence S] [--lease S] [--requires a,b] [--enabled true|false]
manage.py machines set NAME --offers a,b
```

Schemas 1 to 3 named the sources a machine ran, which pinned each source to that
machine and made every deploy `update_or_create` it -- reverting any change made in
the database, and switching a running source off whenever an `enabled` override
was forgotten. The role and the provisioner refuse them whole. Keep a principal
`enabled` while disabling a source (`sources set NAME --enabled false`) to drain
results without admitting work.

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

`GET /v1/status` is the monitoring surface. It is genuinely read-only: it performs
no write, never expires an attempt and never advances executor liveness, so polling
it cannot make a dead client look alive. It reports admission count/limit/utilization
and the growth forecast for the authorized principal, server database bytes and
filesystem headroom, and for every source -- none belongs to a principal -- contact, accepted-result, scan and import
freshness plus the age of un-applied receipts. Expiry is calculated for the reader
and deliberately not persisted; the reconciler and the existing write paths remain
the only places that expire an attempt.

Because the existing JSON-metrics monitor cannot send a bearer header, this one
route also accepts the monitor token over HTTP Basic with the fixed username
`monitor`. Basic is refused on every other route and purpose is still enforced in
the service, so it is a transport for monitor authority, never a path to executor
authority. Serve it over the private TLS origin; the token is a credential at rest
wherever the monitor stores its check configuration.

Storage gauges are sampled server-side on the existing reconciler lifecycle, at most
once per `daybook_operations_api_storage_sample_interval`, from the operator-configured
`daybook_operations_api_storage_path`. No client selects that path and no new client
timer is added. A sample older than `daybook_operations_api_storage_sample_max_age`,
a missing sample, an unconfigured path and an unreadable path are each reported
distinctly and are **unknown/alerting, never green**.

Capacity warns at `daybook_operations_api_capacity_warn_utilization` (0.70) or
`daybook_operations_api_capacity_warn_days` (30) remaining, and goes critical at
0.80 or 14 days. The forecast uses the higher of the configured nominal growth and
the measured 24-hour/7-day growth; a window is only used once the principal's own
history is that old, otherwise the estimate is labelled `insufficient_history` and
the nominal rate keeps the horizon finite rather than infinite. The admission limit
is **principal-wide** and counts the work that machine did -- the messages it
stored, the operations its questions created, the attempts it claimed. It is not
multiplied by the number of sources, and at the boundary that machine stops
acquiring new work on any source while outstanding
receipts, identical replays and status stay available. There is no automatic limit
increase and no automatic deletion.

The configuration directory is service-owned with mode 0750; individual secret
files use mode 0600. The unprivileged restore helper needs directory write access
to replace configuration atomically. The parent `/etc` remains root-owned.
The service account is trusted to rewrite its environment, profiles and lifecycle
configuration, just as it owns the application and these files' contents. This
ownership check is not an operator-authorship guarantee. Systemd units and
privileged service control remain root-owned and outside this trust boundary.

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
daybook_operations_api_storage_path: "{{ daybook_operations_api_home }}"
daybook_operations_api_storage_sample_interval: 300
daybook_operations_api_storage_sample_max_age: 900
daybook_operations_api_nominal_records_per_day: 1152
daybook_operations_api_capacity_warn_utilization: 0.70
daybook_operations_api_capacity_critical_utilization: 0.80
daybook_operations_api_capacity_warn_days: 30
daybook_operations_api_capacity_critical_days: 14
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

Monitoring makes that horizon visible before it is reached, but it does not change
it. Raising `daybook_operations_api_record_limit` remains a deliberate operator
decision that must follow measured sizing, backup and restore evidence at the
intended budget; the role never raises it automatically.
