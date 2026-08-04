# mailgun_relay_deploy

Deploy the `mailgun-relay` FastAPI service: a Mailgun-Messages-API-compatible
HTTP→SMTP adapter for `django-anymail` clients.

The service enforces (in order, before any SMTP submission):

1. HTTP Basic auth with username `api` (constant-time token verify).
2. Per-token sender policy: `{domain}` path, `from`-domain, and optional exact
   `from`-address allowlist.
3. Header-injection and dangerous-header rejection.

It then constructs MIME (including attachments and CC) and submits via
authenticated STARTTLS SMTP to the configured backend with the
relay-controlled mailbox as envelope `MAIL FROM`.

## Companion role

Pair with `mailgun_relay_ingress_deploy` on the host that runs Traefik to
expose the service publicly behind TLS.

## Requirements

- Target host: Ubuntu (jammy or noble).
- `uv` installed (handled via `uv_install` role dependency).
- Reachable authenticated SMTP submission endpoint (default points at the
  home mail stack at `smtp.home.xn--wersdrfer-47a.de:587`).
- A PostfixAdmin mailbox for the relay (envelope `MAIL FROM` + SMTP login):
  PostfixAdmin's `smtpd_sender_login_maps` enforces login-bound senders so the
  envelope sender MUST be the relay's own mailbox (or an alias mapped to it).
  Ops creates this mailbox out-of-band; this role only consumes its
  credentials.

## Role variables (defaults)

| Variable | Default | Notes |
| --- | --- | --- |
| `mailgun_relay_enabled` | `true` | |
| `mailgun_relay_user` | `mailgun-relay` | system user |
| `mailgun_relay_home` | `/opt/apps/mailgun-relay` | |
| `mailgun_relay_site_path` | `{{ home }}/site` | application source |
| `mailgun_relay_venv_path` | `{{ site }}/.venv` | uv-managed venv |
| `mailgun_relay_env_dir` | `/etc/mailgun-relay` | root:mailgun-relay 0750 |
| `mailgun_relay_env_path` | `{{ env_dir }}/mailgun-relay.env` | non-secret runtime config |
| `mailgun_relay_secrets_path` | `{{ env_dir }}/secrets.yml` | secrets, 0640 root:mailgun-relay |
| `mailgun_relay_deploy_method` | `rsync` | `rsync` or `git` |
| `mailgun_relay_source_path` | `""` | REQUIRED when method=rsync |
| `mailgun_relay_python_version` | `3.14` | |
| `mailgun_relay_bind_host` | `127.0.0.1` | loopback by default; reverse proxy fronts it |
| `mailgun_relay_bind_port` | `8085` | |
| `mailgun_relay_public_host` | `mailgun.home.xn--wersdrfer-47a.de` | punycode |
| `mailgun_relay_smtp_host` | `smtp.home.xn--wersdrfer-47a.de` | |
| `mailgun_relay_smtp_port` | `587` | |
| `mailgun_relay_smtp_starttls` | `true` | |
| `mailgun_relay_max_body_bytes` | `26_214_400` | 25 MiB cap (HTTP request) |
| `mailgun_relay_max_attachments` | `10` | |
| `mailgun_relay_max_attachment_bytes` | `10_485_760` | 10 MiB per file |
| `mailgun_relay_max_recipients` | `100` | to+cc+bcc combined |
| `mailgun_relay_max_header_value_length` | `998` | RFC 5322 line limit |
| `mailgun_relay_log_level` | `INFO` | structured JSON to stdout |

## REQUIRED variables (no safe defaults)

These must be set from `ops-control` SOPS secrets; the role rejects
`"CHANGEME"` placeholders:

- `mailgun_relay_smtp_username` — PostfixAdmin mailbox the relay logs in as.
- `mailgun_relay_smtp_password` — same mailbox's password.
- `mailgun_relay_envelope_sender` — envelope `MAIL FROM`. MUST be the relay's
  mailbox (login binding is enforced backend-side).
- `mailgun_relay_tokens` — list of `{ label, token_sha256, mailgun_domains,
  allowed_from_domains, [allowed_from_addresses] }` entries.

`token_sha256` is the lowercase hex SHA-256 of the raw token. The raw token
value is never stored on the server; only this verifier is.

## Example token entry

```yaml
mailgun_relay_tokens:
  - label: homepage-production
    token_sha256: "abcd...ef"
    mailgun_domains: ["wersdoerfer.de"]
    allowed_from_domains: ["wersdoerfer.de"]
    allowed_from_addresses:
      - "jochen-homepage@wersdoerfer.de"
```

## Verification

The role's `health.yml` waits for the bind port, calls `GET /health`, and
checks the structured systemd `active` state plus the exact payload contract:
`status == "ok"` **and no `version` key**. The relay deliberately withholds its
version from `/health` because the Traefik router in front of it has no path
restriction, so the endpoint answers unauthenticated callers. A deploy that
starts failing this assertion means the deployed source predates that hardening
— check what `mailgun_relay_source_path` is actually rsyncing.

## Logging / security

The service emits structured JSON logs, one object per line on stdout, which the
unit routes to the journal under the `mailgun-relay` syslog identifier:

- `event=startup`, once per process start: version, bind address, public host,
  SMTP host/port/STARTTLS, custom-CA flag, log level, configured token
  **labels**, and the body/recipient caps. Raising `mailgun_relay_log_level`
  above `INFO` quietens the request records but never this one.
- `event=request`, once per `POST /v3/{domain}/messages`: `request_id,
  token_label, path_domain, from, recipient_count, message_id, result,
  status_code, error_class, duration_ms`.

It never writes token values or hashes, the `Authorization` header, the SMTP
password, the message body, or attachment content to logs. `GET /health` writes
no log line at all, so the deploy-time probe does not pollute the access log.

### Reading the relay journal

```bash
journalctl -u mailgun-relay -f            # live
journalctl -t mailgun-relay --since -7d   # by syslog identifier
```

Silence is ambiguous, and has already been misread once as a broken logging
pipeline. Work through it in this order:

1. **Is there a `startup` record for the current process?**
   `journalctl -u mailgun-relay --since "$(systemctl show mailgun-relay -p ActiveEnterTimestamp --value)"`.
   If yes, the logging pipeline works and the relay has simply not been asked to
   send anything since it started — that is the normal state for a low-volume
   relay.
2. **Is the startup record missing along with all other history?** Check
   journald retention on the host (`journalctl --disk-usage`,
   `journalctl --list-boots`). A busy host can rotate the relay's records away
   within days, which looks exactly like "the relay never logs".
3. **Only then suspect the service.** Do *not* add `PYTHONUNBUFFERED=1` to the
   unit as a fix: the relay logs through `logging.StreamHandler`, which flushes
   after every record, so a block-buffered stdout pipe cannot hold its lines
   back. The mailgun-relay repo pins this with a test.

## Troubleshooting

- `401`/`403` ratios on the relay typically point at out-of-sync token hashes
  between the app's `.env` and the relay SOPS file.
- `503` from `/v3/.../messages` indicates an SMTP TEMPORARY failure (4xx
  response, connection refused, or timeout) — check the mail backend on
  macmini and the relay journal.
- `502` indicates an SMTP PERMANENT failure (5xx response or auth failure to
  the backend). PostfixAdmin sender/login binding is the most common cause:
  verify the envelope sender equals the relay's mailbox.

## Companion playbook

See `ops-control/playbooks/deploy-mailgun-relay.yml`.
