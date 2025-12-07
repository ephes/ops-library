# mail_remove

Remove the mail stack (Postfix/Dovecot/OpenDKIM/rspamd/postgrey) from a host. Designed for the mail project’s backend or edge relay; does nothing unless explicitly confirmed and at least one component is selected.

## Variables
- `mail_remove_confirm` (bool, required): Must be `true` to proceed.
- `mail_remove_backend` / `mail_remove_relay` / `mail_remove_spam` (bool): Select components to remove on this host.
- `mail_remove_purge_packages` (bool, default `true`): Purge packages for selected components.
- `mail_remove_remove_configs` (bool, default `true`): Delete config directories (e.g., `/etc/postfix`, `/etc/dovecot`, `/etc/rspamd`).
- `mail_remove_remove_state` (bool, default `true`): Delete state dirs (spool, var/lib).
- `mail_remove_remove_data` (bool, default `false`): Delete Maildir/backups (`mail_vmail_path`, `mail_backup_path`).
- `mail_remove_remove_vmail_user` (bool, default `false`): Remove `vmail` user/group (home removed only if `mail_remove_remove_data=true`).
- `mail_remove_drop_database` / `mail_remove_drop_db_user` (bool): Drop `mail` database and user (backend only).
- `mail_remove_db_force_disconnect` (bool, default `false`): If true, terminate active DB connections when dropping the database.

## Notes
- Package lists intentionally overlap across backend/relay so either can be removed independently; tasks dedupe with `unique`.
- Role emits a warning if a mail queue exists (postqueue -p) before removal of backend/relay.

## Example
```yaml
- hosts: mail_backend
  roles:
    - role: mail_remove
      vars:
        mail_remove_confirm: true
        mail_remove_backend: true
        mail_remove_spam: true
        mail_remove_remove_data: false      # preserve Maildir
        mail_remove_drop_database: true     # drop mail DB
        mail_remove_drop_db_user: true
```
