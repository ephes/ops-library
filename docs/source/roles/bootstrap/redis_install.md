# Redis Install Role

Bootstrap role for installing and configuring a standalone Redis instance.

## Capabilities

- Installs `redis-server` (optionally from packages.redis.io)
- Templates `redis.conf` for predictable bind addresses, authentication, backlog, logging, and persistence
- Optional password enforcement (`redis_install_requirepass_enabled`)
- Tunable memory policy (`redis_install_maxmemory`, `redis_install_maxmemory_policy`)
- Optional config validation using a standalone Redis instance with a private Unix socket and no TCP listener
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
- `redis_install_validate_config`: validate the rendered config with the temporary standalone instance (`false` default)

Refer to `roles/redis_install/defaults/main.yml` for the complete list.

## Validation behavior

When enabled, validation creates a mode-0700 temporary subdirectory beneath
`redis_install_validate_dir` (default `/tmp/redis-config-test`). The standalone
validator disables systemd supervision and uses a private Unix socket with TCP
disabled. Use a short validation directory path to stay within the Unix socket
path limit.

On exit, the role signals the validator, polls for termination, escalates to
SIGKILL if necessary, and removes its socket, pidfile, log and temporary
subdirectory. The parent directory may remain empty. Raw Redis diagnostics are
kept in the temporary private log and are not dumped into Ansible output because
configuration directives may contain secrets.

Validation happens after the desired config is rendered, before restarting the
service. Invalid configuration stops the deploy and leaves the existing Redis
process running with its previous configuration, but the invalid rendered file
remains on disk. Correct it and rerun the role before a later service restart.
Validation remains disabled by default.
