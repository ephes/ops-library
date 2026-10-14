# mail_restore

Restore mail server from backup.

## Disposition

`mail_restore` is an `exception`. This family is intentionally outside the
default Echoport deprecation path because mail disaster recovery follows its
own dedicated workflow, including `mail_offsite_replication`. Keep using this
role when you need the mail-specific restore surface.

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
| `mail_restore_config_root` | `/etc` | Parent of the restored configuration directories |
| `mail_restore_config_dirs` | `[postfix, dovecot, opendkim, rspamd]` | Directory names `config.tar.gz` may contain |

## Configuration Restore

`config.tar.gz` stores each directory by name (`postfix/main.cf`, ...). With
`mail_restore_config: true` the role checks every member before stopping the
services: it must sit below one of `mail_restore_config_dirs`, without absolute
paths or `..`. After the database and maildir steps it extracts the archive
into a staging directory below `mail_restore_config_root`, keeps each live
directory present in the archive as
`/etc/<name>.pre-restore-<UTC timestamp>-<suffix>` and moves the restored
files into place. The final message lists these copies; the role never
removes them, so prune them by hand. Earlier versions extracted into `/` and
created `/postfix`, `/dovecot`, ... instead of updating `/etc`.

## Dump Checks

Before the database is dropped, the role checks `database.sql.gz` with
`gzip -t` and fails if it is corrupt or decompresses to nothing, so a broken
backup stops the restore while the current database is still intact. The
`gunzip | psql` restore runs under `bash` with `set -euo pipefail`. `psql`
itself still runs without `ON_ERROR_STOP`, so individual SQL errors inside a
valid dump are reported but do not fail the task.

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
