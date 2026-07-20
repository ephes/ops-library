# logyard_vector_deploy

Deploys Vector on a producer host and ships journald logs to Logyard/Loki.

## Features

- installs Vector from the official apt repository
- reads from journald first
- normalizes logs into a compact JSON payload
- keeps Loki labels low-cardinality and stable
- uses disk buffering and explicit retry settings
- disables Vector's Loki sink startup health check by default so transient Logyard/Loki
  errors do not prevent the producer from booting; runtime delivery still uses retries
  and disk buffering
- writes a shared Vector config directory under `/etc/vector/config.d/`
- stores the Logyard pipeline in its own fragment so it can coexist with other Vector-managed services on the same host
- validates the full staged config directory before replacing the live fragment

## Required Variables

```yaml
logyard_vector_enabled: true
logyard_vector_ingest_endpoint: "https://logyard.home.xn--wersdrfer-47a.de"
```

## Default Label Set

The sink labels are:

- `host`
- `service`
- `source_type`
- `environment`
- `level`

`unit`, `pid`, and `syslog_identifier` stay in the JSON log payload instead of the Loki index.

`host`, `source_type`, and `environment` are rendered into the config as static
literals, since they are constant per host. Only `service` and `level` vary per
event and are emitted as Vector templates.

### Template confinement (Vector >= 0.57)

Vector 0.57 introduced template confinement: a sink value containing `{{ field }}`
must have a literal static prefix, otherwise the sink is rejected at startup and
the unit fails with `exit 78/CONFIG`. Loki label values cannot take a static prefix
without changing the label values themselves, which would break existing selectors
and dashboards. The role therefore sets
`dangerously_allow_unconfined_template_resolution: true` on the Loki sink:

```yaml
logyard_vector_allow_unconfined_label_templates: true  # default
```

| Value | Loki labels | Confinement opt-out |
| --- | --- | --- |
| `true` (default) | static labels plus per-event `service` and `level` | set on Vector >= 0.57 |
| `false` | static labels only | not needed; valid on any Vector version |

With `false`, `service` and `level` are dropped from the Loki **index** but remain
in the JSON log payload, so they are still searchable at query time — you only lose
the ability to select on them as labels.

The role reads `vector --version` after installing the package and emits the opt-out
only when the detected version is >= 0.57, where the option exists. Older Vector
versions do not enforce confinement and do not understand the option, so nothing is
emitted for them.

If the version cannot be determined, the role falls back to
`logyard_vector_supports_template_confinement` (default `true`). In a real run this
cannot happen, because the probe runs after the package is installed; it applies to
check-mode runs against a host that has no Vector installed yet. Set that variable
to `false` if you deploy to hosts pinned below Vector 0.57.

Vector logs a SECURITY warning when the opt-out is enabled. The exposure is limited
to the `service` and `level` labels: `level` is a fixed enum produced by the remap,
and `service` derives from the journald unit or `SYSLOG_IDENTIFIER`. These are Loki
label values rather than filesystem paths, so the path-traversal case the guard
targets does not apply; the residual risk is label cardinality growth if a local
process spoofs `SYSLOG_IDENTIFIER`.

## Common Variables

```yaml
logyard_vector_host_id: "macmini"
logyard_vector_environment: "prod"
logyard_vector_source_type: "journald"
logyard_vector_include_units: []
logyard_vector_exclude_units: []
logyard_vector_current_boot_only: false
logyard_vector_healthcheck_enabled: false
```

## Example Playbook

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.logyard_vector_deploy
      vars:
        logyard_vector_enabled: true
        logyard_vector_ingest_endpoint: "https://logyard.home.xn--wersdrfer-47a.de"
        logyard_vector_host_id: "macmini"
        logyard_vector_environment: "prod"
```

## Validation

```bash
systemctl status vector
journalctl -u vector -n 100 --no-pager
vector validate --config-dir /etc/vector/config.d
ls /etc/vector/config.d
```

Use `vector validate --skip-healthchecks --config-dir /etc/vector/config.d` when
checking producer config syntax/topology without requiring the remote Logyard/Loki
endpoint to be healthy at that moment. This is the same check the role runs against
the staged config directory before replacing the live fragment, and it does
evaluate template confinement.

Do **not** use `vector validate --no-environment` to gate a deploy: it skips the
template confinement check entirely and will report a config as valid that
`systemd` then refuses to start (the unit's `ExecStartPre` runs a plain
`vector validate`).
