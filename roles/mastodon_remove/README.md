# Mastodon Remove Role

Safely removes the Mastodon deployment, systemd units, and related configuration with confirmation gates.

## Usage

```yaml
- hosts: mastodon
  become: true
  roles:
    - role: local.ops_library.mastodon_remove
      vars:
        mastodon_confirm_removal: true
        mastodon_remove_site: true
        mastodon_remove_media: false
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `mastodon_confirm_removal` | `false` | Must be set to `true` to proceed. |
| `mastodon_remove_site` | `true` | Remove the application directory. |
| `mastodon_remove_media` | `false` | Remove local media directory. |
| `mastodon_remove_nginx_config` | `true` | Remove the nginx config file. |
| `mastodon_remove_logs` | `false` | Remove nginx log directory. |
| `mastodon_remove_logrotate` | `true` | Remove nginx logrotate configuration. |
| `mastodon_remove_user` | `true` | Remove the service user and group. |

See `defaults/main.yml` and `roles/mastodon_shared/defaults/main.yml` for the full reference.

## Dependencies

- `local.ops_library.mastodon_shared`

## Testing

```bash
cd /path/to/ops-library
just test-role mastodon_remove
```

## License

MIT
