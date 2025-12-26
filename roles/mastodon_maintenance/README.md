# Mastodon Maintenance Role

Installs a systemd timer and service to run Mastodon `tootctl` maintenance commands (media cleanup, preview-card pruning, account pruning) using the configured runtime and `.env.production`.

## Usage

```yaml
- hosts: mastodon
  become: true
  roles:
    - role: local.ops_library.mastodon_maintenance
      vars:
        mastodon_maintenance_on_calendar: "*-*-* 03:00:00"
        mastodon_maintenance_media_days: 4
        mastodon_maintenance_preview_days: 4
        mastodon_maintenance_status_days: 4
```

To extend or replace the command list:

```yaml
mastodon_maintenance_tootctl_commands:
  - "media remove --days 7"
  - "media remove-orphans"
mastodon_maintenance_extra_commands:
  - "accounts prune"
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `mastodon_maintenance_on_calendar` | `"*-*-* 03:00:00"` | systemd `OnCalendar` schedule. |
| `mastodon_maintenance_persistent` | `true` | Run missed timers on boot when `true`. |
| `mastodon_maintenance_randomized_delay_sec` | `""` | Optional randomized delay for timer execution. |
| `mastodon_maintenance_timer_enabled` | `true` | Enable the systemd timer. |
| `mastodon_maintenance_tootctl_commands` | list | Base list of `tootctl` subcommands to run. |
| `mastodon_maintenance_extra_commands` | `[]` | Extra `tootctl` subcommands appended to the base list. |
| `mastodon_maintenance_run_now` | `false` | Run the maintenance script immediately after installation. |
| `mastodon_maintenance_ignore_errors` | `false` | Continue on failures when set to `true`. |

See `defaults/main.yml` and `roles/mastodon_shared/defaults/main.yml` for the full reference.

## Dependencies

- `local.ops_library.mastodon_shared`

## Testing

```bash
cd /path/to/ops-library
just test-role mastodon_maintenance
```

## License

MIT
