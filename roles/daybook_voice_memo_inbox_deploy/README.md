# daybook_voice_memo_inbox_deploy

Installs Daybook's Apple Voice Memos importer as two quiesce-first macOS Aqua
LaunchAgents. The importer reads Voice Memos and its copied SQLite projection,
transcribes only stable post-baseline recordings through Voxhelm, and creates
one immutable Markdown object per memo revision in an Obsidian S3 bucket.

The short lane (`de.wersdoerfer.daybook.voice-memo-inbox`, every 300 seconds)
transcribes memos up to 180 seconds inline. The long lane
(`de.wersdoerfer.daybook.voice-memo-inbox-long`, every 600 seconds) transcribes
one queued long memo per firing outside the scan budget. Both labels are
installed disabled-first; the long lane does work only when
`daybook_voice_memo_inbox_long_lane_enabled` is true.

The role is public and contains no credentials. Its defaults are disabled and
all environment-specific or secret values use rejected `CHANGEME` placeholders.

## Safety model

- General deployment disables and boots out both exact labels before replacing
  managed code or configuration and leaves them disabled by default. Each
  unloaded proof tolerates launchd's short termination window (up to one
  minute of retries) without weakening the assertion.
- Quiescing never waits for a running long transcription. Booting out the long
  label terminates the process, Voxhelm ends `whisper-cli` when the client
  disconnects, and the next `transcribe-long` window A returns the interrupted
  entry to the queue. Before quiescing, when the protected interpreter and
  policy already exist, the role reads `status --summary-only` as the service
  user and logs only the aggregate `long_in_flight_count`, so an operator can
  see that an item was interrupted. The command output itself is suppressed and
  the count is extracted best-effort with a regular expression rather than a
  JSON parser, so a malformed, truncated, or non-JSON status document reports
  nothing instead of stopping the quiesce. Only a validated non-negative
  integer is ever printed. That read is skipped on a fresh host and never fails
  a deployment.
- Enabling requires the exact value of
  `daybook_voice_memo_inbox_activation_phrase`. On first activation Daybook
  baselines every current database identity as historical before the root-owned
  activation marker is created. `RunAtLoad` is bootstrapped only afterwards. A
  separate root-owned proof marker is written only after a fresh scan advances
  the ledger generation without changing the historical baseline. A genuinely
  new post-baseline memo may be imported during that window; historical source
  identities remain fenced. The proof marker stays bound to the short lane.
- Activation enables and bootstraps the long label after the short one and then
  proves the long lane live with a single
  `transcribe-long --summary-only --no-work` run through the same
  `launchctl asuser` path as the status calls. That run only migrates the
  ledger schema, returns interrupted items, and sweeps vanished entries; it
  never selects or transcribes an item, and it proves the lane even while the
  lane is disabled. Only exit 0 with category `proof_only` or exit 75 with
  `lock_contended` or `ledger_busy` is accepted, each as valid JSON, and
  `launchctl print` must then show the long label loaded. A failed migration
  therefore fails activation, which is the intended fail-closed outcome.
- Every label-scoped `launchctl print` proof (both quiesce checks, the long-lane
  loaded check, and both rescue probes) hides the raw command output, because a
  loaded job prints its `HOME`, private log paths, and full environment. The
  role asserts and reports only the sanitized exit status together with the
  label, so a verbose deployment run never leaks the job's environment. The
  same rule covers the whole-domain Aqua session probe and every task that
  runs the Daybook CLI under `launchctl asuser` (the pre-bootstrap status, the
  long-lane liveness proof, and the first-scan wait): their argv carries the
  service home and user and their stderr can carry a traceback, so the raw
  result and the parsed report are hidden and only the exit status and the
  category are asserted. A test enforces `no_log` on all of them.
- The source directory and live `CloudRecordings.db` are never modified.
- The 300-second job processes only regular supported files whose size/mtime
  signature was unchanged across at least 120 seconds and two runs. It probes
  and fully decodes an owner-only temporary copy with fixed `ffprobe`/`ffmpeg`
  paths before transcription. Media validation failures are retried three times
  before the exact unchanged revision is rejected; later memos keep moving.
- Credentials are written only to a service-user-owned mode-0600 JSON file.
  They never appear in the plist, command arguments, policy, or logs.
- The per-user LaunchAgent plist is installed only in the configured Voice
  Memos owner's `~/Library/LaunchAgents`; other console users never load it.
- The scheduled executable is a root-owned, mode-0755 regular interpreter
  inside the protected checkout, not a symlink to a user- or cache-managed
  runtime. It is copied from the pinned Homebrew interpreter, staged
  root-owned before it becomes live, re-copied when its checksum no longer
  matches that source, and every deployment asserts the checksum equality.
  It runs with Python isolated mode (`-I`) from a pinned root-owned working
  directory, so GUI-domain `PYTHON*` variables and cwd injection cannot add
  executable code. Grant Full Disk Access only to that exact executable.
  When the interpreter is re-copied because the pinned Homebrew source
  changed (for example after a `python3.14` upgrade), its code identity
  changes and macOS silently invalidates the existing grant even though the
  System Settings entry remains: remove and re-grant Full Disk Access for
  `<checkout>/.venv/bin/python` before the next activation, otherwise every
  scan reports `source_unavailable`.
- The Homebrew prefix owner is inside the trust boundary: the role copies
  whatever the pinned `/opt/homebrew/bin/python3.14` resolves to and can
  detect drift from that source but not substitution of it. On a single-user
  Studio the Homebrew owner and the service user are the same principal.
- Every deployment proves the protected checkout is clean (`git status
  --porcelain` empty, `.venv` and caches are ignored) before the runtime is
  synchronized. A modified or foreign file inside the checkout fails the
  deployment; the role never silently keeps or resets such edits.
- Any activation failure is rescued by disabling and booting out both exact
  labels, and the rescue then re-reads `launchctl print-disabled` and probes
  both labels to prove the disabled/unloaded state. If that proof fails the play
  ends with a distinct, louder error instead of claiming a safe state. The
  rescue only touches launchd: it never re-clones, re-syncs, or otherwise
  changes the deployed Daybook revision.
- State and logs are owner-only. Deployment and rollback never delete the
  ledger, source recordings, or existing Obsidian objects.
- An existing protected checkout is replaced only after the newly installed
  bundle passes `git bundle verify` and lists the pinned commit among its
  heads, and only when the checkout's revision is readable and differs from
  the pinned commit; bundle bytes alone never trigger a replacement. Those
  checks are header-level: a bundle whose pack objects are corrupt is only
  rejected by the subsequent clone, which runs after the old checkout was
  removed, so a failed upgrade clone leaves no runtime until the next
  successful deployment (the ledger, markers, and credentials are unaffected;
  re-grant Full Disk Access after the interpreter is recreated). If
  `/usr/bin/git` cannot read the revision, the role fails closed rather than
  deleting the checkout together with the interpreter that holds the Full Disk
  Access grant. `/usr/bin/git` is validated with the other executables.
- After the first successful scan, loss of the separate root-owned activation
  marker is a hard error; the importer will not reinterpret the ledger as a new
  first activation. The role also refuses a surviving proof marker without the
  corresponding activation marker instead of re-baselining.

The protected Python interpreter needs Full Disk Access in System Settings for
the Voice Memos group container. The role cannot grant or modify TCC access.
Every deployment first disables and proves the label unloaded before replacing
that interpreter, so the FDA identity cannot change beneath a running process.
Deployments require the configured service user's Aqua login domain to be
active; logging out safely pauses ingestion, but deployment must wait for the
next login. The venv is built from the pinned Homebrew framework interpreter at
`/opt/homebrew/bin/python3.14`, whose copied executable keeps an absolute
framework linkage; uv-managed standalone interpreters are not supported.

`daybook_voice_memo_inbox_enabled: false` makes the role skip every task; it
does not disable, unload, or remove an existing installation. The only
deactivation paths are the private emergency disable playbook or a
disabled-first apply with `daybook_voice_memo_inbox_launchd_enabled: false`.

## Required variables

| Variable | Purpose |
| --- | --- |
| `daybook_voice_memo_inbox_service_user` | Logged-in Studio user that owns Voice Memos and runtime state. |
| `daybook_voice_memo_inbox_repo_bundle_src` | Controller-local Git bundle containing the exact reviewed Daybook commit. |
| `daybook_voice_memo_inbox_repo_ref` | Exact 40-character commit installed from the bundle. |
| `daybook_voice_memo_inbox_bucket` | Canonical Obsidian bucket. |
| `daybook_voice_memo_inbox_s3_endpoint_url` | Private MinIO endpoint. |
| `daybook_voice_memo_inbox_s3_access_key_id` | Dedicated prefix-scoped MinIO access key. |
| `daybook_voice_memo_inbox_s3_secret_access_key` | Dedicated MinIO secret key. |
| `daybook_voice_memo_inbox_voxhelm_token` | Dedicated Voxhelm bearer token. |

All secret variables must come from a private SOPS-backed control repository and
must be protected with `no_log` at the caller boundary. Required values are
rejected when they are `CHANGEME` or empty, and the endpoint must be an
`http(s)://` URL, so a mis-spelled lookup cannot render empty credentials.

## Production pins and defaults

Paths, label, interval, inbox prefix, loopback Voxhelm endpoint, Homebrew tool
locations, and the 1-second duration tolerance in this table are deliberate
immutable production pins. The role currently supports Apple Silicon Homebrew
under `/opt/homebrew`; an Intel `/usr/local` layout requires a separately
reviewed role change, not a variable override. Size, duration, request timeout,
model, and language/prompt values remain bounded operational configuration.

| Variable | Default |
| --- | --- |
| `daybook_voice_memo_inbox_enabled` | `false` |
| `daybook_voice_memo_inbox_launchd_enabled` | `false` |
| `daybook_voice_memo_inbox_launchd_label` | `de.wersdoerfer.daybook.voice-memo-inbox` |
| `daybook_voice_memo_inbox_long_launchd_label` | `de.wersdoerfer.daybook.voice-memo-inbox-long` |
| `daybook_voice_memo_inbox_interval_seconds` | `300` |
| `daybook_voice_memo_inbox_long_interval_seconds` | `600` (pinned; at least twice the scan interval) |
| activation status window | `72 × 5 seconds` (pinned; six minutes) |
| `daybook_voice_memo_inbox_min_stable_seconds` | `120` |
| `daybook_voice_memo_inbox_max_audio_bytes` | `16777216` |
| `daybook_voice_memo_inbox_max_duration_seconds` | `180` |
| `daybook_voice_memo_inbox_duration_tolerance_seconds` | `1.0` |
| `daybook_voice_memo_inbox_request_timeout_seconds` | `100` (must be `> 0` and `< 300`) |
| `daybook_voice_memo_inbox_ffprobe_path` | `/opt/homebrew/bin/ffprobe` |
| `daybook_voice_memo_inbox_ffmpeg_path` | `/opt/homebrew/bin/ffmpeg` |
| `daybook_voice_memo_inbox_python_source` | `/opt/homebrew/bin/python3.14` |
| `daybook_voice_memo_inbox_voxhelm_endpoint` | `http://127.0.0.1:8787/v1/audio/transcriptions` |
| `daybook_voice_memo_inbox_model` | `gpt-4o-mini-transcribe` |
| `daybook_voice_memo_inbox_prefix` | `Inbox/Voice Memos` |

The 1-second duration tolerance covers expected AAC priming/padding and Apple's
duration rounding. Changing it changes admission behavior and requires a
reviewed rollout. The short lane deliberately caps a memo at 180 seconds and
16 MiB; longer memos belong to the long lane below.
`status --summary-only` reports only aggregate rejection counts and
never source identifiers. Scheduled ingest distinguishes the permanent
`rejected_count` from per-run `rejection_events`.

The service user owns the parent `~/Library/LaunchAgents` directory and could
replace either plist. The enforced boundary prevents ambient Python path
injection and cross-user loading; it does not defend against a malicious
service user who already owns the credentials, source recordings, state, and
launchd domain.

## Long-memo lane

The second LaunchAgent runs `voice-memos transcribe-long --summary-only` every
600 seconds with `RunAtLoad` false. Its `ProgramArguments`, working directory,
and environment are identical to the short lane's; only the subcommand, the
interval, `RunAtLoad`, and the log pair differ. It writes its own owner-only
mode-0600 logs `ingest-long.log` and `ingest-long.err.log` in the existing log
directory, so long-lane output never interleaves with the scan log.

Each firing transcribes at most one queued long memo under its own run lock,
with an item deadline derived from the probed duration. The short lane keeps
its 300-second budget and never blocks behind a long transcription.

| Variable | Default | Accepted range (validated unconditionally) |
| --- | --- | --- |
| `daybook_voice_memo_inbox_long_lane_enabled` | `false` | real YAML boolean |
| `daybook_voice_memo_inbox_long_max_duration_seconds` | `2400` | `180 < x <= 3600` |
| `daybook_voice_memo_inbox_long_max_audio_bytes` | `25165824` (24 MiB) | `16 MiB <= x < 25 MiB` |
| `daybook_voice_memo_inbox_long_realtime_factor` | `0.08` | `0.02 <= x <= 4.0` |
| `daybook_voice_memo_inbox_long_queue_slack_seconds` | `600` | `120–900` |
| `daybook_voice_memo_inbox_long_validation_timeout_seconds` | `60` | `30–120` |
| `daybook_voice_memo_inbox_long_max_attempts` | `5` | `1–10` |
| `daybook_voice_memo_inbox_long_queue_per_run` | `2` | `1–5` |
| `daybook_voice_memo_inbox_long_min_gap_seconds` | `480` | `430 < x <= 900` |

All of them are rendered into the root-owned policy together with the pinned
`long_interval_seconds`. The ranges are asserted on every run of the role,
whether or not `daybook_voice_memo_inbox_long_lane_enabled` is true, because
the values reach the host policy either way; the label, plist path, interval,
and log paths are pinned unconditionally as well.

Deployment also asserts the deadline inequality
`ceil(long_max_duration_seconds x long_realtime_factor) + long_queue_slack_seconds <= 2700`,
so a memo inside the configured ceiling can never be queued with a deadline the
lane refuses to grant. Raising the ceiling therefore requires lowering the
realtime factor or the slack, and the factor must come from the Studio
benchmark (1.5 x the measured value), not from a guess. The 24 MiB size ceiling
stays below Voxhelm's 25 MiB synchronous upload limit.

**Disabled-first rollout.** The role always installs, disables, quiesces, and
(on activation) bootstraps the long label, but ships
`daybook_voice_memo_inbox_long_lane_enabled: false`. A disabled lane behaves
exactly as before this change: the scan keeps the 16 MiB discovery filter and
the 180-second ceiling, and each `transcribe-long` firing only returns
interrupted items and exits `long_lane_disabled`. Queue entries written before
the flag was cleared are kept and counted, and re-enabling resumes them.
ops-control enables the lane after the Studio benchmark.

**Voxhelm dependency (D-24).** Both lanes are non-interactive Voxhelm consumers
and share the single non-interactive inference slot. Enabling the long lane is
only safe while the Voxhelm deployment pins
`VOXHELM_LANE_SCHEDULER_INTERACTIVE_SLOTS=1` and
`VOXHELM_LANE_SCHEDULER_NON_INTERACTIVE_SLOTS=1`, which reserves an interactive
slot for the voice assistant. Those slot variables are set by
`voxhelm_deploy` and pinned in ops-control, which asserts the wiring next to
the importer flag so the two cannot drift apart. This role cannot verify the
Voxhelm configuration itself.

## Example disabled-first deployment

```yaml
- hosts: studio
  become: true
  roles:
    - role: local.ops_library.daybook_voice_memo_inbox_deploy
      vars:
        daybook_voice_memo_inbox_enabled: true
        daybook_voice_memo_inbox_service_user: example
        daybook_voice_memo_inbox_repo_bundle_src: /private/tmp/daybook.bundle
        daybook_voice_memo_inbox_repo_ref: 0123456789abcdef0123456789abcdef01234567
        daybook_voice_memo_inbox_bucket: obsidian
        daybook_voice_memo_inbox_s3_endpoint_url: https://minio.example.invalid
        daybook_voice_memo_inbox_s3_access_key_id: "{{ vault_access_key }}"
        daybook_voice_memo_inbox_s3_secret_access_key: "{{ vault_secret_key }}"
        daybook_voice_memo_inbox_voxhelm_token: "{{ vault_voxhelm_token }}"
        daybook_voice_memo_inbox_launchd_enabled: false
```

For the separate activation play set `daybook_voice_memo_inbox_launchd_enabled:
true` and set `daybook_voice_memo_inbox_activation_confirmation` to the exact
phrase `BASELINE ALL CURRENT VOICE MEMOS AS HISTORICAL`. Never make activation a
generic deploy flag.

A fresh-host `--check` validates inputs, target tools, and planned directories,
but skips artifact copies, rendered files, and interpreter materialization whose
parent directories do not yet exist. Those guards are keyed by the managed
parent path, not by loop position. Run the normal disabled-first apply before
using check mode to preview later convergences.

## Operations and rollback

Run status as the service user with the protected interpreter and policy:

```text
cd '/Library/Application Support/Daybook/voice-memo-inbox/daybook'
DAYBOOK_VOICE_MEMOS_POLICY='/Library/Application Support/Daybook/voice-memo-inbox/policy.json' \
  '/Library/Application Support/Daybook/voice-memo-inbox/daybook/.venv/bin/python' \
  -I -c 'from daybook.cli import main; raise SystemExit(main())' \
  voice-memos status --summary-only
```

If `activation.json` exists but `activation-proven.json` does not after a
fail-closed activation, correct the reported prerequisite and rerun the same
activation procedure; the existing historical ledger is reused. If the ledger
or activation marker is missing or mismatched, keep the label disabled and
restore the matched files from protected backup. Never delete one side or run a
fresh baseline as a repair.

The JSON output contains only aggregate state. The scheduled command likewise
prints no memo identifiers, paths, transcript text, credentials, or upstream
response bodies.

A long memo that was in flight when a deployment, rollback, or emergency
disable quiesced the lane is not lost: the entry returns to `pending` on the
next `transcribe-long` window A, with its attempt restored and an incremented
interruption counter. After three interruptions the entry becomes
`needs_operator` instead of cycling forever.

Rollback disables and boots out both exact labels, then redeploys the prior
reviewed commit/configuration. Preserve `ledger.json`, `activation.json`,
`activation-proven.json`, logs, Voice Memos, and all destination objects.
Removing generated notes is not part of rollback.

Downgrading past the ledger migration needs one extra step, because the
previous Daybook release refuses a schema-2 ledger (`invalid_state`) and both
lanes would stop: with both labels proven disabled and unloaded, restore the
newest `ledger.schema1.<generation>.<UTC>.json` backup whose `activation_id`
matches `activation.json` to `ledger.json` (refuse an older or mismatched
backup), then redeploy the previous release. Consequences: long memos
completed after the migration keep their immutable objects but are
re-rejected by the old duration pre-check, so their completions are absent
from the ledger until a compatible release runs again (no duplicate can be
created); short-lane completions made after the backup are recovered through
`HeadObject`; queue entries and attempt history are lost by design. The
ops-control runbook carries the operator procedure. A GUI logout pauses the Aqua LaunchAgent safely; recordings remain
post-watermark and are considered after login, while monitoring must document
that it shares or does not share that session dependency.
