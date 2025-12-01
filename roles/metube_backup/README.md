# MeTube Backup Role

Backs up MeTube state/config/systemd/Traefik artifacts into timestamped directories (and tarballs) under `{{ metube_backup_root }}`.

- Stops the `{{ metube_service_name }}` service for consistency (toggle via `metube_backup_stop_service`).
- Copies `{{ metube_state_dir }}`, `{{ metube_env_file }}`, optional systemd unit and Traefik config.
- Emits a manifest and optional `*.tar.gz` archive, fetchable to the controller when `metube_backup_fetch_local` is true.

Usage example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.metube_backup
      vars:
        metube_backup_prefix: "{{ backup_prefix | default('manual') }}"
```
