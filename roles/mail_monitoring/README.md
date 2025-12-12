# mail_monitoring

WIP scaffold for mail monitoring helpers (monitor mailbox provisioning + Sieve cleanup) to support nyxmon end-to-end flow checks.

## Status

- **Not implemented yet**: tasks currently fail intentionally when enabled to prevent partial deployments.
- Parent PRD: `../ws-mail-meta/specs/mail-nyxmon-prd.md` (issue `ws-mail-meta-e15`).

## Intended Scope

- Ensure `monitor@` mailbox exists with generated password (from ops-control vault).
- Install Sieve rule to auto-clean monitoring messages (TTL ~1 day).
- Optionally seed Gmail filter instructions (documented, not automated here).

## Variables (defaults)

```yaml
mail_monitoring_enabled: false
mail_monitoring_address: "monitor@xn--wersdrfer-47a.de"
mail_monitoring_password: "CHANGE_ME"   # from ops-control vault
mail_monitoring_sieve_ttl_days: 1
```

## Usage (future)

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

- Implement tasks to provision the monitor mailbox using existing mail roles/db helpers.
- Install Sieve cleanup script and reload Dovecot.
- Add tests to verify mailbox creation and Sieve rule deployment.
