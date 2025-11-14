# Homelab Restore Role

`homelab_restore` rehydrates a Homelab deployment from archives produced by `homelab_backup`. It validates metadata/manifests, creates an optional safety snapshot, restores database/files/configuration, and restarts the service with post-restore checks.

## Features

- Archive discovery (`homelab_restore_archive: latest` finds newest tarball)
- Metadata + SHA256 validation with version-mismatch protection
- Optional dry-run mode that unpacks/validates without touching live files
- Safety snapshot (`/home/homelab/site.pre-restore-<ts>`) for rollback
- Controlled restore of SQLite DB, static/media/cache directories, `.env`, systemd unit, and Traefik config
- Optional static rebuild (`homelab_restore_rebuild_static: true`)
- Post-restore verification: Django `check --deploy`, `showmigrations`, SQLite integrity, HTTP probe

## Key Variables

```yaml
homelab_restore_archive: latest
homelab_restore_root: /opt/backups/homelab
homelab_restore_dry_run: false
homelab_restore_validate_checksums: true
homelab_restore_allow_version_mismatch: false
homelab_restore_create_safe_snapshot: true
homelab_restore_safe_snapshot_delete: true
homelab_restore_restore_env: true
homelab_restore_rebuild_static: false
homelab_restore_verify_http: true
homelab_restore_healthcheck_url: "http://127.0.0.1:{{ homelab_app_port }}/{{ homelab_django_admin_url }}"
homelab_restore_expected_content: "Homelab"
```

## Example Playbook

```yaml
- name: Restore Homelab from latest archive
  hosts: macmini
  become: true
  vars:
    homelab_restore_archive: latest
  roles:
    - role: local.ops_library.homelab_restore
      vars:
        homelab_restore_dry_run: false
        homelab_restore_allow_version_mismatch: false
```

## Usage Tips

- Run `homelab_restore_dry_run: true` to inspect metadata and checksum validation without modifying the host.
- Set `homelab_restore_allow_version_mismatch: true` only when you intentionally restore an archive built with a different ops-library version.
- Safety snapshots are kept until the role completes successfully. Disable auto-deletion (`homelab_restore_safe_snapshot_delete: false`) if you want to inspect the snapshot manually.
