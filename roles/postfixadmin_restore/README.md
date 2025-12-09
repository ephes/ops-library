# postfixadmin_restore

Restore PostfixAdmin configuration and admin tables from backup.

## Overview

This role restores PostfixAdmin's configuration and admin data from a backup created by `postfixadmin_backup`. It restores:

- Configuration file (`config.local.php`)
- Admin accounts and domain permissions
- Optionally, compiled templates

## Requirements

- Existing PostfixAdmin installation
- Valid backup created by `postfixadmin_backup`

## Dependencies

- `local.ops_library.postfixadmin_shared` (included automatically)
- `community.postgresql` collection

## Role Variables

### Required

```yaml
# Timestamp of backup to restore (directory name under backup_path)
postfixadmin_restore_timestamp: "20251208T120000"
```

### Optional

```yaml
# What to restore
postfixadmin_restore_config: true
postfixadmin_restore_admin_tables: true
postfixadmin_restore_templates_c: false
```

## Example Playbook

```yaml
- hosts: mailserver
  become: true
  vars:
    mail_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/mail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.postfixadmin_restore
      vars:
        postfixadmin_db_password: "{{ mail_secrets.postgres_password }}"
        postfixadmin_restore_timestamp: "20251208T120000"
```

## Listing Available Backups

```bash
ls -la /mnt/cryptdata/backups/postfixadmin/
```

Each directory is named with the backup timestamp.

## Restore Behavior

- Configuration file is overwritten if it exists
- Admin accounts are upserted (insert or update)
- Domain admin permissions are inserted if not existing
- Log entries are NOT restored (they're for audit purposes only)

## License

MIT

## Author

Jochen Wersdoerfer
