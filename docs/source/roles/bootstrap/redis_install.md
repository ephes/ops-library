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

Validation renders a root-owned mode-0600 candidate in a mode-0700 temporary
directory and checks it before replacing the active configuration. Only accepted
candidates are atomically installed, with the existing root:root mode-0644
permissions and backup behavior. Invalid candidates leave the previous file and
running Redis process intact. Unchanged candidates are still validated without
a restart. The ephemeral script and candidate directory are removed in an
Ansible `always` block, including normal validation failure.

The validator handles INT/TERM by failing and cleaning up. Signals received
during cleanup defer exit until termination and artifact removal finish, retaining
a failure status; repeated signals cannot turn cleanup into successful validation.
PID reading uses a shell builtin, and the owned removal subprocess ignores
INT/TERM with at most three guarded attempts. Permanent removal failure rejects
validation and may leave artifacts for inspection. This boundary does
not roll back a valid configuration if a later service restart fails or execution
stops between installation and the handler. Abrupt host loss or an unreachable
target may prevent cleanup. Check mode predicts configuration changes without
creating the validator or starting Redis. Validation remains disabled by default;
when disabled, the configuration is installed directly as before.
