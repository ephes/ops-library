# metrics_endpoint

Lightweight JSON health endpoint (e.g., `/.well-known/health`) to expose mail metrics (queue counts, disk usage, service status) for nyxmon. Uses a Python stdlib HTTP server with htpasswd-based basic auth and a shell script for metrics, running on system Python 3 (no venv/uv).

Tracks PRD: `specs/mail-nyxmon-prd.md` (issue `ops-meta-e15`).

## Variables (defaults)

```yaml
metrics_endpoint_enabled: false           # gate execution
metrics_endpoint_user: metrics
metrics_endpoint_group: "{{ metrics_endpoint_user }}"
metrics_endpoint_service_name: metrics-endpoint

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

## Notes

- Auth placeholders must be overridden; role asserts on `CHANGE_ME`.
- The Python server calls `htpasswd -vb` for auth checks; keep `apache2-utils` installed.
- The systemd unit runs `/usr/bin/python3` directly; ensure the system package is present.
- Adjust `metrics_endpoint_services`/paths per host (edge vs backend).
- ACLs are set on queue paths; ensure filesystem supports ACLs (`acl` package installed).
