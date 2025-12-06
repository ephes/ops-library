# mail_backup

Create backups of mail server data and configuration.

## Overview

This role creates comprehensive backups of:

- PostgreSQL database (users, domains, aliases)
- Maildir storage (all email data)
- Configuration files (Postfix, Dovecot, OpenDKIM, rspamd)

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backup_vmail_path` | `/mnt/cryptdata/vmail` | Maildir path |
| `mail_backup_destination` | `/mnt/cryptdata/backups/mail` | Backup destination |
| `mail_backup_retention_days` | `14` | Days to keep backups |
| `mail_backup_maildir` | `true` | Backup maildir |
| `mail_backup_database` | `true` | Backup PostgreSQL |
| `mail_backup_config` | `true` | Backup config files |

## Example Playbook

```yaml
---
- name: Backup Mail Server
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.mail_backup
```

## Backup Contents

Each backup creates a timestamped directory:

```
/mnt/cryptdata/backups/mail/20231201_120000/
├── manifest.yml      # Backup metadata
├── database.sql.gz   # PostgreSQL dump
├── maildir.tar.gz    # Mail storage
└── config.tar.gz     # Configuration files
```

## Scheduled Backups

Create a systemd timer for automated backups:

```ini
# /etc/systemd/system/mail-backup.timer
[Unit]
Description=Daily mail backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

## License

MIT
