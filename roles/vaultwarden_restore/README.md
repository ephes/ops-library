# Vaultwarden Restore Role

Restore Vaultwarden password manager from a backup archive.

## Quick Start

```yaml
# Restore from latest backup
- hosts: server
  roles:
    - role: local.ops_library.vaultwarden_restore
      vars:
        vaultwarden_restore_archive: latest

# Restore from specific backup
- hosts: server
  roles:
    - role: local.ops_library.vaultwarden_restore
      vars:
        vaultwarden_restore_archive: manual-20241207T120000.tar.gz
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `vaultwarden_restore_archive` | `latest` | Archive filename or "latest" |
| `vaultwarden_restore_root` | `/opt/backups/vaultwarden` | Backup directory |
| `vaultwarden_restore_restart` | `true` | Restart service after restore |
| `vaultwarden_restore_cleanup` | `true` | Remove staging directory |

## What Gets Restored

- SQLite database (`db.sqlite3`)
- Attachments directory
- Sends directory
- RSA key files
- Configuration file (`/etc/vaultwarden.env`)
- Systemd override configuration
- Traefik dynamic configuration

## Dependencies

This role depends on `vaultwarden_shared` for common variable definitions.
