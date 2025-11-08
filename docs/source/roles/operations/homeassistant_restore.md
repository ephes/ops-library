# Home Assistant Restore

Restores a backup created by `homeassistant_backup`, verifying manifests and optionally running in dry-run mode before applying changes.

## Capabilities

- Accepts either `latest` or a specific archive/directory via `homeassistant_restore_archive`.
- Validates SHA256 manifest before copying files back into place.
- Stops Home Assistant, syncs `config/`, `data/`, `logs/`, Traefik/systemd definitions, and restarts the service.
- Supports `homeassistant_restore_dry_run: true` for rehearsal without modifying the filesystem.
- Optional HTTP health check (`homeassistant_restore_health_url`) after restart.

## Key Variables

- `homeassistant_restore_archive` – tarball name or directory (relative to `/opt/backups/homeassistant`).
- `homeassistant_restore_manifest_required` – enforce manifest presence.
- `homeassistant_restore_health_url` / `homeassistant_restore_health_headers` – post-restore verification.

Example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.homeassistant_restore
      vars:
        homeassistant_restore_archive: pre-deploy-20251108T130000Z
        homeassistant_restore_health_url: "http://127.0.0.1:10020/auth/providers"
```
