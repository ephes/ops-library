# Guarded Traefik transactions

The `transaction` task entry updates an existing Linux installation without
adopting its configuration. It requires Python 3.11+, an exact release checksum,
a reviewed live baseline, and paired controller/host recovery records. The normal
full deploy, restore and remove entries refuse transaction-managed hosts until
those workflows have been integrated with the same transaction engine.

Operations are separate: `inspect` reads state; `enroll` establishes initial clear
state without changing Traefik; `binary` replaces only the executable; `alias`
changes only the approved per-entrypoint header-alias keys; `metrics_bind` adds the
single loopback-only metrics entrypoint described below; `resume` reconciles an
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
`recovery_access`, `independent_observer`, `observer_delivery_test`, and
`observer_watch_active: true`. These are operator attestations backed by referenced
evidence, not automated proof that access works. For a proxy-only update that
preserves SSH, network and unit configuration, a freshly verified SSH connection
and the retained rollback files can be the recovery path. A provider console is
not a mandatory prerequisite for that scope. The legacy `console_recovery` field
is accepted for existing callers; new callers should use `recovery_access`.

`binary`, `alias`, and `metrics_bind` additionally require:

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
- `metrics_bind`: the same approved executable and candidate fields as `alias`.
  The parsed current configuration must already enable Prometheus without an
  explicit entrypoint and must already carry `aliasHeadersStrategy = "delete"`
  on every existing entrypoint. The only accepted semantic delta adds
  `entryPoints.traefik` at `127.0.0.1:8080` with the delete alias policy and sets
  `metrics.prometheus.entryPoint = "traefik"`. Existing entrypoints and every
  unrelated static field must remain semantically identical. This operation
  cannot write an arbitrary static configuration.

  Before this transaction, update the health probe configuration's
  `entrypoints` to the complete post-change set, including `traefik`, and
  reinstall the probe baseline. The `metrics_bind_acceptance_probe` runs after
  the candidate is live and rejects a pre-change entrypoint set. If a later
  `alias` transaction is required, capture and install that transaction's own
  complete expected entrypoint set first; do not reuse an earlier probe
  configuration whose set no longer matches the live static configuration.

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

## Read-only ingress acceptance

`files/traefik_health_probe.py` supports `capture`, `health`, `alias`,
`metrics_bind` and `cleanup`
with a private JSON configuration. Configure `probes` with host, scheme, port,
address and optional path, and `entrypoints` with the complete expected set.
Capture returns per-probe curl exit/status and hashes of permanent dynamic files;
merge this into the private configuration before the update. Health requires the
same observed results (or recovery from a 5xx backend failure to 2xx) and unchanged permanent routing. TLS verification remains
on; existing failing routes are recorded as baseline failures, not called healthy.
Alias mode additionally verifies `delete` on every configured entrypoint. Cleanup
verifies permanent routing; this probe creates no temporary route, backend or unit.
This provides representative ingress regression checks, not application-specific
upload/websocket tests or live backend header capture. Keep those distinctions in
the operator's verification report.

The health probe requires `/usr/bin/python3` version 3.11 or newer. The role
checks that exact interpreter before installation, and both verification and
transaction invocation use it.

Install via `tasks_from: health_probe` with `traefik_health_probe_config` (default
`{}`) containing the complete captured configuration. The role installs the script
and baseline root-owned under `/var/lib/traefik-update-probes`, validates live
health, and returns `traefik_health_probe_commands` with exact SHA256/argv objects
for `baseline_probe`, `acceptance_probe`, `alias_acceptance_probe`,
`metrics_bind_acceptance_probe` and `cleanup_probe`. Select the action-specific
command as acceptance for an alias or metrics-binding transaction.
Capturing a new baseline is a separate explicit pre-deployment action; do not
recapture after an acceptance failure. The probe refuses an empty list, preserves
exact authentication/redirect expectations, and records bounded curl timeouts.
An explicitly invalid `recovery_access` value is refused even if a legacy console
field is also present; fallback applies only when the new field is absent.

## ACME storage adoption (`acme_storage`)

This phase-1 action moves the populated `/acme.json` to
`/etc/traefik/acme/acme.json` without changing the binary, unit or routing.
Policy must name those exact `acme_source` and `acme_target` paths. The source
must be a root-owned regular 0600 file with a nonempty `letsencrypt` certificate
list. The destination must be absent or a root-owned empty regular file; parent
directories must be real root-owned directories without group/world write access.
The engine saves the previous empty target as `acme-target.orig`, copies the
source bytes atomically at 0600, and sets the ACME directory to 0700.

Supply the same evidence, probes, approved binary hash and isolated compatibility
proof as an alias transaction, plus `candidate_config_base64`. No TOML serializer
is used: the supplied bytes are installed intact, preserving comments and order.
Prepare the candidate by replacing the misplaced `[acme]` header with
`[certificatesResolvers.letsencrypt.acme]` and removing `[letsencrypt]` only if
empty. Parsed validation permits only moving the old top-level email and setting
resolver storage to the target. All other fields, including `httpChallenge`,
`keyType` and `caServer`, must stay identical. Existing resolver email/storage or
extra misplaced keys are refused. This is a forward-only narrow repair, not a
reverse migration or general configuration adoption action.

Before writing, the engine records source SHA256, certificate domains/notAfter,
and local port-443 SNI leaf SHA256 fingerprints for every hostname in the store
in the private transaction directory (`acme-baseline.json`). OpenSSL is required
for public leaf expiry parsing. The copy is hash-checked before the single restart.
After acceptance, the source hash must still match, certificate sets (including
multiplicity) must match, and all served leaf fingerprints must match. Account
metadata may change without invalidating the certificate comparison. TLS identity
comparison uses DER fingerprints; ordinary ingress probes retain CA verification.
A failure restores the previous TOML and restarts against the baseline, checking
fingerprints again, leaving recovery/degraded state for explicit review. Cleanup
failure cannot prevent attempting config rollback. Both stores remain on disk;
the source is never written or deleted, and no ACME archive is restored.

For independent `capture`/`health` probe use, set `tls_fingerprints: true` in the
private probe configuration. Capture adds `tls_sha256` to each HTTPS observation;
health requires a captured TLS observation and refuses fingerprint changes,
including when a backend recovers from 5xx. TCP/TLS failures are recorded with a
null fingerprint and error class, preserving known baseline failures and allowing
health's bounded retries. Transaction post-start and recovery fingerprint checks
also retry five times with two-second delays for resolver startup settling.
Capture/install a fresh baseline before migration. Traefik-generated default
certificates change at restart, so they cannot provide a stable migration baseline:
finish the www resolver fix first. Overlapping stored certificates (expected after
the six-name www fix) are allowed; record the chosen served leaf per hostname.
If Traefik selects a different leaf after settling, exact-identity acceptance
intentionally fails and rolls back, even if the alternate leaf is valid.

The controller supports `--check acme_storage HOST REQUEST` as a wholly offline
candidate check. Include `baseline_config_base64` alongside the candidate; it
validates the exact TOML delta against registry policy without invoking Ansible,
creating a journal, or touching a host. It does not validate live ownership,
source contents, probes, recovery records, or compatibility attestations.

Before production use, run the native isolated Traefik 3.7.14 VM scenario with
synthetic keys, the production-shaped misplaced tables and cwd `/`, and an
unreachable CA endpoint: prove unchanged fingerprints, no CA connection/order,
and automatic recovery after a forced acceptance failure. Keep its report and
exact candidate hash as compatibility evidence. Unit tests are not this VM proof.
