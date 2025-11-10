# paperless_remove

Safely tear down a Paperless-ngx deployment created by `paperless_deploy`. The role stops all services, removes systemd units, cleans up Traefik/SSH drop-ins, deletes application directories, and (optionally) drops the PostgreSQL database/user and scanner resources.

## Safety

Set `paperless_remove_confirm: true` (the `just remove-one paperless` helper exports this automatically) before running. Without explicit confirmation the role aborts. Review the path flags below before enabling destructive options such as media/data removal.

## Defaults

| Variable | Default | Description |
| --- | --- | --- |
| `paperless_remove_confirm` | `false` | Must be `true` to proceed |
| `paperless_service_units` | `paperless*` | Systemd units to stop/remove |
| `paperless_remove_service_units` | `true` | Stop+disable services and delete unit files |
| `paperless_traefik_config_path` | `/etc/traefik/dynamic/paperless.yml` | Dynamic config to remove |
| `paperless_remove_traefik_config` | `true` | Remove Traefik routing file |
| `paperless_scanner_sshd_config_path` | `/etc/ssh/sshd_config.d/sftp-scanner.conf` | Scanner drop-in file |
| `paperless_remove_scanner_config` | `true` | Remove the scanner SSH drop-in |
| `paperless_site_root` | `/home/paperless/site` | uv/app install root |
| `paperless_remove_site_root` | `true` | Delete the site directory (includes venv/releases) |
| `paperless_media_path` | `/mnt/cryptdata/paperless/media` | Media directory |
| `paperless_remove_media_dir` | `false` | Delete media (documents/thumbnails) |
| `paperless_data_path` | `/mnt/cryptdata/paperless/data` | Application data dir |
| `paperless_remove_data_dir` | `false` | Delete data directory |
| `paperless_remove_user` | `false` | Remove the `paperless` system user |
| `paperless_remove_group` | `false` | Remove the `paperless` group |
| `paperless_remove_scanner_user` | `false` | Remove the `scanner` account and chroot |
| `paperless_remove_postgres_database` | `false` | Drop the Paperless database |
| `paperless_remove_postgres_user` | `false` | Drop the Paperless DB user |

External storage (`media`, `data`, `consume`, `export`, `backup`, `tmp`) is preserved by default—toggle the relevant `paperless_remove_*` flag when you intentionally want to wipe those directories.

## Example

```yaml
- hosts: macmini
  become: true
  vars:
    paperless_remove_confirm: true
    paperless_remove_media_dir: true
    paperless_remove_data_dir: true
    paperless_remove_postgres_database: true
    paperless_remove_postgres_user: true
  roles:
    - role: local.ops_library.paperless_remove
```

## PostgreSQL cleanup

Set `paperless_remove_postgres_database: true` and/or `paperless_remove_postgres_user: true` to drop the database/role. The role uses `community.postgresql` modules with `paperless_postgres_become_user` (defaults to `postgres`); adjust if your admin account differs or when remote connections are required.

## Scanner cleanup

If you used the bundled scanner SFTP integration, set `paperless_remove_scanner_config: true` to delete the SSH drop-in and `paperless_remove_scanner_user: true` (plus `paperless_remove_sftp_chroot: true`) to delete the scanner account and chroot directory.
The role automatically attempts to unmount the bind-mounted inbox (`paperless_scanner_inbox_path`, default `/srv/sftp-scanner/inbox`) before deleting the chroot; adjust that path if you changed the mount location.
