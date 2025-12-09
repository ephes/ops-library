# metrics_endpoint

Lightweight JSON health endpoint (e.g., `/.well-known/health`) to expose mail metrics (queue counts, disk usage, service status) for nyxmon. Uses a Python stdlib HTTP server with htpasswd-based basic auth and a shell script for metrics.

Tracks PRD: `../ws-mail-meta/specs/mail-nyxmon-prd.md` (issue `ws-mail-meta-e15`).

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

metrics_endpoint_script_path: "/usr/local/bin/mail-metrics.sh"
metrics_endpoint_server_path: "/usr/local/bin/metrics_httpd.py"
metrics_endpoint_htpasswd_dir: "/etc/metrics-endpoint"
metrics_endpoint_htpasswd_path: "{{ metrics_endpoint_htpasswd_dir }}/htpasswd"

metrics_endpoint_vmail_path: "/mnt/cryptdata/vmail"
metrics_endpoint_queue_path: "/var/spool/postfix"
metrics_endpoint_services: [postfix, dovecot, rspamd]
metrics_endpoint_extra_metrics: []        # list of extra commands to emit into JSON (currently unused)
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

- Installs `python3` + `apache2-utils` (for `htpasswd` verification).
- Creates `metrics` system user/group.
- Deploys `mail-metrics.sh` (queue counts, disk usage, service status).
- Deploys `metrics_httpd.py` (Python HTTP server, basic auth via htpasswd, runs metrics script).
- Generates htpasswd file at `/etc/metrics-endpoint/htpasswd`.
- Creates systemd unit `metrics-endpoint.service`, binds to loopback/Tailscale only.
- Applies ACLs on postfix queue paths so the metrics user can read queue counts.

## Notes

- Auth placeholders must be overridden; role asserts on `CHANGE_ME`.
- The Python server calls `htpasswd -vb` for auth checks; keep `apache2-utils` installed.
- Adjust `metrics_endpoint_services`/paths per host (edge vs backend).
- ACLs are set on queue paths; ensure filesystem supports ACLs (`acl` package installed).
