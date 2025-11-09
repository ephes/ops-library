# redis_install

An ops-library role for installing and configuring Redis with predictable defaults.

## Features

- Installs `redis-server` (optionally from the official packages.redis.io repository)
- Renders `redis.conf` from a template instead of ad-hoc edits
- Supports password-less and password-protected deployments
- Exposes knobs for bind addresses, persistence, memory, and supervised mode
- Optional tuning for backlog/keepalive/logging and RDB safety
- Config validation hook before restarting the service
- Ensures the systemd unit is enabled and running

## Requirements

- Ansible `2.15` or newer
- Target OS: Debian 11+/Ubuntu 20.04+ (systemd)
- Redis `3.2`+ (for multiple `bind` directives)

## Variables

See `defaults/main.yml` for the full list. Key options:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `redis_install_bind_addresses` | `['127.0.0.1', '::1']` | Addresses passed to `bind` |
| `redis_install_port` | `6379` | TCP port |
| `redis_install_requirepass_enabled` | `false` | Toggle password auth |
| `redis_install_password` | `""` | Password when auth enabled |
| `redis_install_maxmemory` | `"0"` | Memory limit (`0` = unlimited, accepts `256mb` style values) |
| `redis_install_maxmemory_policy` | `noeviction` | Eviction policy |
| `redis_install_save_rules` | `["900 1","300 10","60 10000"]` | RDB save schedule |
| `redis_install_appendonly` | `false` | Enable/disable AOF |
| `redis_install_tcp_backlog` | `511` | `tcp-backlog` tuning |
| `redis_install_timeout` | `0` | Client timeout seconds |
| `redis_install_tcp_keepalive` | `300` | TCP keepalive interval |
| `redis_install_stop_writes_on_bgsave_error` | `true` | Stop writes when RDB fails |
| `redis_install_loglevel` | `notice` | Redis log level |
| `redis_install_log_dir` | `/var/log/redis` | Log directory |
| `redis_install_logfile` | `/var/log/redis/redis-server.log` | Log destination |
| `redis_install_validate_config` | `false` | Run `redis-server --test-memory` after writing config |

> Tip: enable `redis_install_validate_config: true` in production to catch syntax errors **before** the service restarts. When enabled, the deploy will stop if validation fails so Redis keeps running with the previous config.

## Examples

### Localhost-only, no password (Paperless default)

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.redis_install
      vars:
        redis_install_bind_addresses:
          - 127.0.0.1
        redis_install_requirepass_enabled: false
```

### Password-protected Redis

```yaml
- hosts: app_servers
  become: true
  roles:
    - role: local.ops_library.redis_install
      vars:
        redis_install_requirepass_enabled: true
        redis_install_password: "{{ sops_secrets.redis_password }}"
        redis_install_bind_addresses:
          - 127.0.0.1
          - ::1
```

## Verification

1. `redis-cli -h localhost -p {{ redis_install_port }} ping`
2. `redis-cli -a "$REDIS_PASSWORD" ping` when auth enabled
3. `systemctl status {{ redis_install_service_name }}` to confirm the service is `active (running)`

## Testing

```bash
# Dry run
ansible-playbook -i localhost, tests/redis.yml --connection=local --check --diff

# Real run
ansible-playbook -i localhost, tests/redis.yml --connection=local
```

After deployment:

```bash
redis-cli ping
systemctl status redis-server
ss -lntp | grep 6379
```

## Troubleshooting

| Issue | Steps |
|-------|-------|
| `redis-cli ping` fails | `journalctl -u redis-server -n 50`, ensure `bind` list matches interfaces |
| Config validation fails | Run `redis-server /etc/redis/redis.conf --test-memory 2` manually to inspect errors |
| Service fails to start after applying template | Verify `redis_install_maxmemory` format (e.g., `256mb`), confirm `redis_install_password` set when auth enabled |
