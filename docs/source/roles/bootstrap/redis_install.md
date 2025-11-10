# Redis Install Role

Bootstrap role for installing and configuring a standalone Redis instance.

## Capabilities

- Installs `redis-server` (optionally from packages.redis.io)
- Templates `redis.conf` for predictable bind addresses, authentication, backlog, logging, and persistence
- Optional password enforcement (`redis_install_requirepass_enabled`)
- Tunable memory policy (`redis_install_maxmemory`, `redis_install_maxmemory_policy`)
- Optional config validation via `redis-server --test-memory`
- Enables and starts the systemd unit

## Usage

```yaml
- hosts: redis_hosts
  become: true
  roles:
    - role: local.ops_library.redis_install
      vars:
        redis_install_bind_addresses:
          - 127.0.0.1
          - ::1
        redis_install_requirepass_enabled: false  # localhost-only, no password
```

With authentication:

```yaml
- hosts: redis_hosts
  become: true
  vars:
    redis_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/secrets/redis.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.redis_install
      vars:
        redis_install_requirepass_enabled: true
        redis_install_password: "{{ redis_secrets.redis_password }}"
```

## Key Variables

- `redis_install_bind_addresses`: list of bind targets (default: `['127.0.0.1', '::1']`)
- `redis_install_maxmemory`: string/integer memory limit (`"0"` = unlimited, accepts `256mb`)
- `redis_install_maxmemory_policy`: eviction policy (`noeviction`, `allkeys-lru`, etc.)
- `redis_install_appendonly`: enable/disable AOF persistence (`false` by default)
- `redis_install_validate_config`: run `redis-server ... --test-memory` after templating (`false` default)

Refer to `roles/redis_install/defaults/main.yml` for the complete list.
