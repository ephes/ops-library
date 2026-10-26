# metrics_endpoint

Lightweight JSON health endpoint (e.g., `/.well-known/health`) to expose mail metrics (queue counts, disk usage, service status) for nyxmon. Uses a Python stdlib HTTP server with htpasswd-based basic auth and a shell script for metrics, running on system Python 3 (no venv/uv).

Tracks PRD: `specs/mail-nyxmon-prd.md` (issue `ops-meta-e15`).

## Variables (defaults)

```yaml
metrics_endpoint_enabled: false           # gate execution
metrics_endpoint_user: metrics
metrics_endpoint_group: "{{ metrics_endpoint_user }}"
metrics_endpoint_service_name: metrics-endpoint
metrics_endpoint_impl: "{{ metrics_httpd_impl | default('python') }}"  # python | rust, see below

metrics_endpoint_bind: "{{ tailscale_ip | default('127.0.0.1') }}"
metrics_endpoint_port: 9100
metrics_endpoint_path: "/.well-known/health"
metrics_endpoint_script_timeout: 10
metrics_endpoint_auth_user: "CHANGE_ME"
metrics_endpoint_auth_password: "CHANGE_ME"

metrics_endpoint_packages:
  - python3
  - apache2-utils
  - acl

metrics_endpoint_script_path: "/usr/local/bin/mail-metrics.sh"
metrics_endpoint_server_path: "/usr/local/bin/metrics_httpd.py"
metrics_endpoint_htpasswd_dir: "/etc/metrics-endpoint"
metrics_endpoint_htpasswd_path: "{{ metrics_endpoint_htpasswd_dir }}/htpasswd"

metrics_endpoint_vmail_path: "/mnt/cryptdata/vmail"
metrics_endpoint_queue_path: "/var/spool/postfix"
metrics_endpoint_services: [postfix, dovecot, rspamd]
metrics_endpoint_extra_metrics: []        # list of extra commands to emit into JSON (currently unused)
metrics_endpoint_probe_states: []         # probe state files exported as sections, see below
```

## Usage

```yaml
- hosts: mail
  become: true
  vars:
    metrics_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/nyxmon.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.metrics_endpoint
      vars:
        metrics_endpoint_enabled: true
        metrics_endpoint_auth_user: nyxmon
        metrics_endpoint_auth_password: "{{ metrics_secrets.nyxmon_metrics_password }}"
        metrics_endpoint_bind: "{{ tailscale_ip }}"
```

## What it does

- Installs `metrics_endpoint_packages` (defaults: `python3`, `apache2-utils`, `acl`).
- Creates `metrics` system user/group.
- Deploys `mail-metrics.sh` (queue counts, disk usage, service status).
- Deploys `metrics_httpd.py` (Python HTTP server, basic auth via htpasswd, runs metrics script).
  Password verification sends the request password on stdin (`htpasswd -vi`),
  keeping it out of process arguments. The Basic Auth realm and ordinary
  responses stay unchanged. Requests with a NUL in the password fail closed with
  401 instead of an exception. The existing 255-byte limit is enforced; CR/LF requests are
  rejected except for already accepted suffix bytes beyond bcrypt's 72-byte
  boundary, and that exception requires every record for the selected user to
  be bcrypt. APR/SHA and other schemes receive no suffix exception.
- Generates htpasswd file at `/etc/metrics-endpoint/htpasswd`.
- Creates systemd unit `metrics-endpoint.service`, binds to loopback/Tailscale only.
- Applies ACLs on postfix queue paths so the metrics user can read queue counts.

## Probe state sections

`metrics_endpoint_probe_states` exports state files written by probe timers,
for example the relay probe of the `mail_monitoring` role:

```yaml
metrics_endpoint_probe_states:
  - name: mailgun_relay
    path: /var/lib/mailgun-relay-probe/state
```

Each file holds `key=value` lines; the endpoint reads `last_status` (HTTP
status, `0` when no response arrived) and `last_run` (epoch seconds) and adds
the age at request time:

```json
"mailgun_relay": {"last_status": 200, "last_run": 1760531400, "age_seconds": 312}
```

A missing, unreadable or malformed file omits the section, so json-metrics
rules on `$.mailgun_relay.*` fail with `path_missing` instead of passing.
`name` must be lowercase (`[a-z][a-z0-9_]*`) and must not shadow a built-in
section; the role asserts both. With the list empty (the default) the
rendered script is unchanged.

## HTTP server implementation (Python or Rust)

`metrics_endpoint_impl` selects the HTTP server: `python` runs
`metrics_endpoint_server_path` (the unit's `ExecStart=`), `rust` runs the
pinned `metrics-httpd` release through the drop-in
`/etc/systemd/system/<service>.service.d/metrics-httpd-impl.conf`
([`metrics_httpd_switch`](../metrics_httpd_switch/README.md),
`rust/metrics-httpd/PLAN.md` section 7). The endpoint keeps its path, port,
realm, htpasswd file, metrics script, user, sandbox and IP allow list; the
unit file and the Python script stay as they are with either value.

| Variable | Default | Meaning |
| --- | --- | --- |
| `metrics_endpoint_impl` | `{{ metrics_httpd_impl \| default('python') }}` | `python` or `rust`; override per host for a canary. |
| `metrics_httpd_impl` | (unset: `python`) | Fleet-wide default for every metrics-httpd endpoint. |
| `metrics_httpd_rust_version` / `metrics_httpd_rust_sha256` | (unset) | Pinned release and the sha256 of its archive. Required for `rust`; with `python` a set version is installed and checked ahead of the switch. |

With `rust` the binary runs `script --bind --port --path --script
--script-timeout --htpasswd-file --realm metrics --server-name
metrics-httpd/0.1` from the variables above. Before the drop-in is written the
binary's `--check-config` must pass as `metrics_endpoint_user` in the unit's
sandbox; after the restart the deploy checks that the unit runs the selected
implementation and that an unauthenticated request gets 401 with the realm,
then pins the version in `/opt/metrics-httpd/.pins/<service>`. Switching back
to `python` removes the drop-in and restarts the Python script.

The Rust `script` mode runs `metrics_endpoint_script_path` like the Python
wrapper: no shell, no arguments, `metrics_endpoint_script_timeout` seconds,
stdout served as the body (PLAN.md 4.4).

## Notes

- Auth placeholders must be overridden; role asserts on `CHANGE_ME`.
- The Python server calls `htpasswd -vi` with the password on stdin for auth checks; keep `apache2-utils` installed.
- The systemd unit runs `/usr/bin/python3` directly; ensure the system package is present.
- Adjust `metrics_endpoint_services`/paths per host (edge vs backend).
- ACLs are set on queue paths; ensure filesystem supports ACLs (`acl` package installed).
