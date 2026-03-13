# MeTube Shared Role

Shared defaults for the MeTube lifecycle roles.

## Current role surface

This role provides the shared variable surface used by:

- `metube_deploy`
- `metube_backup`
- `metube_restore`
- `metube_remove`

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.metube_deploy
```

## Notes

- Most operators do not call this role directly.
- See `defaults/main.yml` for the full variable reference.

## License

MIT
