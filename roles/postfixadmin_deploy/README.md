# postfixadmin_deploy

Deploy PostfixAdmin web UI for managing mail users, domains, and aliases.

## Overview

This role deploys PostfixAdmin as a web-based administration interface for virtual mail hosting. It integrates with the existing PostgreSQL-backed mail infrastructure (Postfix/Dovecot) and provides:

- Domain management
- Mailbox (user) management
- Alias management
- User self-service password changes
- Optional TOTP two-factor authentication

## Requirements

- Ubuntu 22.04 (Jammy) or 24.04 (Noble)
- PHP 8.x with CLI installed
- PostgreSQL with existing `mail` database
- nginx
- Traefik (for HTTPS termination)
- Dovecot (for password hashing with `doveadm pw`)

## Dependencies

- `local.ops_library.postfixadmin_shared` (included automatically)
- `community.postgresql` collection

## Role Variables

### Required Variables (must be set via secrets)

```yaml
# Database password (same as mail_backend_postgres_password)
postfixadmin_db_password: "your-database-password"

# Setup password hash (for initial web setup)
# Generate with: php -r "echo password_hash('your-setup-password', PASSWORD_DEFAULT);"
postfixadmin_setup_password_hash: "$2y$10$..."

# Admin password hash (for CLI admin creation)
# Generate with: doveadm pw -s SHA512-CRYPT -p 'your-admin-password'
postfixadmin_admin_password_hash: "{SHA512-CRYPT}$6$..."
```

### Key Configuration Variables

```yaml
# PostfixAdmin version
postfixadmin_version: "3.3.13"

# Admin account email
postfixadmin_admin_email: "admin@xn--wersdrfer-47a.de"

# Web access
postfixadmin_traefik_host: "mailadmin.home.xn--wersdrfer-47a.de"
postfixadmin_traefik_host_aliases:
  - "mailadmin.home.wersdoerfer.de"

# Feature toggles
postfixadmin_quota_enabled: false
postfixadmin_vacation_enabled: false
postfixadmin_totp_enabled: true

# Schema migration (from old mail_* tables)
postfixadmin_migrate_schema: false
postfixadmin_migration_backup: true
```

See `defaults/main.yml` in `postfixadmin_shared` for all available variables.

## Schema Migration

If you have existing data in the custom `mail_*` tables schema, this role can migrate it to PostfixAdmin's native schema:

1. Set `postfixadmin_migrate_schema: true`
2. Run the role
3. Verify mail flow works with the new schema
4. Update Postfix/Dovecot SQL queries (see below)
5. Optionally drop old tables

### Table Mapping

| Old Table | PostfixAdmin Table |
|-----------|-------------------|
| `mail_domains` | `domain` |
| `mail_users` | `mailbox` |
| `mail_aliases` | `alias` |
| `mail_domain_aliases` | `alias_domain` |

## Postfix/Dovecot Configuration Updates

After migrating to PostfixAdmin schema, update your SQL queries:

### Postfix SQL Queries

**virtual_domains.cf:**
```
query = SELECT domain FROM domain WHERE domain='%s' AND active='1'
```

**virtual_mailbox_maps.cf:**
```
query = SELECT maildir FROM mailbox WHERE username='%s' AND active='1'
```

**virtual_alias_maps.cf:**
```
query = SELECT goto FROM alias WHERE address='%s' AND active='1'
```

### Dovecot SQL Queries

**dovecot-sql.conf.ext:**
```
password_query = SELECT username AS user, password \
  FROM mailbox WHERE username='%u' AND active='1'

user_query = SELECT \
  '/mnt/cryptdata/vmail/' || maildir AS home, \
  'maildir:/mnt/cryptdata/vmail/' || maildir AS mail, \
  5000 AS uid, 5000 AS gid \
  FROM mailbox WHERE username='%u' AND active='1'
```

## Example Playbook

```yaml
- hosts: mailserver
  become: true
  vars:
    mail_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/mail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.postfixadmin_deploy
      vars:
        postfixadmin_db_password: "{{ mail_secrets.postgres_password }}"
        postfixadmin_setup_password_hash: "{{ mail_secrets.postfixadmin_setup_hash }}"
        postfixadmin_admin_password_hash: "{{ mail_secrets.postfixadmin_admin_hash }}"
        postfixadmin_admin_email: "admin@xn--wersdrfer-47a.de"
        postfixadmin_migrate_schema: true
```

## Security Considerations

1. **Access Control**: By default, PostfixAdmin is only accessible via Tailscale (IP whitelist in Traefik)

2. **Setup Page**: The `setup.php` file is automatically removed after deployment

3. **Rate Limiting**: Login attempts are rate-limited at nginx level (5/minute per IP)

4. **TOTP 2FA**: Enabled by default for admin accounts (with Tailscale IP exceptions)

5. **Password Hashing**: Uses SHA512-CRYPT via Dovecot for compatibility

## Files Created

| Path | Description |
|------|-------------|
| `/opt/postfixadmin/` | Application files |
| `/opt/postfixadmin/config.local.php` | Local configuration |
| `/etc/nginx/sites-available/postfixadmin` | nginx vhost |
| `/etc/php/X.Y/fpm/pool.d/postfixadmin.conf` | PHP-FPM pool |
| `/etc/traefik/dynamic/postfixadmin.yml` | Traefik router |

## Troubleshooting

### Check PHP-FPM Status
```bash
systemctl status php8.3-fpm
journalctl -u php8.3-fpm -f
```

### Check nginx Configuration
```bash
nginx -t
tail -f /var/log/nginx/postfixadmin_error.log
```

### Check Database Connection
```bash
sudo -u www-data php /opt/postfixadmin/public/upgrade.php
```

### Regenerate Admin Password Hash
```bash
doveadm pw -s SHA512-CRYPT -p 'new-password'
```

## License

MIT

## Author

Jochen Wersdoerfer
