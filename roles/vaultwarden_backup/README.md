# Vaultwarden Backup Role

Create backups of Vaultwarden password manager data.

## Quick Start

```yaml
- hosts: server
  roles:
    - role: local.ops_library.vaultwarden_backup
```

## What Gets Backed Up

- **SQLite database** - Uses `sqlite3 .backup` for consistent backup
- **Attachments** - File attachments stored in vault
- **Sends** - Bitwarden Send files
- **RSA keys** - Server encryption keys
- **Configuration** - `/etc/vaultwarden.env`
- **Traefik config** - Reverse proxy configuration

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `vaultwarden_backup_root` | `/opt/backups/vaultwarden` | Backup storage directory |
| `vaultwarden_backup_prefix` | `manual` | Backup file prefix |
| `vaultwarden_backup_stop_service` | `true` | Stop service during backup |
| `vaultwarden_backup_create_archive` | `true` | Create tar.gz archive |
| `vaultwarden_backup_fetch_local` | `true` | Download backup to local machine |
| `vaultwarden_backup_local_dir` | `~/backups/vaultwarden` | Local backup destination |
| `vaultwarden_backup_retain` | `7` | Number of backups to keep |

## Backup Location

Backups are stored at:
- Remote: `/opt/backups/vaultwarden/<prefix>-<timestamp>.tar.gz`
- Local: `~/backups/vaultwarden/<prefix>-<timestamp>.tar.gz`

## Dependencies

This role depends on `vaultwarden_shared` for common variable definitions.
