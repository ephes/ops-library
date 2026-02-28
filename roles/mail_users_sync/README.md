# mail_users_sync

Synchronize mail users from secrets into the mail PostgreSQL database. Intended to be called from ops-control `mail-users-sync` playbook.

## Variables
- `mail_users_list` (list, required): Items with:
  - `email` (required)
  - `password` (plaintext, required)
  - `active` (bool, default true)
  - `mailbox_maildir` (optional, PostfixAdmin mode): explicit Maildir target in `<domain>/<localpart>/` format
- `mail_users_disable_unlisted` (bool, default false): If true, disables users present in DB but not in `mail_users_list`.
- `mail_users_schema_mode` (string, default `postfixadmin`): `postfixadmin` or `legacy`.
- `mail_users_postgres_database` (string, default `mail`): target database name.
- `mail_users_additional_alias_domains` (list, default `[]`): for each user localpart, create aliases on these domains pointing to the user mailbox.

## Behavior
- Validates email format and password presence.
- Lowercases localpart/domain, checks domain existence.
- Hashes passwords with `doveadm pw -s SHA512-CRYPT`.
- Idempotent: compares current password via `doveadm pw -t` and only updates when password/active flag changes.
- In `postfixadmin` mode, manages `mailbox` + `alias` rows.
- In `postfixadmin` mode, `mailbox_maildir` can map one login identity to another mailbox storage path (for example reader accounts).
- In `legacy` mode, manages `mail_users` + `mail_aliases` rows.
