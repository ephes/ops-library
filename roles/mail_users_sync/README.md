# mail_users_sync

Synchronize mail users from secrets into the mail PostgreSQL database. Intended to be called from ops-control `mail-users-sync` playbook.

## Variables
- `mail_users_list` (list, required): Items with `email` (required), `password` (plaintext, required), `active` (bool, default true).
- `mail_users_disable_unlisted` (bool, default false): If true, disables users present in DB but not in `mail_users_list`.

## Behavior
- Validates email format and password presence.
- Lowercases localpart/domain, checks domain existence.
- Hashes passwords with `doveadm pw -s SHA512-CRYPT`.
- Idempotent: compares current password via `doveadm pw -t` and only updates when password/active flag changes.
