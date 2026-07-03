# daybook_sessions_deploy

Deploy the Daybook agent-session shipper on macOS as a periodic `launchd`
`LaunchDaemon`. The role validates an existing `uv` binary, keeps a pinned
Daybook checkout on the target, runs `uv sync`, installs the `trufflehog`
Homebrew package, renders a secret environment file, and schedules
`daybook sessions ship`.

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
daybook_sessions_path: "s3://agent-sessions"
daybook_sessions_schedule_interval_seconds: 1800
daybook_sessions_launchd_label: "de.wersdoerfer.daybook.sessions"
daybook_sessions_state_path: "{{ daybook_sessions_service_home }}/.daybook/sessions-shipped.json"
daybook_sessions_brew_packages:
  - "trufflehog"
daybook_sessions_redact_files: []
```

These values must be supplied by the private control repo:

- `daybook_sessions_service_user`
- `daybook_sessions_repo_ref`
- `daybook_sessions_aws_endpoint_url_s3`
- `daybook_sessions_aws_access_key_id`
- `daybook_sessions_aws_secret_access_key`

Use a dedicated least-privilege MinIO account scoped to the
`agent-sessions` bucket. Do not pass the MinIO admin key to this role.

## Redaction Notes

`daybook sessions ship` harvests secret values from its process environment,
`~/.aws/credentials`, `~/.envrc`, and any colon-separated
`DAYBOOK_REDACT_FILES`. The launchd job sources the rendered environment file
before running Daybook, so the injected MinIO credentials are present in the
process environment and can be redacted from transcripts before upload.

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

Verify on the target with:

```sh
launchctl print system/de.wersdoerfer.daybook.sessions
tail -f /var/log/daybook-sessions/ship.log
```
