# mail_users_sync

Synchronize mail users from secrets into the mail PostgreSQL database. Intended to be called from ops-control `mail-users-sync` playbook.

## Variables
- `mail_users_list` (list, required): Items with:
  - `email` (required)
  - `password` (plaintext, required)
  - `active` (bool, default true)
  - `mailbox_maildir` (optional, PostfixAdmin mode): explicit Maildir target in `<domain>/<localpart>/` format
  - `send_as` (optional list, PostfixAdmin mode): additional envelope-sender addresses this login may use
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
- When `mailbox_maildir` points to a mailbox user that is also created in the same run, place that target user earlier in `mail_users_list`.
- In `legacy` mode, manages `mail_users` + `mail_aliases` rows.

## send_as (envelope-sender authorisation)

The backend enforces `reject_sender_login_mismatch` on submission (587) and smtps
(465), resolved through `smtpd_sender_login_maps`, whose query is:

```sql
SELECT username FROM mailbox WHERE LOWER(username) = LOWER('%s') AND active = '1'
UNION
SELECT goto FROM alias WHERE LOWER(address) = LOWER('%s') AND active = '1' AND goto LIKE '%@%'
```

A login may therefore send as its own address, or as any *alias* that points at it.
`send_as` is that second case: each entry becomes an `alias` row
(`address = <entry>`, `goto = <user email>`).

```yaml
mail_users_list:
  - email: fedi-smtp@xn--wersdrfer-47a.de
    password: "..."
    send_as:
      - notifications@fedi.wersdoerfer.de
      - noreply@fedi.python-podcast.de
```

Use it when an application on another host submits mail whose `From:`/envelope
sender is in a domain the backend does not host mailboxes for.

Constraints, all enforced before the first row of the run is written — the database
checks run ahead of the per-user sync loop, so a bad entry cannot leave earlier users
half-applied:

- PostfixAdmin schema mode only.
- Each entry must be a bare `localpart@domain`.
- No address may appear in two users' `send_as`.
- No entry may collide with an address the role already manages for a mailbox —
  its own address, or its localpart on a `mail_users_additional_alias_domains`
  domain. Without this check a stray entry could repoint a real person's alias.
- No entry may already exist in the `alias` table pointing somewhere else. The
  previous check only sees `mail_users_list`; this one sees the database, and so
  catches rows the role never created — `postmaster@`/`abuse@` from
  `mail_backend_deploy`, a mailbox self-alias, or a leftover from a user that has
  since been removed from the secrets file.
- The entry's domain must already exist in the `domain` table. For a domain that
  should have no mailboxes, add it to `mail_backend_sender_only_domains` in
  `mail_backend_deploy` and deploy the backend first.

Note that an `alias` row is also read by `virtual_alias_maps`, so a `send_as`
address doubles as a recipient alias delivering to the same mailbox. For a
sender-only domain that is useful — it is where a bounce lands if one ever reaches
the backend.

Removing a `send_as` entry does not delete the alias row. Delete it by hand if the
authorisation must actually be revoked.
