# daybook_sessions_deploy

Deploy the Daybook agent-session shipper on macOS as a periodic `launchd`
`LaunchDaemon`. The role validates an existing `uv` binary, keeps a pinned
Daybook checkout on the target, runs `uv sync`, installs the `trufflehog`
Homebrew package, renders a secret environment file, and schedules
`daybook sessions ship`. It can also install the optional Archive quote
classifier launchd job that runs `daybook archive classify-quotes` from the same
checkout and environment.

Run the role with facts enabled. It validates the macOS target, rejects
placeholder credentials, and expects real MinIO credentials to come from a
private control repo such as ops-control SOPS.

## What This Role Manages

- a pinned Daybook source checkout
- an existing `uv` binary at `daybook_sessions_uv_bin`
- the `trufflehog` Homebrew package
- `/etc/daybook-sessions/sessions.env`
- `/etc/daybook-sessions/ship-sessions.sh`
- `/Library/LaunchDaemons/de.wersdoerfer.daybook.sessions.plist`
- optional `/etc/daybook-sessions/archive-quotes.env`
- optional `/etc/daybook-sessions/classify-archive-quotes.sh`
- optional `/Library/LaunchDaemons/de.wersdoerfer.daybook.archive-quotes.plist`
- optional dedicated `~/.daybook/archive-quote-browser` profile directory (never
  a user's live Helium profile)
- launchd stdout/stderr logs under `/var/log/daybook-sessions/`
- the default shipper watermark state path at
  `~/.daybook/sessions-shipped.json`

The role removes the legacy by-hand `~/daybook-ship.sh` runner by default. It
does not delete the watermark state file; keeping it lets the first timed run
skip sessions that were already shipped manually.

## Important Defaults

```yaml
daybook_sessions_repo_url: "https://github.com/ephes/daybook.git"
daybook_sessions_repo_ref: "CHANGEME"
daybook_sessions_checkout_path: "{{ daybook_sessions_service_home }}/projects/daybook"
daybook_sessions_repo_update: true
daybook_sessions_path: "s3://agent-sessions"
daybook_sessions_schedule_interval_seconds: 1800
daybook_sessions_launchd_label: "de.wersdoerfer.daybook.sessions"
daybook_sessions_launchd_scope: "system"
daybook_sessions_state_path: "{{ daybook_sessions_service_home }}/.daybook/sessions-shipped.json"
daybook_sessions_brew_packages:
  - "trufflehog"
daybook_sessions_redact_files: []
daybook_archive_quote_classifier_enabled: false
daybook_archive_quote_classifier_state: "s3://agent-sessions/archive-quote-classifier.json"
daybook_archive_quote_classifier_env_file: "{{ daybook_sessions_config_dir }}/archive-quotes.env"
daybook_archive_quote_classifier_cmd: "CHANGEME"
daybook_archive_quote_classifier_probe_enabled: true
daybook_archive_quote_classifier_probe_prompt: "Return exactly OK."
daybook_archive_quote_classifier_probe_timeout_seconds: 120
daybook_archive_quote_classifier_throttle_interval_seconds: 60
daybook_archive_url: "CHANGEME"
daybook_archive_token: "CHANGEME"
daybook_quotes_enabled: false
daybook_quotes_unused_path: "CHANGEME"
daybook_quotes_used_path: "CHANGEME"
daybook_quote_lifecycle_state: "s3://agent-sessions/weeknotes-quote-lifecycle.json"
daybook_archive_browser_executable: "/Applications/Helium.app/Contents/MacOS/Helium"
daybook_archive_browser_user_data_dir: "{{ daybook_sessions_service_home }}/.daybook/archive-quote-browser"
daybook_archive_browser_headless: true
daybook_archive_browser_launch_timeout_seconds: 30
daybook_archive_browser_navigation_timeout_seconds: 30
daybook_archive_browser_render_wait_seconds: 1
```

These values must be supplied by the private control repo:

- `daybook_sessions_service_user`
- `daybook_sessions_repo_ref`
- `daybook_sessions_aws_endpoint_url_s3`
- `daybook_sessions_aws_access_key_id`
- `daybook_sessions_aws_secret_access_key`
- `daybook_archive_url`, `daybook_archive_token`, and
  `daybook_archive_quote_classifier_cmd` when the optional classifier is
  enabled; and `daybook_quotes_unused_path` plus `daybook_quotes_used_path`
  when either quote lifecycle or classification is enabled. The
  `daybook_quote_lifecycle_state` default is the exact production location,
  `s3://agent-sessions/weeknotes-quote-lifecycle.json`; override it together
  with the Markdown paths for local or non-production lifecycles. The role
  probes the classifier command by default during deploy, which verifies both
  the executable and provider/subscription authentication before launchd is
  enabled.

The three quote lifecycle settings must be distinct locations on one backend.
The unused and used locations must be safe absolute local `.md` paths or safe,
exact `s3://bucket/key.md` object URIs; lifecycle state must be a safe absolute
local `.json` path or exact `s3://bucket/key.json` URI. Mixing local and S3
locations is rejected, as is reusing either Markdown location for state. All
three variables are written to `sessions.env` on handoff/delivery machines and
to the classifier environment when classification is enabled.

The role deliberately does not stat local quote files, contact S3, or create
files/object keys. Daybook reads the exact existing Markdown and JSON locations
and fails closed if any are missing or malformed. For an S3 lifecycle, the
configured MinIO credentials therefore need `GetObject` and `PutObject` for all
three objects in addition to the existing session scope; delete remains
unnecessary. The configured browser executable must be a real executable file
accessible to that user. The browser profile must be an absent/empty directory
or an already Daybook-marked directory directly below `~/.daybook/`; the role
validates its real path and rejects symlinks, unsafe marker/lock files, wrong
ownership, and non-empty unmarked profiles. Never configure or copy a normal
Helium/Chromium user-data directory. A fresh empty dedicated profile is
sufficient for public X pages that do not require authentication.

`uv sync --frozen` installs the Python Playwright dependency from `uv.lock` with
`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`. Daybook launches the configured Helium
binary, so this role does not install Playwright's bundled Chromium.

Use a dedicated least-privilege MinIO account scoped to the existing session
objects and production lifecycle state object in `agent-sessions`, plus exactly
the two configured Obsidian quote objects. Do not grant quote-bucket
listing/delete access and do not pass the MinIO admin key to this role.

Set `daybook_sessions_repo_update: false` only when the private control repo has
pre-staged a service-user-owned checkout on the target and
`daybook_sessions_repo_ref` is the full 40-character commit id already present
there. The role verifies the checkout and commit locally, always rejects
untracked files, rejects tracked changes when force is disabled, and uses a
local detached checkout without any remote operation. A missing checkout or
object fails instead of cloning or fetching.

## Launchd Scope

The default `daybook_sessions_launchd_scope: "system"` installs a LaunchDaemon
under `/Library/LaunchDaemons` and runs as `daybook_sessions_service_user`.
Use `daybook_sessions_launchd_scope: "user"` for laptops or hosts where the
control repo deploys as the logged-in service user without passwordless sudo.
Headed browser mode is accepted only in this GUI LaunchAgent scope and the plist
is restricted to an Aqua session; system LaunchDaemons must remain headless. In
user mode, override the managed paths to user-writable locations, for example:

```yaml
daybook_sessions_launchd_scope: "user"
daybook_sessions_config_dir: "/Users/jochen/.config/daybook-sessions"
daybook_sessions_env_file: "/Users/jochen/.config/daybook-sessions/sessions.env"
daybook_sessions_launcher_path: "/Users/jochen/.config/daybook-sessions/ship-sessions.sh"
daybook_sessions_log_dir: "/Users/jochen/Library/Logs/daybook-sessions"
daybook_sessions_stdout_log: "/Users/jochen/Library/Logs/daybook-sessions/ship.log"
daybook_sessions_stderr_log: "/Users/jochen/Library/Logs/daybook-sessions/ship.err.log"
daybook_sessions_launchd_plist_path: "/Users/jochen/Library/LaunchAgents/de.wersdoerfer.daybook.sessions.plist"
daybook_archive_quote_classifier_launcher_path: "/Users/jochen/.config/daybook-sessions/classify-archive-quotes.sh"
daybook_archive_quote_classifier_env_file: "/Users/jochen/.config/daybook-sessions/archive-quotes.env"
daybook_archive_quote_classifier_stdout_log: "/Users/jochen/Library/Logs/daybook-sessions/archive-quotes.log"
daybook_archive_quote_classifier_stderr_log: "/Users/jochen/Library/Logs/daybook-sessions/archive-quotes.err.log"
daybook_archive_quote_classifier_launchd_plist_path: "/Users/jochen/Library/LaunchAgents/de.wersdoerfer.daybook.archive-quotes.plist"
```

## Redaction Notes

`daybook sessions ship` harvests secret values from its process environment,
`~/.aws/credentials`, `~/.envrc`, and any colon-separated
`DAYBOOK_REDACT_FILES`. The launchd job sources the rendered environment file
before running Daybook, so the injected MinIO credentials are present in the
process environment and can be redacted from transcripts before upload. When
quote classification is enabled, the role automatically adds
`archive-quotes.env` to `DAYBOOK_REDACT_FILES`, allowing Daybook's secret-name
harvester to redact the Archive token without logging or exposing its value.

Set `daybook_sessions_redact_files` to host-local files that contain other API
keys worth redacting, for example project `.envrc` files:

```yaml
daybook_sessions_redact_files:
  - "/Users/jochen/projects/daybook/.envrc"
  - "/Users/jochen/projects/ops-control/.envrc"
```

## Example

```yaml
- name: Deploy Daybook session shipper
  hosts: mac_session_feeders
  become: true
  roles:
    - role: local.ops_library.daybook_sessions_deploy
      vars:
        daybook_sessions_service_user: "jochen"
        daybook_sessions_brew_user: "jochen"
        daybook_sessions_repo_ref: "main"
        daybook_sessions_aws_endpoint_url_s3: "{{ daybook_sessions_secrets.aws_endpoint_url_s3 }}"
        daybook_sessions_aws_access_key_id: "{{ daybook_sessions_secrets.aws_access_key_id }}"
        daybook_sessions_aws_secret_access_key: "{{ daybook_sessions_secrets.aws_secret_access_key }}"
```

The classifier job runs as a background, low-I/O launchd process with a throttle
interval and fixed calendar schedule. The profile lock prevents overlapping
manual and scheduled browser runs; headless mode is the safe unattended default.

Verify on the target with:

```sh
launchctl print system/de.wersdoerfer.daybook.sessions
tail -f /var/log/daybook-sessions/ship.log
```
