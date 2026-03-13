# Jellyfin Shared Role

Shared defaults for the Jellyfin lifecycle roles.

## Current role surface

This role provides the shared variable surface used by:

- `jellyfin_deploy`
- `jellyfin_backup`
- `jellyfin_restore`
- `jellyfin_remove`

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.jellyfin_deploy
```

## Notes

- Most operators do not call this role directly.
- See `defaults/main.yml` for the full variable reference.

## License

MIT
