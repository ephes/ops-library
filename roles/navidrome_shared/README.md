# Navidrome Shared Role

Shared defaults for the Navidrome lifecycle roles.

## Current role surface

This role provides the shared variable surface used by:

- `navidrome_deploy`
- `navidrome_backup`
- `navidrome_restore`
- `navidrome_remove`

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.navidrome_deploy
```

## Notes

- Most operators do not call this role directly.
- See `defaults/main.yml` for the full variable reference.

## License

MIT
