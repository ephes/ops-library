# Takahe Remove Role

Safely removes the Takahe deployment, systemd units, and related configuration with confirmation gates.

## Usage

```yaml
- hosts: takahe
  become: true
  roles:
    - role: local.ops_library.takahe_remove
      vars:
        takahe_confirm_removal: true
        takahe_remove_site: true
        takahe_remove_media: false
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `takahe_confirm_removal` | `false` | Must be set to `true` to proceed. |
| `takahe_remove_site` | `true` | Remove the application directory. |
| `takahe_remove_media` | `false` | Remove local media directory. |
| `takahe_remove_cache` | `true` | Remove nginx cache directory. |
| `takahe_remove_user` | `true` | Remove the service user and group. |

See `defaults/main.yml` and `roles/takahe_shared/defaults/main.yml` for the full reference.

## Dependencies

- `local.ops_library.takahe_shared`

## Testing

```bash
cd /path/to/ops-library
just test-role takahe_remove
```

## License

MIT
