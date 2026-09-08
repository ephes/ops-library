# Guarded Traefik transactions

The `transaction` task entry updates an existing Linux installation without
adopting its configuration. It requires Python 3.11+, an exact release checksum,
a reviewed live baseline, and paired controller/host recovery records. The normal
full deploy, restore and remove entries refuse transaction-managed hosts until
those workflows have been integrated with the same transaction engine.

Operations are separate: `inspect` reads state; `enroll` establishes initial clear
state without changing Traefik; `binary` replaces only the executable; `alias`
changes only the approved per-entrypoint header-alias keys; `resume` reconciles an
active recovery record after reviewed recovery. Enrollment never clears recovery.
The controller must persist a pending record before starting a mutation, retain it
on transport failure, and persist the exact returned host record only on success.

Every mutation requires fresh operator evidence of separate recovery access and
independent observation, baseline and acceptance probe commands, complete backups,
and isolated candidate compatibility evidence tied to the binary and static,
dynamic and unit hashes. Probe programs are trusted administrator-supplied code;
their exact SHA256 is approved in the request. They must check real ingress,
authentication, TLS, streaming/uploads and observer health, not merely a listening
socket. No placeholder probe or recovery claim is supplied by the collection.

Binary and alias operations share one exclusive host lock. The engine verifies
both installed and running executable identities, checks exact startup arguments,
backs up the complete configured rollback set, replaces one file atomically,
restarts, and verifies runtime identity and acceptance probes. On failure it
restores the changed file, verifies recovery, and leaves an active interlock.
ACME backups are retained but never restored over live certificate state. A binary
rollback after aliases are enabled requires an explicitly validated compatible
binary/configuration pair. Interrupted operations remain pending and require
reviewed reconciliation; they are never silently considered successful.

Required variables and the request schema are documented in the private operator
runbook. The public engine rejects absent fields rather than inventing operational
approval. `transaction_request` is a JSON object; `transaction_controller_state`
is managed by the controller. No target selection defaults to a fleet deployment.

## Variables and request schema

| Variable | Default | Purpose |
| --- | --- | --- |
| `traefik_transaction_required` | `false` | Refuse legacy full deploy/restore/remove even before enrollment |
| `traefik_transaction_request` | `{}` | Explicit JSON-compatible request for `tasks_from: transaction` |
| `traefik_transaction_result_path` | empty | Absolute private result file on the controller |
| `traefik_alias_policy` | `{}` | Entrypoint → `delete` map retained by future full configuration rendering |

Requests have `action`, `policy`, and `controller_state` fields. Policy contains
`host` (canonical operator inventory name), `binary_path`, `config_path`,
`dynamic_path`, `backup_paths`, `acme_paths`, and `alias_policy`. This first entry
supports `/usr/bin/traefik` or `/usr/local/bin/traefik`,
`/etc/traefik/traefik.toml`, `/etc/traefik/dynamic`, the directory file provider,
and exactly `--configFile=...` startup arguments without `TRAEFIK_` overrides.
Unknown startup models fail closed. Additional external certificate or unit
paths must be explicitly included in the backup set. Existing `/etc/letsencrypt`
and unit drop-ins are mandatory backup members when present.

The `inspect` result supplies a content identity (machine ID, binary hash/version,
static configuration hash, dynamic tree hash and effective unit-text hash) and the
host state. Every other action needs `evidence` with that exact `baseline`,
`verified_at` (Unix seconds, at most one hour old), `owner`, `review_reference`,
`console_recovery`, `independent_observer`, `observer_delivery_test`, and
`observer_watch_active: true`. These are operator attestations backed by referenced
evidence, not automated proof that a console or observer works.

`binary` and `alias` additionally require:

- `baseline_probe`, `acceptance_probe`, `cleanup_probe`: objects with `argv` and
  `sha256` for trusted root-owned executable programs. No shell string is accepted.
  Cleanup is invoked after acceptance even on failure, before identity readback,
  and before rollback. A cleanup failure leaves recovery degraded.
- `compatibility`: `baseline`, `architecture` from the target's `uname -m`,
  `candidate_binary_sha256`, `candidate_config_sha256`, `passed: true`, `baseline_pair_passed: true`, and
  `report_reference`. Obtain these from isolated startup of the exact native
  release/configuration pair; ARM compatibility tests do not authorize x86 updates.
- `binary`: `release.version`, `release.arch` and `release.sha256`. The Ansible
  transport fetches that exact upstream archive and supplies `archive_path` to the
  engine. Downgrades are refused. Extraction accepts only the named regular binary.
- `alias`: `approved_binary_sha256` and `candidate_config_base64`. Both installed
  and running hashes must match; versions before 3.7.12 are refused. Parsed TOML
  must differ only by `http.aliasHeadersStrategy=delete` on every entrypoint.
  Legacy underscore settings and UDP entrypoints require separate reconciliation.

Probe programs must be reviewed with their host-specific route/expiry manifests.
The engine does **not** supply or authorize temporary echo routes, observation
infrastructure or expiry jobs. The acceptance program owns their safe creation,
independent expiry and unconditional removal; the cleanup program independently
verifies the exact manifest is absent and the permanent routing baseline restored.
Do not run the writer before those implementations and evidence are ready.

`resume` requires fresh evidence, a successful `baseline_probe`, and an explicit
`recovery_review_reference`. The controller also requires `host_state_digest` and
`controller_record_digest` from inspection. This is a reviewed administrative
reconciliation, including unchanged-content restarts or expected permanent-route
changes; it is not a retry flag. Keep the original intended secure release visible
when recovery temporarily leaves an older version running.

## Controller example

The generic `files/traefik_control.py` reads a private YAML registry with `schema: 1`,
`hosts.<name>.desired_release` and `releases.<version>.linux_amd64.sha256`.
Each release needs `approval_reference`. It invokes the operator playbook
`playbooks/traefik/transaction.yml` using a private temporary vars file and keeps
owner-only controller records in `~/.local/state/ops-control/traefik`.

```sh
python traefik_control.py --root /path/to/control --registry /path/to/releases.yml inspect canary
python traefik_control.py --root /path/to/control --registry /path/to/releases.yml binary canary /private/window.json
```

Use the same persistent controller journal for every invocation. Losing or
switching it does not establish clear state: inspect and perform reviewed resume.
The request/journal may contain sensitive probe arguments and operational evidence;
keep it outside Git. Never restore ACME archives as part of binary recovery.
Interrupted pending records require console-assisted investigation and reviewed
reconciliation; there is no automatic retry or unattended-upgrade timer.

## Initial prerequisite repairs

The separate `prepare` task entry accepts `traefik_preparation_request` (default
`{}`) only before enrollment. It uses the same host lock and refuses any existing
transaction state directory or unresolved preparation journal. It never restarts
Traefik. Successful and interrupted attempts retain private evidence under
`/var/lib/traefik-preparation/<id>`; a pending attempt requires manual inspection,
not an automatic retry or deletion of its record.

Every request contains `action`, exact `machine_id`, and `review_reference`.
`ownership` also requires `binary_path`, `binary_sha256` independently verified
against the official executable, and `previous_owner: [uid, gid]`. It checks the
regular 0755 file and running executable, records prior metadata, changes ownership
through the verified open file descriptor, and verifies unchanged bytes/PID.

`retire` requires `service`, the linked `unit_target` at
`/home/<service>/site/<service>.service`, `route_sha256`, and `candidate_base64`.
The candidate is JSON (valid YAML) containing only `http.middlewares`; the Ansible task parses the hash-verified original YAML and requires exact
preservation of its middleware map before transport. The engine also checks the
candidate against this transport-derived map. The service must already be inactive. The task archives its
route and unit source, disables and masks the unit, and atomically replaces its
route file with the retained middleware. Application files, users, databases,
media, and DNS records are preserved. This is retirement, not data destruction.

To recover an interrupted retirement, inspect `before.json` and the saved files.
Restore the recorded route bytes/mode if needed, remove only the created unit mask,
and recreate the recorded unit symlink followed by `systemctl daemon-reload`.
Do not start a service that was inactive before retirement. For ownership repair,
recheck the saved hash and runtime before any further action; reverting to an
unprivileged owner is not an automatic recovery action. Mark a pending journal
reconciled only after reviewing the actual host state and retaining the record.
These initial repairs do not replace the recovery/observer requirements of a
binary or alias transaction.
