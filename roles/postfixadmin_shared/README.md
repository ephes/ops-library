# PostfixAdmin Shared Role

Shared defaults for the PostfixAdmin lifecycle roles.

## Current role surface

This role provides the shared variable surface used by:

- `postfixadmin_deploy`
- `postfixadmin_backup`
- `postfixadmin_restore`
- `postfixadmin_remove`

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: mail
  become: true
  roles:
    - role: local.ops_library.postfixadmin_deploy
```

## Notes

- Most operators do not call this role directly.
- `tasks/main.yml` is only a lightweight placeholder; the meaningful shared
  surface is in `defaults/main.yml`.

## License

MIT
