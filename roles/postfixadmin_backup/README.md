# postfixadmin_backup

Backup PostfixAdmin configuration and admin-specific database tables.

## Overview

This role creates backups of PostfixAdmin's configuration and admin data. Core mail tables (`domain`, `mailbox`, `alias`, `alias_domain`) are backed up by the `mail_backup` role - this role only backs up PostfixAdmin UI-specific data.

## What Gets Backed Up

1. **Configuration File**
   - `/opt/postfixadmin/config.local.php`

2. **Database Tables**
   - `admin` - PostfixAdmin administrator accounts
   - `domain_admins` - Admin-to-domain permissions
   - `log` - Audit log of admin actions (last 10,000 entries)

3. **Optional**
   - `templates_c/` - Compiled Smarty templates (usually not needed)

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

# Retention period
postfixadmin_backup_retention_days: 14

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
