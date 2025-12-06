# mail_restore

Restore mail server from backup.

## Overview

This role restores mail server data from a backup created by `mail_backup`:

- PostgreSQL database (users, domains, aliases)
- Maildir storage (all email data)
- Configuration files (optional, disabled by default)

## Requirements

- Backup created by `mail_backup` role
- Backup timestamp to restore

## Required Variables

| Variable | Description |
|----------|-------------|
| `mail_restore_timestamp` | Timestamp of backup to restore (e.g., `20231201_120000`) |

## Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_restore_backup_path` | `/mnt/cryptdata/backups/mail` | Backup location |
| `mail_restore_maildir` | `true` | Restore maildir |
| `mail_restore_database` | `true` | Restore PostgreSQL |
| `mail_restore_config` | `false` | Restore config files |

## Example Playbook

```yaml
---
- name: Restore Mail Server
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.mail_restore
      vars:
        mail_restore_timestamp: "20231201_120000"
```

## List Available Backups

```bash
ls -la /mnt/cryptdata/backups/mail/
```

## Safety Notes

1. **Configuration restore is disabled by default** - Config changes should be reviewed before applying
2. **Services will be stopped** during restore
3. **Existing data will be replaced** - Make a backup first if unsure

## License

MIT
