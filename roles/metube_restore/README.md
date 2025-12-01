# MeTube Restore Role

Restores MeTube from archives produced by `metube_backup`, reapplying state/config/systemd/Traefik files.

- Selects a specific archive or `latest` under `{{ metube_restore_root }}`.
- Restores `{{ metube_state_dir }}` via rsync, env file to `{{ metube_env_file }}`, systemd unit, and Traefik config.
- Stops the service during restore and restarts afterwards (toggles via `metube_restore_stop_service`/`metube_restore_restart`).

Example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.metube_restore
      vars:
        metube_restore_archive: "{{ archive | default('latest') }}"
```
