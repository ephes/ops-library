# mail_monitoring

Provisioning helpers for nyxmon end-to-end mail flow checks:

- Ensures the local `monitor@...` mailbox exists in PostgreSQL (PostfixAdmin schema by default).
- Creates the mailbox Maildir directory.
- Installs a systemd timer to expunge old messages (mailbox hygiene fallback).

Tracks PRD: `specs/mail-nyxmon-prd.md` (issue `ops-meta-e15`).

## Intended Scope

- Ensure `monitor@` mailbox exists with generated password (from ops-control vault).
- Install cleanup policy to auto-clean monitoring messages (TTL ~1 day).
- Optionally seed Gmail filter instructions (documented, not automated here).

## Variables (defaults)

```yaml
mail_monitoring_enabled: false
mail_monitoring_address: "monitor@xn--wersdrfer-47a.de"
mail_monitoring_password: "CHANGE_ME"   # from ops-control vault (plaintext)
mail_monitoring_active: true
mail_monitoring_schema_mode: "{{ mail_backend_schema_mode | default('legacy') }}"  # postfixadmin|legacy

mail_monitoring_postgres_database: "{{ mail_backend_postgres_database | default('mail') }}"
mail_monitoring_vmail_path: "{{ mail_backend_vmail_path | default('/mnt/cryptdata/vmail') }}"
mail_monitoring_vmail_user: "{{ mail_backend_vmail_user | default('vmail') }}"
mail_monitoring_vmail_group: "{{ mail_backend_vmail_group | default(mail_monitoring_vmail_user) }}"

mail_monitoring_cleanup_enabled: true
mail_monitoring_cleanup_ttl_days: 1
mail_monitoring_cleanup_timer_on_calendar: "daily"
mail_monitoring_cleanup_script_path: "/usr/local/bin/mail-monitoring-cleanup.sh"
mail_monitoring_cleanup_service_name: "mail-monitoring-cleanup"
```

## Usage

```yaml
- hosts: mail
  become: true
  vars:
    mail_monitoring_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/nyxmon.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.mail_monitoring
      vars:
        mail_monitoring_enabled: true
        mail_monitoring_password: "{{ mail_monitoring_secrets.nyxmon_local_monitor_password }}"
```

## Next Steps

- Add optional support for creating the `domain` row if missing (currently fails fast).
- Add optional domain-wide monitor aliases (if useful).

## Notes

- PostfixAdmin schema expects the `domain` row to exist before creating the mailbox.
- Cleanup uses `doveadm expunge` via systemd timer (no Sieve dependency). If the mailbox doesn't exist yet, the cleanup script treats exit code 68 as success.
