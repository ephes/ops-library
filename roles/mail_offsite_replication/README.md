# mail_offsite_replication

Pull mail data from a remote source host into an offsite ZFS dataset on the local host.

## Description

This role installs an rsync-over-SSH replication script and wires a systemd service + timer.
Each run:

1. Executes a remote pre-sync staging command (typically `pg_dump` + config archive generation).
2. Pulls maildir (`vmail`) incrementally via rsync with `--delete`.
3. Pulls staged DB/config artifacts via rsync.
4. Creates an explicit post-sync ZFS snapshot and prunes old `mail-sync-*` snapshots.
5. Writes a status JSON file + marker file for monitoring.

This role is designed for a Fractal-pulls-from-macmini topology where disaster recovery
should work from one dataset (`tank/backups/mail`) without requiring MinIO/Echoport.

## Requirements

- Source host exposes SSH access for:
  - `mail_offsite_replication_source_stage_command`
  - rsync sender access to `mail_offsite_replication_source_vmail_path`
  - rsync sender access to `mail_offsite_replication_source_stage_path`
- Destination host has ZFS tools available when snapshots are enabled.
- `mail` command available when alerting is enabled.

## Role Variables

### Required

```yaml
mail_offsite_replication_source_host: "macmini.tailde2ec.ts.net"
mail_offsite_replication_source_vmail_path: "/mnt/cryptdata/vmail"
mail_offsite_replication_source_stage_path: "/mnt/cryptdata/mail-backup-stage"
mail_offsite_replication_source_stage_command: "/usr/local/sbin/mail-backup-stage.sh"
mail_offsite_replication_destination_path: "/tank/backups/mail"
```

### SSH

```yaml
mail_offsite_replication_ssh_key_manage: true
mail_offsite_replication_ssh_private_key: "{{ vault_mail_replication_private_key }}"
mail_offsite_replication_ssh_key_path: "/root/.ssh/mail-offsite-replication-ed25519"
mail_offsite_replication_manage_known_hosts: true
mail_offsite_replication_ssh_known_hosts_path: "/root/.ssh/known_hosts"
```

### Schedule and behavior

```yaml
mail_offsite_replication_on_calendar: "04:00"
mail_offsite_replication_randomized_delay_sec: "15m"
mail_offsite_replication_timeout_sec: "4h"
mail_offsite_replication_destination_vmail_subdir: "vmail"
mail_offsite_replication_destination_stage_subdir: "stage"
```

### Snapshot management

```yaml
mail_offsite_replication_snapshot_enabled: true
mail_offsite_replication_snapshot_dataset: "tank/backups/mail"
mail_offsite_replication_snapshot_prefix: "mail-sync"
mail_offsite_replication_snapshot_keep: 30
```

### Alerting

```yaml
mail_offsite_replication_alert_enabled: true
mail_offsite_replication_alert_email: "root"
mail_offsite_replication_alert_subject_prefix: "[mail-offsite]"
```

For the full list, see `defaults/main.yml`.

## Example Playbook

```yaml
- name: Configure mail offsite replication on fractal
  hosts: fractal
  become: true
  vars:
    mail_offsite_replication_ssh_private_key: "{{ vault_mail_replication_private_key }}"
  roles:
    - role: local.ops_library.mail_offsite_replication
      vars:
        mail_offsite_replication_source_host: "macmini.tailde2ec.ts.net"
        mail_offsite_replication_source_vmail_path: "/mnt/cryptdata/vmail"
        mail_offsite_replication_source_stage_path: "/mnt/cryptdata/mail-backup-stage"
        mail_offsite_replication_destination_path: "/tank/backups/mail"
        mail_offsite_replication_alert_email: "root"
```

## Handlers

- `reload systemd` - reloads systemd daemon after unit changes
- `restart mail-offsite-replication-timer` - restarts timer after updates

## Tags

- `mail_offsite_replication`

## Testing

```bash
just test-role mail_offsite_replication
```

## License

MIT
