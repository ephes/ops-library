# Paperless Remove Role

Remove a Paperless-ngx deployment that was installed via `paperless_deploy`.

## Capabilities

- Stops and disables the `paperless`, `paperless-worker`, `paperless-scheduler`, and `paperless-consumer` units
- Deletes the corresponding systemd unit files and reloads the daemon
- Removes the Traefik dynamic config as well as the scanner SSH drop-in
- Deletes the uv/virtualenv/site directories (toggleable), plus temporary files
- Optionally removes external storage directories (`media`, `data`, `consume`, etc.)
- Optionally drops the PostgreSQL database and role using `community.postgresql`
- Optionally removes the `paperless` and `scanner` system accounts/chroot

## Important Variables

| Variable | Purpose |
| --- | --- |
| `paperless_remove_confirm` | Must be `true` to proceed (safety catch) |
| `paperless_service_units` | List of units to stop/remove |
| `paperless_remove_site_root` | Delete `/home/paperless/site` (includes uv env/releases) |
| `paperless_remove_media_dir` / `paperless_remove_data_dir` | Remove external storage contents |
| `paperless_remove_postgres_database` / `_user` | Drop the database/user via PostgreSQL modules |
| `paperless_remove_user` / `_group` | Remove the Paperless system account |
| `paperless_remove_scanner_user` / `_sftp_chroot` | Remove scanner user and SFTP chroot |

Refer to `roles/paperless_remove/defaults/main.yml` for the complete list of toggles.

## Example

```yaml
- hosts: homelab
  become: true
  vars:
    paperless_remove_confirm: true
    paperless_remove_site_root: true
    paperless_remove_media_dir: false  # keep documents
    paperless_remove_postgres_database: true
    paperless_remove_postgres_user: true
  roles:
    - role: local.ops_library.paperless_remove
```

## Safety Notes

- Media and data directories are **not** removed unless you set the respective flags to `true`.
- PostgreSQL objects are preserved by default; enable the cleanup flags when you know no other service depends on the database.
- Always take a backup (`just backup-paperless ...`) before running the removal role.
