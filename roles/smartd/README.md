# smartd

Installs and configures `smartd` (smartmontools) for disk health monitoring and alerting.

## Variables

### Required

- `smartd_devices` (list)
- `smartd_mail_to` (string)

### Mail relay

If `smartd_configure_mail_relay=true`, set:

- `smartd_mail_relay_client_relayhost`
