# mailgun_relay_deploy

Deploy the `mailgun-relay` FastAPI service: a Mailgun-Messages-API-compatible
HTTP→SMTP adapter for `django-anymail` clients. The unit can instead run the
Rust port of the relay, a single release binary; see
[Implementation: Python or Rust](#implementation-python-or-rust).

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
| `mailgun_relay_rsync_excludes` | see `defaults/main.yml` | rsync `--exclude` patterns; see [What the rsync deploy ships](#what-the-rsync-deploy-ships) |
| `mailgun_relay_python_version` | `3.14` | |
| `mailgun_relay_bind_host` | `127.0.0.1` | loopback by default; reverse proxy fronts it |
| `mailgun_relay_bind_port` | `8085` | |
| `mailgun_relay_public_host` | `mailgun.home.xn--wersdrfer-47a.de` | punycode |
| `mailgun_relay_smtp_host` | `smtp.home.xn--wersdrfer-47a.de` | |
| `mailgun_relay_smtp_port` | `587` | |
| `mailgun_relay_smtp_starttls` | `true` | |
| `mailgun_relay_smtp_max_concurrency` | `""` | optional; empty keeps the relay default (8). Rendered as `MAILGUN_RELAY_SMTP_MAX_CONCURRENCY`, must be a whole number of at least 1 |
| `mailgun_relay_max_body_bytes` | `26_214_400` | 25 MiB cap (HTTP request) |
| `mailgun_relay_max_attachments` | `10` | |
| `mailgun_relay_max_attachment_bytes` | `10_485_760` | 10 MiB per file |
| `mailgun_relay_max_recipients` | `100` | to+cc+bcc combined |
| `mailgun_relay_max_header_value_length` | `998` | RFC 5322 line limit |
| `mailgun_relay_log_level` | `INFO` | structured JSON to stdout |

## Implementation: Python or Rust

`mailgun-relay.service` runs either the Python service from the venv
(`python -m mailgun_relay`, the default) or the Rust port, a single binary
published as a GitHub release of mailgun-relay (tag `rs-v<version>`, asset
`mailgun-relay-<version>-x86_64-unknown-linux-gnu.tar.gz`; the release build
needs no glibc symbol newer than 2.35, so Ubuntu 22.04 or newer runs it). Both
read the same env file and secrets and serve the same port, so only one of
them runs at a time.

| Variable | Default | Meaning |
| --- | --- | --- |
| `mailgun_relay_impl` | `python` | `python` or `rust`: which implementation the unit starts |
| `mailgun_relay_rust_version` | `""` | Release to install, e.g. `0.2.0`. Empty: nothing is installed, validated or pruned. Required for `rust` |
| `mailgun_relay_rust_sha256` | `""` | sha256 of the release archive (64 lowercase hex digits); required with a version unless a local archive is used |
| `mailgun_relay_rust_release_url` | GitHub release asset of `mailgun_relay_rust_version` | Download URL |
| `mailgun_relay_rust_local_archive` | `""` | Controller path of an archive with the release layout; replaces the download (development). Checked against `mailgun_relay_rust_sha256` when both are set |
| `mailgun_relay_rust_install_root` | `/opt/mailgun-relay` | Versions are installed to `<root>/<version>/mailgun-relay`; a normalized absolute path (no `.`, `..` or empty components) outside the rsync-managed site path |
| `mailgun_relay_rust_keep_versions` | `3` | Newest installed versions kept by pruning |

Set these in host variables, not in the play's role `vars:`, so the inventory
is the one place to switch. A pinned version is installed with either
implementation, which allows installing the binary ahead of the switch.
`/opt/mailgun-relay` (Rust releases, root-owned) is not
`/opt/apps/mailgun-relay` (the service user's home with the Python site).

What the role does, in order:

1. Validates the settings before anything changes (`rust` needs a version; a
   version needs a checksum or a local archive).
2. Deploys source, venv, env file and secrets for both implementations: the
   venv is the rollback path, and env and secrets are shared. A Python code or
   lock change therefore restarts the unit even while Rust runs.
3. With `python`: removes the drop-in
   `/etc/systemd/system/mailgun-relay.service.d/impl.conf` **before** any Rust
   step, so switching back never depends on the Rust release.
4. With a version set and `<root>/<version>/` missing: downloads the archive
   with `get_url` and the pinned checksum (or copies the local archive and
   checks its checksum), refuses an archive that does not hold exactly the
   regular files `mailgun-relay` and `LICENSE` (checked with `tar --list`
   before extraction; links and devices are refused), unpacks it into
   `<root>/.staging/`, records the archive checksum in
   `<root>/<version>/.archive-sha256` and moves the directory into place
   (root-owned, `0755`). An installed version is never modified: the same
   version from a different archive is refused.
5. Validates the candidate by the versioned path: `mailgun-relay --version` as
   the service user (must print `mailgun-relay <version> (<commit>)`), then
   `mailgun-relay --check-config` under the unit's identity, environment file
   and sandbox:

   ```bash
   systemd-run --wait --pipe --collect --quiet \
     -p User=mailgun-relay -p Group=mailgun-relay \
     -p EnvironmentFile=/etc/mailgun-relay/mailgun-relay.env \
     -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes \
     -p PrivateTmp=yes -p PrivateDevices=yes \
     /opt/mailgun-relay/<version>/mailgun-relay --check-config
   ```

   It loads the env file and the secrets file exactly as the server would
   (schema, file mode, token shapes, the SMTP CA file) and binds nothing.
   A failure in steps 4–5 removes a version installed in this run again and
   leaves the drop-in, the running unit and the other versions alone. With
   `rust` it stops the play. With `python` it is reported as an ignored
   failure (`WARNING: ...`, `ignored=1` in the recap) and the deploy goes on to
   restart and verify Python; nothing is pruned in that run.
6. With `rust`: writes the drop-in

   ```ini
   [Service]
   ExecStart=
   ExecStart=/opt/mailgun-relay/<version>/mailgun-relay
   Environment=MALLOC_MMAP_THRESHOLD_=131072
   ```

   The base unit keeps the Python `ExecStart`, `WorkingDirectory`, `User`,
   `EnvironmentFile`, `SyslogIdentifier=mailgun-relay` and the hardening for
   both implementations. `MALLOC_MMAP_THRESHOLD_` fixes glibc's mmap threshold
   at 128 KiB: with the default dynamic threshold, buffers of a request with
   large attachments stay on the heap afterwards (40–100 MiB resident after a
   request at the 25 MiB limit, against 4.5 MiB with the fixed threshold). The
   version is part of the drop-in, so a version change or a switch changes the
   file and restarts the unit; a deploy that changes neither restarts nothing.
   When the selection moves away from a Rust version, that version is written
   to `<root>/.previous-version`.
7. After the handlers and the health check: waits up to 30 s until the unit
   is active and its main process is the selected implementation: for `rust`,
   `readlink /proc/<pid>/exe` equals the versioned binary; for `python`, the
   argv in `/proc/<pid>/cmdline` contains `<venv>/bin/python`, `-m` and
   `mailgun_relay`, and the executable is not below the install root.
8. Only then, with a version set: prunes version directories beyond the
   newest `mailgun_relay_rust_keep_versions` (by modification time). The
   pinned version, the version the live process runs and the previously
   selected one are always kept; directories that are not version-shaped are
   never touched.

Example (host variables):

```yaml
# Install 0.2.0 next to the running Python service, nothing switched
mailgun_relay_impl: python
mailgun_relay_rust_version: "0.2.0"
mailgun_relay_rust_sha256: "<sha256 from the release's .sha256 asset>"

# Switch: the next deploy writes the drop-in and restarts mailgun-relay
mailgun_relay_impl: rust
```

Development build instead of a release (an archive with the release layout):

```yaml
mailgun_relay_impl: rust
mailgun_relay_rust_version: "0.2.0"
mailgun_relay_rust_local_archive: /path/to/mailgun-relay-0.2.0-x86_64-unknown-linux-gnu.tar.gz
```

### Rollback

- Back to Python: set `mailgun_relay_impl: python` and deploy. The drop-in is
  removed first, the unit restarts with the venv. This works even when the
  pinned release is broken or rejects the configuration (step 5). The binary
  stays installed, so switching forward again needs no download.
- Emergency without Ansible, on the host:
  `rm /etc/systemd/system/mailgun-relay.service.d/impl.conf && systemctl daemon-reload && systemctl restart mailgun-relay`.
  Set `mailgun_relay_impl: python` in the inventory before the next deploy, or
  that deploy writes the drop-in again.
- Bad Rust release: pin the previous `mailgun_relay_rust_version` and
  `mailgun_relay_rust_sha256` again and deploy. Its directory is still
  installed (pruning keeps the previously selected version), the drop-in
  changes and the unit restarts.

The relay holds no state, so every switch is a plain restart (about 1–2 s in
which a send fails; Anymail does not retry).

## What the rsync deploy ships

With `mailgun_relay_deploy_method: rsync` the role pushes
`mailgun_relay_source_path` to `mailgun_relay_site_path` with `--delete`,
minus `mailgun_relay_rsync_excludes`. Besides caches, virtualenvs and `.env`
files, the defaults keep two things off the host:

- `.git` (no trailing slash), so git metadata stays behind both for a normal
  clone, where it is a directory, and for a git worktree, where it is a file
  pointing at the main repository.
- `/rust/`, the Rust port in the relay repository (sources, plans, fixtures and
  Cargo build output). The Python service needs none of it. The leading slash
  anchors the pattern at the source root, so a directory named `rust` deeper in
  the tree is still synced.

rsync never deletes excluded paths on the receiving side, so a `.git` or
`rust/` that an earlier deploy already copied stays in the site directory until
it is removed by hand. The `git` deploy method clones the whole repository and
does not use these excludes.

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
`status == "ok"` **and no `version` key** (the same contract for both
implementations; step 7 of [the implementation switch](#implementation-python-or-rust)
then checks which one answers). The relay deliberately withholds its
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

## Testing

- `just test-mailgun-relay-deploy`: unit tests for the rsync excludes and the
  implementation switch (defaults, validation, task order, drop-in, failure
  handling, live check, pruning).
- `just test-mailgun-relay-deploy-molecule`: the Molecule scenario. It deploys
  the Python service from the public repository (pinned commit) into a systemd
  container, then fake Rust release archives built in the container from a
  small C program that answers `--version`, `--check-config` and
  `GET /health`: install ahead of the switch without a restart, switch,
  version change with pruning, a wrong version, a failing `--check-config`, a
  different archive for an installed version and a symlink member (each
  refused with nothing switched), and rollbacks to Python while the pinned
  release fails `--check-config` or its archive is broken.

## Companion playbook

See `ops-control/playbooks/deploy-mailgun-relay.yml`.

## Restart behavior

Source and dependency changes notify the existing restart handlers after deployment.
mailgun-relay restarts its systemd service. Unchanged syncs do not request a restart.
A changed drop-in (implementation switch or Rust version change) reloads systemd and
restarts the unit; installing a Rust release with `mailgun_relay_impl: python` does not.
