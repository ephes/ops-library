# Vaultwarden Shared Role

Shared defaults for the Vaultwarden backup and restore roles.

## Current role surface

This role currently provides the shared variable surface used by:

- `vaultwarden_backup`
- `vaultwarden_restore`

That partial wiring is intentional today. `vaultwarden_deploy` and
`vaultwarden_remove` keep their own role-local defaults instead of depending on
this role.

The role also provides shared Molecule fixtures under `molecule/shared/` for the
Vaultwarden role test scenarios.

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: vaultwarden
  become: true
  roles:
    - role: local.ops_library.vaultwarden_backup
```

## Notes

- Most operators do not call this role directly.
- See `defaults/main.yml` for the shared backup/restore variable surface.

## License

MIT
