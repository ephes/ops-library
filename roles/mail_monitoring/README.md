# mail_monitoring

Provisioning helpers for nyxmon end-to-end mail flow checks:

- Ensures the local `monitor@...` mailbox exists in PostgreSQL (PostfixAdmin schema by default).
- Creates the mailbox Maildir directory.
- Installs a systemd timer to expunge old messages (mailbox hygiene fallback).
- Optionally installs a Mailgun-API end-to-end probe: a systemd timer that
  POSTs one message through a Mailgun-compatible relay to the monitor mailbox
  (see "Relay probe").

Tracks PRD: `specs/mail-nyxmon-prd.md` (issue `ops-meta-e15`).

## Intended Scope

- Ensure `monitor@` mailbox exists with generated password (from ops-control vault).
- Install cleanup policy to auto-clean monitoring messages (TTL ~1 day).
- Optionally seed Gmail filter instructions (documented, not automated here).

## Variables (defaults)

```yaml
mail_monitoring_enabled: false
mail_monitoring_address: "monitor@xn--wersdrfer-47a.de"
mail_monitoring_password: "CHANGE_ME"   # from ops-control vault (plaintext)
mail_monitoring_active: true
mail_monitoring_schema_mode: "{{ mail_backend_schema_mode | default('legacy') }}"  # postfixadmin|legacy

mail_monitoring_postgres_database: "{{ mail_backend_postgres_database | default('mail') }}"
mail_monitoring_vmail_path: "{{ mail_backend_vmail_path | default('/mnt/cryptdata/vmail') }}"
mail_monitoring_vmail_user: "{{ mail_backend_vmail_user | default('vmail') }}"
mail_monitoring_vmail_group: "{{ mail_backend_vmail_group | default(mail_monitoring_vmail_user) }}"

mail_monitoring_cleanup_enabled: true
mail_monitoring_cleanup_ttl_days: 1
mail_monitoring_cleanup_timer_on_calendar: "daily"
mail_monitoring_cleanup_script_path: "/usr/local/bin/mail-monitoring-cleanup.sh"
mail_monitoring_cleanup_service_name: "mail-monitoring-cleanup"

mail_monitoring_relay_probe_enabled: false
mail_monitoring_relay_probe_url: "CHANGE_ME"      # relay base URL
mail_monitoring_relay_probe_domain: "CHANGE_ME"   # Mailgun path domain
mail_monitoring_relay_probe_from: "CHANGE_ME"     # sender the token may use
mail_monitoring_relay_probe_to: "{{ mail_monitoring_address }}"
mail_monitoring_relay_probe_subject_prefix: "[nyxmon-relay]"
mail_monitoring_relay_probe_token: "CHANGE_ME"    # raw API token (ops-control vault)
mail_monitoring_relay_probe_timeout: 30           # seconds per HTTP attempt
mail_monitoring_relay_probe_retries: 2
mail_monitoring_relay_probe_on_calendar: "*:0/15"
mail_monitoring_relay_probe_randomized_delay_sec: 60
mail_monitoring_relay_probe_user: "mailgun-relay-probe"
mail_monitoring_relay_probe_service_name: "mailgun-relay-probe"
```

## Usage

```yaml
- hosts: mail
  become: true
  vars:
    mail_monitoring_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/nyxmon.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.mail_monitoring
      vars:
        mail_monitoring_enabled: true
        mail_monitoring_password: "{{ mail_monitoring_secrets.nyxmon_local_monitor_password }}"
```

## Relay probe

With `mail_monitoring_relay_probe_enabled: true` the role installs a probe for
a Mailgun-compatible HTTP relay such as `mailgun-relay` (role
`mailgun_relay_deploy`):

| Path | Owner / mode | Content |
| --- | --- | --- |
| `/etc/<service_name>/token` | probe user, `0600` (dir root:probe group, `0750`) | raw API token |
| `/usr/local/bin/<service_name>` | root, `0755` | probe script |
| `/etc/systemd/system/<service_name>.{service,timer}` | root, `0644` | oneshot unit and timer |
| `/var/lib/<service_name>/state` | probe user, `0644` (dir `0755`) | `last_status`, `last_run`, `curl_exit` |

Every run (default every 15 minutes, `Persistent=true`) sends
`POST <url>/v3/<domain>/messages` with Basic-Auth `api:<token>` and the form
fields `from`, `to`, `subject` (`<prefix> <UTC timestamp>-<random hex>`) and
`text`. The unit runs as the unprivileged system user
`mail_monitoring_relay_probe_user`, the only user besides root that can read
the token. The script hands the token to curl on stdin (`--config -`), so it
never appears in a process list or the journal. The
journal line per run shows the endpoint, subject, HTTP status, curl exit code
and the first 300 bytes of the response.

The state file holds HTTP `0` when no response arrived. Export it with
`metrics_endpoint_probe_states` (see the `metrics_endpoint` README) and check
it with nyxmon `json-metrics` (status `200`, age below twice the interval),
plus an `imap` check on the monitor mailbox for `search_subject: <prefix>`.
The cleanup timer above also removes old probe mail.

The token should be a dedicated one whose relay policy allows exactly one path
domain and one sender (`mail_monitoring_relay_probe_domain` and
`mail_monitoring_relay_probe_from`). The probe only ever sends to
`mail_monitoring_relay_probe_to`.

### Manual runs and other targets

The script is usable on its own, for example against a second relay instance
on another port:

```bash
sudo /usr/local/bin/mailgun-relay-probe --url http://127.0.0.1:8086 --retries 0
```

| Option | Effect |
| --- | --- |
| `--url BASE_URL` | other relay base URL (`/v3/<domain>/messages` is appended) |
| `--state-file PATH` | record the result; only the timer passes it, so manual runs leave the production metric alone |
| `--retries N` | curl retries on connection refused, timeout, 408/429/5xx; `0` shows the first answer |
| `--subject-suffix TEXT` | appended to the subject |
| `--token-file PATH` | another token file (default `/etc/<service_name>/token`) |
| `-- ARGS...` | passed to curl unchanged, e.g. `--form-string 'html=<p>…</p>' -F attachment=@file` |

Exit code `0` means HTTP 200; `1` any other status or no response; `2` a
usage, URL or token error.

Setting `mail_monitoring_relay_probe_enabled: false` again stops and disables
the timer and removes the units, script, token and state.

## Next Steps

- Add optional support for creating the `domain` row if missing (currently fails fast).
- Add optional domain-wide monitor aliases (if useful).

## Notes

- PostfixAdmin schema expects the `domain` row to exist before creating the mailbox.
- Cleanup uses `doveadm expunge` via systemd timer (no Sieve dependency). If the mailbox doesn't exist yet, the cleanup script treats exit code 68 as success.
