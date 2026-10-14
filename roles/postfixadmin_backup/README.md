# postfixadmin_backup

Backup PostfixAdmin configuration and admin-specific database tables.

## Overview

This role creates backups of PostfixAdmin's configuration and admin data. It
does **not** back up the mail tables (`domain`, `mailbox`, `alias`,
`alias_domain`, `config`, `vacation`, ...). They live in the same `mail`
PostgreSQL database and are covered by whole-database dumps, which restore with
`pg_restore` rather than row by row: the daily `mail_offsite_replication` stage
dump (`pg_dump --format=custom --dbname=mail`, kept as ZFS snapshots on the
offsite host) and the Echoport runner
`echoport_backup/templates/mail_db_backup.py.j2` (a daily `pg_dump` of the
whole database into MinIO). The `mail_backup` role can also dump the
database, but it is only run by hand.

## Disposition

`postfixadmin_backup` is `ad-hoc only`. Echoport is the preferred operator path
for routine PostfixAdmin recovery work. This narrow mail-adjacent role remains
callable for manual exceptions and compatibility, but it is not the default
operator workflow and should not be treated as an auto-removal candidate.

## What Gets Backed Up

Required parts. If one cannot be written, the backup fails, nothing is
published and retention does not run:

- `config.local.php` (copied from `postfixadmin_install_path`)
- `admin.json`: the whole `admin` table, every column, including the TOTP
  secret, `phone`, `email_other` and the password reset token. The query must
  succeed and return at least one row.
- `domain_admins.json`: the query must succeed; no rows is valid
  (superadmin-only setup).
- `manifest.yml`: lists exactly the parts that were written, plus the
  PostfixAdmin version and the database schema version (`config.version`).
  Reading the schema version is required as well.

Optional parts. A failure is a warning, the part is left out of the manifest
and recorded under `skipped`:

- `log.json`: the newest 10,000 rows of the audit log
- `templates_c.tar.gz`: compiled Smarty templates, only with
  `postfixadmin_backup_include_templates_c: true` (regenerable)

## How a Run Works

1. All parts are written into `<timestamp>.tmp/`.
2. When every required part is there, the manifest is written and the
   directory is renamed to `<timestamp>/`.
3. If any step fails, the `.tmp` directory is removed and the play fails.
   An existing directory for the same timestamp is never reused.
4. Only after a successful run, retention prunes completed backups (names
   `YYYYMMDDTHHMMSS`, never `.tmp` or other directories) that are older than
   `postfixadmin_backup_retention_days`, except the newest
   `postfixadmin_backup_keep_min`, which are always kept.

## Requirements

- Existing PostfixAdmin installation
- PostgreSQL database access

## Dependencies

- `local.ops_library.postfixadmin_shared` (included automatically)
- `community.postgresql` collection

## Role Variables

```yaml
# Backup location
postfixadmin_backup_path: /mnt/cryptdata/backups/postfixadmin

# Retention: completed backups older than this are pruned after a successful run ...
postfixadmin_backup_retention_days: 14
# ... except the newest N, which are always kept
postfixadmin_backup_keep_min: 5

# Include templates_c directory
postfixadmin_backup_include_templates_c: false
```

## Backup Structure

```
/mnt/cryptdata/backups/postfixadmin/
└── 20251208T120000/
    ├── manifest.yml
    ├── config.local.php
    ├── admin.json
    ├── domain_admins.json
    └── log.json
```

`manifest.yml`:

```yaml
backup_type: postfixadmin
manifest_version: 2
timestamp: 20251208T120000
postfixadmin_version: 4.0.5
db_schema_version: 1851
contents: [admin.json, config.local.php, domain_admins.json, log.json]
skipped: []
```

## Example Playbook

```yaml
- hosts: mailserver
  become: true
  vars:
    mail_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/mail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.postfixadmin_backup
      vars:
        postfixadmin_db_password: "{{ mail_secrets.postgres_password }}"
```

## Scheduling Backups

Add to your cron or systemd timer:

```yaml
- name: Schedule PostfixAdmin backup
  ansible.builtin.cron:
    name: "PostfixAdmin backup"
    minute: "30"
    hour: "3"
    job: "ansible-playbook /path/to/backup-playbook.yml"
    user: root
```

## License

MIT

## Author

Jochen Wersdoerfer

## Credential logging

Password-bearing admin queries and admin backup writes use `no_log: true` to keep password hashes out of Ansible output, including verbose runs.
