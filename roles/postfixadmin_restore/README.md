# postfixadmin_restore

Restore PostfixAdmin configuration and admin tables from backup.

## Disposition

`postfixadmin_restore` is `ad-hoc only`. Echoport is the preferred operator
path for routine PostfixAdmin recovery work. This narrow mail-adjacent role
remains callable for manual exceptions and compatibility, but it is not the
default operator workflow and should not be treated as an auto-removal
candidate.

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

Before anything changes, the restore refuses the backup when:

- `postfixadmin_restore_timestamp` is not a backup directory name
  (`YYYYMMDDTHHMMSS`; paths are rejected)
- `manifest.yml` is missing, is not a PostfixAdmin manifest or has no
  `contents`
- a required part (`config.local.php`, `admin.json`, `domain_admins.json`) is
  not listed, or any listed part is missing from the directory
- `postfixadmin_restore_templates_c` is set but the backup has no
  `templates_c.tar.gz`
- the manifest's `db_schema_version` is newer than the target's
  `config.version` (upgrade PostfixAdmin on the target first). Backups written
  before the version was recorded are restored with a warning.
- `admin.json` holds no admin, or a column the target's `admin` table lacks

Then:

- the configuration file is overwritten
- admin accounts are upserted with every column of the backup, so TOTP
  secrets, `phone`, `email_other` and tokens survive
- domain admin permissions are inserted if not existing
- log entries are NOT restored (they're for audit purposes only)

## License

MIT

## Author

Jochen Wersdoerfer
