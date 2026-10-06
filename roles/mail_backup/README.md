# mail_backup

Create backups of mail server data and configuration.

## Disposition

`mail_backup` is an `exception`. This family is intentionally outside the
default Echoport deprecation path because mail disaster recovery follows its
own dedicated workflow, including `mail_offsite_replication`. Keep using this
role when you need the mail-specific backup surface.

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

## Failure Handling

A backup run either completes or fails loudly; it never keeps a partial
backup:

- `pg_dump | gzip` runs under `bash` with `set -euo pipefail`, so a failed
  dump (database down, authentication error, missing database) fails the task
  instead of leaving an empty `database.sql.gz`. The dump is written to
  `database.sql.gz.tmp`, checked with `gzip -t`, rejected if it decompresses
  to nothing, and only then renamed to `database.sql.gz`.
- The maildir archive is written to `maildir.tar.gz.tmp`, checked with
  `gzip -t` and then renamed.
- If any backup or archive step fails, the role removes the incomplete
  timestamped directory and its archive, then fails the play. Before it
  starts, the role refuses to run if this run's directory or archive already
  exists (for example a second run in the same play, which reuses the
  gathered timestamp), so the cleanup can only ever remove this run's files. Retention runs
  only after a complete backup, so a failing database never ages out the
  older good backups, and a `latest` restore never picks a half-written one.

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
