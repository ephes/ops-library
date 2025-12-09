# postfixadmin_remove

Remove PostfixAdmin web UI without affecting mail data.

## Overview

This role safely removes PostfixAdmin while keeping the core mail tables (domain, mailbox, alias, alias_domain) intact. This is useful if you want to:

- Uninstall PostfixAdmin but keep using its schema with Postfix/Dovecot
- Downgrade to a different version
- Clean up after testing

## Safety Features

1. **Explicit confirmation required** - Must set `postfixadmin_remove_confirm: true`
2. **Keeps mail data by default** - Only removes PostfixAdmin UI files
3. **Granular control** - Choose exactly what to remove

## Requirements

- None (only removes existing files/configs)

## Dependencies

- `local.ops_library.postfixadmin_shared` (included automatically)
- `community.postgresql` collection (if removing database tables)

## Role Variables

### Required

```yaml
# Must be true to proceed
postfixadmin_remove_confirm: true
```

### What to Remove

```yaml
# Application and configs (safe defaults)
postfixadmin_remove_application: true      # Remove /opt/postfixadmin
postfixadmin_remove_nginx_config: true     # Remove nginx site config
postfixadmin_remove_traefik_config: true   # Remove Traefik router config
postfixadmin_remove_php_pool: true         # Remove PHP-FPM pool

# Database tables (CAREFUL)
postfixadmin_remove_admin_tables: false    # admin, domain_admins, log, etc.
postfixadmin_remove_mail_tables: false     # domain, mailbox, alias, alias_domain

# Backup data
postfixadmin_remove_backups: false         # Remove backup directory
```

## What Gets Removed

### Default (safe removal)

- `/opt/postfixadmin/` - Application files
- `/etc/nginx/sites-*/postfixadmin` - nginx configuration
- `/etc/traefik/dynamic/postfixadmin.yml` - Traefik router
- `/etc/php/X.Y/fpm/pool.d/postfixadmin.conf` - PHP-FPM pool

### With `postfixadmin_remove_admin_tables: true`

- `admin` - PostfixAdmin admin accounts
- `domain_admins` - Admin permissions
- `log` - Audit log
- `vacation`, `vacation_notification` - Vacation auto-responder
- `quota`, `quota2` - Quota tracking
- `config` - PostfixAdmin config storage
- `fetchmail` - Fetchmail settings

### With `postfixadmin_remove_mail_tables: true` (DESTRUCTIVE)

- `domain` - All mail domains
- `mailbox` - All mail users
- `alias` - All mail aliases
- `alias_domain` - All domain aliases

## Example Playbook

### Safe Removal (keep mail data)

```yaml
- hosts: mailserver
  become: true
  roles:
    - role: local.ops_library.postfixadmin_remove
      vars:
        postfixadmin_remove_confirm: true
```

### Complete Removal (including admin tables)

```yaml
- hosts: mailserver
  become: true
  vars:
    mail_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/mail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.postfixadmin_remove
      vars:
        postfixadmin_remove_confirm: true
        postfixadmin_remove_admin_tables: true
        postfixadmin_db_password: "{{ mail_secrets.postgres_password }}"
```

## Recovery

If you removed PostfixAdmin and want it back:

1. Run `postfixadmin_deploy` role to reinstall
2. Run `postfixadmin_restore` to restore admin accounts from backup

Mail data in Postfix/Dovecot is unaffected by PostfixAdmin removal.

## License

MIT

## Author

Jochen Wersdoerfer
