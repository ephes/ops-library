# SnappyMail Shared Role

Shared defaults for the SnappyMail lifecycle roles.

## Current role surface

This role provides the shared variable surface used by:

- `snappymail_deploy`
- `snappymail_backup`
- `snappymail_restore`
- `snappymail_remove`

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: mail
  become: true
  roles:
    - role: local.ops_library.snappymail_deploy
```

## Notes

- Most operators do not call this role directly.
- See `defaults/main.yml` for the full variable reference.

## License

MIT
